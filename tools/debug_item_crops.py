#!/usr/bin/env python3
"""
Debug item crops - save all item crops for visual inspection.
Uses column_mapping.yaml for accurate positioning.
"""

import cv2
import numpy as np
import os
import sys
import yaml
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.parser.detector import detect_player_rows
from app.core.field_config import get_config

def get_column_mapping():
    with open("config/column_mapping.yaml", 'r') as f:
        config = yaml.safe_load(f)
    return config['columns']

def main():
    # Load test image
    img_path = "tests/fixtures/test (1).jpeg"
    img = cv2.imread(img_path)
    if img is None:
        print(f"Failed to load {img_path}")
        return
    
    h, w = img.shape[:2]
    print(f"Image size: {w}x{h}")
    
    # Get column mapping
    columns = get_column_mapping()
    
    # Create output directory
    output_dir = Path("output/item_crops")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Detect rows
    field_config = get_config()
    ally_rows = detect_player_rows(img, field_config)
    print(f"\nDetected {len(ally_rows)} player rows")
    
    # Ground truth for comparison
    ALLY_ITEMS = [
        ["Tough Boots", "War Axe", "Hunter Strike", "Ares Belt", "Hero's Ring", "EMPTY"],
        ["Magic Shoes", "Enchanted Talisman", "Glowing Wand", "Lightning Truncheon", "Mystery Codex", "EMPTY"],
        ["Warrior Boots", "Windtalker", "Haas' Claws", "Berserker's Fury", "Malefic Gun", "EMPTY"],
        ["Rapid Boots", "Thunder Belt", "Dominance Ice", "Oracle", "Ares Belt", "Vitality Crystal"],
        ["Rapid Boots", "Corrosion Scythe", "War Axe", "Great Dragon Spear", "Blade of the Heptaseas", "EMPTY"]
    ]
    
    ENEMY_ITEMS = [
        ["Tough Boots", "Blade Armor", "Antique Cuirass", "Athena's Shield", "Immortality", "EMPTY"],
        ["Ice Retribution", "Tough Boots", "Dominance Ice", "Athena's Shield", "Antique Cuirass", "Oracle"],
        ["Tough Boots", "Genius Wand", "Clock of Destiny", "Lightning Truncheon", "Divine Glaive", "Holy Crystal"],
        ["Swift Boots", "Endless Battle", "Blade of the Heptaseas", "War Axe", "Hunter Strike", "Malefic Roar"],
        ["Magic Shoes", "Clock of Destiny", "Lightning Truncheon", "Divine Glaive", "Holy Crystal", "EMPTY"]
    ]
    
    # ===============================
    # ALLY ITEM CROPS
    # ===============================
    print("\n" + "=" * 60)
    print("ALLY ITEM CROPS")
    print("=" * 60)
    
    print("\nAlly item slot positions from config:")
    for i in range(1, 7):
        key = f"item{i}"
        if key in columns:
            cfg = columns[key]
            x_start = int(cfg["x_start_pct"] * w)
            x_end = int(cfg["x_end_pct"] * w)
            print(f"  Slot {i}: x={x_start}-{x_end} (width: {x_end-x_start}px)")
    
    for player_idx, (y_start, y_end) in enumerate(ally_rows):
        print(f"\nAlly {player_idx + 1} (row y={y_start}-{y_end}):")
        
        for slot_num in range(1, 7):
            key = f"item{slot_num}"
            if key not in columns:
                print(f"  Slot {slot_num}: NOT IN CONFIG")
                continue
                
            slot_config = columns[key]
            x_start = int(slot_config["x_start_pct"] * w)
            x_end = int(slot_config["x_end_pct"] * w)
            
            # Apply y offset
            y_offset = int(slot_config.get("y_offset_pct", 0.4) * (y_end - y_start))
            height = int(slot_config.get("height_pct", 0.46) * (y_end - y_start))
            
            cell_y_start = y_start + y_offset
            cell_y_end = cell_y_start + height
            
            # Crop the cell
            cell = img[cell_y_start:cell_y_end, x_start:x_end]
            
            if cell.size > 0:
                expected = ALLY_ITEMS[player_idx][slot_num - 1]
                safe_name = expected.replace(' ', '_').replace("'", "")
                crop_name = f"ally{player_idx+1}_slot{slot_num}_{safe_name}.png"
                crop_path = output_dir / crop_name
                cv2.imwrite(str(crop_path), cell)
                print(f"  Slot {slot_num}: {cell.shape[1]}x{cell.shape[0]}px @ ({x_start},{cell_y_start}) - expected: {expected}")
    
    # ===============================
    # ENEMY ITEM CROPS
    # ===============================
    print("\n" + "=" * 60)
    print("ENEMY ITEM CROPS")
    print("=" * 60)
    
    # Check enemy_item* columns
    has_enemy_items = f"enemy_item1" in columns
    
    if has_enemy_items:
        print("\nEnemy item slot positions from config:")
        for i in range(1, 7):
            key = f"enemy_item{i}"
            if key in columns:
                cfg = columns[key]
                x_start = int(cfg["x_start_pct"] * w)
                x_end = int(cfg["x_end_pct"] * w)
                print(f"  Slot {i}: x={x_start}-{x_end} (width: {x_end-x_start}px)")
        
        # Note: enemy items in config are VISUAL order
        # enemy_item6 is LEFTMOST (x=0.5984), enemy_item1 is RIGHTMOST (x=0.7674)
        # This is the REVERSE of ally items
        
        for player_idx, (y_start, y_end) in enumerate(ally_rows):
            print(f"\nEnemy {player_idx + 1} (row y={y_start}-{y_end}):")
            
            for slot_num in range(1, 7):
                key = f"enemy_item{slot_num}"
                if key not in columns:
                    print(f"  Slot {slot_num}: NOT IN CONFIG")
                    continue
                    
                slot_config = columns[key]
                x_start = int(slot_config["x_start_pct"] * w)
                x_end = int(slot_config["x_end_pct"] * w)
                
                # Apply y offset
                y_offset = int(slot_config.get("y_offset_pct", 0.4) * (y_end - y_start))
                height = int(slot_config.get("height_pct", 0.46) * (y_end - y_start))
                
                cell_y_start = y_start + y_offset
                cell_y_end = cell_y_start + height
                
                # Crop the cell
                cell = img[cell_y_start:cell_y_end, x_start:x_end]
                
                if cell.size > 0:
                    expected = ENEMY_ITEMS[player_idx][slot_num - 1]
                    safe_name = expected.replace(' ', '_').replace("'", "")
                    crop_name = f"enemy{player_idx+1}_slot{slot_num}_{safe_name}.png"
                    crop_path = output_dir / crop_name
                    cv2.imwrite(str(crop_path), cell)
                    print(f"  Slot {slot_num}: {cell.shape[1]}x{cell.shape[0]}px @ ({x_start},{cell_y_start}) - expected: {expected}")
    else:
        print("\nNo enemy_item* columns defined in column_mapping.yaml")
    
    # ===============================
    # VISUAL COMPARISON IMAGE
    # ===============================
    print("\n" + "=" * 60)
    print("Creating visual comparison image...")
    print("=" * 60)
    
    # Draw rectangles on image for all item slots
    debug_img = img.copy()
    
    for player_idx, (y_start, y_end) in enumerate(ally_rows):
        # Ally items - green
        for slot_num in range(1, 7):
            key = f"item{slot_num}"
            if key in columns:
                cfg = columns[key]
                x1 = int(cfg["x_start_pct"] * w)
                x2 = int(cfg["x_end_pct"] * w)
                y_offset = int(cfg.get("y_offset_pct", 0.4) * (y_end - y_start))
                height = int(cfg.get("height_pct", 0.46) * (y_end - y_start))
                y1 = y_start + y_offset
                y2 = y1 + height
                cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 1)
        
        # Enemy items - red
        for slot_num in range(1, 7):
            key = f"enemy_item{slot_num}"
            if key in columns:
                cfg = columns[key]
                x1 = int(cfg["x_start_pct"] * w)
                x2 = int(cfg["x_end_pct"] * w)
                y_offset = int(cfg.get("y_offset_pct", 0.4) * (y_end - y_start))
                height = int(cfg.get("height_pct", 0.46) * (y_end - y_start))
                y1 = y_start + y_offset
                y2 = y1 + height
                cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 0, 255), 1)
    
    cv2.imwrite(str(output_dir / "debug_all_items.png"), debug_img)
    print(f"Saved debug image: {output_dir}/debug_all_items.png")
    
    print(f"\n\n✓ Saved all crops to {output_dir}")
    print("\nItem files saved:")
    saved_files = list(output_dir.glob("*.png"))
    print(f"  Total: {len(saved_files)} files")

if __name__ == "__main__":
    main()
