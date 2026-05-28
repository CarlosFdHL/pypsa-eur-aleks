#!/bin/bash
source ~/miniforge3/condabin/conda
conda activate pypsa-eur-mga-v2026.02

# CONFIG="config/mga_carlos/sector_droughts_mga.yaml"
CONFIG="config/mga_carlos/full0.005.yaml"
# CONFIG="config/mga_carlos/full0.01.yaml"
# CONFIG="config/mga_carlos/full0.02.yaml"
# CONFIG="config/mga_carlos/full0.05.yaml"

# ======================================
# FORCE RUN OPTION
FORCE_RUN=false
# ======================================

if [ "$FORCE_RUN" = true ]; then
    FORCE_FLAG="--forceall"
    echo "⚠  FORCE_RUN enabled: all rules will be re-executed"
else
    FORCE_FLAG=""
fi

PREFIX=$(python -c "import yaml; c=yaml.safe_load(open('$CONFIG')); print(c['run']['prefix'])")
export SLURM_LOG_DIR="slurm_logs/$PREFIX"
mkdir -p "$SLURM_LOG_DIR"

# ======================================
# INTERACTIVE STEP SELECTION
# ======================================
STEPS=(
    "Prepare sector networks"
    "Solve baseline networks"
    "Compute MGA solutions"
    "Validate baseline networks"
    "Validate MGA solutions"
)

echo ""
echo "======================================"
echo " MGA PIPELINE - $(date)"
echo "======================================"
echo ""
echo "Select steps to run (space-separated numbers, e.g. '1 3 5'):"
echo "  0) Run ALL steps"
for i in "${!STEPS[@]}"; do
    printf "  %d) %s\n" "$((i+1))" "${STEPS[$i]}"
done
echo ""
read -rp "Steps: " STEP_INPUT

if [[ "$STEP_INPUT" == "0" ]]; then
    RUN_STEPS=(1 2 3 4 5)
else
    read -ra RUN_STEPS <<< "$STEP_INPUT"
fi

should_run() {
    local step=$1
    for s in "${RUN_STEPS[@]}"; do
        [[ "$s" == "$step" ]] && return 0
    done
    return 1
}

echo ""
echo "Steps selected: ${RUN_STEPS[*]}"
echo "Config: $CONFIG"
echo "Force run: $FORCE_RUN"
echo "Slurm logs: $SLURM_LOG_DIR"
echo "======================================"

LAST_STEP=0
for s in "${RUN_STEPS[@]}"; do
    [[ "$s" -gt "$LAST_STEP" ]] && LAST_STEP="$s"
done

run_step() {
    local step_num=$1
    local label=$2
    local total=${#RUN_STEPS[@]}

    echo ""
    echo "[Step $step_num/5] $label..."
}

add_sleep() {
    local step_num=$1
    if [[ "$step_num" -lt "$LAST_STEP" ]]; then
        echo "Waiting 60s before next step..."; sleep 60
    fi
}

# Step 1
if should_run 1; then
    run_step 1 "Preparing sector networks"
    ./snakemake_prepare_sector_network --configfile="$CONFIG" --jobs=100 $FORCE_FLAG
    if [ $? -ne 0 ]; then echo "ERROR in step 1. Aborting."; exit 1; fi
    add_sleep 1
fi

# Step 2
if should_run 2; then
    run_step 2 "Solving (thin)"
    ./snakemake_solve_thin --configfile="$CONFIG" --keep-going --jobs=15 $FORCE_FLAG
    if [ $? -ne 0 ]; then echo "ERROR in step 2. Aborting."; exit 1; fi
    add_sleep 2
fi

# Step 3
if should_run 3; then
    run_step 3 "Computing MGA solutions"
    ./snakemake_solve_thin compute_mga_solutions --jobs=15 --keep-going --configfile="$CONFIG" $FORCE_FLAG
    if [ $? -ne 0 ]; then echo "ERROR in step 3. Aborting."; exit 1; fi
    add_sleep 3
fi

# Step 4
if should_run 4; then
    run_step 4 "Generating baseline scenarios for MGA validation"
    ./snakemake_solve_thin test_networks --configfile="$CONFIG" --keep-going --jobs=5 $FORCE_FLAG
    add_sleep 4
fi

# Step 5
if should_run 5; then
    run_step 5 "Validating MGA solutions"
    ./snakemake_solve_thin validate_mga_solutions --configfile="$CONFIG" --keep-going --jobs=15 $FORCE_FLAG
    if [ $? -ne 0 ]; then echo "ERROR in step 5. Aborting."; exit 1; fi
fi

echo ""
echo "======================================"
echo " PIPELINE COMPLETE - $(date)"
echo "======================================"
