# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: 2026 Aleksander Grochowicz
#
# SPDX-License-Identifier: MIT
"""
Aggregate MGA validation results for a design year into a single summary CSV.

Scans the validation directory for existing metadata/shedding files.
Missing validations (infeasible after all retries) appear as rows with
status=infeasible.
"""

import json
import logging
import re
from pathlib import Path

import pandas as pd

from _helpers import configure_logging

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    if "snakemake" not in globals():
        from _helpers import mock_snakemake

        snakemake = mock_snakemake(
            "collect_mga_validation",
            configfiles="config/mini-sector_droughts.yaml",
            opts="50seg-lv1.0",
            clusters="50",
            sector_opts="Co2L0.0+T+H+B+I+A",
            planning_horizons="2050",
        )

    configure_logging(snakemake)

    # Read expected directions and network hash
    near_opt = pd.read_csv(snakemake.input.near_opt_solutions)
    network_hash = Path(snakemake.input.network_hash).read_text().strip()
    expected_dirs = near_opt["dir_hash"].unique().tolist() if "dir_hash" in near_opt.columns else []
    logger.info(f"Network hash: {network_hash}, expected directions: {len(expected_dirs)}")

    # Scan validation directory for existing metadata and shedding files
    val_dir = Path(snakemake.output.summary).parent
    meta_pattern = re.compile(
        rf"mga_{re.escape(network_hash)}_([a-z0-9]+)_(weather_year_\d+_\d+H)_.*_metadata\.json"
    )
    load_pattern = re.compile(
        rf"mga_{re.escape(network_hash)}_([a-z0-9]+)_(weather_year_\d+_\d+H)_.*_load_shedding\.csv"
    )

    found_meta = {}
    for f in val_dir.glob(f"mga_{network_hash}_*_metadata.json"):
        m = meta_pattern.match(f.name)
        if m:
            found_meta[(m.group(1), m.group(2))] = f

    # Also find completed runs without metadata (backwards compatibility)
    found_load = {}
    for f in val_dir.glob(f"mga_{network_hash}_*_load_shedding.csv"):
        m = load_pattern.match(f.name)
        if m:
            found_load[(m.group(1), m.group(2))] = f

    completed = found_load.keys() | found_meta.keys()
    logger.info(
        f"Found {len(completed)} completed validations "
        f"({len(found_meta)} with metadata, {len(found_load) - len(found_meta)} without)"
    )

    # Build summary rows
    rows = []
    stress_years = sorted({sy for (_, sy) in completed})

    for dir_hash in expected_dirs:
        for stress_year in stress_years:
            key = (dir_hash, stress_year)
            if key in completed:
                # Load metadata if available, otherwise assume attempt 1 / feasible
                if key in found_meta:
                    with open(found_meta[key]) as f:
                        meta = json.load(f)
                else:
                    meta = {"attempt": 1, "buffer": 0.001, "status": "ok", "condition": "optimal"}

                # Read shedding totals
                load_path = found_load.get(key)
                heat_path = load_path.parent / load_path.name.replace("_load_shedding.csv", "_heat_shedding.csv") if load_path else None

                try:
                    load_df = pd.read_csv(load_path, index_col=0)
                    total_load_shed = load_df.values.sum()
                    hours_load_shed = int((load_df.values > 0).any(axis=1).sum())
                except Exception:
                    total_load_shed = float("nan")
                    hours_load_shed = float("nan")

                try:
                    heat_df = pd.read_csv(heat_path, index_col=0)
                    total_heat_shed = heat_df.values.sum()
                    hours_heat_shed = int((heat_df.values > 0).any(axis=1).sum())
                except Exception:
                    total_heat_shed = float("nan")
                    hours_heat_shed = float("nan")

                try:
                    load_shed_rounded = round(total_load_shed, 3)
                except (TypeError, ValueError):
                    load_shed_rounded = None
                try:
                    heat_shed_rounded = round(total_heat_shed, 3)
                except (TypeError, ValueError):
                    heat_shed_rounded = None

                rows.append({
                    "network_hash": network_hash,
                    "dir_hash": dir_hash,
                    "stress_year": stress_year,
                    "attempt": meta.get("attempt"),
                    "buffer": meta.get("buffer"),
                    "status": meta.get("status"),
                    "condition": meta.get("condition"),
                    "total_load_shed_MWh": load_shed_rounded,
                    "total_heat_shed_MWh": heat_shed_rounded,
                    "hours_load_shed": hours_load_shed,
                    "hours_heat_shed": hours_heat_shed,
                })
            else:
                rows.append({
                    "network_hash": network_hash,
                    "dir_hash": dir_hash,
                    "stress_year": stress_year,
                    "attempt": None,
                    "buffer": None,
                    "status": "infeasible",
                    "condition": None,
                    "total_load_shed_MWh": None,
                    "total_heat_shed_MWh": None,
                    "hours_load_shed": None,
                    "hours_heat_shed": None,
                })

    summary = pd.DataFrame(rows)
    summary.to_csv(snakemake.output.summary, index=False)

    n_infeasible = (summary["status"] == "infeasible").sum()
    n_total = len(summary)
    logger.info(
        f"Summary written: {n_total} combinations, {n_infeasible} infeasible "
        f"({100*n_infeasible/n_total:.1f}%)"
    )
    logger.info(
        f"Buffer distribution:\n{summary['buffer'].value_counts(dropna=False).to_string()}"
    )
