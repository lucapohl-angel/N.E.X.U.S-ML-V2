import cv2
import sys
from pathlib import Path
sys.path.insert(0, 'app/parser')
from item_matcher import ItemMatcher

matcher = ItemMatcher(Path('items/icons'))

# Test each failing case
failures = [
    ('ally4_slot6_Vitality_Crystal.png', 'Vitality Crystal', 'Resonating Heart'),
    ('ally5_slot5_Legion_Sword.png', 'Legion Sword', 'Mystic Container'),
    ('enemy1_slot5_Vitality_Crystal.png', 'Vitality Crystal', 'Resonating Heart'),
    ('enemy5_slot1_Magic_Shoes.png', 'Magic Shoes', 'Tough Boots'),
]

for crop_file, expected, wrong_detected in failures:
    crop = cv2.imread(f'output/debug_failures/{crop_file}')
    if crop is None:
        print(f'SKIP: {crop_file} not found')
        continue
    
    results = matcher.match_item(crop, top_n=20)
    
    print(f'\n{"="*70}')
    print(f'{crop_file}')
    print(f'Expected: {expected}')
    print(f'{"="*70}')
    
    # Find expected item's rank and score
    exp_result = None
    exp_rank = None
    for i, r in enumerate(results):
        if r.item_name == expected:
            exp_result = r
            exp_rank = i + 1
            break
    
    # Show top 5
    print(f'\nTop 5 matches:')
    for i, r in enumerate(results[:5]):
        marker = ' <-- EXPECTED' if r.item_name == expected else ''
        print(f'  #{i+1}: {r.item_name} (conf={r.confidence:.3f}){marker}')
        print(f'       template={r.method_scores["template"]:.3f}, phash={r.method_scores["phash"]:.3f}, hist={r.method_scores["histogram"]:.3f}')
        print(f'       ssim={r.method_scores["ssim"]:.3f}, edge={r.method_scores["edge"]:.3f}, color={r.method_scores["color"]:.3f}')
    
    if exp_result and exp_rank > 5:
        print(f'\n  ... ({expected} is at rank #{exp_rank})')
        print(f'       conf={exp_result.confidence:.3f}')
        print(f'       template={exp_result.method_scores["template"]:.3f}, phash={exp_result.method_scores["phash"]:.3f}')
    elif exp_result is None:
        print(f'\n  *** {expected} NOT FOUND in results!')
