# SPDX-FileCopyrightText: 2025 Aleksander Grochowicz & Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT

if config["run"].get("fixed_network", {}).get("enable", False):

    FIXED_NET_DIR = (
        "resources/fixed_network/" + config["run"]["fixed_network"]["scenario"] + "/"
    )

    def fixed_network_year(wildcards):
        scenario_name = config["run"]["fixed_network"]["scenario"]
        return ancient(
            "resources/" + config["run"]["prefix"] + "/" + scenario_name
            + "/networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc"
        )


    # For fixing different networks
    rule solve_first_network:
        params:
            solving=config_provider("solving"),
            foresight=config_provider("foresight"),
            co2_sequestration_potential=config_provider(
                "sector", "co2_sequestration_potential", default=200
            ),
            custom_extra_functionality=input_custom_extra_functionality,
        input:
            network=fixed_network_year,
        output:
            network=FIXED_NET_DIR
            + "base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_net.nc",
            config=FIXED_NET_DIR
            + "config.base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_net.yaml",
        shadow:
            shadow_config
        log:
            solver=FIXED_NET_DIR
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_net_solver.log",
            memory=FIXED_NET_DIR
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_net_memory.log",
            python=FIXED_NET_DIR
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_net_python.log",
        threads: solver_threads
        resources:
            mem_mb=config_provider("solving", "mem_mb"),
            runtime=config_provider("solving", "runtime", default="6h"),
        benchmark:
            (
                FIXED_NET_DIR
                + "benchmarks/solve_sector_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_net"
            )
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/solve_network.py"

    # Run on a fixed network
    rule solve_second_network:
        params:
            solving=config_provider("solving"),
            foresight=config_provider("foresight"),
            co2_sequestration_potential=config_provider(
                "sector", "co2_sequestration_potential", default=200
            ),
            custom_extra_functionality=input_custom_extra_functionality,
        input:
            network=resources(
                "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc"
            ),
            fixed_network=ancient(
                FIXED_NET_DIR
                + "base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_net.nc"
            ),
        output:
            network=RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            config=RESULTS
            + "configs/config.base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.yaml",
        shadow:
            shadow_config
        log:
            solver=RESULTS
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_solver.log",
            memory=RESULTS
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_memory.log",
            python=RESULTS
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_python.log",
        threads: solver_threads
        resources:
            mem_mb=config_provider("solving", "mem_mb"),
            runtime=config_provider("solving", "runtime", default="6h"),
        benchmark:
            (
                RESULTS
                + "benchmarks/solve_second_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
            )
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/solve_second_network.py"
 
else:
    rule solve_sector_network:
        params:
            solving=config_provider("solving"),
            foresight=config_provider("foresight"),
            co2_sequestration_potential=config_provider(
                "sector", "co2_sequestration_potential", default=200
            ),
            custom_extra_functionality=input_custom_extra_functionality,
        input:
            network=resources(
                "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc"
            ),
        output:
            network=RESULTS
            + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
            config=RESULTS
            + "configs/config.base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.yaml",
        shadow:
            shadow_config
        log:
            solver=RESULTS
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_solver.log",
            memory=RESULTS
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_memory.log",
            python=RESULTS
            + "logs/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_python.log",
        threads: solver_threads
        resources:
            mem_mb=config_provider("solving", "mem_mb"),
            runtime=config_provider("solving", "runtime", default="6h"),
        benchmark:
            (
                RESULTS
                + "benchmarks/solve_sector_network/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
            )
        conda:
            "../envs/environment.yaml"
        script:
            "../scripts/solve_network.py"


# Custom rule for operational testing with different weather years
rule test_operations:
    params:
        solving=config_provider("solving"),
        foresight=config_provider("foresight"),
        co2_sequestration_potential=config_provider(
            "sector", "co2_sequestration_potential", default=200
        ),
        custom_extra_functionality=input_custom_extra_functionality,
    input:
        network=RESULTS
        + "networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
        weather_network = "resources/" + config["run"]["prefix"] + "/{operational_year}/networks/base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
    output:
        network=RESULTS
        + "networks/{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}.nc",
        load_shedding= RESULTS + "validation/{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_load_shedding.csv",
        heat_shedding= RESULTS + "validation/{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_heat_shedding.csv",
    shadow:
        None
    log:
        solver=RESULTS
        + "logs/{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_solver.log",
        memory=RESULTS
        + "logs/{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_memory.log",
        python=RESULTS
        + "logs/{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}_python.log",
    retries: 3
    threads: solver_threads
    resources:
        mem_mb=config_provider("solving", "mem_mb"),
        runtime=8 * 60,
    benchmark:
        (
            RESULTS
            + "benchmarks/test_operations/{operational_year}_base_s_{clusters}_{opts}_{sector_opts}_{planning_horizons}"
        )
    conda:
        "../envs/environment.yaml"
    script:
        "../scripts/test_operations.py"
