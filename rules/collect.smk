# SPDX-FileCopyrightText: 2025 Aleksander Grochowicz & Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT

import yaml
import pandas as pd
import hashlib
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


def compute_network_hash(network_file):
    """
    Compute MD5 hash of a network file.

    Parameters
    ----------
    network_file : str or Path
        Path to network .nc file

    Returns
    -------
    str or None
        First 8 characters of MD5 hash, or None if file doesn't exist
    """
    file_path = Path(network_file)
    if not file_path.exists():
        return None

    try:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):  # 64kb chunks
                hasher.update(chunk)
        # Return first 8 characters like other hashes in the system
        return hasher.hexdigest()[:8]
    except Exception as e:
        print(f"Warning: Could not compute hash for {network_file}: {e}")
        return None


def get_network_hash_for_near_opt(near_opt_file, cache_dir, design_year=None, scenario=None):
    """
    Get the specific network hash for a given near_opt CSV file.

    Computes the hash directly from the network file used for that design_year.

    Parameters
    ----------
    near_opt_file : str or Path
        Path to near_opt_solutions CSV file (used for validation only)
    cache_dir : str or Path
        Path to cache directory (unused, kept for compatibility)
    design_year : str, optional
        Design year (e.g., 'weather_year_2013_3H')
    scenario : str, optional
        Scenario string (e.g., 'base_s_50_lv1.0_50seg_Co2L0.0+T+H+B+I+A_2050')

    Returns
    -------
    str or None
        Network hash for this design_year, or None if not found
    """
    if design_year is None or scenario is None:
        return None

    # Construct path to network file for this design_year
    network_file = (
        f"results/{config['run']['prefix']}/{design_year}/networks/"
        f"{scenario}.nc"
    )

    return compute_network_hash(network_file)



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


rule cluster_networks:
    input:
        expand(
            resources("networks/base_s_{clusters}.nc"),
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule prepare_elec_networks:
    input:
        expand(
            resources("networks/base_s_{clusters}_elec_{opts}.nc"),
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule prepare_sector_networks:
    input:
        expand(
            resources(
                "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc"
            ),
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule solve_elec_networks:
    input:
        expand(
            RESULTS + "networks/base_s_{clusters}_elec_{opts}.nc",
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule solve_sector_networks:
    input:
        expand(
            RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            **config["scenario"],
            run=config["run"]["name"],
        ),


rule solve_sector_networks_perfect:
    input:
        expand(
            RESULTS
            + "maps/base_s_{clusters}_{opts}_{sector_opts}-costs-all_{planning_horizons}.pdf",
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


rule plot_balance_maps:
    input:
        lambda w: expand(
            (
                RESULTS
                + "maps/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}-balance_map_{carrier}.pdf"
            ),
            **config["scenario"],
            run=config["run"]["name"],
            carrier=config_provider("plotting", "balance_map", "bus_carriers")(w),
        ),


rule plot_power_networks_clustered:
    input:
        expand(
            resources("maps/power-network-s-{clusters}.pdf"),
            **config["scenario"],
            run=config["run"]["name"],
        ),