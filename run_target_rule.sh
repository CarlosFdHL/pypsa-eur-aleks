#!/bin/bash
source ~/miniforge3/condabin/conda

CONFIG="config/tsam-test/consecutive_years_segmented.yaml"
TARGET="resources/consecutive_years_seg/weather_years_1941_1986_2010_9h/networks/base_s.nc"

# Extract prefix from config and set up Slurm log directory
PREFIX=$(python -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c['run']['prefix'])")
export SLURM_LOG_DIR="slurm_logs/$PREFIX"
mkdir -p "$SLURM_LOG_DIR"
echo "Slurm logs will be stored in: $SLURM_LOG_DIR"

snakemake "$TARGET" --configfile="$CONFIG" --jobs=8