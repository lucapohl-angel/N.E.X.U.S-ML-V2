#!/usr/bin/env python3
"""Debug item matching to understand false matches."""
import sys
sys.path.insert(0, '.')
from app.parser.item_matcher import ItemMatcher
import cv2

matcher = ItemMatcher()

# Load a crop that's getting wrong match
crop = cv2.imread('output/item_crops/ally4_slot1_Rapid_Boots.png')

# Get top matches
results = matcher.match_item(crop, top_n=5)

print('Top 5 matches for Ally4 Slot1 (expected: Rapid Boots):')
for r in results:
    print(f'  {r.item_name}: {r.confidence:.3f}')
    scores = r.method_scores
    print(f'    template={scores.get("template", 0):.3f}, color={scores.get("color", 0):.3f}, edge={scores.get("edge", 0):.3f}')
    print(f'    ssim={scores.get("ssim", 0):.3f}, histogram={scores.get("histogram", 0):.3f}, center={scores.get("center", 0):.3f}')
