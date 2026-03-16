# SPDX-FileCopyrightText: Aleksander Grochowicz 2025
#
# SPDX-License-Identifier: MIT


rule compute_near_opt:
    params:
        solving=config_provider("solving"),
        foresight=config_provider("foresight"),
        co2_sequestration_potential=config_provider(
            "sector", "co2_sequestration_potential", default=200
        ),
        custom_extra_functionality=input_custom_extra_functionality,
        save_network=config_provider("near-opt", "approx", "save_network", default=False),  
        results_dir=RESULTS,  
    input:
        network=RESULTS + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
    output:
        near_opt_solutions=RESULTS + "near_opt/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
        network_hash=RESULTS + "near_opt/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_network_hash.txt",
        network=RESULTS + "near_opt/networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc"
            if (config.get("near-opt", {}).get("approx", {}).get("iterations", 1) == 0
                and config.get("near-opt", {}).get("approx", {}).get("save_network", False))
            else [],
    log:
        python=RESULTS + "logs/mga/compute_near_opt/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_python.log",
    benchmark:
        RESULTS + "benchmarks/mga/compute_near_opt/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
    threads: lambda wildcards: config_provider("near-opt", "approx", "max_parallel")(wildcards)
    resources:
        mem_mb=memory,
        runtime=lambda wildcards: (
            lambda rt: int(rt[:-1]) * 60 if isinstance(rt, str) and rt.endswith('h') else int(rt)
        )(config_provider("solving", "runtime", default=360)(wildcards)) * (
            config_provider("near-opt", "approx", "iterations")(wildcards)
            + (2 * len(config_provider("near-opt", "projection")(wildcards)) if config_provider("near-opt", "approx", "minmax")(wildcards) else 0)
        ),
    shadow:
        shadow_config
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/compute_near_opt.py"


rule validation_mga:
    wildcard_constraints:
        network_hash=r"[a-zA-Z0-9_]+",
        dir_hash=r"[a-zA-Z0-9_]+",
        design_year=r"weather_year_\d+_\d+H",
        operational_year=r"weather_year_\d+_\d+H",
    params:
        solving=config_provider("solving"),
        foresight=config_provider("foresight"),
        co2_sequestration_potential=config_provider(
            "sector", "co2_sequestration_potential", default=200
        ),
        custom_extra_functionality=input_custom_extra_functionality,
    input:
        network="results/" + config["run"]["prefix"] +
            "/{design_year}/networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
        weather_network="resources/" + config["run"]["prefix"] +
            "/{operational_year}/networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
        mga_capacities=lambda w: config_provider("near-opt", "cache_dir")(w) +
            f"/caps/caps_{w.network_hash}_{w.dir_hash}.csv",
        near_opt_solutions="results/" + config["run"]["prefix"] +
            "/{design_year}/near_opt/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.csv",
    output:
        load_shedding="results/" + config["run"]["prefix"] +
            "/{design_year}/validation/mga_{network_hash}_{dir_hash}_{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_load_shedding.csv",
        heat_shedding="results/" + config["run"]["prefix"] +
            "/{design_year}/validation/mga_{network_hash}_{dir_hash}_{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_heat_shedding.csv",
    shadow:
        shadow_config
    log:
        solver="results/" + config["run"]["prefix"] +
            "/{design_year}/logs/mga/validation_mga_{network_hash}_{dir_hash}_{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_solver.log",
        memory="results/" + config["run"]["prefix"] +
            "/{design_year}/logs/mga/validation_mga_{network_hash}_{dir_hash}_{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_memory.log",
        python="results/" + config["run"]["prefix"] +
            "/{design_year}/logs/mga/validation_mga_{network_hash}_{dir_hash}_{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_python.log",
    threads: solver_threads
    resources:
        mem_mb=config_provider("solving", "mem_mb"),
        runtime=config_provider("solving", "runtime", default="6h"),
    benchmark:
        "results/" + config["run"]["prefix"] +
            "/{design_year}/benchmarks/mga/validation_mga_{network_hash}_{dir_hash}_{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/test_mga_operations.py"

