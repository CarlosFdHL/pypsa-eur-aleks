# v2026.02.0 Migration Testing Checklist

**Use this on Sophia to track migration progress**

## Pre-Migration

- [ ] Current commit hash: `________________`
- [ ] All current work committed and pushed
- [ ] Created backup branch: `git branch backup-v2025.07.0-$(date +%Y%m%d)`
- [ ] Created migration branch: `git checkout -b upgrade-v2026.02.0`
- [ ] Verified no uncommitted changes: `git status`

## Phase 1: Config Updates (One File at a Time)

### File 1: config/mini-sector_droughts.yaml
- [ ] Remove `shared_cutouts: false`
- [ ] Remove `retrieve_databundle: true`
- [ ] Remove `retrieve_cost_data: true`
- [ ] Change `from_gem: true` → `from_powerplantmatching: true`
- [ ] Remove `MWh_MeOH_per_MWh_H2`, `MWh_MeOH_per_tCO2`, `MWh_MeOH_per_MWh_e`
- [ ] Wrap cutout params in `prepare_kwargs:`
- [ ] Committed: `git commit -m "config: update mini-sector_droughts for v2026.02.0"`
- [ ] **Test**: `snakemake -n --configfile config/mini-sector_droughts.yaml`
- [ ] Test result: ✅ / ❌ (notes: _______________)

### File 2: config/config.default.yaml
- [ ] Same changes as above
- [ ] Committed: `git commit -m "config: update config.default for v2026.02.0"`
- [ ] **Test**: `snakemake -n --configfile config/config.default.yaml`
- [ ] Test result: ✅ / ❌ (notes: _______________)

### Files 3-7: Remaining configs
Repeat for:
- [ ] `config/sector_droughts.yaml`
- [ ] `config/sector_droughts+h2.yaml`
- [ ] `config/sector_droughts+bio.yaml`
- [ ] `config/sector_droughts+h2+bio.yaml`
- [ ] `config/sector_droughts-trans.yaml`

Each file:
- [ ] Updated and committed separately
- [ ] Dry run tested
- [ ] Notes: _______________

## Phase 2: Directory Structure

### Cutout Directory
- [ ] Current cutout location verified: `ls -la cutouts/` or `data/cutouts/`
- [ ] Decision: Update symlinks / Update config path
- [ ] Action taken: _______________
- [ ] Committed: `git commit -m "config: update cutout paths"`
- [ ] **Test**: Check cutout access works

## Phase 3: Small Test Run

### Test Case 1: Minimal run
```bash
# Use mini config with 1 weather year
snakemake prepare_sector_networks \
  --configfile config/mini-sector_droughts.yaml \
  -n  # dry run first
```
- [ ] Dry run passed
- [ ] Actual run: `_____________` (date/time)
- [ ] Result: ✅ / ❌
- [ ] Errors encountered: _______________

### Test Case 2: MGA workflow check
```bash
# Test MGA-specific rules
snakemake -n compute_near_opt --configfile config/mini-sector_droughts.yaml
```
- [ ] MGA rules still recognized
- [ ] Path references correct
- [ ] Result: ✅ / ❌
- [ ] Notes: _______________

## Phase 4: Full Test (If Phase 3 passed)

### Single Weather Year
```bash
# Run one complete weather year scenario
snakemake solve_sector_networks \
  --configfile config/sector_droughts.yaml \
  # ... (your usual cluster submission)
```
- [ ] Started: `_____________` (date/time)
- [ ] Completed: `_____________` (date/time)
- [ ] Result: ✅ / ❌
- [ ] Output files verified: ✅ / ❌
- [ ] Errors: _______________

## Phase 5: Decision Point

**All tests passed?**
- [ ] Yes → Proceed to merge
- [ ] No → Document issues and decide next steps

**Issues found:**
```
1. _____________________
2. _____________________
3. _____________________
```

**Action:**
- [ ] Merge to main: `git checkout sector-droughts && git merge upgrade-v2026.02.0`
- [ ] Stay on migration branch for more testing
- [ ] Revert: `git checkout sector-droughts && git branch -D upgrade-v2026.02.0`
- [ ] Postpone migration

## Rollback Procedure (If Needed)

```bash
# If something breaks badly:
git checkout sector-droughts  # or backup-v2025.07.0-YYYYMMDD
git log  # verify you're at the right place
# Continue work on old version
```

## Notes & Observations

Date: _______________

```
Test run observations:
-
-
-

Performance differences:
-
-

Issues to investigate:
-
-
```

## Communication Log

Keep track of when you need to sync with me:

- [ ] Issue found: _______________ → Document here, discuss when back
- [ ] Unexpected behavior: _______________ → Note details
- [ ] Success: _______________ → Update documentation

---

**Remember**: Each phase should work before moving to the next. Commit small, test often.
