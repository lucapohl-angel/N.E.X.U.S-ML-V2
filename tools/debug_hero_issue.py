"""Debug script to investigate hero matching issues."""

import cv2
import yaml
from app.parser.hero_matcher import HeroMatcher
from app.parser.detector import detect_player_rows
from app.core.field_config import get_config

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
    hero_col = columns['hero_portrait']
    
    # Detect rows
    field_config = get_config()
    rows = detect_player_rows(img, field_config)
    
    # Initialize hero matcher
    hero_matcher = HeroMatcher()
    
    # Process first player (ally 1)
    y_start, y_end = rows[0]
    row_height = y_end - y_start
    
    x_start = int(w * hero_col['x_start_pct'])
    x_end = int(w * hero_col['x_end_pct'])
    y_offset = int(row_height * hero_col['y_offset_pct'])
    cell_height = int(row_height * hero_col['height_pct'])
    
    cell_y_start = y_start + y_offset
    cell_y_end = cell_y_start + cell_height
    
    print(f"\nAlly 1 hero cell coordinates:")
    print(f"  x: {x_start}-{x_end}")
    print(f"  y: {cell_y_start}-{cell_y_end}")
    
    # Crop hero portrait
    hero_cell = img[cell_y_start:cell_y_end, x_start:x_end]
    
    # Save crop for inspection
    cv2.imwrite("output/debug_ally1_hero.png", hero_cell)
    print(f"\nSaved hero crop to output/debug_ally1_hero.png")
    
    # Try to match
    print("\n=== Hero Matching Results ===")
    match = hero_matcher.match_hero(hero_cell, top_n=5)
    
    if match:
        print(f"\nBest match: {match.hero_name} (ID: {match.hero_id})")
        print(f"Confidence: {match.confidence:.3f}")
        print(f"\nMethod scores:")
        for method, score in sorted(match.method_scores.items(), key=lambda x: -x[1]):
            print(f"  {method}: {score:.3f}")
    
    # Check Yu Zhong's scores specifically
    print("\n=== Yu Zhong Scores ===")
    yu_zhong_key = "hero_095_yu_zhong"
    if yu_zhong_key in hero_matcher.hero_database:
        yu_zhong_template = hero_matcher.hero_database[yu_zhong_key]
        
        # Calculate all method scores for Yu Zhong
        scores = {}
        scores['template'] = hero_matcher._template_match_score(hero_cell, yu_zhong_template)
        scores['ssim'] = hero_matcher._ssim_score(hero_cell, yu_zhong_template)
        scores['edges'] = hero_matcher._edge_match_score(hero_cell, yu_zhong_template)
        scores['hu_moments'] = hero_matcher._hu_moments_score(hero_cell, yu_zhong_template)
        scores['color_moments'] = hero_matcher._color_moments_score(hero_cell, yu_zhong_template)
        scores['phash'] = hero_matcher._phash_score(hero_cell, yu_zhong_template)
        scores['contour'] = hero_matcher._contour_match_score(hero_cell, yu_zhong_template)
        
        print(f"\nYu Zhong method scores:")
        for method, score in sorted(scores.items(), key=lambda x: -x[1]):
            print(f"  {method}: {score:.3f}")
        
        # Also compare Lancelot
        lancelot_key = "hero_047_lancelot"
        if lancelot_key in hero_matcher.hero_database:
            lancelot_template = hero_matcher.hero_database[lancelot_key]
            lancelot_scores = {}
            lancelot_scores['template'] = hero_matcher._template_match_score(hero_cell, lancelot_template)
            lancelot_scores['ssim'] = hero_matcher._ssim_score(hero_cell, lancelot_template)
            lancelot_scores['edges'] = hero_matcher._edge_match_score(hero_cell, lancelot_template)
            lancelot_scores['hu_moments'] = hero_matcher._hu_moments_score(hero_cell, lancelot_template)
            lancelot_scores['color_moments'] = hero_matcher._color_moments_score(hero_cell, lancelot_template)
            lancelot_scores['phash'] = hero_matcher._phash_score(hero_cell, lancelot_template)
            lancelot_scores['contour'] = hero_matcher._contour_match_score(hero_cell, lancelot_template)
            
            print(f"\nLancelot method scores:")
            for method, score in sorted(lancelot_scores.items(), key=lambda x: -x[1]):
                print(f"  {method}: {score:.3f}")
    
    # Also try a manual match against Yu Zhong
    print("\n=== Manual comparison with Yu Zhong ===")
    yu_zhong_path = "heroes/portraits/hero_095_yu_zhong.png"
    yu_zhong_img = cv2.imread(yu_zhong_path)
    if yu_zhong_img is not None:
        print(f"Yu Zhong portrait size: {yu_zhong_img.shape}")
        print(f"Query cell size: {hero_cell.shape}")
        
        # Calculate similarity directly
        resized_yz = cv2.resize(yu_zhong_img, (hero_cell.shape[1], hero_cell.shape[0]))
        diff = cv2.absdiff(hero_cell, resized_yz)
        similarity = 1 - (np.mean(diff) / 255)
        print(f"Direct similarity to Yu Zhong: {similarity:.3f}")
        
        # Save comparison
        comparison = cv2.hconcat([hero_cell, cv2.resize(resized_yz, (hero_cell.shape[1], hero_cell.shape[0]))])
        cv2.imwrite("output/debug_hero_comparison.png", comparison)
        print("Saved comparison to output/debug_hero_comparison.png")

if __name__ == "__main__":
    import numpy as np
    main()
