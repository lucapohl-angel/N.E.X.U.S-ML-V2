"""
Analysis of 4 failing item detections
"""
import cv2
import json

# Ground truth failures
failures = [
    ('ally', 4, 6, 'Vitality Crystal', 'Resonating Heart'),
    ('ally', 5, 5, 'Legion Sword', 'Mystic Container'),  
    ('enemy', 1, 5, 'Vitality Crystal', 'Resonating Heart'),
    ('enemy', 5, 1, 'Magic Shoes', 'Tough Boots'),
]

with open('output/test (1)_extraction.json') as f:
    data = json.load(f)

print("FAILURE ANALYSIS")
print("="*60)

for side, player_num, slot_num, expected, detected in failures:
    player_idx = player_num - 1
    slot_idx = slot_num - 1
    
    if side == 'ally':
        player = data['allies'][player_idx]
    else:
        player = data['enemies'][player_idx]
    
    hero = player['hero']['hero_name'] if player.get('hero') else 'Unknown'
    item = player['items'][slot_idx]
    
    print(f"\n{side.capitalize()} {player_num} ({hero}) - Slot {slot_num}:")
    print(f"  Ground truth: {expected}")
    print(f"  Detected:     {detected}")
    print(f"  Confidence:   {item['confidence']:.1%}" if item else "  Empty slot")
    
    # Check surrounding items for context
    print(f"  Other items detected:")
    for i, it in enumerate(player['items']):
        if i == slot_idx:
            continue
        if it:
            print(f"    Slot {i+1}: {it['item_name']} ({it['confidence']:.0%})")

print("\n" + "="*60)
print("\nRECOMMENDATIONS:")
print("""
1. Vitality Crystal (ally4 & enemy1):
   - Detected as Resonating Heart with high template score (0.73-0.79)
   - Vitality Crystal template score is only 0.49-0.56
   - LIKELY: Reference icon mismatch - needs update

2. Legion Sword (ally5):
   - Not even in top 20 results
   - Detected as Mystic Container (0.66 template)
   - LIKELY: Reference icon fundamentally different - needs replacement

3. Magic Shoes (enemy5):
   - Only 0.10 template score vs reference
   - Detected as Tough Boots (0.45 template)
   - Ally2 has correctly-detected Magic Shoes (0.71 conf)
   - Ally2 Magic Shoes looks completely different from Enemy5 crop
   - POSSIBLY: Ground truth error OR different item variant

NEXT STEPS:
- Update reference icons from official game assets
- OR verify ground truth visually from screenshot
- OR accept 92-93% accuracy as practical limit
""")
