"""
Phase 1: Image Mapping Debug Tool

This script visualizes row and column detection on a screenshot.
Use this to verify that the column_mapping.yaml coordinates are correct.

Usage:
    python tools/phase1_debug_mapping.py <screenshot_path>

Output:
    - Annotated image saved to output/debug_mapping.png
    - Console output showing detected regions
"""

import sys
import cv2
import numpy as np
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.field_config import get_config
from app.parser.preprocessor import load_and_normalize
from app.parser.detector import detect_player_rows, crop_column


def draw_rectangles_on_image(img: np.ndarray, rows: list, config) -> np.ndarray:
    """
    Draw colored rectangles showing detected regions.
    
    Args:
        img: Original image
        rows: List of (y_start, y_end) tuples for each row
        config: Field configuration
        
    Returns:
        Annotated image with rectangles drawn
    """
    # Convert to color if grayscale
    if len(img.shape) == 2:
        img_color = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    else:
        img_color = img.copy()
    
    height, width = img.shape[:2]
    
    # Colors for different column types
    colors = {
        'hero_portrait': (255, 100, 100),  # Blue
        'player_name': (100, 255, 100),    # Green
        'stats': (100, 100, 255),          # Red
        'gold': (255, 255, 100),           # Cyan
        'mvp': (255, 100, 255),            # Magenta
    }
    
    # Draw row boundaries
    half_width = width // 2  # Split at middle for blue team (left) and enemy team (right)
    for i, (y_start, y_end) in enumerate(rows):
        # Blue team (left half) - Green lines
        cv2.line(img_color, (0, y_start), (half_width, y_start), (0, 255, 0), 2)
        cv2.line(img_color, (0, y_end), (half_width, y_end), (0, 255, 0), 2)
        cv2.putText(img_color, f"Ally {i+1}", (10, y_start + 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Enemy team (right half) - Red lines
        cv2.line(img_color, (half_width, y_start), (width, y_start), (0, 0, 255), 2)
        cv2.line(img_color, (half_width, y_end), (width, y_end), (0, 0, 255), 2)
        cv2.putText(img_color, f"Enemy {i+1}", (half_width + 10, y_start + 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    
    # Draw column boundaries for each row
    important_columns = [
        'hero_portrait', 'hero_level', 'player_name', 'kills', 'deaths', 'assists',
        'total_gold', 'individual_rating', 'item1', 'item2', 'item3', 'item4', 'item5', 'item6',
        'enemy_hero_portrait', 'enemy_hero_level', 'enemy_player_name', 
        'enemy_kills', 'enemy_deaths', 'enemy_assists', 'enemy_total_gold', 'enemy_rating',
        'enemy_item1', 'enemy_item2', 'enemy_item3', 'enemy_item4', 'enemy_item5', 'enemy_item6'
    ]
    
    for row_idx, (y_start, y_end) in enumerate(rows):
        row_height = y_end - y_start
        
        for col_key in important_columns:
            col_def = config.columns.get(col_key)
            if not col_def:
                continue
            
            # Calculate absolute coordinates
            x_start = int(width * col_def.x_start_pct)
            x_end = int(width * col_def.x_end_pct)
            y_offset = int(row_height * col_def.y_offset_pct)
            col_height = int(row_height * col_def.height_pct)
            
            rect_y_start = y_start + y_offset
            rect_y_end = rect_y_start + col_height
            
            # Choose color based on column type
            if col_key in ['hero_level', 'enemy_hero_level']:
                color = (0, 255, 255)  # Yellow for hero level
            elif col_key in ['kills', 'enemy_kills']:
                color = (0, 255, 0)  # Green for kills
            elif col_key in ['deaths', 'enemy_deaths']:
                color = (0, 0, 255)  # Red for deaths
            elif col_key in ['assists', 'enemy_assists']:
                color = (255, 0, 255)  # Magenta for assists
            elif col_key in ['individual_rating', 'enemy_rating']:
                color = (255, 255, 255)  # White for ratings
            elif col_key.startswith('item') or col_key.startswith('enemy_item'):
                color = (255, 0, 180)  # Pink for items
            elif 'hero' in col_key:
                color = colors['hero_portrait']
            elif 'name' in col_key:
                color = colors['player_name']
            elif 'gold' in col_key:
                color = colors['gold']
            elif 'mvp' in col_key:
                color = colors['mvp']
            else:
                color = colors['stats']
            
            # Draw rectangle
            cv2.rectangle(img_color, 
                         (x_start, rect_y_start), 
                         (x_end, rect_y_end), 
                         color, 2)
            
            # Add label (only on first row to avoid clutter)
            if row_idx == 0:
                cv2.putText(img_color, col_key, 
                           (x_start, rect_y_start - 5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    
    # Draw battle_id as single element below all rows
    if 'battle_id' in config.columns:
        battle_id_def = config.columns['battle_id']
        x_start = int(width * battle_id_def.x_start_pct)
        x_end = int(width * battle_id_def.x_end_pct)
        # Interpret y_offset_pct and height_pct as absolute percentages of image height
        y_start_abs = int(height * battle_id_def.y_offset_pct)
        y_end_abs = int(height * (battle_id_def.y_offset_pct + battle_id_def.height_pct))
        
        color = (0, 165, 255)  # Orange for battle ID
        
        cv2.rectangle(img_color,
                     (x_start, y_start_abs),
                     (x_end, y_end_abs),
                     color, 2)
        
        cv2.putText(img_color, 'battle_id',
                   (x_start, y_start_abs - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    
    # Draw match metadata (non-row elements like battle_id)
    if hasattr(config, 'match_metadata'):
        for meta_key, meta_def in config.match_metadata.items():
            x_start = int(width * meta_def.x_start_pct)
            x_end = int(width * meta_def.x_end_pct)
            y_start_abs = int(height * meta_def.y_start_pct)
            y_end_abs = int(height * meta_def.y_end_pct)
            
            # Orange color for battle_id
            color = (0, 165, 255)
            
            cv2.rectangle(img_color,
                         (x_start, y_start_abs),
                         (x_end, y_end_abs),
                         color, 2)
            
            cv2.putText(img_color, meta_key,
                       (x_start, y_start_abs - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    
    # Draw metadata_regions (game_duration, game_result, etc.)
    if hasattr(config, 'metadata_regions'):
        for meta_key, meta_def in config.metadata_regions.items():
            x_start = int(width * meta_def.x_start_pct)
            x_end = int(width * meta_def.x_end_pct)
            y_start_abs = int(height * meta_def.y_start_pct)
            y_end_abs = int(height * meta_def.y_end_pct)
            
            # Cyan color for metadata regions
            color = (255, 255, 0)  # Bright cyan
            
            cv2.rectangle(img_color,
                         (x_start, y_start_abs),
                         (x_end, y_end_abs),
                         color, 3)
            
            cv2.putText(img_color, meta_key,
                       (x_start, y_start_abs - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    
    return img_color


def print_detection_summary(rows: list, config):
    """Print textual summary of detections."""
    print("\n" + "="*60)
    print("DETECTION SUMMARY")
    print("="*60)
    
    print(f"\n✓ Detected {len(rows)} player rows (expected: 5 for blue team)")
    
    if len(rows) != 5:
        print("\n⚠ WARNING: Expected exactly 5 rows for blue team!")
        print("   Check row_region in column_mapping.yaml")
    
    print("\nRow positions (Y coordinates):")
    for i, (y_start, y_end) in enumerate(rows):
        print(f"  Row {i+1}: y={y_start:4d} to {y_end:4d} (height: {y_end-y_start}px)")
    
    print("\n--- BLUE TEAM (Left Side) ---")
    for col_key, col_def in config.columns.items():
        if col_def.x_start_pct < 0.5:  # Blue team
            print(f"  {col_key:20s}: x={col_def.x_start_pct:.1%} to {col_def.x_end_pct:.1%}")
    
    print("\n--- ENEMY TEAM (Right Side) ---")
    for col_key, col_def in config.columns.items():
        if col_def.x_start_pct >= 0.5:  # Enemy team
            print(f"  {col_key:20s}: x={col_def.x_start_pct:.1%} to {col_def.x_end_pct:.1%}")
    
    # Print metadata regions if they exist
    if hasattr(config, 'metadata_regions'):
        print("\n--- METADATA REGIONS (Absolute Positions) ---")
        for meta_key, meta_def in config.metadata_regions.items():
            print(f"  {meta_key:20s}: x={meta_def.x_start_pct:.1%} to {meta_def.x_end_pct:.1%}, y={meta_def.y_start_pct:.1%} to {meta_def.y_end_pct:.1%}")
    
    print("\n" + "="*60)


def main():
    if len(sys.argv) < 2:
        print("Usage: python phase1_debug_mapping.py <screenshot_path>")
        print("\nExample:")
        print("  python tools/phase1_debug_mapping.py tests/fixtures/sample_screenshot.png")
        sys.exit(1)
    
    screenshot_path = sys.argv[1]
    
    if not Path(screenshot_path).exists():
        print(f"Error: File not found: {screenshot_path}")
        sys.exit(1)
    
    print("="*60)
    print("PHASE 1: IMAGE MAPPING DEBUG TOOL")
    print("="*60)
    print(f"\nProcessing: {screenshot_path}")
    
    # Load configuration
    print("\n1. Loading configuration...")
    config = get_config()
    print(f"   Reference resolution: {config.reference_resolution.width}x{config.reference_resolution.height}")
    print(f"   Expected rows: {config.row_config.get('expected_count', 5)}")
    
    # Load and preprocess image
    print("\n2. Loading and normalizing image...")
    img = load_and_normalize(screenshot_path)
    print(f"   Image size: {img.shape[1]}x{img.shape[0]}")
    
    # Detect rows
    print("\n3. Detecting player rows (blue team only)...")
    rows = detect_player_rows(img, config)
    
    if not rows:
        print("   ✗ ERROR: No rows detected!")
        print("   Try adjusting row_region in column_mapping.yaml")
        sys.exit(1)
    
    print(f"   ✓ Detected {len(rows)} rows")
    
    # Draw visualizations
    print("\n4. Drawing debug visualizations...")
    annotated = draw_rectangles_on_image(img, rows, config)
    
    # Save output
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "debug_mapping.png"
    cv2.imwrite(str(output_path), annotated)
    print(f"   ✓ Saved annotated image to: {output_path}")
    
    # Print summary
    print_detection_summary(rows, config)
    
    print("\n✓ Phase 1 complete!")
    print(f"\nNext steps:")
    print("1. Open {output_path} and verify rectangles align with columns")
    print("2. If misaligned, adjust percentages in config/column_mapping.yaml")
    print("3. Re-run this script until alignment is perfect")
    print("4. Then proceed to Phase 2: python tools/phase2_debug_ocr.py")


if __name__ == "__main__":
    main()
