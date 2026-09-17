# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: : 2023-2025 Aleksander Grochowicz
#
# SPDX-License-Identifier: MIT
"""
Test MGA capacity solutions with different operational weather years.

Loads MGA capacities from cache, applies them to the base network, and runs
dispatch optimization with weather from a different year.
"""

import json
import logging
import os
import pandas as pd
import numpy as np
import pypsa
import sys
from pathlib import Path
from _helpers import (
    configure_logging,
    set_scenario_config,
    update_config_from_wildcards,
)
from solve_network import prepare_network, collect_kwargs, create_optimization_model
from _benchmark import memory_logger
from test_operations import set_weather, set_co2_price, extract_shedding_metrics

logger = logging.getLogger(__name__)


def load_mga_capacities(file_path: str) -> pd.DataFrame:
    """
    Load MGA capacities from cache CSV file.

    Expected format (long format):
    component,name,attribute,value
    Generator,DE0 0 solar,p_nom_opt,150.5
    Store,DE0 0 battery,e_nom_opt,100.0

    Parameters
    ----------
    file_path : str
        Path to MGA capacities CSV file

    Returns
    -------
    pd.DataFrame
        MGA capacities in long format
    """
    return pd.read_csv(file_path)


def apply_mga_capacities(n: pypsa.Network, capacities_df: pd.DataFrame) -> None:
    """
    Apply MGA capacity values to network components.

    Parameters
    ----------
    n : pypsa.Network
        Network to modify
    capacities_df : pd.DataFrame
        MGA capacities in long format (component, name, attribute, value)
    """
    # Component name mapping for new PyPSA API
    component_map = {
        'Generator': 'generators',
        'Store': 'stores',
        'Link': 'links',
        'Line': 'lines',
        'StorageUnit': 'storage_units',
        'Load': 'loads',
        'Bus': 'buses',
    }
    for component in capacities_df["component"].unique():
        component_caps = capacities_df[capacities_df["component"] == component]

        # Get component dataframe using new API (removes deprecation warning)
        component_attr = component_map.get(component, component.lower())
        try:
            comp_df = getattr(n, component_attr)
        except AttributeError:
            continue

        for attribute in component_caps["attribute"].unique():
            attr_caps = component_caps[component_caps["attribute"] == attribute]

            # Set the attribute values
            for _, row in attr_caps.iterrows():
                name = row["name"]
                value = row["value"]

                # Check existence to prevent NaN rows (no warning spam)
                if name in comp_df.index:
                    comp_df.loc[name, attribute] = value



if __name__ == "__main__":
    if "snakemake" not in globals():
        from _helpers import mock_snakemake

        snakemake = mock_snakemake(
            "validation_mga",
            configfiles="config/mini-sector_droughts.yaml",
            opts="50seg-lv1.0",
            clusters="50",
            sector_opts="Co2L0.0+T+H+B+I+A",
            planning_horizons="2050",
            dir_hash="abc123de",  # Example hash
            operational_year="2019",
        )

    configure_logging(snakemake)
    set_scenario_config(snakemake)
    update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    solve_opts = snakemake.params.solving["options"]

    # Activate load shedding
    solve_opts["load_shedding"] = True

    np.random.seed(solve_opts.get("seed", 123))

    # Load base network and weather network
    n = pypsa.Network(snakemake.input.network)
    m = pypsa.Network(snakemake.input.weather_network)

    # Load and apply MGA capacities
    logger.info(f"Loading MGA capacities from {snakemake.input.mga_capacities}")
    mga_capacities = load_mga_capacities(snakemake.input.mga_capacities)

    # Add small operational buffer to avoid numerical infeasibilities
    # when operating with different weather patterns.
    # Buffer increases with each retry attempt.
    capacity_buffers = [0.001, 0.005, 0.01, 0.02]
    attempt = getattr(snakemake, "attempt", 1)
    buffer = capacity_buffers[min(attempt - 1, len(capacity_buffers) - 1)]
    logger.info(f"Adding {buffer*100:.2f}% operational buffer to all MGA capacities (attempt {attempt})")
    mga_capacities['value'] *= (1 + buffer)

    apply_mga_capacities(n, mga_capacities)
    logger.info(f"Applied MGA capacities for direction {snakemake.wildcards.dir_hash}")

    planning_horizons = snakemake.wildcards.get("planning_horizons", "")

    try:
        # Apply weather and fix capacities
        set_weather(n, m)
        n.optimize.fix_optimal_capacities()

        # NEW: set e_cyclic of co2 atmosphere to False
        if n.stores[n.stores['bus'] == 'co2 atmosphere'].e_cyclic.item() == True:
            idx = n.stores.index[n.stores["bus"].eq("co2 atmosphere")]
            n.stores.loc[idx, "e_cyclic"] = False

        # Prepare network
        prepare_network(
            n,
            solve_opts=solve_opts,
            foresight=snakemake.params.foresight,
            planning_horizons=planning_horizons,
            co2_sequestration_potential=snakemake.params["co2_sequestration_potential"],
            limit_max_growth=snakemake.params.get("sector", {}).get("limit_max_growth"),
        )

        # Apply CO2 price if configured
        logging_frequency = snakemake.config.get("solving", {}).get(
            "mem_logging_frequency", 30
        )
        if snakemake.config["run"]["stress_tests"].get("mode", "") == "co2-price":
            logger.info("Setting CO2 price based on previous optimization.")
            set_co2_price(n)

        # Solve network
        with memory_logger(
            filename=getattr(snakemake.log, "memory", None), interval=logging_frequency
        ) as mem:
            model_kwargs, solve_kwargs = collect_kwargs(
                snakemake.config,
                snakemake.params.solving,
                planning_horizons,
                log_fn=snakemake.log.solver,
                mode="single",
            )
            create_optimization_model(
                n,
                config=snakemake.config,
                params=snakemake.params,
                model_kwargs=model_kwargs,
                solve_kwargs=solve_kwargs,
                planning_horizons=planning_horizons,
            )
            status, condition = n.optimize.solve_model(**solve_kwargs)
            if status == "warning":
                logger.warning(
                    f"Solver status: {status}, condition: {condition}"
                )
                # Commented for large models
                # try:
                #     n.model.print_infeasibilities()
                # except AttributeError:
                #     logger.warning("print_infeasibilities not available in this pypsa version")

        logger.info(f"Maximum memory usage: {mem.mem_usage}")

        # Extract shedding metrics
        load_shedding, heat_shedding = extract_shedding_metrics(n)

        # Export shedding results (no full network to save disk space)
        load_shedding.round(3).to_csv(snakemake.output.load_shedding)
        heat_shedding.round(3).to_csv(snakemake.output.heat_shedding)

        # Record metadata so analysis can flag solutions that needed buffer relaxation.
        # Written alongside load_shedding but not tracked by snakemake as a required output.
        metadata_path = snakemake.output.load_shedding.replace("_load_shedding.csv", "_metadata.json")
        metadata = {
            "attempt": attempt,
            "buffer": buffer,
            "status": status,
            "condition": condition,
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        # -- Save validation network if iterations=0 and save_validation_network=True --
        n_iterations = snakemake.config.get("near-opt", {}).get("approx", {}).get("iterations", 1)
        save_val_network = snakemake.params.get("save_validation_network", False)

        if n_iterations == 0 and save_val_network:
            wc = snakemake.wildcards
            
            filename = f"{wc.network_hash}_{wc.dir_hash}_{wc.operational_year}.nc"
            out_path = Path(snakemake.params.results_dir) / filename
            
            # Ensure output directory exists before saving
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            n.export_to_netcdf(out_path)
            logger.info(f"Saved validation network → {out_path}")

        logger.info(f"MGA validation complete for direction {snakemake.wildcards.dir_hash}, year {snakemake.wildcards.operational_year}")

    except Exception as e:
          logger.exception(f"Error in MGA validation: {e}")  # Changed to .exception()
          import traceback
          traceback.print_exc()  # Print full traceback
          sys.exit(1)
