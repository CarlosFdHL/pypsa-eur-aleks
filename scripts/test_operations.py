# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: : 2023-2025 Aleksander Grochowicz & Koen van Greevenbroek
#
# SPDX-License-Identifier: MIT
"""
Solves linear optimal dispatch in hourly resolution using the capacities of
previous capacity expansion in rule `solve_network`.
"""

import json
import logging

import numpy as np
import pandas as pd
import pypsa
import sys
from _helpers import (
    configure_logging,
    set_scenario_config,
    update_config_from_wildcards,
)
from solve_network import prepare_network, collect_kwargs, create_optimization_model
from _benchmark import memory_logger

logger = logging.getLogger(__name__)


def set_weather(
    n: pypsa.Network,
    n_weather: pypsa.Network,
) -> None:
    """Set weather-dependent parameters from n_weather to n."""
    for c, attr in [
        ("Generator", "p_max_pu"),
        ("StorageUnit", "p_max_pu"),
        ("StorageUnit", "inflow"),
        ("Load", "p_set"),
        ("Link", "efficiency")
    ]:
        target = n.pnl(c)[attr]
        source = n_weather.pnl(c)[attr].values

        # Check if the source has the same shape as the target
        if target.shape != source.shape:
            logger.error(
                f"Shape mismatch between source and target for {c} {attr}: "
                f"{source.shape} != {target.shape}"
            )
            raise ValueError(
                f"Shape mismatch between source and target for {c} {attr}: "
                f"{source.shape} != {target.shape}"
            )
        else:
            target.loc[:, :] = source

class NetworkSyncError(Exception):
    """Design and weather networks cannot be synced."""
class MissingWeatherDependentError(NetworkSyncError): pass
class NoProxyProfileError(NetworkSyncError): pass
class InconsistentTimeSeriesError(NetworkSyncError): pass
class InconsistentTopologyError(NetworkSyncError): pass


# Order matters: carriers and buses are added first and removed last
SYNC_COMPONENTS = ["Carrier", "Bus", "Line", "Transformer", "Link", "Generator", "Load", "StorageUnit", "Store"]
# Similar technologies at the same location, in order of priority
PROXY_CARRIERS = {
    "offwind-float": ["offwind-dc", "offwind-ac"],
    "offwind-dc": ["offwind-ac", "offwind-float"],
    "offwind-ac": ["offwind-dc", "offwind-float"],
    "solar": ["solar-hsat", "solar rooftop"],
    "solar-hsat": ["solar", "solar rooftop"],
    "solar rooftop": ["solar", "solar-hsat"],
}
# Added later by prepare_network: never copied nor removed
EXCLUDED = ""


def input_ts(n: pypsa.Network, c: str, name: str = None) -> list:
    """Input time series attributes of class c (only those of component `name`, if given)."""
    attrs = n.components[c].attrs
    out = [a for a in n.pnl(c) if a in attrs.index and str(attrs.at[a, "status"]).startswith("Input")]
    return out if name is None else [a for a in out if name in n.pnl(c)[a].columns]


def find_proxy(n: pypsa.Network, n_weather: pypsa.Network, name: str):
    """(proxy, scale, profile) of the first similar technology at the same location, or None."""
    loc = n.generators.bus.map(n.buses.location) if "location" in n.buses else n.generators.bus
    loc = loc.where(loc.fillna("") != "", n.generators.bus)
    ts, ts_weather = n.generators_t.p_max_pu, n_weather.generators_t.p_max_pu
    w = n.snapshot_weightings.generators
    cf = lambda s: (s * w).sum() / w.sum()
    for carrier in PROXY_CARRIERS[n.generators.at[name, "carrier"]]:
        found = loc.index[(n.generators.carrier == carrier) & (loc == loc[name])]
        found = sorted(found.intersection(ts.columns).intersection(ts_weather.columns))
        if found and cf(ts[found[0]]) > 0:
            scale = cf(ts[name]) / cf(ts[found[0]])
            return found[0], scale, (ts_weather[found[0]] * scale).clip(upper=1)
    return None


def sync_components(n: pypsa.Network, n_weather: pypsa.Network) -> None:
    """Make n_weather contain exactly the components of the design network n.

    Phase 1, validation (read only). All issues are collected and raised
    together; n_weather is not modified if any issue is found.
    - Missing component (in n, not in n_weather):
        * no input time series in n: copied from n.
        * Generator with only p_max_pu and carrier in PROXY_CARRIERS (offshore
          wind, solar variants): copied from n; p_max_pu = weather-year profile
          of the first similar technology at the same bus location, scaled by
          the ratio of their design capacity factors (weighted by snapshot
          weightings) and clipped to 1. No valid proxy: NoProxyProfileError.
        * anything else with time series (EV, hydro, ror, heat pumps, onwind,
          solar thermal, time-varying loads...): MissingWeatherDependentError.
    - Common component with a time series in only one network:
      InconsistentTimeSeriesError.
    - Component kept in n_weather referring to a bus or carrier not in n:
      InconsistentTopologyError.

    Phase 2, modification.
    - Extra components (in n_weather, not in n) are removed, logged with
      timestamp and names; weather-dependent ones are flagged.
    - Missing components are added (copies and proxies).
    Common components keep their weather-year time series. Components matching
    EXCLUDED are ignored. Capacities are set afterwards in set_capacities.
    """
    issues, remove, add, proxies = [], {}, {}, {}
    keep = lambda idx: idx[~idx.str.contains(EXCLUDED)] if len(idx) else idx

    for c in SYNC_COMPONENTS:
        # Check for missing components and time series inconsistencies
        df, df_weather = n.df(c), n_weather.df(c)
        # 
        remove[c] = keep(df_weather.index.difference(df.index))
        add[c] = []
        for name in keep(df.index.difference(df_weather.index)):
            ts = input_ts(n, c, name)
            carrier = df.at[name, "carrier"] if "carrier" in df else ""
            if not ts:
                add[c].append(name)
            elif c == "Generator" and carrier in PROXY_CARRIERS and ts == ["p_max_pu"]:
                proxies[name] = find_proxy(n, n_weather, name)
                add[c].append(name)
                if proxies[name] is None:
                    issues.append((NoProxyProfileError, f"Generator '{name}' ({carrier}): no {PROXY_CARRIERS[carrier]} with profile at same location in both networks"))
            else:
                issues.append((MissingWeatherDependentError, f"{c} '{name}' ({carrier}): missing, has time series {ts} in design network"))

        common = df.index.intersection(df_weather.index)
        for a in input_ts(n, c):
            one_side = common.intersection(n.pnl(c)[a].columns).symmetric_difference(common.intersection(n_weather.pnl(c)[a].columns))
            issues += [(InconsistentTimeSeriesError, f"{c} '{name}': '{a}' is a time series in only one network") for name in one_side]

        kept = df_weather.drop(remove[c])
        for col in [col for col in kept if col == "carrier" or col.rstrip("0123456789") == "bus"]:
            valid = n.carriers.index if col == "carrier" else n.buses.index
            bad = kept[col][(kept[col] != "") & ~kept[col].isin(valid)]
            issues += [(InconsistentTopologyError, f"{c} '{name}': {col} '{ref}' not in design network") for name, ref in bad.items()]

    if issues:
        classes = {cls for cls, _ in issues}
        msg = f"Weather network not modified, {len(issues)} issue(s):\n" + "\n".join(f"  [{cls.__name__}] {m}" for cls, m in issues)
        raise (classes.pop() if len(classes) == 1 else NetworkSyncError)(msg)

    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    for c in reversed(SYNC_COMPONENTS):
        if remove[c].empty:
            continue
        weather_dependent = [name for name in remove[c] if input_ts(n_weather, c, name)]
        logger.warning(
            f"[{now}] REMOVED {len(remove[c])} {c} from weather network (not in design network): {list(remove[c])}"
            + (f". WEATHER-DEPENDENT, check configs: {weather_dependent}" if weather_dependent else "")
        )
        n_weather.remove(c, remove[c])
    for c in SYNC_COMPONENTS:
        if add[c]:
            cols = n.df(c).columns.intersection(n_weather.df(c).columns)
            n_weather.add(c, add[c], **n.df(c).loc[add[c], cols].to_dict("series"))
            logger.warning(f"[{now}] ADDED {len(add[c])} {c} from design network: {add[c]}")
    for name, (proxy, scale, profile) in proxies.items():
        n_weather.generators_t.p_max_pu[name] = profile
        logger.warning(f"[{now}] PROXY '{name}': p_max_pu of '{proxy}' scaled by {scale:.3f}")


def set_capacities(
    n: pypsa.Network,
    n_weather: pypsa.Network,
) -> None:
    """Sync components and set capacities from the design network n to n_weather."""
    sync_components(n, n_weather)

    for c, attr in [
        ("Generator", "p_nom"),
        ("StorageUnit", "p_nom"),
        ("Link", "p_nom"),
        ("Store", "e_nom"),
        ("Line", "s_nom"),
        ("Transformer", "s_nom"),
    ]:
        cols = [attr, attr + "_opt", attr + "_extendable"]
        common = n.df(c).index.intersection(n_weather.df(c).index)
        n_weather.df(c).loc[common, cols] = n.df(c).loc[common, cols]

    # Keep CO2 shadow price of the design network (used by set_co2_price)
    if "CO2Limit" in n_weather.global_constraints.index:
        n_weather.global_constraints.loc["CO2Limit", "mu"] = n.global_constraints.loc["CO2Limit", "mu"]

    # Non weather-dependent loads (static p_set, no time series in n_weather):
    # use design values, as in the original set_weather workflow
    static_loads = (
        n.loads.index
        .intersection(n_weather.loads.index)
        .difference(n_weather.loads_t.p_set.columns)
    )
    diff = (n_weather.loads.loc[static_loads, "p_set"] - n.loads.loc[static_loads, "p_set"]).abs()
    logger.info(
        f"Copying static p_set of {len(static_loads)} loads from design network "
        f"({(diff > 1e-6).sum()} differ, max abs diff {diff.max():.3f} MW)"
    )
    n_weather.loads.loc[static_loads, "p_set"] = n.loads.loc[static_loads, "p_set"]


def set_co2_price(
    n: pypsa.Network,
) -> None:
    """Sets CO2 price based on the dual variable of the CO2 constraint (from the already optimized network n). Removes CO2 limit."""
    # Follow implementation roughly by Gotske et al, 2024. (https://github.com/ebbekyhl/multi-weather-year-assessment/blob/8aed88728e7a0848de5fd987ff8303761a8f5687/scripts/update_network.py#L150)

    # Extract CO2 price from optimised network
    co2_price = -n.global_constraints.loc["CO2Limit","mu"] # in EUR/tCO2

    # Remove hard CO2 cap.
    n.remove("GlobalConstraint", "CO2Limit")

    # Add CO2 price to all emitters - note that net removers will have marginal prices lowered by CO2 price.
    # All is weighted by efficiency.
    # bus1: Process emissions, HVC
    process_i = n.links.query('bus1 == "co2 atmosphere"').index
    process = n.links.loc[process_i]
    process_co2_price = co2_price * process.efficiency
    # bus2: power plants, industry, boilers, but also DAC, biomass to liquid etc.
    emitters_i = n.links.query('bus2 == "co2 atmosphere"').index
    emitters = n.links.loc[emitters_i]
    emitters_co2_price = co2_price * emitters.efficiency2 # note that also negative values for net removers are allowed here
    # bus3: chp
    chp_i = n.links.query('bus3 == "co2 atmosphere"').index
    chp = n.links.loc[chp_i]
    chp_co2_price = co2_price * chp.efficiency3

    # Update marginal costs
    n.links.loc[process_i, "marginal_cost"] += process_co2_price
    n.links.loc[emitters_i, "marginal_cost"] += emitters_co2_price
    n.links.loc[chp_i, "marginal_cost"] += chp_co2_price


def extract_shedding_metrics(n: pypsa.Network) -> tuple:
    """
    Extract load and heat shedding time series from solved network.

    Returns
    -------
    load_shedding : pd.DataFrame
        Load shedding time series (excluding battery and H2)
    heat_shedding : pd.DataFrame
        Heat shedding time series
    """
    # Load shedding
    load_shedding = n.generators_t.p.filter(like="load shedding", axis="columns")
    load_shedding = load_shedding.loc[
        :, ~load_shedding.columns.str.contains("battery|H2")
    ].round(0)

    # Heat shedding
    heat_shedding = n.generators_t.p.filter(like="heat shedding", axis="columns")

    return load_shedding, heat_shedding

# def extract_operational_costs(n)

# def extract_electricity_prices(n)

# def extract_net_load(n)

# def extract_dispatch(n)

if __name__ == "__main__":
    if "snakemake" not in globals():
        from _helpers import mock_snakemake

        snakemake = mock_snakemake(
            "test_operations",
            configfiles="config/test_sec.yaml",
            opts="50seg-lv1.0",
            clusters="50",
            sector_opts="Co2L0.0+T+H+B+I+A",
            planning_horizons="2050",
        )
    import solve_network
    solve_network.snakemake = snakemake
    configure_logging(snakemake)
    set_scenario_config(snakemake)
    update_config_from_wildcards(snakemake.config, snakemake.wildcards)

    solve_opts = snakemake.params.solving["options"]

    # Activate load shedding
    solve_opts["load_shedding"] = True

    np.random.seed(solve_opts.get("seed", 123))

    n = pypsa.Network(snakemake.input.network)
    m = pypsa.Network(snakemake.input.weather_network)

    planning_horizons = snakemake.wildcards.get("planning_horizons", "")

    # Add small buffer to optimal capacities to avoid numerical infeasibilities
    # when running under a different weather year. Scales with retry attempt.
    capacity_buffers = [0.001, 0.005, 0.01, 0.02]
    attempt = getattr(snakemake, "attempt", 1)
    buffer = capacity_buffers[min(attempt - 1, len(capacity_buffers) - 1)]
    logger.info(f"Adding {buffer*100:.2f}% capacity buffer (attempt {attempt})")
    for comp in [n.generators, n.links, n.stores, n.storage_units]:
        for attr in ["p_nom_opt", "e_nom_opt"]:
            if attr in comp.columns:
                comp[attr] *= (1 + buffer)

    try:
        # set_weather(n, m)
        set_capacities(n, m)
        design = n         # keep reference to the design network if needed later
        n = m               # from here on, solve the weather-year network
        n.optimize.fix_optimal_capacities()
        prepare_network(
            n,
            solve_opts=solve_opts,
            foresight=snakemake.params.foresight,
            planning_horizons=planning_horizons,
            co2_sequestration_potential=snakemake.params["co2_sequestration_potential"],
            limit_max_growth=snakemake.params.get("sector", {}).get("limit_max_growth"),
        )
        logging_frequency = snakemake.config.get("solving", {}).get(
            "mem_logging_frequency", 30
        )
        if snakemake.config["run"]["stress_tests"].get("mode", "") == "co2-price":
            print("Setting CO2 price based on previous optimization.")
            set_co2_price(n)
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
                try:
                    n.model.print_infeasibilities()
                except AttributeError:
                    logger.warning("print_infeasibilities not available in this pypsa version")
            if status != "ok":
                logger.warning(f"Solver status: {status}, condition: {condition}")
                try:
                    n.model.print_infeasibilities()
                except AttributeError:
                    logger.warning("print_infeasibilities not available in this pypsa version")
                raise RuntimeError(f"Validation not solved: status={status}, condition={condition}")

        logger.info(f"Maximum memory usage: {mem.mem_usage}")

        n.meta = dict(snakemake.config, **dict(wildcards=dict(snakemake.wildcards)))
        n.export_to_netcdf(snakemake.output.network)

        # Extract shedding metrics
        load_shedding, heat_shedding = extract_shedding_metrics(n)

        # Export the results
        load_shedding.round(3).to_csv(snakemake.output.load_shedding)
        heat_shedding.round(3).to_csv(snakemake.output.heat_shedding)

        # Write metadata sidecar (not tracked by snakemake)
        metadata_path = snakemake.output.load_shedding.replace("_load_shedding.csv", "_metadata.json")
        with open(metadata_path, "w") as f:
            json.dump({"attempt": attempt, "buffer": buffer, "status": status, "condition": condition}, f, indent=2)

    except Exception as e:
        logger.exception(f"Error in test_operations: {e}")
        sys.exit(1)