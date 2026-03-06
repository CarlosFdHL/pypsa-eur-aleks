#!/usr/bin/env bash
#SBATCH --mail-type=FAIL,END
#SBATCH --mail-user=tu_correo@dtu.dk

set -euo pipefail

mkdir -p slurm_logs

# Ajusta si tu repo está en otra ruta
cd /home/s243308/projects/pypsa-eur-aleks

# Activa conda
source ~/miniforge3/etc/profile.d/conda.sh
conda activate pypsa-eur-mga

MAIL_USER="s243308@dtu.dk"

# 1) PREPARE (jobs=70)
prep_jid=$(sbatch --parsable -p workq -n 1 --time=24:00:00 \
  --output=slurm_logs/prep-master-%j.out --error=slurm_logs/prep-master-%j.err \
  --wrap='bash -lc "cd /home/s243308/projects/pypsa-eur-aleks && source ~/miniforge3/etc/profile.d/conda.sh && conda activate pypsa-eur-mga && snakemake prepare_sector_networks --jobs 70 --rerun-incomplete --latency-wait 100 --executor cluster-generic --cluster-generic-submit-cmd '\''sbatch --parsable -p workq,fatq -n 1 --output=slurm_logs/slurm-%j.out --error=slurm_logs/slurm-%j.err --cpus-per-task={threads}'\''"' )

echo "Submitted PREP master job: $prep_jid"

# 2) SOLVE (jobs=15) depende de PREP
solve_jid=$(sbatch --parsable -p workq -n 1 --time=24:00:00 --dependency=afterok:${prep_jid} \
  --output=slurm_logs/solve-master-%j.out --error=slurm_logs/solve-master-%j.err \
  --wrap='bash -lc "cd /home/s243308/projects/pypsa-eur-aleks && source ~/miniforge3/etc/profile.d/conda.sh && conda activate pypsa-eur-mga && snakemake --jobs 15 --rerun-incomplete --latency-wait 100 --executor cluster-generic --cluster-generic-submit-cmd '\''sbatch --parsable -p workq -n 1 --exclusive --output=slurm_logs/slurm-%j.out --time=12:00:00 --cpus-per-task=32'\''"' )

echo "Submitted SOLVE master job (after PREP): $solve_jid"

# 3) EMAIL cuando acabe SOLVE (END/FAIL)
mail_jid=$(sbatch --parsable -p workq -n 1 --time=00:10:00 --dependency=afterany:${solve_jid} \
  --output=slurm_logs/mail-%j.out --error=slurm_logs/mail-%j.err \
  --mail-type=END,FAIL --mail-user="${MAIL_USER}" \
  --wrap='bash -lc "echo Pipeline finished. Check logs under slurm_logs/ | cat"' )

echo "Submitted MAIL notifier job (after SOLVE): $mail_jid"
echo "Done. Track with: squeue -u $USER"