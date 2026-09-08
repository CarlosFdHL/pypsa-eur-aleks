"""Adds a constraint to enforce cyclic behaviour on long-term storages for each contiguous block of snapshots in the model
independently on their foresight.

Long-term storages included:
- H2 storage
- Gas storage
- Water pits
- Reservoir & Dan
"""

import logging
import pandas as pd
from _helpers import PYPSA_V1

logger = logging.getLogger(__name__)


def cyclic_per_weather_year(n, snapshots, snakemake):
    if n._multi_invest:
        logger.info("Multi-investment detected; not required to enforce cyclic behaviour per weather year.")
        return
    
    # Detects blocks by gaps in the temporal index
    sns = pd.Index(snapshots)
    diffs = sns.to_series().diff()
    step = diffs.median()
    block = (diffs > 2 * step).cumsum()
    last_sns = [grp.index[-1] for _, grp in block.groupby(block)]

    if len(last_sns) < 2:
        logger.info("Only one contiguous block; nothing to constrain.")
        return
    
    carriers = ["H2", "water pits", "gas"]
    mask = n.stores.e_cyclic & n.stores.carrier.str.contains("|".join(carriers))
    stores = n.stores.index[mask]

    su_mask = n.storage_units.cyclic_state_of_charge & (n.storage_units.carrier == "hydro")
    sus = n.storage_units.index[su_mask]

    if stores.empty and sus.empty:
        logger.info("No seasonal storage found; nothing to constrain.")
        return

    ref = last_sns[-1]
    n_constraints = 0

    if not stores.empty:
        for names in stores:
            v = n.model["Store-e"]
            dim = next(x for x in v.dims if x != "snapshot")
            for t in last_sns[:-1]:
                lhs = v.sel({"snapshot": t, dim: names}) - v.sel({"snapshot": ref, dim: names})
                n.model.add_constraints(lhs == 0, name=f"cyclic-store-block-{names}-{t:%Y%m%d}")
                n_constraints += 1
    if not sus.empty:
        for names in sus:
            v = n.model["StorageUnit-state_of_charge"]
            dim = next(x for x in v.dims if x != "snapshot")
            for t in last_sns[:-1]:
                lhs = v.sel({"snapshot": t, dim: names}) - v.sel({"snapshot": ref, dim: names})
                n.model.add_constraints(lhs == 0, name=f"cyclic-storage_unit-block-{names}-{t:%Y%m%d}")
                n_constraints += 1

    logger.info(
        f"Cyclic storage per weather year: {len(last_sns)} blocks, "
        f"{len(stores)} stores, {len(sus)} storage units, "
        f"{n_constraints} constraints added."
    )
