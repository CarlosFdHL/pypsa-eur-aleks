#!/usr/bin/env bash
set -euo pipefail

# ======================================================================
# EDIT THESE VALUES BEFORE RUNNING
# ======================================================================

SRC_PREFIX="full0.01_v5"                     # prefix con todo ya resuelto (origen)
DST_PREFIX="test"              # prefix destino
CONFIGFILE="config/mga-constraints/test.yaml"  # configfile del destino

# Años cuya red resuelta (results/) quieres reutilizar -> salida de solve_second_network
DESIGN_YEARS=(1941 1962)
# Años climáticos con los que validas en test_operations -> solo necesitan resources/
OPERATIONAL_YEARS=(1962)

RESOLUTION="50"        # base_s_<RESOLUTION>
TARGET_YEAR="2050"     # ___<TARGET_YEAR>
PROJECT_DIR="$(pwd)"   # raíz de pypsa-eur (donde están results/ y resources/)
DRY_RUN=0              # 1 = solo mostrar lo que haría

COPY_RESOURCES=1        # 1 = copiar resources/<SRC>/weather_year_X_3H/ completo (unión de años)
COPY_RESULTS=1          # 1 = copiar results/<SRC>/weather_year_X_3H/{networks,configs} (DESIGN_YEARS)
RUN_CLEANUP_METADATA=0  # 1 = snakemake --cleanup-metadata sobre todo lo copiado
RUN_TOUCH=1             # 1 = snakemake --touch sobre redes resueltas y de recursos (ordena mtimes del DAG)
RUN_VERIFY=1            # 1 = dry-run final (muestra los reason: por defecto)
VERIFY_TARGETS=(test_networks)   # target(s) para la verificación

# ======================================================================
# NOTHING BELOW THIS LINE NEEDS TO BE EDITED
# ======================================================================

cd "$PROJECT_DIR"

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then echo "    [dry-run] $*"; else "$@"; fi
}
warn() { echo "  [WARNING] $*" >&2; }

NET="networks/base_s_${RESOLUTION}___${TARGET_YEAR}.nc"
CFG="configs/config.base_s_${RESOLUTION}___${TARGET_YEAR}.yaml"

declare -a COPIED_FILES=()
declare -a TOUCH_TARGETS=()
declare -a SKIPPED=()

[[ "$DRY_RUN" -eq 1 ]] && echo "(dry-run: no se copia ni se ejecuta nada)"

# ---- Unión de años para resources (diseño + operacionales, sin duplicados)
declare -A _seen=()
RESOURCE_YEARS=()
for y in "${DESIGN_YEARS[@]}" "${OPERATIONAL_YEARS[@]}"; do
  if [[ -z "${_seen[$y]:-}" ]]; then _seen[$y]=1; RESOURCE_YEARS+=("$y"); fi
done

# ---- 1) resources/
if [[ "$COPY_RESOURCES" -eq 1 ]]; then
  echo ""
  echo "== resources/: '$SRC_PREFIX' -> '$DST_PREFIX' (años: ${RESOURCE_YEARS[*]}) =="
  for y in "${RESOURCE_YEARS[@]}"; do
    src="resources/${SRC_PREFIX}/weather_year_${y}_3H"
    dst="resources/${DST_PREFIX}/weather_year_${y}_3H"
    if [[ ! -f "$src/$NET" ]]; then
      warn "Año $y: no existe $src/$NET. Se omite."
      SKIPPED+=("resources:$y"); continue
    fi
    n=$(find "$src" -type f | wc -l)
    echo "  Año $y: $src/ -> $dst/  ($n ficheros)"
    run mkdir -p "$dst"
    run cp -a "$src/." "$dst/"
    while IFS= read -r f; do
      COPIED_FILES+=("$dst/${f#"$src"/}")
    done < <(find "$src" -type f)
  done
else
  echo ""
  echo "== Saltando copia de resources/ (COPY_RESOURCES=0) =="
fi

# ---- 2) results/
if [[ "$COPY_RESULTS" -eq 1 ]]; then
  echo ""
  echo "== results/: '$SRC_PREFIX' -> '$DST_PREFIX' (años: ${DESIGN_YEARS[*]}) =="
  for y in "${DESIGN_YEARS[@]}"; do
    src="results/${SRC_PREFIX}/weather_year_${y}_3H"
    dst="results/${DST_PREFIX}/weather_year_${y}_3H"
    if [[ ! -f "$src/$NET" || ! -f "$src/$CFG" ]]; then
      warn "Año $y: falta $src/$NET o $src/$CFG. Se omite."
      SKIPPED+=("results:$y"); continue
    fi
    echo "  Año $y: $src/{$NET,$CFG} -> $dst/"
    run mkdir -p "$dst/networks" "$dst/configs"
    run cp -a "$src/$NET" "$dst/$NET"
    run cp -a "$src/$CFG" "$dst/$CFG"
    COPIED_FILES+=("$dst/$NET" "$dst/$CFG")
  done
else
  echo ""
  echo "== Saltando copia de results/ (COPY_RESULTS=0) =="
fi

# ---- Targets para --touch: redes resueltas del destino
for y in "${DESIGN_YEARS[@]}"; do
  f="results/${DST_PREFIX}/weather_year_${y}_3H/$NET"
  if [[ -f "$f" || "$DRY_RUN" -eq 1 ]]; then
    TOUCH_TARGETS+=("$f")
  else
    warn "Año $y: $f no existe en destino; no se incluye en --touch."
  fi
done

# ---- Targets para --touch: redes de recursos (diseño + operacionales), para que
#      también se pongan al día las cadenas de los años que solo usa test_operations
for y in "${RESOURCE_YEARS[@]}"; do
  f="resources/${DST_PREFIX}/weather_year_${y}_3H/$NET"
  if [[ -f "$f" || "$DRY_RUN" -eq 1 ]]; then
    TOUCH_TARGETS+=("$f")
  else
    warn "Año $y: $f no existe en destino; no se incluye en --touch."
  fi
done

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  echo ""
  echo "Omitidos por falta de ficheros en origen: ${SKIPPED[*]}"
fi

# ---- 3) cleanup-metadata
if [[ "$RUN_CLEANUP_METADATA" -eq 1 && ${#COPIED_FILES[@]} -gt 0 ]]; then
  echo ""
  echo "== Limpiando metadata de Snakemake (${#COPIED_FILES[@]} ficheros) =="
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "    [dry-run] snakemake --cleanup-metadata <${#COPIED_FILES[@]} ficheros> --configfile=$CONFIGFILE"
  else
    if ! snakemake --cleanup-metadata "${COPIED_FILES[@]}" --configfile="$CONFIGFILE"; then
      echo "  [Aviso] Algunos ficheros no tenían metadata (normal en ficheros copiados). Se continúa."
    fi
  fi
else
  echo ""
  echo "== Saltando cleanup-metadata =="
fi

# ---- 4) touch en orden del DAG (resources -> results)
if [[ "$RUN_TOUCH" -eq 1 && ${#TOUCH_TARGETS[@]} -gt 0 ]]; then
  echo ""
  echo "== snakemake --touch sobre ${#TOUCH_TARGETS[@]} redes (resueltas + recursos) =="
  run snakemake "${TOUCH_TARGETS[@]}" --touch --rerun-triggers=mtime --configfile="$CONFIGFILE"
else
  echo ""
  echo "== Saltando --touch =="
fi

# ---- 5) verificación
if [[ "$RUN_VERIFY" -eq 1 ]]; then
  echo ""
  echo "== Dry-run de verificación: en 'Job stats' solo deberían aparecer test_operations / test_networks =="
  run snakemake "${VERIFY_TARGETS[@]}" -n --rerun-triggers=mtime --configfile="$CONFIGFILE"
fi

echo ""
echo "Done. Lanza la validación con: snakemake ${VERIFY_TARGETS[*]} --rerun-triggers=mtime --configfile=$CONFIGFILE (+ tu profile)"