#!/bin/bash
# Activate the conda environment (adjust the path if necessary)
source ~/miniforge3/condabin/conda
conda activate pypsa-eur-mga-v2026.02

# MGA Pipeline - mini-sector droughts 
CONFIG="config/mga_carlos/sector_droughts_mga.yaml"

# Extract prefix from config and set up Slurm log directory
PREFIX=$(python -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c['run']['prefix'])")
export SLURM_LOG_DIR="slurm_logs/$PREFIX"
mkdir -p "$SLURM_LOG_DIR"
echo "Slurm logs will be stored in: $SLURM_LOG_DIR"

echo "======================================"
echo " MGA PIPELINE - $(date)"
echo "======================================"

# 1. Prepare sector networks
echo ""
echo "[1/4] Preparing sector networks..."
./snakemake_prepare_sector_network --configfile="$CONFIG" --jobs=100

if [ $? -ne 0 ]; then echo "ERROR in step 1. Aborting."; exit 1; fi

echo "Waiting 60s before next step..."; sleep 60

# 2. Solve thin
echo ""
echo "[2/4] Solving (thin)..."
./snakemake_solve_thin --configfile="$CONFIG" --jobs=45

if [ $? -ne 0 ]; then echo "ERROR in step 2. Aborting."; exit 1; fi

echo "Waiting 60s before next step..."; sleep 60

# 3. Compute MGA solutions
echo ""
echo "[3/4] Computing MGA solutions..."
./snakemake_solve_thin compute_mga_solutions --jobs=45 --configfile="$CONFIG"

if [ $? -ne 0 ]; then echo "ERROR in step 3. Aborting."; exit 1; fi

echo "Waiting 60s before next step..."; sleep 60

# 4. Validate MGA solutions
echo ""
echo "[4/4] Validating MGA solutions..."
./snakemake_solve_thin validate_mga_solutions --configfile="$CONFIG" --jobs=45

if [ $? -ne 0 ]; then echo "ERROR in step 4. Aborting."; exit 1; fi

echo ""
echo "======================================"
echo " PIPELINE COMPLETE - $(date)"
echo "======================================"