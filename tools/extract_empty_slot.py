"""Script to extract empty slot image for empty detection."""

import cv2
import yaml
from pathlib import Path

def main():
    # Load image
    img = cv2.imread("tests/fixtures/test (1).jpeg")
    if img is None:
        print("Could not load image")
        return
    
    h, w = img.shape[:2]
    print(f"Image size: {w}x{h}")
    
    # Load column mappings
    with open("config/column_mapping.yaml", 'r') as f:
        config = yaml.safe_load(f)
    
    columns = config['columns']
    
    # Ally 2 slot 6 is empty according to ground truth
    # Row 2 (ally 2) coordinates - approximate
    y_start_pct = 0.17
    y_end_pct = 0.52
    num_rows = 5
    
    row_region_height = h * (y_end_pct - y_start_pct)
    row_height = row_region_height / num_rows
    
    # Row 2 (index 1) - Ally 2
    row2_y_start = int(h * y_start_pct + row_height * 1)
    row2_y_end = int(row2_y_start + row_height)
    
    print(f"Ally 2 row: {row2_y_start} to {row2_y_end}")
    
    # Get item6 column
    item6 = columns['item6']
    x_start = int(w * item6['x_start_pct'])
    x_end = int(w * item6['x_end_pct'])
    y_offset = int(row_height * item6['y_offset_pct'])
    cell_height = int(row_height * item6['height_pct'])
    
    cell_y_start = row2_y_start + y_offset
    cell_y_end = cell_y_start + cell_height
    
    print(f"Empty slot coordinates: x={x_start}-{x_end}, y={cell_y_start}-{cell_y_end}")
    
    # Crop empty slot
    empty_slot = img[cell_y_start:cell_y_end, x_start:x_end]
    
    # Save to items folder
    output_path = Path("items/icons/item_EMPTY.png")
    cv2.imwrite(str(output_path), empty_slot)
    print(f"✓ Saved empty slot image to: {output_path}")
    
    # Also save a reference crop
    cv2.imwrite("output/empty_slot_reference.png", empty_slot)
    print(f"✓ Saved reference to: output/empty_slot_reference.png")


if __name__ == "__main__":
    main()
