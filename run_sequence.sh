#!/bin/bash

YAML="/home/s243308/projects/pypsa-eur-aleks/config/mga_carlos/full0.01.yaml"


snakemake --touch --configfile="$YAML"

# Paso 1: ejecutar con opción 3
echo "3" | bash run_mga_pipeline.sh

# Paso 2: cambiar el parámetro en el yaml
sed -i '/options: gurobi-default-v2/s/gurobi-default-v2/gurobi-default/' "$YAML"

# Paso 3: ejecutar con opciones 4 5
echo "4 5" | bash run_mga_pipeline.sh