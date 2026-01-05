#!/usr/bin/env python3
"""Debug specific failing item matches to understand why they're wrong."""

import cv2
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.detector import detect_player_rows
from app.parser.item_matcher import ItemMatcher
from app.parser.hero_matcher import HeroMatcher
from app.core.field_config import get_config
import yaml

os.makedirs('output/debug_failures', exist_ok=True)

# Load image and config
img = cv2.imread('tests/fixtures/test (1).jpeg')
height, width = img.shape[:2]

with open('config/column_mapping.yaml', 'r') as f:
    col_config = yaml.safe_load(f)

columns = col_config['columns']
config = get_config()
rows = detect_player_rows(img, config)

item_matcher = ItemMatcher()
hero_matcher = HeroMatcher()

# Failures to debug
FAILURES = [
    # (team, player_idx, slot_idx, expected_name)
    ("ally", 1, 4, "Lightning Truncheon"),  # Ally 2 Slot 4
    ("ally", 3, 6, "Vitality Crystal"),      # Ally 4 Slot 6
    ("ally", 4, 5, "Legion Sword"),           # Ally 5 Slot 5
    ("enemy", 4, 1, "Magic Shoes"),           # Enemy 5 Slot 1
]

HERO_FAILURES = [
]

def get_item_crop(team, player_idx, slot_idx):
    """Get item crop for given player and slot."""
    row = rows[player_idx]
    y_start, y_end = row
    row_height = y_end - y_start
    
    if team == "ally":
        slot_key = f"item{slot_idx}"
    else:
        # Enemy items are reversed: slot 1 = enemy_item6, etc.
        enemy_slot = 7 - slot_idx
        slot_key = f"enemy_item{enemy_slot}"
    
    col_def = columns[slot_key]
    x_start = int(width * col_def['x_start_pct'])
    x_end = int(width * col_def['x_end_pct'])
    y_offset = int(row_height * col_def['y_offset_pct'])
    cell_height = int(row_height * col_def['height_pct'])
    
    cell_y_start = y_start + y_offset
    cell_y_end = cell_y_start + cell_height
    
    return img[cell_y_start:cell_y_end, x_start:x_end].copy()

def get_hero_crop(team, player_idx):
    """Get hero crop for given player."""
    row = rows[player_idx]
    y_start, y_end = row
    row_height = y_end - y_start
    
    if team == "ally":
        col_key = "hero_portrait"
    else:
        col_key = "enemy_hero_portrait"
    
    col_def = columns[col_key]
    x_start = int(width * col_def['x_start_pct'])
    x_end = int(width * col_def['x_end_pct'])
    y_offset = int(row_height * col_def['y_offset_pct'])
    cell_height = int(row_height * col_def['height_pct'])
    
    cell_y_start = y_start + y_offset
    cell_y_end = cell_y_start + cell_height
    
    return img[cell_y_start:cell_y_end, x_start:x_end].copy()

print("=" * 70)
print("DEBUGGING ITEM FAILURES")
print("=" * 70)

for team, player_idx, slot_idx, expected in FAILURES:
    print(f"\n{team.upper()} {player_idx+1} Slot {slot_idx} - Expected: {expected}")
    print("-" * 50)
    
    crop = get_item_crop(team, player_idx, slot_idx)
    
    # Save crop
    safe_name = expected.replace(' ', '_').replace("'", "")
    fname = f"output/debug_failures/{team}{player_idx+1}_slot{slot_idx}_{safe_name}.png"
    cv2.imwrite(fname, crop)
    print(f"  Saved crop: {crop.shape[1]}x{crop.shape[0]}px")
    
    # Get top 5 matches
    matches = item_matcher.match_item(crop, top_n=5)
    print(f"  Top 5 matches:")
    for i, m in enumerate(matches[:5]):
        marker = "✓" if m.item_name.lower() == expected.lower() else " "
        print(f"    {marker} {i+1}. {m.item_name}: {m.confidence:.1%}")
        if i == 0:
            print(f"       Methods: {dict(list(m.method_scores.items())[:4])}")

print("\n" + "=" * 70)
print("DEBUGGING HERO FAILURES")
print("=" * 70)

for team, player_idx, expected in HERO_FAILURES:
    print(f"\n{team.upper()} {player_idx+1} - Expected: {expected}")
    print("-" * 50)
    
    crop = get_hero_crop(team, player_idx)
    
    # Save crop
    fname = f"output/debug_failures/{team}{player_idx+1}_hero_{expected}.png"
    cv2.imwrite(fname, crop)
    print(f"  Saved crop: {crop.shape[1]}x{crop.shape[0]}px")
    
    # Get match
    match = hero_matcher.match_hero(crop)
    if match:
        print(f"  Detected: {match.hero_name} ({match.confidence:.1%})")
        print(f"  Methods: {dict(list(match.method_scores.items())[:5])}")

print("\n" + "=" * 70)
print(f"Crops saved to output/debug_failures/")
print("=" * 70)
