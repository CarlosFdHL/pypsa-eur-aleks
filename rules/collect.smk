# SPDX-FileCopyrightText: 2025 Aleksander Grochowicz & Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT

import yaml
import pandas as pd
from pathlib import Path

def design_years(file_path):
    with open(file_path, 'r') as file:
        data = yaml.safe_load(file)
    return list(data.keys())

def test_years(file_path):
    with open(file_path, 'r') as file:
        data = yaml.safe_load(file)
    return list(data.keys())

def network_year(config):
    if config["run"]["fixed_network"].get("enable", False):
        return config["run"]["fixed_network"]["scenario"]
    else:
        return None


def get_mga_directions(near_opt_file):
    """
    Extract MGA direction hashes from a near_opt_solutions CSV file.

    Parameters
    ----------
    near_opt_file : str or Path
        Path to near_opt_solutions CSV file

    Returns
    -------
    list
        List of dir_hash values
    """
    file_path = Path(near_opt_file)
    if not file_path.exists():
        return []

    try:
        df = pd.read_csv(file_path)
        if 'dir_hash' in df.columns:
            return df['dir_hash'].tolist()
        else:
            return []
    except Exception as e:
        print(f"Warning: Could not read MGA directions from {near_opt_file}: {e}")
        return []


def get_network_hash_from_cache(cache_dir):
    """
    Extract network hash from MGA cache directory.

    Looks for cache files matching pattern: mga_cache_{network_hash}.csv

    Parameters
    ----------
    cache_dir : str or Path
        Path to cache directory

    Returns
    -------
    list
        List of network_hash values
    """
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return []

    network_hashes = []
    for cache_file in cache_path.glob('mga_cache_*.csv'):
        # Extract hash from filename: mga_cache_{hash}.csv
        hash_value = cache_file.stem.replace('mga_cache_', '')
        network_hashes.append(hash_value)

    return network_hashes


def get_network_hash_for_near_opt(near_opt_file, cache_dir, design_year=None, scenario=None):
    """
    Get the network hash from the network_hash txt file.

    Reads the network hash from the corresponding hash file in the same
    directory as the near_opt CSV file.

    Parameters
    ----------
    near_opt_file : str or Path
        Path to near_opt_solutions CSV file
    cache_dir : str or Path
        Path to cache directory (unused, kept for compatibility)
    design_year : str, optional
        Design year (unused, kept for compatibility)
    scenario : str, optional
        Scenario string (unused, kept for compatibility)

    Returns
    -------
    str or None
        Network hash from the hash file, or None if not found
    """
    near_opt_path = Path(near_opt_file)
    if not near_opt_path.exists():
        return None

    # Construct hash filename by replacing .csv with _network_hash.txt
    # e.g., base_s_50___2050.csv -> base_s_50___2050_network_hash.txt
    hash_file = near_opt_path.with_suffix('').with_suffix('').parent / (near_opt_path.stem + "_network_hash.txt")

    if not hash_file.exists():
        print(f"Warning: {hash_file} not found")
        return None

    try:
        network_hash = hash_file.read_text().strip()
        return network_hash
    except Exception as e:
        print(f"Warning: Could not read network_hash from {hash_file}: {e}")
        return None



localrules:
    all,
    cluster_networks,
    prepare_elec_networks,
    prepare_sector_networks,
    solve_elec_networks,
    solve_sector_networks,
    test_networks,
    compute_mga_solutions,
    validate_mga_solutions,


rule process_costs:
    input:
        lambda w: (
            expand(
                resources(
                    f"costs_{config_provider('costs', 'year')(w)}_processed.csv"
                ),
                run=config["run"]["name"],
            )
            if config_provider("foresight")(w) == "overnight"
            else expand(
                resources("costs_{planning_horizons}_processed.csv"),
                **config["scenario"],
                run=config["run"]["name"],
            )
        ),


rule cluster_networks:
    message:
        "Collecting clustered network files"
    input:
        expand(
            resources("networks/base_s_{clusters}.nc"),
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule prepare_elec_networks:
    message:
        "Collecting prepared electricity network files"
    input:
        expand(
            resources("networks/base_s_{clusters}_elec_{opts}.nc"),
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule prepare_sector_networks:
    message:
        "Collecting prepared sector-coupled network files"
    input:
        expand(
            resources(
                "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc"
            ),
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule solve_elec_networks:
    message:
        "Collecting solved electricity network files"
    input:
        expand(
            RESULTS + "networks/base_s_{clusters}_elec_{opts}.nc",
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule solve_sector_networks:
    message:
        "Collecting solved sector-coupled network files"
    input:
        expand(
            RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule solve_sector_networks_perfect:
    message:
        "Collecting solved sector-coupled network files with perfect foresight"
    input:
        expand(
            RESULTS
            + "maps/static/base_s_{clusters}_{opts}_{sector_opts}-costs-all_{planning_horizons}.pdf",
            **config["scenario"],
            run=config["run"]["name"],
        ),

rule test_networks:
    input:
        expand(
            "results/" + config["run"]["prefix"] + "/{design_year}/validation/{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_load_shedding.csv",
            operational_year = test_years(config["run"]["stress_tests"]["stress_years"]),
            **config["scenario"],
            design_year = design_years(config["run"]["stress_tests"]["design_years"]),
            run=config["run"]["name"],
        ),


rule compute_mga_solutions:
    """Compute all near-optimal (MGA) solutions for specified design years."""
    input:
        lambda w: expand(
            "results/" + config["run"]["prefix"] + "/{design_year}/near_opt/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
            design_year=design_years(config["run"]["stress_tests"]["design_years"]),
            **config["scenario"],
        ) if config.get("near-opt", {}).get("enable", False) else [],


rule collect_mga_summaries:
    """Collect MGA validation summaries for all design years."""
    input:
        lambda w: [
            f"results/{config['run']['prefix']}/{design_year}/validation/_summary_{scenario}.csv"
            for design_year in design_years(config["run"]["stress_tests"]["design_years"])
            for scenario in expand("base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}", **config["scenario"])
        ] if config.get("near-opt", {}).get("validation", {}).get("enable", False) else [],


rule validate_mga_solutions:
    """Validate all MGA capacity solutions with different operational weather years."""
    input:
        lambda w: [
            f"results/{config['run']['prefix']}/{design_year}/validation/mga_{network_hash}_{dir_hash}_{operational_year}_{scenario}_load_shedding.csv"
            # Static loops from config
            for design_year in design_years(config["run"]["stress_tests"]["design_years"])
            for operational_year in test_years(config["run"]["stress_tests"]["stress_years"])
            for scenario in expand("base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}", **config["scenario"])
            # Dynamic lookups from files
            for near_opt_file in [f"results/{config['run']['prefix']}/{design_year}/near_opt/{scenario}.csv"]
            for network_hash in [get_network_hash_for_near_opt(near_opt_file, config.get("near-opt", {}).get("cache_dir", "mga-cache"), design_year=design_year, scenario=scenario) or ""]
            for dir_hash in get_mga_directions(near_opt_file)
            if network_hash  # Skip if network_hash lookup failed
        ] if config.get("near-opt", {}).get("validation", {}).get("enable", False) else [],

rule validation_mga_all:
    input:
        lambda w: [
            f"results/{config['run']['prefix']}/{design_year}/validation/"
            f"mga_{network_hash}_{dir_hash}_{operational_year}_{scenario}_load_shedding.csv"
            for design_year in design_years(config["run"]["stress_tests"]["design_years"])
            for operational_year in test_years(config["run"]["stress_tests"]["stress_years"])
            for scenario in expand("base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}", **config["scenario"])
            for near_opt_file in [f"results/{config['run']['prefix']}/{design_year}/near_opt/{scenario}.csv"]
            for network_hash in [get_network_hash_for_near_opt(
                near_opt_file,
                config.get("near-opt", {}).get("cache_dir", "mga-cache"),
                design_year=design_year,
                scenario=scenario,
            ) or ""]
            for dir_hash in get_mga_directions(near_opt_file)
            if network_hash
        ] + [
            f"results/{config['run']['prefix']}/{design_year}/validation/"
            f"mga_{network_hash}_{dir_hash}_{operational_year}_{scenario}_heat_shedding.csv"
            for design_year in design_years(config["run"]["stress_tests"]["design_years"])
            for operational_year in test_years(config["run"]["stress_tests"]["stress_years"])
            for scenario in expand("base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}", **config["scenario"])
            for near_opt_file in [f"results/{config['run']['prefix']}/{design_year}/near_opt/{scenario}.csv"]
            for network_hash in [get_network_hash_for_near_opt(
                near_opt_file,
                config.get("near-opt", {}).get("cache_dir", "mga-cache"),
                design_year=design_year,
                scenario=scenario,
            ) or ""]
            for dir_hash in get_mga_directions(near_opt_file)
            if network_hash
        ]

def balance_map_paths(kind, w):
    """
    kind = "static" or "interactive"
    """
    cfg_key = "balance_map" if kind == "static" else "balance_map_interactive"

    return expand(
        RESULTS
        + f"maps/{kind}/base_s_{{clusters}}_{{opts}}_{{sector_opts}}_{{planning_horizons}}"
        f"-balance_map_{{carrier}}.{'pdf'if kind== 'static' else 'html'}",
        **config["scenario"],
        run=config["run"]["name"],
        carrier=config_provider("plotting", cfg_key, "bus_carriers")(w),
    )


rule plot_balance_maps:
    message:
        "Plotting energy balance maps"
    input:
        static=lambda w: balance_map_paths("static", w),
        interactive=lambda w: balance_map_paths("interactive", w),


rule plot_balance_maps_static:
    input:
        lambda w: balance_map_paths("static", w),


rule plot_balance_maps_interactive:
    input:
        lambda w: balance_map_paths("interactive", w),


rule plot_power_networks_clustered:
    message:
        "Plotting clustered power network topology"
    input:
        expand(
            resources("maps/power-network-s-{clusters}.pdf"),
            **config["scenario"],
            run=config["run"]["name"],
        ),
