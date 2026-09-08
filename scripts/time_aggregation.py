# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""
Defines the time aggregation to be used for sector-coupled network.

Description
-----------
Computes a time aggregation scheme for the given network, in the form of a CSV
file with the snapshot weightings, indexed by the new subset of snapshots. This
rule only computes said aggregation scheme; aggregation of time-varying network
data is done in ``prepare_sector_network.py``.
"""

import logging

import numpy as np
import pandas as pd
import pypsa
import tsam.timeseriesaggregation as tsam
import xarray as xr
from pathlib import Path

from scripts._helpers import (
    configure_logging,
    set_scenario_config,
    update_config_from_wildcards,
)

logger = logging.getLogger(__name__)


def _modelled_years(sns):
    """Return (year, block) per contiguous weather year; years span July to June."""
    d = sns.to_series().diff()
    step = d.median()
    starts = np.flatnonzero(np.r_[True, d.values[1:] > 1.5 * step])
    ends = np.r_[starts[1:], len(sns)]
    blocks = [(int(sns[s].year), sns[s:e]) for s, e in zip(starts, ends)]
    years = [y for y, _ in blocks]
    if len(set(years)) != len(years):
        raise ValueError(f"Repeated starting years across snapshot blocks: {years}")
    return blocks


def _price_signal(
    n, 
    price_dir,
    ) -> pd.DataFrame:
    """Load one price file per modelled year and align it with the network snapshots."""
    price_dir = Path(price_dir)
    blocks = _modelled_years(n.snapshots)
    logger.info(
        f"Segmenting on prices for {len(blocks)} weather year(s): "
        + ", ".join(f"{y} ({len(b)} snapshots)" for y, b in blocks)
    )

    parts = []
    for year, block in blocks:
        path = price_dir / f"{year}.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"Price-based segmentation requested but {path} is missing."
            )

        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if df.shape[1] != 1:
            raise ValueError(
                f"{path} must hold a single price column, found {list(df.columns)}"
            )
        s = df.iloc[:, 0].astype(float).sort_index()
        if s.index.has_duplicates:
            raise ValueError(f"{path} has duplicate timestamps.")
        if s.isna().any():
            raise ValueError(f"{path} contains NaNs.")
        step = s.index.to_series().diff().median()
        covers_until = s.index[-1] + step
        if covers_until <= block[-1]:
            raise ValueError(
                f"{path} covers until {covers_until} (exclusive), block runs to {block[-1]}."
            )

        aligned = s.reindex(block, method="ffill") # If time resolution is greater than 1H fills the missing values with the last available value
        if aligned.isna().any():
            raise ValueError(
                f"{path} does not cover snapshot {block[aligned.isna()][0]} "
                f"(file spans {s.index[0]} to {s.index[-1]})."
            )
        logger.info(
            f"  {path.name}: {s.index.to_series().diff().median()} resolution, "
            f"mean {aligned.mean():.1f}, range [{aligned.min():.1f}, {aligned.max():.1f}]"
        )
        parts.append(aligned)

    prices = pd.concat(parts)
    lo, hi = prices.min(), prices.quantile(0.995) # Normalization on 99.5%
    if hi - lo < 1e-6:
        raise ValueError("Price signal is flat; the source networks were not solved.")
    normed = ((prices - lo) / (hi - lo)).clip(upper=1.0)
    logger.info(
        f"Normalising on [{lo:.1f}, {hi:.1f}] (99.5th pct); "
        f"{(prices > hi).sum()} hours clipped, max was {prices.max():.1f}."
    )
    return normed.to_frame("price")


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "time_aggregation",
            configfiles="test/config.overnight.yaml",
            opts="",
            clusters="37",
            sector_opts="Co2L0-24h-T-H-B-I-A-dist1",
            planning_horizons="2030",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    n = pypsa.Network(snakemake.input.network)
    resolution = snakemake.params.time_resolution

    if resolution["resolution_elec"] not in (False, 1, "1h", "1H"):
        raise ValueError(
            f"Invalid configuration: expected 'resolution_elec' = False for the "
            f"sector-coupled model, received {resolution['resolution_elec']!r}. "
            "Use 'resolution_sector' to define temporal resolution instead."
        )
    resolution = resolution["resolution_sector"]

    # Representative snapshots
    if not resolution or isinstance(resolution, str) and "sn" in resolution.lower():
        logger.info("Use representative snapshot or no aggregation at all")
        # Output an empty csv; this is taken care of in prepare_sector_network.py
        pd.DataFrame().to_csv(snakemake.output.snapshot_weightings)

    # Plain resampling
    elif isinstance(resolution, str) and "h" in resolution.lower():
        offset = resolution.lower()
        logger.info(f"Averaging every {offset} hours")

        # Resample years separately to handle non-contiguous years
        years = pd.DatetimeIndex(n.snapshots).year.unique()
        snapshot_weightings = []
        for year in years:
            sws_year = n.snapshot_weightings[n.snapshots.year == year]
            sws_year = sws_year.resample(offset).sum()
            snapshot_weightings.append(sws_year)
        snapshot_weightings = pd.concat(snapshot_weightings)

        # The resampling produces a contiguous date range. In case the original
        # index was not contiguous, all rows with zero weight must be dropped
        # (corresponding to time steps not included in the original snapshots).
        zeros_i = snapshot_weightings.query("objective == 0").index
        snapshot_weightings.drop(zeros_i, inplace=True)

        swi = snapshot_weightings.index
        leap_days = swi[(swi.month == 2) & (swi.day == 29)]
        if snakemake.params.drop_leap_day and not leap_days.empty:
            for year in leap_days.year.unique():
                year_leap_days = leap_days[leap_days.year == year]
                leap_weights = snapshot_weightings.loc[year_leap_days].sum()
                march_first = pd.Timestamp(year, 3, 1, 0, 0, 0)
                snapshot_weightings.loc[march_first] = leap_weights
            snapshot_weightings = snapshot_weightings.drop(leap_days).sort_index()

        sns = snapshot_weightings.index
        snapshot_weightings = snapshot_weightings.loc[sns]
        snapshot_weightings.to_csv(snakemake.output.snapshot_weightings)

    # Temporal segmentation
    elif isinstance(resolution, str) and "seg" in resolution.lower():
        price_dir = "resources/prices" if snakemake.config.get("segmentation", {}).get("prices") else None
        segmentation_strategy = "prices" if price_dir else "profiles"
        segments = int(resolution[:-3])
        logger.info(f"Use temporal segmentation with {segments} segments using {segmentation_strategy}")

        # Get all time-dependent data
        dfs = [
            pnl
            for c in n.components
            for attr, pnl in c.dynamic.items()
            if not pnl.empty and attr != "e_min_pu"
        ]
        if snakemake.input.hourly_heat_demand_total:
            dfs.append(
                xr.open_dataset(snakemake.input.hourly_heat_demand_total)
                .to_dataframe()
                .unstack(level=1)
            )
        if snakemake.input.solar_thermal_total:
            sts = (
                xr.open_dataset(snakemake.input.solar_thermal_total)
                .to_dataframe()
                .rename(
                    columns={"__xarray_dataarray_variable__": "solar thermal total"}
                )
                .unstack(level=1)
            )
            sts.columns = sts.columns.droplevel(0)
            dfs.append(sts)
        df = pd.concat(dfs, axis=1)
        df = df.dropna(how="any")

        # Reset columns to flat index
        df = df.T.reset_index(drop=True).T

        # Normalise all time-dependent data
        annual_max = df.max().replace(0, 1)
        df = df.div(annual_max, level=0)

        raw = _price_signal(n, price_dir) if price_dir else df

        # Get representative segments
        agg = tsam.TimeSeriesAggregation(
            raw,
            hoursPerPeriod=len(raw),
            noTypicalPeriods=1,
            noSegments=segments,
            segmentation=True,
            solver=snakemake.params.solver_name,
        )
        agg = agg.createTypicalPeriods()

        weightings = agg.index.get_level_values("Segment Duration")
        offsets = np.insert(np.cumsum(weightings[:-1]), 0, 0)
        snapshot_weightings = n.snapshot_weightings.loc[n.snapshots[offsets]].mul(
            weightings, axis=0
        )

        logger.info(
            f"Distribution of snapshot durations:\n{snapshot_weightings.objective.value_counts()}"
        )

        snapshot_weightings.to_csv(snakemake.output.snapshot_weightings)
