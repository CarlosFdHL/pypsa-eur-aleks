# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT


"""
Prepare PyPSA network for solving according to :ref:`opts`, such
as.

- adding an annual **limit** of carbon-dioxide emissions,
- adding an exogenous **price** per tonne emissions of carbon-dioxide (or other kinds),
- setting an **N-1 security margin** factor for transmission line capacities,
- specifying an expansion limit on the **cost** of transmission expansion,
- specifying an expansion limit on the **volume** of transmission expansion, and
- reducing the **temporal** resolution by averaging over multiple hours
  or segmenting time series into chunks of varying lengths using ``tsam``.

Description
-----------

.. tip::
    The rule :mod:`prepare_elec_networks` runs
    for all ``scenario`` s in the configuration file
    the rule :mod:`prepare_network`.
"""

import logging

import numpy as np
import pandas as pd
import pypsa
from pathlib import Path

from scripts._helpers import (
    PYPSA_V1,
    configure_logging,
    get,
    load_costs,
    set_scenario_config,
    update_config_from_wildcards,
)
from scripts.add_electricity import set_transmission_costs

# Allow for PyPSA versions <0.35
if PYPSA_V1:
    from pypsa.common import expand_series
else:
    from pypsa.descriptors import expand_series


idx = pd.IndexSlice

logger = logging.getLogger(__name__)


def modify_attribute(n, adjustments, investment_year, modification="factor"):
    if not adjustments[modification]:
        return
    change_dict = adjustments[modification]
    for c in change_dict.keys():
        if c not in n.component_attrs.keys():
            logger.warning(f"{c} needs to be a PyPSA Component")
            continue
        for carrier in change_dict[c].keys():
            ind_i = (
                n.components[c].static[n.components[c].static.carrier == carrier].index
            )
            if ind_i.empty:
                continue
            for parameter in change_dict[c][carrier].keys():
                if parameter not in n.components[c].static.columns:
                    logger.warning(f"Attribute {parameter} needs to be in {c} columns.")
                    continue
                if investment_year:
                    factor = get(change_dict[c][carrier][parameter], investment_year)
                else:
                    factor = change_dict[c][carrier][parameter]
                if modification == "factor":
                    logger.info(f"Modify {parameter} of {carrier} by factor {factor} ")
                    n.components[c].static.loc[ind_i, parameter] *= factor
                elif modification == "absolute":
                    logger.info(f"Set {parameter} of {carrier} to {factor} ")
                    n.components[c].static.loc[ind_i, parameter] = factor
                else:
                    logger.warning(
                        f"{modification} needs to be either 'absolute' or 'factor'."
                    )


def maybe_adjust_costs_and_potentials(n, adjustments, investment_year=None):
    if not adjustments:
        return
    for modification in adjustments.keys():
        modify_attribute(n, adjustments, investment_year, modification)


def add_co2limit(n, co2limit, Nyears=1.0):
    n.add(
        "GlobalConstraint",
        "CO2Limit",
        carrier_attribute="co2_emissions",
        sense="<=",
        constant=co2limit * Nyears,
    )


def add_gaslimit(n, gaslimit, Nyears=1.0):
    sel = n.carriers.index.intersection(["OCGT", "CCGT", "CHP"])
    n.carriers.loc[sel, "gas_usage"] = 1.0

    n.add(
        "GlobalConstraint",
        "GasLimit",
        carrier_attribute="gas_usage",
        sense="<=",
        constant=gaslimit * Nyears,
    )


def add_emission_prices(n, emission_prices={"co2": 0.0}, exclude_co2=False):
    if exclude_co2:
        emission_prices.pop("co2")
    ep = (
        pd.Series(emission_prices).rename(lambda x: x + "_emissions")
        * n.carriers.filter(like="_emissions")
    ).sum(axis=1)
    gen_ep = n.generators.carrier.map(ep) / n.generators.efficiency
    n.generators["marginal_cost"] += gen_ep
    n.generators_t["marginal_cost"] += gen_ep[n.generators_t["marginal_cost"].columns]
    su_ep = n.storage_units.carrier.map(ep) / n.storage_units.efficiency_dispatch
    n.storage_units["marginal_cost"] += su_ep


def add_dynamic_emission_prices(n, fn):
    co2_price = (
        pd.read_csv(fn, index_col=0, parse_dates=True).squeeze().reindex(n.snapshots)
    )

    emissions = (
        n.generators.carrier.map(n.carriers.co2_emissions) / n.generators.efficiency
    )
    co2_cost = expand_series(emissions, n.snapshots).T.mul(co2_price, axis=0)

    static = n.generators.marginal_cost
    dynamic = n.get_switchable_as_dense("Generator", "marginal_cost")

    marginal_cost = dynamic + co2_cost.reindex(columns=dynamic.columns, fill_value=0)
    n.generators_t.marginal_cost = marginal_cost.loc[:, marginal_cost.ne(static).any()]

    # remove the static marginal cost from generators with dynamic marginal cost
    affected = co2_cost.where(co2_cost > 0).dropna(axis=1).columns
    n.generators.loc[affected, "marginal_cost"] = 0.0


def set_line_s_max_pu(n, s_max_pu=0.7):
    n.lines["s_max_pu"] = s_max_pu
    logger.info(f"N-1 security margin of lines set to {s_max_pu}")


def set_transmission_limit(n, kind, factor, costs, Nyears=1):
    links_dc_b = n.links.carrier == "DC" if not n.links.empty else pd.Series()

    _lines_s_nom = (
        np.sqrt(3)
        * n.lines.type.map(n.line_types.i_nom)
        * n.lines.num_parallel
        * n.lines.bus0.map(n.buses.v_nom)
    )
    lines_s_nom = n.lines.s_nom.where(n.lines.type == "", _lines_s_nom)

    col = "capital_cost" if kind == "c" else "length"
    ref = (
        lines_s_nom @ n.lines[col]
        + n.links.loc[links_dc_b, "p_nom"] @ n.links.loc[links_dc_b, col]
    )

    set_transmission_costs(n, costs)

    if factor == "opt" or float(factor) > 1.0:
        n.lines["s_nom_min"] = lines_s_nom
        n.lines["s_nom_extendable"] = True

        n.links.loc[links_dc_b, "p_nom_min"] = n.links.loc[links_dc_b, "p_nom"]
        n.links.loc[links_dc_b, "p_nom_extendable"] = True

    if factor != "opt":
        con_type = "expansion_cost" if kind == "c" else "volume_expansion"
        rhs = float(factor) * ref
        n.add(
            "GlobalConstraint",
            f"l{kind}_limit",
            type=f"transmission_{con_type}_limit",
            sense="<=",
            constant=rhs,
            carrier_attribute="AC, DC",
        )

    return n


def average_every_nhours(n, offset, drop_leap_day=False):
    logger.info(f"Resampling the network to {offset}")
    m = n.copy(snapshots=[])

    snapshot_weightings = n.snapshot_weightings.resample(offset).sum()
    sns = snapshot_weightings.index
    if drop_leap_day:
        sns = sns[~((sns.month == 2) & (sns.day == 29))]
    m.set_snapshots(snapshot_weightings.index)
    m.snapshot_weightings = snapshot_weightings

    for c in n.components:
        pnl = getattr(m, c.list_name + "_t")
        for k, df in c.dynamic.items():
            if not df.empty:
                pnl[k] = df.resample(offset).mean()

    return m


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
        if s.index[-1] < block[-1]:
            raise ValueError(f"{path} ends at {s.index[-1]}, block runs to {block[-1]}.")

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
    lo, hi = prices.min(), prices.max()
    if hi - lo < 1e-6:
        raise ValueError("Price signal is flat; the source networks were not solved.")
    return ((prices - lo) / (hi - lo)).to_frame("price") # Normalize using minmax


def apply_time_segmentation(n, segments, solver_name="cbc", price_dir=None):
    basis = "prices" if price_dir else "profiles"
    logger.info(f"Aggregating time series to {segments} segments based on {basis}.")
    try:
        import tsam.timeseriesaggregation as tsam
    except ImportError:
        raise ModuleNotFoundError(
            "Optional dependency 'tsam' not found.Install via 'pip install tsam'"
        )

    p_max_pu_norm = n.generators_t.p_max_pu.max()
    p_max_pu = n.generators_t.p_max_pu / p_max_pu_norm

    # Replace p_max_pu that are NaN with 0's (assume no possible generation, this hapepns for BA0 and SI0 offwind-float,)
    p_max_pu = p_max_pu.fillna(0)

    load_norm = n.loads_t.p_set.max()
    load = n.loads_t.p_set / load_norm

    inflow_norm = n.storage_units_t.inflow.max()
    inflow = n.storage_units_t.inflow / inflow_norm

    profiles = pd.concat([p_max_pu, load, inflow], axis=1, sort=False)
    raw = _price_signal(n, price_dir) if price_dir else profiles

    agg = tsam.TimeSeriesAggregation(
        raw,
        hoursPerPeriod=len(raw),
        noTypicalPeriods=1,
        noSegments=int(segments),
        segmentation=True,
        solver=solver_name,
    )

    segmented = agg.createTypicalPeriods()

    # tsam counts rows, not hours; convert to snapshots and real durations
    steps = segmented.index.get_level_values("Segment Duration").astype(int).values
    starts = np.insert(np.cumsum(steps[:-1]), 0, 0)
    seg_id = np.repeat(np.arange(len(steps)), steps)
    assert len(seg_id) == len(n.snapshots)

    snapshots = pd.DatetimeIndex(n.snapshots[starts], name="snapshot")
    w = n.snapshot_weightings.objective.values
    hours = pd.Series(w, index=seg_id).groupby(level=0).sum()

    def segment_mean(df):
        num = pd.DataFrame(df.values * w[:, None], index=seg_id, columns=df.columns)
        out = num.groupby(level=0).sum().div(hours, axis=0)
        out.index = snapshots
        return out

    profiles = segment_mean(profiles)

    n.set_snapshots(snapshots)
    n.snapshot_weightings = pd.Series(
        hours.values, index=snapshots, name="weightings", dtype="float64"
    )

    n.generators_t.p_max_pu = profiles[n.generators_t.p_max_pu.columns] * p_max_pu_norm
    n.loads_t.p_set = profiles[n.loads_t.p_set.columns] * load_norm
    n.storage_units_t.inflow = profiles[n.storage_units_t.inflow.columns] * inflow_norm

    return n


def enforce_autarky(n, only_crossborder=False):
    if only_crossborder:
        lines_rm = n.lines.loc[
            n.lines.bus0.map(n.buses.country) != n.lines.bus1.map(n.buses.country)
        ].index
        links_rm = n.links.loc[
            n.links.bus0.map(n.buses.country) != n.links.bus1.map(n.buses.country)
        ].index
    else:
        lines_rm = n.lines.index
        links_rm = n.links.loc[n.links.carrier == "DC"].index
    n.remove("Line", lines_rm)
    n.remove("Link", links_rm)


def set_line_nom_max(
    n,
    s_nom_max_set=np.inf,
    p_nom_max_set=np.inf,
    s_nom_max_ext=np.inf,
    p_nom_max_ext=np.inf,
):
    if np.isfinite(s_nom_max_ext) and s_nom_max_ext > 0:
        logger.info(f"Limiting line extensions to {s_nom_max_ext} MW")
        n.lines["s_nom_max"] = n.lines["s_nom"] + s_nom_max_ext

    if np.isfinite(p_nom_max_ext) and p_nom_max_ext > 0:
        logger.info(f"Limiting link extensions to {p_nom_max_ext} MW")
        hvdc = n.links.index[n.links.carrier == "DC"]
        n.links.loc[hvdc, "p_nom_max"] = n.links.loc[hvdc, "p_nom"] + p_nom_max_ext

    n.lines["s_nom_max"] = n.lines.s_nom_max.clip(upper=s_nom_max_set)
    n.links["p_nom_max"] = n.links.p_nom_max.clip(upper=p_nom_max_set)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake(
            "prepare_network",
            clusters="50",
            opts="",
        )
    configure_logging(snakemake)  # pylint: disable=E0606
    set_scenario_config(snakemake)
    update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    n = pypsa.Network(snakemake.input[0])
    Nyears = n.snapshot_weightings.objective.sum() / 8760.0
    costs = load_costs(snakemake.input.costs)

    set_line_s_max_pu(n, snakemake.params.lines["s_max_pu"])

    # temporal averaging
    time_resolution = snakemake.params.time_resolution
    is_string = isinstance(time_resolution, str)
    if is_string and time_resolution.lower().endswith("h"):
        n = average_every_nhours(n, time_resolution, snakemake.params.drop_leap_day)

    # segments with package tsam
    if is_string and time_resolution.lower().endswith("seg"):
        solver_name = snakemake.config["solving"]["solver"]["name"]
        segments = int(time_resolution.replace("seg", ""))
        n = apply_time_segmentation(n, segments, solver_name)

    if snakemake.params.co2limit_enable:
        add_co2limit(n, snakemake.params.co2limit, Nyears)

    if snakemake.params.gaslimit_enable:
        add_gaslimit(n, snakemake.params.gaslimit, Nyears)

    maybe_adjust_costs_and_potentials(n, snakemake.params["adjustments"])

    emission_prices = snakemake.params.emission_prices
    if emission_prices["dynamic"]:
        logger.info(
            "Setting time dependent emission prices according spot market price"
        )
        add_dynamic_emission_prices(n, snakemake.input.co2_price)
    elif emission_prices["enable"]:
        if isinstance(emission_prices["co2"], dict):
            logger.warning(
                "Not setting emission prices on generators and storage units, "
                "due to their configuration per planning horizon"
            )
        elif isinstance(emission_prices["co2"], float):
            add_emission_prices(n, dict(co2=emission_prices["co2"]))

    kind = snakemake.params.transmission_limit[0]
    factor = snakemake.params.transmission_limit[1:]
    set_transmission_limit(n, kind, factor, costs, Nyears)

    set_line_nom_max(
        n,
        s_nom_max_set=snakemake.params.lines.get("s_nom_max", np.inf),
        p_nom_max_set=snakemake.params.links.get("p_nom_max", np.inf),
        s_nom_max_ext=snakemake.params.lines.get("max_extension", np.inf),
        p_nom_max_ext=snakemake.params.links.get("max_extension", np.inf),
    )

    if snakemake.params.autarky["enable"]:
        only_crossborder = snakemake.params.autarky["by_country"]
        enforce_autarky(n, only_crossborder=only_crossborder)

    n.meta = dict(snakemake.config, **dict(wildcards=dict(snakemake.wildcards)))
    n.export_to_netcdf(snakemake.output[0])
