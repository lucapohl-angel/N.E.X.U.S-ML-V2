import json

with open('output/test (1)_extraction.json') as f:
    data = json.load(f)

# Search for specific items
targets = ['vitality', 'legion', 'magic shoes']

print("Searching for target items in extraction results:")
for side, side_data in [('ally', data['allies']), ('enemy', data['enemies'])]:
    for i, player in enumerate(side_data):
        for j, item in enumerate(player['items']):
            if item is None:
                continue
            name = item.get('item_name', '')
            if name is None:
                continue
            name_lower = name.lower()
            for target in targets:
                if target in name_lower:
                    print(f'  {side} {i+1} slot {j+1}: {name} ({item["confidence"]:.1%})')
