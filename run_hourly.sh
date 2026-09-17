#!/bin/bash
source ~/miniforge3/etc/profile.d/conda.sh

CONFIG="config/tsam-test/seg_cuadratic_yearly.yaml"
# CONFIG="config/tsam-test/consecutive_years_segmented.yaml" # weight to 1
# CONFIG="config/tsam-test/hourly.yaml"

# Extract prefix from config and set up Slurm log directory
PREFIX=$(python -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c['run']['prefix'])")
export SLURM_LOG_DIR="slurm_logs/$PREFIX"
mkdir -p "$SLURM_LOG_DIR"
echo "Slurm logs will be stored in: $SLURM_LOG_DIR"

find data/cutout/archive/v1.0/ -maxdepth 1 -exec stat {} \; > /dev/null 2>&1
sleep 5

# ============================================================
#  Step 1: prepare_sector_network — cluster settings
# ============================================================
export SNK_PARTITION="windq"
export SNK_TIME_LIMIT="12:00:00"
export SNK_CPUS_PER_TASK=32
export SNK_EXCLUDE_NODES=""
export SNK_RESTART_TIMES=3
# ============================================================

./snakemake_prepare_sector_network --configfile="$CONFIG" --jobs=100 --latency-wait 300
if [ $? -ne 0 ]; then echo "ERROR in step 1. Aborting."; exit 1; fi

# ============================================================
#  Step 2: solve_thin — cluster settings
# ============================================================
export SNK_PARTITION="windq"
export SNK_TIME_LIMIT="48:00:00"
export SNK_CPUS_PER_TASK=32
export SNK_EXCLUDE_NODES="sn040,sn047,sn179,sn202,sn251"
# ============================================================

./snakemake_solve_thin --configfile="$CONFIG" --keep-going --jobs=1
if [ $? -ne 0 ]; then echo "ERROR in step 2."; exit 1; fi