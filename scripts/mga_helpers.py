# SPDX-FileCopyrightText: 2025 Aleksander Grochowicz
#
# SPDX-License-Identifier: MIT

"""Helper functions for MGA (Modeling to Generate Alternatives) workflows."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def extract_optimal_capacities(n):
    """
    Extract all optimal capacities from a solved PyPSA network.

    Parameters
    ----------
    n : pypsa.Network
        Solved PyPSA network

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: component, name, attribute, value
        Contains all optimal capacities from the network (including zeros).
    """
    capacities = []

    # Generator p_nom_opt
    if "p_nom_opt" in n.generators.columns:
        for name, gen in n.generators.iterrows():
            value = gen.get("p_nom_opt", 0.0)
            capacities.append(
                {
                    "component": "Generator",
                    "name": name,
                    "attribute": "p_nom_opt",
                    "value": value,
                }
            )

    # StorageUnit p_nom_opt
    if "p_nom_opt" in n.storage_units.columns:
        for name, su in n.storage_units.iterrows():
            value = su.get("p_nom_opt", 0.0)
            capacities.append(
                {
                    "component": "StorageUnit",
                    "name": name,
                    "attribute": "p_nom_opt",
                    "value": value,
                }
            )

    # Store e_nom_opt
    if "e_nom_opt" in n.stores.columns:
        for name, store in n.stores.iterrows():
            value = store.get("e_nom_opt", 0.0)
            capacities.append(
                {
                    "component": "Store",
                    "name": name,
                    "attribute": "e_nom_opt",
                    "value": value,
                }
            )

    # Link p_nom_opt
    if "p_nom_opt" in n.links.columns:
        for name, link in n.links.iterrows():
            value = link.get("p_nom_opt", 0.0)
            capacities.append(
                {
                    "component": "Link",
                    "name": name,
                    "attribute": "p_nom_opt",
                    "value": value,
                }
            )

    # Line s_nom_opt
    if "s_nom_opt" in n.lines.columns:
        for name, line in n.lines.iterrows():
            value = line.get("s_nom_opt", 0.0)
            capacities.append(
                {
                    "component": "Line",
                    "name": name,
                    "attribute": "s_nom_opt",
                    "value": value,
                }
            )

    return pd.DataFrame(capacities)


def export_mga_capacities(n, snapshots, cache_dir, network_hash, direction_hash, check_only=False):
    """
    Export or check optimal capacities (and optionally the network) for an MGA solution.

    This function is designed to be used as mga_extra_functionality callback
    in pypsa-mga optimization.

    Parameters
    ----------
    n : pypsa.Network or None
        Solved PyPSA network (None when check_only=True)
    snapshots : pd.DatetimeIndex
        Snapshots used in optimization
    cache_dir : str
        Cache directory for storing results
    network_hash : str
        Network configuration hash
    direction_hash : str
        Direction vector hash
    check_only : bool, default False
        If True, only check if capacities file exists and return bool.
        If False, extract and export capacities and network.

    Returns
    -------
    bool (only when check_only=True)
        True if capacities file exists, False otherwise
    """
    # Construct output paths
    caps_dir = Path(cache_dir) / "caps"
    caps_file = caps_dir / f"caps_{network_hash}_{direction_hash}.csv"

    networks_dir = Path(cache_dir) / "networks"
    network_file = networks_dir / f"{network_hash}_{direction_hash}.nc"

    if check_only:
        return caps_file.exists()

    # Export capacities
    caps_dir.mkdir(parents=True, exist_ok=True)
    capacities = extract_optimal_capacities(n)
    capacities.to_csv(caps_file, index=False)
    logger.info(f"Exported {len(capacities)} capacities to {caps_file.name}")

    # Export network
    networks_dir.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(network_file))
    logger.info(f"Exported network to {network_file.name}")