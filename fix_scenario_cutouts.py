#!/usr/bin/env python3
import sys
import yaml

if len(sys.argv) != 2:
    print("Usage: python fix_scenario_cutouts.py <scenario-file.yaml>")
    sys.exit(1)

input_file = sys.argv[1]
output_file = input_file + '.new'

with open(input_file, 'r') as f:
    data = yaml.safe_load(f)

# Fix cutout structure in each scenario
for scenario_name, scenario_config in data.items():
    if 'atlite' in scenario_config and 'cutouts' in scenario_config['atlite']:
        for cutout_name, cutout_config in scenario_config['atlite']['cutouts'].items():
            # Wrap in prepare_kwargs if not already
            if 'prepare_kwargs' not in cutout_config:
                # Move all params under prepare_kwargs
                scenario_config['atlite']['cutouts'][cutout_name] = {
                    'prepare_kwargs': cutout_config
                }

with open(output_file, 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)

print(f"✅ Fixed: {output_file}")
print(f"Review with: diff {input_file} {output_file}")
