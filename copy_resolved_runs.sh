#!/usr/bin/env bash
set -euo pipefail

# ======================================================================
# EDIT THESE VALUES BEFORE RUNNING
# ======================================================================

SRC_PREFIX="consecutive_years_seg3"                               # source prefix (everything already solved)
DST_PREFIX="consecutive_years_seg4"                               # destination prefix
CONFIGFILE="config/tsam-test/consecutive_years_segmented.yaml"    # destination configfile

# Each entry can be either:
#   - a year (or years joined with "_")  -> expanded to weather_year_<entry>_<DEFAULT_TIME_RES>
#   - a full scenario name starting with "weather_year" -> used as is
#     (e.g. weather_year_1941_1986_2010_9h, weather_years_1941_1986_2010_3H)
DEFAULT_TIME_RES="3H"

# Scenarios whose solved network (results/) you want to reuse -> output of solve_second_network
DESIGN_SCENARIOS=(weather_years_1941_1986_2010_9h)
# Operational scenarios validated in test_operations -> only need resources/
OPERATIONAL_SCENARIOS=(1962 1965 1996 2013)

RESOLUTION="50"        # base_s_<RESOLUTION>
TARGET_YEAR="2050"     # ___<TARGET_YEAR>
PROJECT_DIR="$(pwd)"   # pypsa-eur root (where results/ and resources/ live)
DRY_RUN=0              # 1 = only print what would be done

COPY_RESOURCES=1        # 1 = copy resources/<SRC>/<scenario>/ entirely (design + operational)
COPY_RESULTS=1          # 1 = copy results/<SRC>/<scenario>/{networks,configs} (design only)
RUN_CLEANUP_METADATA=0  # 1 = snakemake --cleanup-metadata on everything copied
RUN_TOUCH=1             # 1 = snakemake --touch on solved + resource networks (orders DAG mtimes)
RUN_VERIFY=1            # 1 = final dry-run (shows the reason: lines by default)
VERIFY_TARGETS=(test_networks)   # target(s) for verification

# ======================================================================
# NOTHING BELOW THIS LINE NEEDS TO BE EDITED
# ======================================================================

cd "$PROJECT_DIR"

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then echo "    [dry-run] $*"; else "$@"; fi
}
warn() { echo "  [WARNING] $*" >&2; }

# Resolve an entry into its scenario directory name
scenario_dir() {
  local s="$1"
  if [[ "$s" == weather_year* ]]; then
    echo "$s"
  else
    echo "weather_year_${s}_${DEFAULT_TIME_RES}"
  fi
}

NET="networks/base_s_${RESOLUTION}___${TARGET_YEAR}.nc"
CFG="configs/config.base_s_${RESOLUTION}___${TARGET_YEAR}.yaml"

declare -a COPIED_FILES=()
declare -a TOUCH_TARGETS=()
declare -a SKIPPED=()

[[ "$DRY_RUN" -eq 1 ]] && echo "(dry-run: nothing is copied or executed)"

# ---- Resolve scenario names
DESIGN_DIRS=()
for s in "${DESIGN_SCENARIOS[@]}"; do DESIGN_DIRS+=("$(scenario_dir "$s")"); done

# ---- Union of scenarios for resources (design + operational, no duplicates)
declare -A _seen=()
RESOURCE_DIRS=()
for s in "${DESIGN_SCENARIOS[@]}" "${OPERATIONAL_SCENARIOS[@]}"; do
  d="$(scenario_dir "$s")"
  if [[ -z "${_seen[$d]:-}" ]]; then _seen[$d]=1; RESOURCE_DIRS+=("$d"); fi
done

# ---- 1) resources/
if [[ "$COPY_RESOURCES" -eq 1 ]]; then
  echo ""
  echo "== resources/: '$SRC_PREFIX' -> '$DST_PREFIX' (scenarios: ${RESOURCE_DIRS[*]}) =="
  for d in "${RESOURCE_DIRS[@]}"; do
    src="resources/${SRC_PREFIX}/${d}"
    dst="resources/${DST_PREFIX}/${d}"
    if [[ ! -f "$src/$NET" ]]; then
      warn "$d: $src/$NET does not exist. Skipping."
      SKIPPED+=("resources:$d"); continue
    fi
    n=$(find "$src" -type f | wc -l)
    echo "  $d: $src/ -> $dst/  ($n files)"
    run mkdir -p "$dst"
    run cp -a "$src/." "$dst/"
    while IFS= read -r f; do
      COPIED_FILES+=("$dst/${f#"$src"/}")
    done < <(find "$src" -type f)
  done
else
  echo ""
  echo "== Skipping resources/ copy (COPY_RESOURCES=0) =="
fi

# ---- 2) results/
if [[ "$COPY_RESULTS" -eq 1 ]]; then
  echo ""
  echo "== results/: '$SRC_PREFIX' -> '$DST_PREFIX' (scenarios: ${DESIGN_DIRS[*]}) =="
  for d in "${DESIGN_DIRS[@]}"; do
    src="results/${SRC_PREFIX}/${d}"
    dst="results/${DST_PREFIX}/${d}"
    if [[ ! -f "$src/$NET" || ! -f "$src/$CFG" ]]; then
      warn "$d: missing $src/$NET or $src/$CFG. Skipping."
      SKIPPED+=("results:$d"); continue
    fi
    echo "  $d: $src/{$NET,$CFG} -> $dst/"
    run mkdir -p "$dst/networks" "$dst/configs"
    run cp -a "$src/$NET" "$dst/$NET"
    run cp -a "$src/$CFG" "$dst/$CFG"
    COPIED_FILES+=("$dst/$NET" "$dst/$CFG")
  done
else
  echo ""
  echo "== Skipping results/ copy (COPY_RESULTS=0) =="
fi

# ---- --touch targets: solved networks in destination
for d in "${DESIGN_DIRS[@]}"; do
  f="results/${DST_PREFIX}/${d}/$NET"
  if [[ -f "$f" || "$DRY_RUN" -eq 1 ]]; then
    TOUCH_TARGETS+=("$f")
  else
    warn "$d: $f does not exist in destination; not included in --touch."
  fi
done

# ---- --touch targets: resource networks (design + operational), so the chains of
#      scenarios only used by test_operations are also brought up to date
for d in "${RESOURCE_DIRS[@]}"; do
  f="resources/${DST_PREFIX}/${d}/$NET"
  if [[ -f "$f" || "$DRY_RUN" -eq 1 ]]; then
    TOUCH_TARGETS+=("$f")
  else
    warn "$d: $f does not exist in destination; not included in --touch."
  fi
done

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  echo ""
  echo "Skipped due to missing source files: ${SKIPPED[*]}"
fi

# ---- 3) cleanup-metadata
if [[ "$RUN_CLEANUP_METADATA" -eq 1 && ${#COPIED_FILES[@]} -gt 0 ]]; then
  echo ""
  echo "== Cleaning Snakemake metadata (${#COPIED_FILES[@]} files) =="
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    [dry-run] snakemake --cleanup-metadata <${#COPIED_FILES[@]} files> --configfile=$CONFIGFILE"
  else
    if ! snakemake --cleanup-metadata "${COPIED_FILES[@]}" --configfile="$CONFIGFILE"; then
      echo "  [Note] Some files had no metadata (normal for copied files). Continuing."
    fi
  fi
else
  echo ""
  echo "== Skipping cleanup-metadata =="
fi

# ---- 4) touch in DAG order (resources -> results)
if [[ "$RUN_TOUCH" -eq 1 && ${#TOUCH_TARGETS[@]} -gt 0 ]]; then
  echo ""
  echo "== snakemake --touch on ${#TOUCH_TARGETS[@]} networks (solved + resources) =="
  run snakemake "${TOUCH_TARGETS[@]}" --touch --rerun-triggers=mtime --configfile="$CONFIGFILE"
else
  echo ""
  echo "== Skipping --touch =="
fi

# ---- 5) verification
if [[ "$RUN_VERIFY" -eq 1 ]]; then
  echo ""
  echo "== Verification dry-run: only test_operations / test_networks should appear in 'Job stats' =="
  run snakemake "${VERIFY_TARGETS[@]}" -n --rerun-triggers=mtime --configfile="$CONFIGFILE"
fi

echo ""
echo "Done. Launch validation with: snakemake ${VERIFY_TARGETS[*]} --rerun-triggers=mtime --configfile=$CONFIGFILE (+ your profile)"