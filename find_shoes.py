import cv2
import sys
from pathlib import Path
sys.path.insert(0, 'app/parser')
from item_matcher import ItemMatcher

matcher = ItemMatcher(Path('items/icons'))

# Test Enemy 5 Slot 1 crop with all results
crop = cv2.imread('output/debug_failures/enemy5_slot1_Magic_Shoes_wrong.png')
results = matcher.match_item(crop, top_n=105)

# Find Magic Shoes
for i, r in enumerate(results):
    if r.item_name == 'Magic Shoes':
        print(f'Magic Shoes is at rank #{i+1} ({r.confidence:.1%})')
        print(f'  template={r.method_scores["template"]:.3f}')
        print(f'  phash={r.method_scores["phash"]:.3f}')
        break
else:
    print('Magic Shoes not found at all!')
