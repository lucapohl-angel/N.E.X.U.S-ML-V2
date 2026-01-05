#!/usr/bin/env python3
"""Debug enemy column positions on screenshot."""

import cv2
import yaml

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

print(f'Row region: y={y_start}-{y_end}')

# Calculate row height assuming 5 equal rows
row_height = (y_end - y_start) // 5
print(f'Row height: {row_height}')

# Draw all 5 enemy rows
enemy_cols = ['enemy_hero_portrait'] + [f'enemy_item{i}' for i in range(1,7)]
colors = [(0, 0, 255), (255, 0, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 0), (128, 128, 255)]

for row_idx in range(5):
    row_y_start = y_start + row_idx * row_height
    
    for col_idx, col_name in enumerate(enemy_cols):
        if col_name in columns:
            col = columns[col_name]
            x1 = int(width * col['x_start_pct'])
            x2 = int(width * col['x_end_pct'])
            
            y_off = int(row_height * col['y_offset_pct'])
            cell_h = int(row_height * col['height_pct'])
            
            cy1 = row_y_start + y_off
            cy2 = cy1 + cell_h
            
            cv2.rectangle(img, (x1, cy1), (x2, cy2), colors[col_idx], 2)
            if row_idx == 0:
                x_start_pct = col['x_start_pct']
                x_end_pct = col['x_end_pct']
                print(f'{col_name}: x={x1}-{x2} (x%={x_start_pct:.3f}-{x_end_pct:.3f})')

cv2.imwrite('output/enemy_columns_debug.png', img)
print('Saved to output/enemy_columns_debug.png')
