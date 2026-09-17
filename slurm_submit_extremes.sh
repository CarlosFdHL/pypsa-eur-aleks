#!/bin/bash
# Envuelve el jobscript que genera Snakemake para que corra con el grupo "extremes".
# Snakemake lo llama así: slurm_submit_extremes.sh <flags de sbatch...> <jobscript>

jobscript="${!#}"                 # último argumento = ruta al jobscript generado
flags=("${@:1:$#-1}")             # todo lo demás son los flags de sbatch

wrapdir="$HOME/.snakemake_sg_wrappers"
mkdir -p "$wrapdir"
wrapped="$(mktemp "$wrapdir/wrap_XXXXXX.sh")"

cat > "$wrapped" <<EOF
#!/bin/bash
sg extremes -c "bash '$jobscript'"
rm -f "$wrapped"
EOF
chmod +x "$wrapped"

sbatch "${flags[@]}" "$wrapped"