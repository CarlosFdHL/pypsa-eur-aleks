#!/bin/bash
source ~/miniforge3/condabin/conda

# CONFIG="config/tsam-test/consecutive_years_segmented.yaml"
CONFIG="config/tsam-test/hourly.yaml"

# Extract prefix from config and set up Slurm log directory
PREFIX=$(python -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c['run']['prefix'])")
export SLURM_LOG_DIR="slurm_logs/$PREFIX"
mkdir -p "$SLURM_LOG_DIR"
echo "Slurm logs will be stored in: $SLURM_LOG_DIR"

./snakemake_prepare_sector_network --configfile="$CONFIG" --jobs=100
./snakemake_solve_thin --configfile="$CONFIG" --keep-going --jobs=1