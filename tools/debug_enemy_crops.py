#!/usr/bin/env python3
"""Debug what's actually being cropped for enemies."""

import cv2
import yaml
import os

os.makedirs('output/debug_enemy_crops', exist_ok=True)

# Load image
img = cv2.imread('tests/fixtures/test (1).jpeg')
height, width = img.shape[:2]
print(f'Image size: {width}x{height}')

# Load column mappings
with open('config/column_mapping.yaml', 'r') as f:
    config = yaml.safe_load(f)

columns = config['columns']

# Get row region
row_cfg = config['rows']['row_region']
y_start = int(height * row_cfg['y_start_pct'])
y_end = int(height * row_cfg['y_end_pct'])

# Calculate row height assuming 5 equal rows
row_height = (y_end - y_start) // 5
print(f'Row region: y={y_start}-{y_end}, row_height={row_height}')

# Save crops for enemy player 1 (row 0)
enemy_cols = ['enemy_hero_portrait'] + [f'enemy_item{i}' for i in range(1,7)]

for row_idx in range(5):
    row_y_start = y_start + row_idx * row_height
    print(f'\nEnemy {row_idx+1} (row_y_start={row_y_start}):')
    
    for col_name in enemy_cols:
        if col_name in columns:
            col = columns[col_name]
            x1 = int(width * col['x_start_pct'])
            x2 = int(width * col['x_end_pct'])
            
            y_off = int(row_height * col['y_offset_pct'])
            cell_h = int(row_height * col['height_pct'])
            
            cy1 = row_y_start + y_off
            cy2 = cy1 + cell_h
            
            # Crop the cell
            crop = img[cy1:cy2, x1:x2].copy()
            
            # Save crop
            fname = f'output/debug_enemy_crops/enemy{row_idx+1}_{col_name}.png'
            cv2.imwrite(fname, crop)
            print(f'  {col_name}: saved {crop.shape[1]}x{crop.shape[0]}px')

print('\nAll crops saved to output/debug_enemy_crops/')
