import json

# Ground truth from test1_data.txt
gt = {
    'allies': [
        # Ally 1: Yu Zhong
        ['Tough Boots', 'War Axe', 'Hunter Strike', 'Ares Belt', "Hero's Ring", None],
        # Ally 2: Xavier
        ['Magic Shoes', 'Enchanted Talisman', 'Glowing Wand', 'Lightning Truncheon', 'Mystery Codex', None],
        # Ally 3: Layla
        ['Warrior Boots', 'Windtalker', "Haas' Claws", "Berserker's Fury", 'Malefic Gun', None],
        # Ally 4: Badang
        ['Rapid Boots', 'Thunder Belt', 'Dominance Ice', 'Oracle', 'Ares Belt', 'Vitality Crystal'],
        # Ally 5: Sun
        ['Rapid Boots', 'Windtalker', 'Corrosion Scythe', 'Great Dragon Spear', 'Legion Sword', None],
    ],
    'enemies': [
        # Enemy 1: X.Borg
        ['Tough Boots', 'Sky Piercer', 'War Axe', 'Ares Belt', 'Vitality Crystal', 'Leather Jerkin'],
        # Enemy 2: Hanabi
        ['Swift Boots', 'Corrosion Scythe', 'Demon Hunter Sword', 'Regular Spear', 'Dagger', 'Dagger'],
        # Enemy 3: Estes
        ['Demon Shoes', 'Flask of the Oasis', 'Enchanted Talisman', None, None, None],
        # Enemy 4: Vexana
        ['Demon Shoes', 'Blood Wings', 'Exotic Veil', 'Mystery Codex', 'Expert Gloves', 'Expert Gloves'],
        # Enemy 5: Fanny
        ['Tough Boots', 'Blade of the Heptaseas', 'War Axe', 'Leather Jerkin', None, None],
    ]
}

with open('output/test (1)_extraction.json') as f:
    ext = json.load(f)

correct = 0
wrong = 0
empty_matches = 0
print('ITEM COMPARISON:')
print('='*80)

for side in ['allies', 'enemies']:
    for i, (gt_items, ext_data) in enumerate(zip(gt[side], ext[side])):
        ext_items = [item['item_name'] if item else None for item in ext_data['items']]
        side_name = f'{side[:-3].capitalize()} {i+1}'
        
        for slot in range(6):
            gt_item = gt_items[slot]
            ext_item = ext_items[slot]
            
            # Normalize None comparisons
            gt_is_empty = gt_item is None
            ext_is_empty = ext_item is None or ext_item == 'empty'
            
            if gt_is_empty and ext_is_empty:
                empty_matches += 1
            elif gt_item == ext_item:
                correct += 1
            else:
                wrong += 1
                print(f'{side_name} Slot {slot+1}: {ext_item} (expected: {gt_item})')

print()
print('='*80)
non_empty = 60 - empty_matches
print(f'Correct: {correct}/{non_empty} ({100*correct/non_empty:.1f}%)')
print(f'Wrong: {wrong}')
print(f'Empty slots: {empty_matches}')
