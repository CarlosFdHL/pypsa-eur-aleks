#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: : 2025 Aleksander Grochowicz
#
# SPDX-License-Identifier: MIT
"""
Generate mock MGA capacities for testing validation_mga workflow.

This script creates fake MGA capacity variations based on an existing
optimized network, allowing you to test the validation workflow without
needing real MGA results.

Usage:
    python scripts/generate_mock_mga_capacities.py \
        --network results/networks/base_s_50_elec_50seg-lv1.0.nc \
        --output-dir mga-cache \
        --network-hash testnet \
        --n-directions 3 \
        --variation 0.2
"""

import argparse
import logging
import pandas as pd
import pypsa
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


def extract_capacities(n: pypsa.Network) -> pd.DataFrame:
    """
    Extract all optimal capacities from network in long format.

    Returns DataFrame with columns: component, name, attribute, value
    """
    capacities = []

    # Generator p_nom_opt
    for name, gen in n.generators.iterrows():
        if gen.get('p_nom_extendable', False) or 'p_nom_opt' in n.generators.columns:
            value = gen.get('p_nom_opt', gen.get('p_nom', 0.0))
            if value > 0:  # Only include non-zero capacities
                capacities.append({
                    'component': 'Generator',
                    'name': name,
                    'attribute': 'p_nom_opt',
                    'value': value
                })

    # StorageUnit p_nom_opt
    for name, su in n.storage_units.iterrows():
        if su.get('p_nom_extendable', False) or 'p_nom_opt' in n.storage_units.columns:
            value = su.get('p_nom_opt', su.get('p_nom', 0.0))
            if value > 0:
                capacities.append({
                    'component': 'StorageUnit',
                    'name': name,
                    'attribute': 'p_nom_opt',
                    'value': value
                })

    # Store e_nom_opt
    for name, store in n.stores.iterrows():
        if store.get('e_nom_extendable', False) or 'e_nom_opt' in n.stores.columns:
            value = store.get('e_nom_opt', store.get('e_nom', 0.0))
            if value > 0:
                capacities.append({
                    'component': 'Store',
                    'name': name,
                    'attribute': 'e_nom_opt',
                    'value': value
                })

    # Link p_nom_opt
    for name, link in n.links.iterrows():
        if link.get('p_nom_extendable', False) or 'p_nom_opt' in n.links.columns:
            value = link.get('p_nom_opt', link.get('p_nom', 0.0))
            if value > 0:
                capacities.append({
                    'component': 'Link',
                    'name': name,
                    'attribute': 'p_nom_opt',
                    'value': value
                })

    # Line s_nom_opt
    for name, line in n.lines.iterrows():
        if line.get('s_nom_extendable', False) or 's_nom_opt' in n.lines.columns:
            value = line.get('s_nom_opt', line.get('s_nom', 0.0))
            if value > 0:
                capacities.append({
                    'component': 'Line',
                    'name': name,
                    'attribute': 's_nom_opt',
                    'value': value
                })

    return pd.DataFrame(capacities)


def vary_capacities(df: pd.DataFrame, variation: float, seed: int) -> pd.DataFrame:
    """
    Apply random variation to capacities to simulate MGA.

    Parameters
    ----------
    df : pd.DataFrame
        Base capacities
    variation : float
        Maximum relative variation (e.g., 0.2 = ±20%)
    seed : int
        Random seed for reproducibility

    Returns
    -------
    pd.DataFrame
        Varied capacities
    """
    import numpy as np

    df = df.copy()
    rng = np.random.RandomState(seed)

    # Apply random variation: value * (1 + uniform(-variation, +variation))
    factors = 1 + rng.uniform(-variation, variation, size=len(df))
    df['value'] = df['value'] * factors

    # Ensure non-negative
    df['value'] = df['value'].clip(lower=0)

    return df


def main():
    parser = argparse.ArgumentParser(description='Generate mock MGA capacities for testing')
    parser.add_argument('--network', required=True, help='Path to optimized network file')
    parser.add_argument('--output-dir', default='mga-cache', help='Output directory for capacities')
    parser.add_argument('--network-hash', default='testnet', help='Network hash identifier')
    parser.add_argument('--n-directions', type=int, default=3, help='Number of MGA directions to generate')
    parser.add_argument('--variation', type=float, default=0.2, help='Maximum capacity variation (0.2 = ±20%)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')

    args = parser.parse_args()

    # Load network
    logger.info(f"Loading network from {args.network}")
    n = pypsa.Network(args.network)

    # Extract base capacities
    logger.info("Extracting capacities from network")
    base_capacities = extract_capacities(n)
    logger.info(f"Extracted {len(base_capacities)} capacity values")

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    # Generate mock MGA directions
    for i in range(args.n_directions):
        dir_hash = f"test{i:03d}"  # test000, test001, test002, ...

        # Vary capacities
        if i == 0:
            # First direction = base case (no variation)
            varied_caps = base_capacities.copy()
        else:
            # Subsequent directions = varied
            varied_caps = vary_capacities(base_capacities, args.variation, seed=args.seed + i)

        # Save to file
        output_file = output_dir / f"caps_{args.network_hash}_{dir_hash}.csv"
        varied_caps.to_csv(output_file, index=False)
        logger.info(f"Saved {len(varied_caps)} capacities to {output_file}")

    logger.info(f"\nGenerated {args.n_directions} mock MGA capacity files")
    logger.info(f"Network hash: {args.network_hash}")
    logger.info(f"Direction hashes: test000, test001, ..., test{args.n_directions-1:03d}")
    logger.info(f"\nTo test validation_mga, use wildcards:")
    logger.info(f"  network_hash={args.network_hash}")
    logger.info(f"  dir_hash=test000 (or test001, test002, ...)")


if __name__ == "__main__":
    main()
