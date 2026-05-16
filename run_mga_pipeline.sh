#!/bin/bash
# Activate the conda environment (adjust the path if necessary)
source ~/miniforge3/condabin/conda
conda activate pypsa-eur-mga-v2026.02

# MGA Pipeline - mini-sector droughts v2025
# CONFIG="config/mga_carlos/sector_droughts_mga.yaml"
CONFIG="config/mga_carlos/full0.005.yaml"
# CONFIG="config/mga_carlos/full0.01.yaml"
# CONFIG="config/mga_carlos/full0.02.yaml"
# CONFIG="config/mga_carlos/full0.05.yaml"

# ======================================
# FORCE RUN OPTION
# Set to true to re-run all rules even if output files already exist
FORCE_RUN=false
# ======================================

# Build force flag for snakemake
if [ "$FORCE_RUN" = true ]; then
    FORCE_FLAG="--forceall"
    echo "⚠  FORCE_RUN enabled: all rules will be re-executed regardless of existing outputs"
else
    FORCE_FLAG=""
fi

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
echo "[1/5] Preparing sector networks..."
./snakemake_prepare_sector_network --configfile="$CONFIG" --jobs=100 $FORCE_FLAG

if [ $? -ne 0 ]; then echo "ERROR in step 1. Aborting."; exit 1; fi

echo "Waiting 60s before next step..."; sleep 60

# 2. Solve thin
echo ""
echo "[2/5] Solving (thin)..."
./snakemake_solve_thin --configfile="$CONFIG" --keep-going --jobs=15 $FORCE_FLAG

if [ $? -ne 0 ]; then echo "ERROR in step 2. Aborting."; exit 1; fi

echo "Waiting 60s before next step..."; sleep 60

# 3. Compute MGA solutions
echo ""
echo "[3/5] Computing MGA solutions..."
./snakemake_solve_thin compute_mga_solutions --jobs=15 --keep-going --configfile="$CONFIG" $FORCE_FLAG

if [ $? -ne 0 ]; then echo "ERROR in step 3. Aborting."; exit 1; fi

echo "Waiting 60s before next step..."; sleep 60

# 4. Generate baseline scenarios for MGA validation
echo ""
echo "[4/5] Generating baseline scenarios for MGA validation..."
./snakemake_solve_thin test_networks --configfile="$CONFIG" --keep-going --jobs=5 $FORCE_FLAG

# 5. Validate MGA solutions
echo ""
echo "[5/5] Validating MGA solutions..."
./snakemake_solve_thin validate_mga_solutions --configfile="$CONFIG" --keep-going --jobs=15 $FORCE_FLAG

if [ $? -ne 0 ]; then echo "ERROR in step 5. Aborting."; exit 1; fi

echo ""
echo "======================================"
echo " PIPELINE COMPLETE - $(date)"
echo "======================================"