#!/bin/bash
# Config Migration Script for v2026.02.0
# Run this in sector-droughts/workflow/pypsa-eur directory
#
# USAGE: ./config-migration-script.sh config/sector_droughts.yaml
#
# This creates a .new file - review before replacing original

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <config-file>"
    echo "Example: $0 config/sector_droughts.yaml"
    exit 1
fi

CONFIG_FILE="$1"
OUTPUT_FILE="${CONFIG_FILE}.new"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: File $CONFIG_FILE not found"
    exit 1
fi

echo "Creating migrated config: $OUTPUT_FILE"
echo "Original preserved at: $CONFIG_FILE"

# Create working copy
cp "$CONFIG_FILE" "$OUTPUT_FILE"

# 1. Remove shared_cutouts line
sed -i.bak '/shared_cutouts:/d' "$OUTPUT_FILE"

# 2. Remove retrieve lines from enable section
sed -i.bak '/retrieve_databundle:/d' "$OUTPUT_FILE"
sed -i.bak '/retrieve_cost_data:/d' "$OUTPUT_FILE"

# 3. Rename from_gem to from_powerplantmatching
sed -i.bak 's/from_gem:/from_powerplantmatching:/g' "$OUTPUT_FILE"

# 4. Remove MWh_MeOH lines (but NOT MWh_MeOH_per_tMeOH)
sed -i.bak '/MWh_MeOH_per_MWh_H2:/d' "$OUTPUT_FILE"
sed -i.bak '/MWh_MeOH_per_tCO2:/d' "$OUTPUT_FILE"
sed -i.bak '/MWh_MeOH_per_MWh_e:/d' "$OUTPUT_FILE"

# Clean up backup files
rm -f "${OUTPUT_FILE}.bak"

echo ""
echo "✅ Migration complete!"
echo ""
echo "Next steps:"
echo "1. Review differences: diff $CONFIG_FILE $OUTPUT_FILE"
echo "2. If looks good: mv $OUTPUT_FILE $CONFIG_FILE"
echo "3. Test: snakemake -n --configfile $CONFIG_FILE"
echo ""
echo "⚠️  Note: Cutout structure (prepare_kwargs) must be updated manually"
echo "   See migration guide for details"
