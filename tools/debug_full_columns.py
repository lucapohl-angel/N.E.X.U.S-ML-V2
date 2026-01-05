#!/usr/bin/env python3
"""Create a comprehensive debug image showing ally AND enemy column positions."""

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

# Calculate row height assuming 5 equal rows
row_height = (y_end - y_start) // 5
print(f'Row region: y={y_start}-{y_end}, row_height={row_height}')

# Define colors for each column type
ALLY_HERO_COLOR = (0, 255, 0)       # Green
ALLY_ITEM_COLOR = (255, 0, 0)       # Blue
ENEMY_HERO_COLOR = (0, 0, 255)      # Red
ENEMY_ITEM_COLOR = (255, 0, 255)    # Magenta

# Ally columns
ally_hero_col = 'hero_portrait'
ally_item_cols = [f'item{i}' for i in range(1,7)]

# Enemy columns
enemy_hero_col = 'enemy_hero_portrait'
enemy_item_cols = [f'enemy_item{i}' for i in range(1,7)]

# Draw all 5 rows
for row_idx in range(5):
    row_y_start = y_start + row_idx * row_height
    
    # Draw ally hero portrait
    if ally_hero_col in columns:
        col = columns[ally_hero_col]
        x1 = int(width * col['x_start_pct'])
        x2 = int(width * col['x_end_pct'])
        y_off = int(row_height * col['y_offset_pct'])
        cell_h = int(row_height * col['height_pct'])
        cy1 = row_y_start + y_off
        cy2 = cy1 + cell_h
        cv2.rectangle(img, (x1, cy1), (x2, cy2), ALLY_HERO_COLOR, 2)
        if row_idx == 0:
            cv2.putText(img, 'ALLY HERO', (x1, cy1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, ALLY_HERO_COLOR, 1)
    
    # Draw ally items
    for col_name in ally_item_cols:
        if col_name in columns:
            col = columns[col_name]
            x1 = int(width * col['x_start_pct'])
            x2 = int(width * col['x_end_pct'])
            y_off = int(row_height * col['y_offset_pct'])
            cell_h = int(row_height * col['height_pct'])
            cy1 = row_y_start + y_off
            cy2 = cy1 + cell_h
            cv2.rectangle(img, (x1, cy1), (x2, cy2), ALLY_ITEM_COLOR, 1)
    
    # Draw enemy hero portrait
    if enemy_hero_col in columns:
        col = columns[enemy_hero_col]
        x1 = int(width * col['x_start_pct'])
        x2 = int(width * col['x_end_pct'])
        y_off = int(row_height * col['y_offset_pct'])
        cell_h = int(row_height * col['height_pct'])
        cy1 = row_y_start + y_off
        cy2 = cy1 + cell_h
        cv2.rectangle(img, (x1, cy1), (x2, cy2), ENEMY_HERO_COLOR, 2)
        if row_idx == 0:
            cv2.putText(img, 'ENEMY HERO', (x1, cy1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, ENEMY_HERO_COLOR, 1)
    
    # Draw enemy items
    for col_name in enemy_item_cols:
        if col_name in columns:
            col = columns[col_name]
            x1 = int(width * col['x_start_pct'])
            x2 = int(width * col['x_end_pct'])
            y_off = int(row_height * col['y_offset_pct'])
            cell_h = int(row_height * col['height_pct'])
            cy1 = row_y_start + y_off
            cy2 = cy1 + cell_h
            cv2.rectangle(img, (x1, cy1), (x2, cy2), ENEMY_ITEM_COLOR, 1)

# Draw midline
midline = width // 2
cv2.line(img, (midline, 0), (midline, height), (255, 255, 255), 1)
cv2.putText(img, 'MIDLINE', (midline+5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

cv2.imwrite('output/full_columns_debug.png', img)
print(f'Saved to output/full_columns_debug.png')
print()
print(f'Legend:')
print(f'  GREEN = Ally Hero')
print(f'  BLUE = Ally Items')
print(f'  RED = Enemy Hero')
print(f'  MAGENTA = Enemy Items')
