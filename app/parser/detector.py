"""
Row and column detection module.

Detects player rows and extracts column regions from screenshots.
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class RowRegion:
    """Represents a detected player row."""
    index: int
    y_start: int
    y_end: int
    height: int
    
    @property
    def center_y(self) -> int:
        return (self.y_start + self.y_end) // 2


def detect_player_rows(img: np.ndarray, config) -> List[Tuple[int, int]]:
    """
    Detect player rows in the screenshot (blue team only).
    
    Uses the configured row_region to focus on blue team area,
    then detects horizontal lines/bands corresponding to player rows.
    
    Args:
        img: Preprocessed image
        config: Field configuration with row settings
        
    Returns:
        List of (y_start, y_end) tuples for each detected row
    """
    height, width = img.shape[:2]
    row_cfg = config.row_config
    
    # Get Y-axis region for blue team
    y_start_pct = row_cfg.get('row_region', {}).get('y_start_pct', 0.17)
    y_end_pct = row_cfg.get('row_region', {}).get('y_end_pct', 0.52)
    
    y_start = int(height * y_start_pct)
    y_end = int(height * y_end_pct)
    
    # Crop to blue team region
    roi = img[y_start:y_end, :]
    
    # Convert to grayscale if needed
    if len(roi.shape) == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = roi.copy()
    
    # Use horizontal projection to find rows
    # Sum pixels horizontally to get vertical profile
    projection = np.sum(gray, axis=1)
    
    # Smooth the projection
    kernel_size = 5
    projection_smooth = np.convolve(projection, np.ones(kernel_size)/kernel_size, mode='same')
    
    # Find peaks (brighter regions = player rows)
    # In game UI, player rows are usually brighter than gaps between them
    threshold = np.mean(projection_smooth)
    
    # Find contiguous regions above threshold
    rows = []
    in_row = False
    current_row_start = 0
    
    for i, val in enumerate(projection_smooth):
        if not in_row and val > threshold:
            # Start of a row
            in_row = True
            current_row_start = i
        elif in_row and val <= threshold:
            # End of a row
            in_row = False
            row_height = i - current_row_start
            
            # Filter out very small regions (noise)
            min_height = row_cfg.get('min_row_height_px', 40)
            max_height = row_cfg.get('max_row_height_px', 120)
            
            if min_height <= row_height <= max_height:
                # Convert back to full image coordinates
                rows.append((y_start + current_row_start, y_start + i))
    
    # Handle case where last row extends to end
    if in_row:
        row_height = len(projection_smooth) - current_row_start
        min_height = row_cfg.get('min_row_height_px', 40)
        max_height = row_cfg.get('max_row_height_px', 120)
        if min_height <= row_height <= max_height:
            rows.append((y_start + current_row_start, y_start + len(projection_smooth)))
    
    # Expected count (should be 5 for blue team)
    expected_count = row_cfg.get('expected_count', 5)
    
    # If we detected more or fewer rows, try to fix
    if len(rows) != expected_count:
        # Fallback: divide region into equal parts
        rows = _fallback_equal_division(y_start, y_end, expected_count)
    
    return rows


def _fallback_equal_division(y_start: int, y_end: int, count: int) -> List[Tuple[int, int]]:
    """
    Fallback method: divide region into equal rows.
    
    Used when automatic detection fails.
    """
    total_height = y_end - y_start
    row_height = total_height // count
    
    rows = []
    for i in range(count):
        row_start = y_start + (i * row_height)
        row_end = row_start + row_height
        rows.append((row_start, row_end))
    
    return rows


def crop_column(img: np.ndarray, 
                row: Tuple[int, int], 
                column_def, 
                width: Optional[int] = None) -> np.ndarray:
    """
    Crop a specific column from a row.
    
    Args:
        img: Full image
        row: (y_start, y_end) tuple for the row
        column_def: Column definition from config
        width: Image width (if None, will be inferred from img)
        
    Returns:
        Cropped column image
    """
    if width is None:
        height, width = img.shape[:2]
    
    y_start, y_end = row
    row_height = y_end - y_start
    
    # Calculate absolute coordinates
    x_start = int(width * column_def.x_start_pct)
    x_end = int(width * column_def.x_end_pct)
    y_offset = int(row_height * column_def.y_offset_pct)
    col_height = int(row_height * column_def.height_pct)
    
    # Calculate final crop region
    crop_y_start = y_start + y_offset
    crop_y_end = min(crop_y_start + col_height, y_end)
    crop_x_start = max(0, x_start)
    crop_x_end = min(x_end, width)
    
    # Crop
    cropped = img[crop_y_start:crop_y_end, crop_x_start:crop_x_end]
    
    return cropped


def crop_match_metadata_region(img: np.ndarray, region_def) -> np.ndarray:
    """
    Crop a match metadata region (not tied to player rows).
    
    Args:
        img: Full image
        region_def: MatchMetadataRegion definition
        
    Returns:
        Cropped region
    """
    height, width = img.shape[:2]
    
    x_start = int(width * region_def.x_start_pct)
    x_end = int(width * region_def.x_end_pct)
    y_start = int(height * region_def.y_start_pct)
    y_end = int(height * region_def.y_end_pct)
    
    # Bounds checking
    x_start = max(0, x_start)
    x_end = min(x_end, width)
    y_start = max(0, y_start)
    y_end = min(y_end, height)
    
    return img[y_start:y_end, x_start:x_end]


def detect_active_tab(img: np.ndarray) -> str:
    """
    Detect which tab is currently active by analyzing header text.
    
    Args:
        img: Full screenshot
        
    Returns:
        Tab name: 'overall', 'equipment', 'dps', 'team', 'farm', or 'unknown'
    """
    # This is a simplified version - in Phase 2 we'll use OCR on headers
    # For now, return 'unknown' and let the user specify
    
    # TODO Phase 2: OCR the header row to detect tab
    # Look for keywords:
    # - "Total Gold" + "Jungle Gold" = 'overall' or 'farm'
    # - "Hero Damage" + "Turret Damage" = 'dps'
    # - "Crowd Control" + "Healing" = 'team'
    # - Items visible = 'equipment'
    
    return 'unknown'


if __name__ == "__main__":
    # Test detection
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    from app.core.field_config import get_config
    from app.parser.preprocessor import load_and_normalize
    
    if len(sys.argv) < 2:
        print("Usage: python detector.py <image_path>")
        sys.exit(1)
    
    img_path = sys.argv[1]
    print(f"Loading: {img_path}")
    
    config = get_config()
    img = load_and_normalize(img_path)
    
    print("Detecting rows...")
    rows = detect_player_rows(img, config)
    print(f"Detected {len(rows)} rows:")
    for i, (y_start, y_end) in enumerate(rows):
        print(f"  Row {i+1}: y={y_start} to {y_end} (height: {y_end-y_start}px)")
    
    # Test cropping a column
    if rows:
        player_name_col = config.columns.get('player_name')
        if player_name_col:
            print("\nTesting column crop (player_name from row 1)...")
            cropped = crop_column(img, rows[0], player_name_col)
            print(f"  Cropped region size: {cropped.shape[1]}x{cropped.shape[0]}")
            
            output_path = "output/test_crop.png"
            Path("output").mkdir(exist_ok=True)
            cv2.imwrite(output_path, cropped)
            print(f"  Saved to: {output_path}")
