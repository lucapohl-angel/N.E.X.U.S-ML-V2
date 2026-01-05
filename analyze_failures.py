import cv2
import numpy as np

def get_dominant_colors(img):
    # Convert to HSV
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    return {
        'mean_h': np.mean(h),
        'mean_s': np.mean(s),
        'mean_v': np.mean(v),
        'std_h': np.std(h),
        'std_s': np.std(s),
        'std_v': np.std(v),
    }

# Test each failing case
failures = [
    ('Vitality Crystal', 'ally4_slot6_Vitality_Crystal.png'),
    ('Legion Sword', 'ally5_slot5_Legion_Sword.png'),
    ('Vitality Crystal', 'enemy1_slot5_Vitality_Crystal.png'),
    ('Magic Shoes', 'enemy5_slot1_Magic_Shoes.png'),
]

for expected, crop_file in failures:
    crop = cv2.imread(f'output/debug_failures/{crop_file}')
    icon = cv2.imread(f'items/icons/item_{expected}.png')
    
    if icon is None:
        print(f'{expected}: ICON NOT FOUND')
        continue
        
    crop_colors = get_dominant_colors(crop)
    icon_colors = get_dominant_colors(icon)
    
    print(f'{expected}:')
    print(f'  Crop: H={crop_colors["mean_h"]:.1f}+-{crop_colors["std_h"]:.1f}, S={crop_colors["mean_s"]:.1f}, V={crop_colors["mean_v"]:.1f}')
    print(f'  Icon: H={icon_colors["mean_h"]:.1f}+-{icon_colors["std_h"]:.1f}, S={icon_colors["mean_s"]:.1f}, V={icon_colors["mean_v"]:.1f}')
    print(f'  H diff: {abs(crop_colors["mean_h"] - icon_colors["mean_h"]):.1f}')
    print()
