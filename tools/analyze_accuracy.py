#!/usr/bin/env python3
"""
Analyze extraction accuracy against ground truth.
"""

import json

# Ground truth for allies (from test1_data.txt)
GROUND_TRUTH_ALLIES = [
    {
        "hero": "Yu Zhong",
        "items": ["Tough Boots", "War Axe", "Hunter Strike", "Ares Belt", "Hero's Ring", "EMPTY"]
    },
    {
        "hero": "Xavier",
        "items": ["Magic Shoes", "Enchanted Talisman", "Glowing Wand", "Lightning Truncheon", "Mystery Codex", "EMPTY"]
    },
    {
        "hero": "Layla",
        "items": ["Warrior Boots", "Windtalker", "Haas' Claws", "Berserker's Fury", "Malefic Gun", "EMPTY"]
    },
    {
        "hero": "Badang",
        "items": ["Rapid Boots", "Thunder Belt", "Dominance Ice", "Oracle", "Ares Belt", "Vitality Crystal"]
    },
    {
        "hero": "Sun",
        "items": ["Rapid Boots", "Windtalker", "Corrosion Scythe", "Great Dragon Spear", "Legion Sword", "EMPTY"]
    }
]

# Ground truth for enemies (from test1_data.txt)
GROUND_TRUTH_ENEMIES = [
    {
        "hero": "X.Borg",
        "items": ["Tough Boots", "Sky Piercer", "War Axe", "Ares Belt", "Vitality Crystal", "Leather Jerkin"]
    },
    {
        "hero": "Hanabi",
        "items": ["Swift Boots", "Corrosion Scythe", "Demon Hunter Sword", "Regular Spear", "Dagger", "Dagger"]
    },
    {
        "hero": "Estes",
        "items": ["Demon Shoes", "Flask of the Oasis", "Enchanted Talisman", "EMPTY", "EMPTY", "EMPTY"]
    },
    {
        "hero": "Vexana",
        "items": ["Demon Shoes", "Blood Wings", "Exotic Veil", "Mystery Codex", "Expert Gloves", "Expert Gloves"]
    },
    {
        "hero": "Fanny",
        "items": ["Magic Shoes", "Blade of the Heptaseas", "War Axe", "Leather Jerkin", "EMPTY", "EMPTY"]
    }
]

def load_extraction(path: str) -> dict:
    with open(path, 'r') as f:
        return json.load(f)

def analyze_team(team_name: str, players: list, ground_truth: list):
    """Analyze accuracy for one team."""
    print(f"\n{'=' * 70}")
    print(f"{team_name.upper()} TEAM ANALYSIS")
    print("=" * 70)
    
    hero_correct = 0
    item_correct = 0
    item_total = 0
    
    for i, (player, gt) in enumerate(zip(players, ground_truth)):
        print(f"\n--- {team_name.title()} {i+1} ---")
        
        # Hero comparison
        detected_hero = player.get("hero", {}).get("hero_name") or "NONE"
        expected_hero = gt["hero"]
        hero_match = detected_hero.lower() == expected_hero.lower()
        if hero_match:
            hero_correct += 1
            print(f"✓ Hero: {detected_hero}")
        else:
            print(f"✗ Hero: {detected_hero} (expected: {expected_hero})")
        
        # Item comparison
        print("  Items:")
        for slot in range(6):
            item_info = player.get("items", [{}] * 6)[slot] if slot < len(player.get("items", [])) else {}
            if item_info.get("is_empty"):
                detected_item = "EMPTY"
            else:
                detected_item = item_info.get("item_name") or "EMPTY"
            
            expected_item = gt["items"][slot]
            confidence = item_info.get("confidence", 0)
            
            item_total += 1
            
            # Normalize for comparison
            detected_norm = detected_item.lower().replace("'", "'").replace("'", "'")
            expected_norm = expected_item.lower().replace("'", "'").replace("'", "'")
            
            # Check match
            is_match = detected_norm == expected_norm
            if is_match:
                item_correct += 1
                print(f"    ✓ Slot {slot+1}: {detected_item} ({confidence:.1%})")
            else:
                print(f"    ✗ Slot {slot+1}: {detected_item} ({confidence:.1%}) → expected: {expected_item}")
    
    return hero_correct, item_correct, item_total, len(ground_truth)

def analyze_accuracy(extraction: dict):
    print("=" * 70)
    print("ACCURACY ANALYSIS - FULL MATCH (Allies + Enemies)")
    print("=" * 70)
    
    # Check if new format (allies/enemies) or old format (players)
    if "allies" in extraction:
        allies = extraction["allies"]
        enemies = extraction.get("enemies", [])
    else:
        allies = extraction.get("players", [])
        enemies = []
    
    # Analyze allies
    ally_hero, ally_item, ally_item_total, ally_count = analyze_team("ally", allies, GROUND_TRUTH_ALLIES)
    
    # Analyze enemies if present
    if enemies:
        enemy_hero, enemy_item, enemy_item_total, enemy_count = analyze_team("enemy", enemies, GROUND_TRUTH_ENEMIES)
    else:
        enemy_hero, enemy_item, enemy_item_total, enemy_count = 0, 0, 0, 0
        print("\n(No enemy data in extraction)")
    
    # Combined summary
    total_heroes = ally_count + enemy_count
    total_hero_correct = ally_hero + enemy_hero
    total_items = ally_item_total + enemy_item_total
    total_item_correct = ally_item + enemy_item
    
    print("\n" + "=" * 70)
    print("COMBINED SUMMARY")
    print("=" * 70)
    print(f"Heroes:  {total_hero_correct}/{total_heroes} ({total_hero_correct/total_heroes*100:.1f}%)")
    print(f"  - Allies:  {ally_hero}/{ally_count}")
    print(f"  - Enemies: {enemy_hero}/{enemy_count}")
    print()
    print(f"Items:   {total_item_correct}/{total_items} ({total_item_correct/total_items*100:.1f}%)")
    print(f"  - Allies:  {ally_item}/{ally_item_total}")
    print(f"  - Enemies: {enemy_item}/{enemy_item_total}")

if __name__ == "__main__":
    extraction = load_extraction("output/test (1)_extraction.json")
    analyze_accuracy(extraction)
