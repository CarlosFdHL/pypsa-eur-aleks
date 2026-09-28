"""Adds constraints that make each contiguous block of snapshots (e.g. each weather year)
behave independently, regardless of the model's foresight.

Blocks are detected from gaps in the temporal index (a gap larger than twice the median time step).
If the network uses multi-investment periods, or only one contiguous block is found, no constraints are added.

1. Cyclic long-term storage per block:
   For every cyclic store and storage unit, the state of charge at the first snapshot of each block is set
   equal to the state of charge at its last snapshot. 

2. CO2 atmosphere budget per block:
   For every global constraint of type 'co2_atmosphere', the net CO2 accumulated in the atmosphere store
   within each block must not exceed that block's share of the budget:
       e(t_end_k) - e(t_end_{k-1}) <= constant * w_k / sum(w)
   Here w_k is the sum of the store snapshot weightings in block k.
   The first block uses the store's e_initial in place of the previous block's end level.
   These constraints are named 'co2_atmosphere-block-<name>-<store>-<date>'. Their duals give the CO2 price
   of each block and are not written to n.global_constraints.mu.
   The original global co2_atmosphere constraint is implied by these and becomes redundant.
"""
import logging
import pandas as pd
from _helpers import PYPSA_V1

logger = logging.getLogger(__name__)

def co2_atmosphere_per_block(n, block, last_sns):
    """Split the co2_atmosphere budget across contiguous snapshot blocks
    and constrain the net atmospheric CO2 accumulation within each block."""
    glcs = n.global_constraints.query("type == 'co2_atmosphere'")
    if glcs.empty:
        logger.info("No co2_atmosphere global constraint; skipping per-block CO2 budget.")
        return 0

    v = n.model["Store-e"]
    dim = next(x for x in v.dims if x != "snapshot")

    # Share of the total budget per block, proportional to snapshot weightings
    w = n.snapshot_weightings.stores.loc[block.index]
    block_share = w.groupby(block).sum() / w.sum()

    n_constraints = 0
    for name, glc in glcs.iterrows():
        carattr = glc.carrier_attribute
        emissions = n.carriers.query(f"{carattr} != 0")[carattr]
        if emissions.empty:
            continue

        bus_carrier = n.stores.bus.map(n.buses.carrier)
        stores = n.stores.index[bus_carrier.isin(emissions.index) & ~n.stores.e_cyclic]

        for s in stores:
            t_prev = None
            for k, t1 in enumerate(last_sns):
                budget = glc.constant * block_share.iloc[k]
                e_end = v.sel({"snapshot": t1, dim: s})

                if t_prev is None:
                    # First block starts from the store's initial level
                    lhs = e_end
                    rhs = budget + n.stores.at[s, "e_initial"]
                else:
                    lhs = e_end - v.sel({"snapshot": t_prev, dim: s})
                    rhs = budget

                n.model.add_constraints(
                    lhs <= rhs, name=f"co2_atmosphere-block-{name}-{s}-{t1:%Y%m%d}"
                )
                n_constraints += 1
                t_prev = t1

    return n_constraints


def cyclic_per_weather_year(n, snapshots, snakemake):
    if n._multi_invest:
        logger.info("Multi-investment detected; not required to enforce cyclic behaviour per weather year.")
        return

    # Detect blocks by gaps in the temporal index
    sns = pd.Index(snapshots)
    diffs = sns.to_series().diff()
    step = diffs.median()
    block = (diffs > 2 * step).cumsum()
    first_sns = [grp.index[0] for _, grp in block.groupby(block)]
    last_sns = [grp.index[-1] for _, grp in block.groupby(block)]

    if len(last_sns) < 2:
        logger.info("Only one contiguous block; nothing to constrain.")
        return

    # Per-block CO2 budget 
    n_co2 = co2_atmosphere_per_block(n, block, last_sns)
    logger.info(f"CO2 atmosphere budget per block: {n_co2} constraints added.")

    mask = n.stores.e_cyclic
    stores = n.stores.index[mask]

    su_mask = n.storage_units.cyclic_state_of_charge
    sus = n.storage_units.index[su_mask]

    if stores.empty and sus.empty:
        logger.info("No seasonal storage found; nothing to constrain.")
        return

    n_constraints = 0

    if not stores.empty:
        v = n.model["Store-e"]
        dim = next(x for x in v.dims if x != "snapshot")
        for names in stores:
            for t0, t1 in zip(first_sns, last_sns):
                lhs = v.sel({"snapshot": t0, dim: names}) - v.sel({"snapshot": t1, dim: names})
                n.model.add_constraints(lhs == 0, name=f"cyclic-store-block-{names}-{t1:%Y%m%d}")
                n_constraints += 1

    if not sus.empty:
        v = n.model["StorageUnit-state_of_charge"]
        dim = next(x for x in v.dims if x != "snapshot")
        for names in sus:
            for t0, t1 in zip(first_sns, last_sns):
                lhs = v.sel({"snapshot": t0, dim: names}) - v.sel({"snapshot": t1, dim: names})
                n.model.add_constraints(lhs == 0, name=f"cyclic-storage_unit-block-{names}-{t1:%Y%m%d}")
                n_constraints += 1

    logger.info(
        f"Cyclic storage per weather year: {len(last_sns)} blocks, "
        f"{len(stores)} stores, {len(sus)} storage units, "
        f"{n_constraints} constraints added."
    )