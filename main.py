"""Squad STATS - Main Extraction Script

Central script that orchestrates all extraction components:
- Image preprocessing and row detection
- Hero portrait matching (screen1 only)
- Item icon matching (screen1 only)
- OCR text extraction (all screens)
- JSON output generation

Usage:
    python main.py <screenshot_path> [screentype]
    python main.py "tests/fixtures/test (1).jpeg"           # defaults to screen1
    python main.py "tests/fixtures/Screen2.jpeg" screen2    # damage stats screen
"""

import sys
import cv2
import json
import pytesseract
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Import core components
from app.parser.detector import detect_player_rows
from app.parser.ocr import extract_field
from app.core.field_config import get_config


# Mapping of screen types to their column mapping files
SCREEN_MAPPING_FILES = {
    "screen1": "screen1_column_mapping.yaml",
    "screen2": "screen2_column_mapping.yaml",
    "screen3": "screen3_column_mapping.yaml",
    "screen4": "screen4_column_mapping.yaml",
    "screen5": "screen5_column_mapping.yaml",
}

# Screens that require hero/item matching (only screen1)
SCREENS_WITH_HERO_ITEMS = {"screen1"}


class SquadStatsExtractor:
    """Main extraction orchestrator."""
    
    def __init__(self, screentype: str = "screen1"):
        """Initialize all extraction components.
        
        Args:
            screentype: Type of screen to process (screen1, screen2, etc.)
        """
        print("🔧 Initializing Squad STATS Extractor...")
        
        self.screentype = screentype
        
        # Determine mapping file (just the filename - get_config adds the config/ directory)
        if screentype in SCREEN_MAPPING_FILES:
            self.mapping_file = SCREEN_MAPPING_FILES[screentype]
        else:
            # Allow custom mapping file path
            self.mapping_file = f"{screentype}_column_mapping.yaml"
        
        print(f"  ✓ Screen type: {screentype}")
        print(f"  ✓ Mapping file: {self.mapping_file}")
        
        # Load configuration
        self.field_config = get_config(mapping_file=self.mapping_file)
        
        # Initialize matchers only for screens that need them
        self.hero_matcher = None
        self.item_matcher = None
        
        if screentype in SCREENS_WITH_HERO_ITEMS:
            from app.parser.hero_matcher import HeroMatcher
            from app.parser.item_matcher import ItemMatcher
            
            self.hero_matcher = HeroMatcher()
            self.item_matcher = ItemMatcher()
            
            print(f"  ✓ Loaded {len(self.hero_matcher.hero_database)} heroes")
            print(f"  ✓ Loaded {len(self.item_matcher.item_database)} items")
        else:
            print("  ✓ OCR-only mode (no hero/item matching)")
        
        print("✓ Initialization complete\n")
    
    def extract_player_data(
        self, 
        img: Any, 
        row: tuple, 
        row_index: int,
        column_mappings: Dict
    ) -> Dict[str, Any]:
        """
        Extract all data for a single player row.
        
        Args:
            img: Normalized screenshot image
            row: (y_start, y_end) tuple for player row
            row_index: Player number (0-4)
            column_mappings: Column coordinate mappings
            
        Returns:
            Dictionary with player data including hero, items, and stats
        """
        y_start, y_end = row
        height, width = img.shape[:2]
        row_height = y_end - y_start
        
        player_data = {
            "player_number": row_index + 1,
            "row_coordinates": {"y_start": int(y_start), "y_end": int(y_end)}
        }
        
        # 1. Extract Hero Portrait (only for screens with hero matching)
        if self.hero_matcher and "hero_portrait" in column_mappings:
            hero_data = self._extract_hero(img, y_start, row_height, width, column_mappings["hero_portrait"])
            player_data["hero"] = hero_data
        
        # 2. Extract Items (6 slots) (only for screens with item matching)
        if self.item_matcher:
            items_data = self._extract_items(img, y_start, row_height, width, column_mappings)
            player_data["items"] = items_data
        
        # 3. Extract OCR Fields (all screens - dynamically based on mapping)
        ocr_fields = self._extract_ocr_fields(img, y_start, row_height, width, column_mappings)
        player_data.update(ocr_fields)
        
        return player_data
    
    def _extract_hero(
        self, 
        img: Any, 
        y_start: int, 
        row_height: int, 
        width: int,
        hero_col_def: Dict
    ) -> Optional[Dict[str, Any]]:
        """Extract and match hero portrait."""
        # Skip hero matching if matcher not available (OCR-only mode)
        if self.hero_matcher is None:
            return None
            
        try:
            # Calculate cell coordinates
            x_start = int(width * hero_col_def['x_start_pct'])
            x_end = int(width * hero_col_def['x_end_pct'])
            y_offset = int(row_height * hero_col_def['y_offset_pct'])
            cell_height = int(row_height * hero_col_def['height_pct'])
            
            cell_y_start = y_start + y_offset
            cell_y_end = cell_y_start + cell_height
            
            # Crop hero portrait
            hero_cell = img[cell_y_start:cell_y_end, x_start:x_end]
            
            # Match hero
            match = self.hero_matcher.match_hero(hero_cell)
            
            if match and match.confidence > 0.3:
                return {
                    "hero_id": match.hero_id,
                    "hero_name": match.hero_name,
                    "confidence": round(match.confidence, 3),
                    "top_methods": {
                        k: round(v, 3) 
                        for k, v in sorted(
                            match.method_scores.items(), 
                            key=lambda x: x[1], 
                            reverse=True
                        )[:3]
                    }
                }
            else:
                return {
                    "hero_id": None,
                    "hero_name": None,
                    "confidence": 0.0,
                    "error": "No match found or confidence too low"
                }
                
        except Exception as e:
            return {
                "hero_id": None,
                "hero_name": None,
                "error": str(e)
            }
    
    def _extract_items(
        self, 
        img: Any, 
        y_start: int, 
        row_height: int, 
        width: int,
        column_mappings: Dict
    ) -> List[Dict[str, Any]]:
        """Extract and match all 6 item slots."""
        items = []
        
        # Skip item matching if matcher not available (OCR-only mode)
        if self.item_matcher is None:
            return items
        
        for slot_idx in range(1, 7):
            slot_key = f"item{slot_idx}"  # Changed from item_slot_{slot_idx}
            
            if slot_key not in column_mappings:
                items.append({
                    "slot": slot_idx,
                    "item_name": None,
                    "error": "Column mapping not found"
                })
                continue
            
            try:
                col_def = column_mappings[slot_key]
                
                # Calculate cell coordinates
                x_start = int(width * col_def['x_start_pct'])
                x_end = int(width * col_def['x_end_pct'])
                y_offset = int(row_height * col_def['y_offset_pct'])
                cell_height = int(row_height * col_def['height_pct'])
                
                cell_y_start = y_start + y_offset
                cell_y_end = cell_y_start + cell_height
                
                # Crop item slot
                item_cell = img[cell_y_start:cell_y_end, x_start:x_end]
                
                # Match item (returns list of ItemMatchResult)
                matches = self.item_matcher.match_item(item_cell, top_n=1)
                
                if matches and len(matches) > 0:
                    best_match = matches[0]
                    
                    # Check if it's an empty slot
                    if best_match.item_name == "EMPTY":
                        items.append({
                            "slot": slot_idx,
                            "item_name": None,
                            "confidence": 0.0,
                            "is_empty": True
                        })
                    else:
                        items.append({
                            "slot": slot_idx,
                            "item_name": best_match.item_name,
                            "confidence": round(best_match.confidence, 3),
                            "top_method": max(
                                best_match.method_scores.items(), 
                                key=lambda x: x[1]
                            )[0] if best_match.method_scores else None
                        })
                else:
                    items.append({
                        "slot": slot_idx,
                        "item_name": None,
                        "confidence": 0.0,
                        "is_empty": True
                    })
                
            except Exception as e:
                items.append({
                    "slot": slot_idx,
                    "item_name": None,
                    "error": str(e)
                })
        
        return items
    
    def _extract_ocr_fields(
        self, 
        img: Any, 
        y_start: int, 
        row_height: int, 
        width: int,
        column_mappings: Dict
    ) -> Dict[str, Any]:
        """Extract OCR text fields dynamically based on column mappings.
        
        For screen1: player_name, hero_level, kills, deaths, assists, total_gold, individual_rating
        For screen2: hero_damage, turret_damage, damage_taken, teamfight_participation
        """
        ocr_data = {}
        
        # Fields to skip (handled separately or not OCR fields)
        skip_fields = {
            "hero_portrait", "enemy_hero_portrait",
            "item1", "item2", "item3", "item4", "item5", "item6",
            "enemy_item1", "enemy_item2", "enemy_item3", "enemy_item4", "enemy_item5", "enemy_item6"
        }
        
        # Enemy fields (processed separately in extract_enemy_data)
        enemy_prefixes = {"enemy_"}
        
        # Screen2 damage fields that need specialized OCR
        screen2_damage_fields = {
            "hero_damage", "turret_damage", "damage_taken", "teamfight_participation"
        }
        
        # Screen3 fields that need specialized OCR
        screen3_hero_damage_fields = {"hero_damage"}
        screen3_consecutive_kills_fields = {"consecutive_kills"}
        
        # Screen1 fields with dedicated OCR functions
        screen1_kda_fields = {"kills", "deaths", "assists"}
        
        # Dynamic OCR extraction - iterate through all columns in the mapping
        for field_name, col_def in column_mappings.items():
            # Skip non-OCR fields
            if field_name in skip_fields:
                continue
            
            # Skip enemy fields (handled separately)
            if any(field_name.startswith(prefix) for prefix in enemy_prefixes):
                continue
            
            # Skip metadata fields that aren't per-row (like battle_id)
            if field_name in {"battle_id"}:
                continue
            
            try:
                # Calculate cell coordinates
                x_start = int(width * col_def['x_start_pct'])
                x_end = int(width * col_def['x_end_pct'])
                y_offset = int(row_height * col_def['y_offset_pct'])
                cell_height = int(row_height * col_def['height_pct'])
                
                cell_y_start = y_start + y_offset
                cell_y_end = cell_y_start + cell_height
                
                # Crop cell
                cell = img[cell_y_start:cell_y_end, x_start:x_end]
                
                # Use specialized OCR based on screen type and field
                if self.screentype == "screen2" and field_name in screen2_damage_fields:
                    # Screen2 damage stats (95% accuracy - DO NOT MODIFY)
                    result = self._ocr_damage_stat(cell, field_name)
                elif self.screentype == "screen3":
                    # Screen3 specialized OCR functions
                    if field_name in screen3_hero_damage_fields:
                        result = self._ocr_screen3_hero_damage(cell)
                    elif field_name in screen3_consecutive_kills_fields:
                        result = self._ocr_screen3_consecutive_kills(cell)
                    else:
                        # Use standard OCR for other screen3 fields
                        field_type = self._get_field_type(field_name)
                        result = extract_field(cell, field_type, field_name)
                elif self.screentype == "screen1":
                    # Screen1 specialized OCR functions
                    if field_name == "individual_rating":
                        result = self._ocr_screen1_individual_rating(cell)
                    elif field_name == "hero_level":
                        result = self._ocr_screen1_hero_level(cell)
                    elif field_name in screen1_kda_fields:
                        result = self._ocr_screen1_kda(cell, field_name)
                    else:
                        # Use standard OCR for other fields (player_name, total_gold)
                        field_type = self._get_field_type(field_name)
                        result = extract_field(cell, field_type, field_name)
                elif self.screentype == "screen4":
                    # Screen4 specialized OCR functions
                    if field_name == "crowd_control":
                        result = self._ocr_screen4_crowd_control(cell)
                    elif field_name == "healing_and_shields":
                        result = self._ocr_screen4_healing_and_shields(cell)
                    elif field_name == "damage_taken":
                        result = self._ocr_screen4_damage_taken(cell)
                    else:
                        # Use standard OCR for other screen4 fields
                        field_type = self._get_field_type(field_name)
                        result = extract_field(cell, field_type, field_name)
                elif self.screentype == "screen5":
                    # Screen5 specialized OCR functions for gold breakdown
                    if field_name == "total_gold":
                        result = self._ocr_screen5_total_gold(cell)
                    elif field_name == "jungle_gold":
                        result = self._ocr_screen5_jungle_gold(cell)
                    elif field_name == "kill_gold":
                        result = self._ocr_screen5_kill_gold(cell)
                    elif field_name == "minion_gold":
                        result = self._ocr_screen5_minion_gold(cell)
                    else:
                        # Use standard OCR for other screen5 fields
                        field_type = self._get_field_type(field_name)
                        result = extract_field(cell, field_type, field_name)
                else:
                    # Default: use standard OCR from app/parser/ocr.py
                    field_type = self._get_field_type(field_name)
                    result = extract_field(cell, field_type, field_name)
                
                # Parse value
                parsed_value = result if result is not None else None
                
                ocr_data[field_name] = {
                    "value": parsed_value,
                    "confidence": 0.0  # OCR confidence not returned by extract_field
                }
                
            except Exception as e:
                ocr_data[field_name] = {
                    "value": None,
                    "error": str(e)
                }
        
        return ocr_data
    
    def _ocr_damage_stat(self, cell: Any, field_name: str) -> Optional[int]:
        """Specialized OCR for screen2 damage stats with multi-pass voting.
        
        - Damage numbers (hero_damage, turret_damage, damage_taken) are LEFT-aligned
        - Teamfight participation is RIGHT-aligned
        All numbers are contiguous with no spaces.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Use center 60% of cell to avoid edge artifacts from adjacent columns
        center_margin = int(w * 0.2)
        cropped = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
        
        # Convert to grayscale
        if len(cropped.shape) == 3:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped.copy()
        
        results = []
        
        # Pass 1: Standard CLAHE + Otsu at 3x scale
        scale = 3
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1:
            results.append(text1)
        
        # Pass 2: Higher scale (4x) with LANCZOS for finer details
        scale2 = 4
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        clahe2 = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(scaled2)
        _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
            
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2:
            results.append(text2)
        
        # Pass 3: Bilateral filter + higher threshold
        filtered = cv2.bilateralFilter(scaled, 5, 50, 50)
        _, binary3 = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary3) < 127:
            binary3 = cv2.bitwise_not(binary3)
        
        text3 = pytesseract.image_to_string(binary3, config=config).strip()
        text3 = ''.join(c for c in text3 if c.isdigit())
        if text3:
            results.append(text3)
        
        if not results:
            return None
        
        # For participation, prefer 2-digit results as max is 99
        if "participation" in field_name:
            two_digit = [r for r in results if len(r) == 2]
            if two_digit:
                counter = Counter(two_digit)
                text = counter.most_common(1)[0][0]
            else:
                # No 2-digit result, take the first 2 digits of most common
                counter = Counter(results)
                text = counter.most_common(1)[0][0][:2]
        else:
            # For damage stats, majority voting with preference to most common
            counter = Counter(results)
            text = counter.most_common(1)[0][0]
        
        if text:
            try:
                value = int(text)
                
                # Teamfight participation: max 2 digits (0-99)
                if "participation" in field_name:
                    value = max(0, min(99, value))
                
                return value
            except ValueError:
                return None
        
        return None
    
    def _extract_battle_id(self, img: Any, col_def: Dict) -> Optional[str]:
        """Extract battle ID from metadata region - must be 100% accurate."""
        import numpy as np
        
        try:
            height, width = img.shape[:2]
            
            # Calculate absolute coordinates
            x_start = int(width * col_def['x_start_pct'])
            x_end = int(width * col_def['x_end_pct'])
            y_start = int(height * col_def['y_offset_pct'])
            cell_height = int(height * col_def['height_pct'])
            y_end = y_start + cell_height
            
            # Crop cell
            cell = img[y_start:y_end, x_start:x_end]
            
            # Convert to grayscale
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
            
            # Scale up significantly for small text
            scale = 4
            scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            
            # Apply CLAHE
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(scaled)
            
            # Binarize
            _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Invert if needed
            if np.mean(binary) < 127:
                binary = cv2.bitwise_not(binary)
            
            # OCR with strict digit whitelist
            config = '--psm 7 -c tessedit_char_whitelist=0123456789'
            text = pytesseract.image_to_string(binary, config=config).strip()
            
            # Clean - only digits
            text = ''.join(c for c in text if c.isdigit())
            
            return text if text else None
            
        except Exception as e:
            print(f"  ⚠️ Failed to extract battle_id: {e}")
            return None
    
    def _ocr_screen1_battle_id(self, img: Any, col_def: Dict) -> Optional[str]:
        """Extract battle ID for screen1 - MUST be exactly 18 digits.
        
        Battle ID is critical - if wrong, match data is useless.
        Uses multiple passes and validates exactly 18 digits.
        """
        import numpy as np
        from collections import Counter
        
        try:
            height, width = img.shape[:2]
            
            # Calculate absolute coordinates
            x_start = int(width * col_def['x_start_pct'])
            x_end = int(width * col_def['x_end_pct'])
            y_start = int(height * col_def['y_offset_pct'])
            cell_height = int(height * col_def['height_pct'])
            y_end = y_start + cell_height
            
            # Crop cell
            cell = img[y_start:y_end, x_start:x_end]
            
            # Convert to grayscale
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
            
            results = []
            
            # Pass 1: High scale (5x) with CLAHE
            scale = 5
            scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            enhanced = clahe.apply(scaled)
            _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if np.mean(binary) < 127:
                binary = cv2.bitwise_not(binary)
            
            config = '--psm 7 -c tessedit_char_whitelist=0123456789'
            text1 = pytesseract.image_to_string(binary, config=config).strip()
            text1 = ''.join(c for c in text1 if c.isdigit())
            if len(text1) == 18:
                results.append(text1)
            
            # Pass 2: Very high scale (6x) with bilateral filter
            scale2 = 6
            scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
            filtered = cv2.bilateralFilter(scaled2, 9, 75, 75)
            clahe2 = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced2 = clahe2.apply(filtered)
            _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            if np.mean(binary2) < 127:
                binary2 = cv2.bitwise_not(binary2)
            
            text2 = pytesseract.image_to_string(binary2, config=config).strip()
            text2 = ''.join(c for c in text2 if c.isdigit())
            if len(text2) == 18:
                results.append(text2)
            
            # Pass 3: Adaptive threshold
            scaled3 = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
            binary3 = cv2.adaptiveThreshold(scaled3, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, 11, 2)
            if np.mean(binary3) > 127:
                binary3 = cv2.bitwise_not(binary3)
            
            text3 = pytesseract.image_to_string(binary3, config=config).strip()
            text3 = ''.join(c for c in text3 if c.isdigit())
            if len(text3) == 18:
                results.append(text3)
            
            # Return most common 18-digit result
            if results:
                counter = Counter(results)
                return counter.most_common(1)[0][0]
            
            # Fallback: return any result that looks like battle ID (15-20 digits)
            all_texts = [text1, text2, text3]
            for text in all_texts:
                if 15 <= len(text) <= 20:
                    return text[:18] if len(text) > 18 else text
            
            return None
            
        except Exception as e:
            print(f"  ⚠️ Failed to extract screen1 battle_id: {e}")
            return None
    
    # ==========================================
    # SCREEN3 SPECIALIZED OCR FUNCTIONS
    # ==========================================
    
    def _ocr_screen3_hero_damage(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen3 hero damage (4-6 digit integers like 20656, 63726).
        
        Screen3 hero damage numbers are LEFT-aligned with thin white/gray text.
        Uses multi-pass voting with aggressive preprocessing for accuracy.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Convert to grayscale
        if len(cell.shape) == 3:
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
        else:
            gray = cell.copy()
        
        results = []
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        
        # Pass 1: Standard preprocessing at 4x scale
        scale = 4
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1 and 3 <= len(text1) <= 6:
            results.append(text1)
        
        # Pass 2: Higher scale (5x) with LANCZOS for fine details
        scale2 = 5
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(scaled2)
        _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2 and 3 <= len(text2) <= 6:
            results.append(text2)
        
        # Pass 3: Bilateral filter to reduce noise while preserving edges
        scaled3 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        filtered = cv2.bilateralFilter(scaled3, 9, 75, 75)
        _, binary3 = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary3) < 127:
            binary3 = cv2.bitwise_not(binary3)
        
        text3 = pytesseract.image_to_string(binary3, config=config).strip()
        text3 = ''.join(c for c in text3 if c.isdigit())
        if text3 and 3 <= len(text3) <= 6:
            results.append(text3)
        
        # Pass 4: HSV white mask (numbers are white text on dark background)
        if len(cell.shape) == 3:
            hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            # Target white/light gray text
            mask = cv2.inRange(hsv, np.array([0, 0, 120]), np.array([180, 80, 255]))
            masked_gray = cv2.bitwise_and(gray, gray, mask=mask)
            scaled4 = cv2.resize(masked_gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
            # Invert to make text dark on light
            inverted = cv2.bitwise_not(scaled4)
            _, binary4 = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            text4 = pytesseract.image_to_string(binary4, config=config).strip()
            text4 = ''.join(c for c in text4 if c.isdigit())
            if text4 and 3 <= len(text4) <= 6:
                results.append(text4)
        
        # Pass 5: Adaptive threshold for varying lighting
        scaled5 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        binary5 = cv2.adaptiveThreshold(scaled5, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        if np.mean(binary5) > 127:
            binary5 = cv2.bitwise_not(binary5)
        
        text5 = pytesseract.image_to_string(binary5, config=config).strip()
        text5 = ''.join(c for c in text5 if c.isdigit())
        if text5 and 3 <= len(text5) <= 6:
            results.append(text5)
        
        if not results:
            return None
        
        # Majority voting - prefer 5-digit results (most common for hero damage)
        five_digit = [r for r in results if len(r) == 5]
        if five_digit:
            counter = Counter(five_digit)
            best = counter.most_common(1)[0][0]
        else:
            # Fall back to most common result of any length
            counter = Counter(results)
            best = counter.most_common(1)[0][0]
        
        try:
            return int(best)
        except ValueError:
            return None
    
    def _ocr_screen3_consecutive_kills(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen3 consecutive kills (single digit 0-9).
        
        Consecutive kills are small single-digit numbers (0-9).
        Need very aggressive preprocessing for small numbers.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Convert to grayscale
        if len(cell.shape) == 3:
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
        else:
            gray = cell.copy()
        
        results = []
        config = '--psm 10 -c tessedit_char_whitelist=0123456789'  # PSM 10 = single character
        config_psm7 = '--psm 7 -c tessedit_char_whitelist=0123456789'  # PSM 7 = single line
        
        # Pass 1: High scale (6x) for small digits
        scale = 6
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        # Try both single char and single line mode
        for cfg in [config, config_psm7]:
            text = pytesseract.image_to_string(binary1, config=cfg).strip()
            text = ''.join(c for c in text if c.isdigit())
            if text and len(text) <= 2:
                results.append(text[:1])  # Take only first digit
        
        # Pass 2: Very high scale (8x) with sharpening
        scale2 = 8
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(scaled2, -1, kernel)
        clahe2 = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(sharpened)
        _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        for cfg in [config, config_psm7]:
            text = pytesseract.image_to_string(binary2, config=cfg).strip()
            text = ''.join(c for c in text if c.isdigit())
            if text and len(text) <= 2:
                results.append(text[:1])
        
        # Pass 3: Bilateral filter
        scaled3 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        filtered = cv2.bilateralFilter(scaled3, 5, 50, 50)
        _, binary3 = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary3) < 127:
            binary3 = cv2.bitwise_not(binary3)
        
        for cfg in [config, config_psm7]:
            text = pytesseract.image_to_string(binary3, config=cfg).strip()
            text = ''.join(c for c in text if c.isdigit())
            if text and len(text) <= 2:
                results.append(text[:1])
        
        # Pass 4: HSV white mask for white numbers
        if len(cell.shape) == 3:
            hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 140]), np.array([180, 60, 255]))
            masked_gray = cv2.bitwise_and(gray, gray, mask=mask)
            scaled4 = cv2.resize(masked_gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
            inverted = cv2.bitwise_not(scaled4)
            _, binary4 = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            for cfg in [config, config_psm7]:
                text = pytesseract.image_to_string(binary4, config=cfg).strip()
                text = ''.join(c for c in text if c.isdigit())
                if text and len(text) <= 2:
                    results.append(text[:1])
        
        if not results:
            return None
        
        # Majority voting
        counter = Counter(results)
        best = counter.most_common(1)[0][0]
        
        try:
            value = int(best)
            # Consecutive kills are typically 0-9
            if 0 <= value <= 9:
                return value
            return value  # Return anyway, might be valid
        except ValueError:
            return None
    
    # ==========================================
    # SCREEN4 SPECIALIZED OCR FUNCTIONS
    # ==========================================
    
    def _ocr_screen4_crowd_control(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen4 crowd control stat (0-99999).
        
        Crowd control values are integers, can be 0 or 4-5 digit numbers.
        Uses multi-pass voting with focused center cropping to avoid overlap.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Use center 50% of cell to avoid edge artifacts from adjacent columns
        center_margin = int(w * 0.25)
        cropped = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
        
        # Convert to grayscale
        if len(cropped.shape) == 3:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped.copy()
        
        results = []
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        
        # Pass 1: Standard preprocessing at 3x scale
        scale = 3
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1 and len(text1) <= 6:
            results.append(text1)
        
        # Pass 2: Higher contrast with adaptive threshold
        scale2 = 4
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        binary2 = cv2.adaptiveThreshold(scaled2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2 and len(text2) <= 6:
            results.append(text2)
        
        # Pass 3: Bilateral filter to reduce noise
        filtered = cv2.bilateralFilter(gray, 5, 50, 50)
        scaled3 = cv2.resize(filtered, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, binary3 = cv2.threshold(scaled3, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary3) < 127:
            binary3 = cv2.bitwise_not(binary3)
        
        text3 = pytesseract.image_to_string(binary3, config=config).strip()
        text3 = ''.join(c for c in text3 if c.isdigit())
        if text3 and len(text3) <= 6:
            results.append(text3)
        
        # Pass 4: White text mask for bright numbers
        if len(cell.shape) == 3:
            cropped_color = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
            hsv = cv2.cvtColor(cropped_color, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 150]), np.array([180, 50, 255]))
            masked = cv2.bitwise_and(gray, gray, mask=mask)
            scaled4 = cv2.resize(masked, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
            inverted = cv2.bitwise_not(scaled4)
            _, binary4 = cv2.threshold(inverted, 100, 255, cv2.THRESH_BINARY)
            
            text4 = pytesseract.image_to_string(binary4, config=config).strip()
            text4 = ''.join(c for c in text4 if c.isdigit())
            if text4 and len(text4) <= 6:
                results.append(text4)
        
        if not results:
            return 0  # Default to 0 if no valid text
        
        # Majority voting
        counter = Counter(results)
        best = counter.most_common(1)[0][0]
        
        try:
            value = int(best)
            if 0 <= value <= 99999:
                return value
            return value
        except ValueError:
            return 0
    
    def _ocr_screen4_healing_and_shields(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen4 healing and shields stat.
        
        Values can be 0 or 4-5 digit numbers. Many values are 0.
        Uses tight center cropping to avoid picking up adjacent column data.
        Special handling for zero detection - if single digit "1" detected with low
        white content, it's likely noise and should be 0.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Use center 40% of cell - very tight crop to avoid adjacent columns
        center_margin = int(w * 0.30)
        cropped = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
        
        # Convert to grayscale
        if len(cropped.shape) == 3:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped.copy()
        
        # FIRST: Check white pixel content to determine if this is likely a zero
        # This is the primary zero detection mechanism
        is_likely_zero = False
        if len(cell.shape) == 3:
            cropped_color = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
            hsv = cv2.cvtColor(cropped_color, cv2.COLOR_BGR2HSV)
            # Strict white mask: high value, low saturation
            mask = cv2.inRange(hsv, np.array([0, 0, 170]), np.array([180, 50, 255]))
            white_pixels = cv2.countNonZero(mask)
            total_pixels = mask.shape[0] * mask.shape[1]
            white_ratio = white_pixels / total_pixels if total_pixels > 0 else 0
            
            # If very few white pixels (< 2%), this is almost certainly 0
            if white_ratio < 0.02:
                is_likely_zero = True
        
        # If we're confident it's zero, return early
        if is_likely_zero:
            return 0
        
        results = []
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        
        # Pass 1: Standard preprocessing
        scale = 3
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1 and len(text1) <= 6:
            results.append(text1)
        
        # Pass 2: Higher threshold to filter out noise
        scale2 = 4
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        _, binary2 = cv2.threshold(scaled2, 180, 255, cv2.THRESH_BINARY)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2 and len(text2) <= 6:
            results.append(text2)
        
        # Pass 3: Very strict white mask - only pick up bright white text
        if len(cell.shape) == 3:
            cropped_color = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
            hsv = cv2.cvtColor(cropped_color, cv2.COLOR_BGR2HSV)
            # Very strict white: high value, low saturation
            mask = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([180, 40, 255]))
            masked = cv2.bitwise_and(gray, gray, mask=mask)
            
            # Check if mask has any significant content
            white_pixels = cv2.countNonZero(mask)
            total_pixels = mask.shape[0] * mask.shape[1]
            white_ratio = white_pixels / total_pixels if total_pixels > 0 else 0
            
            if white_ratio < 0.02:
                # Almost no white content - likely 0
                results.append("0")
            else:
                scaled3 = cv2.resize(masked, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
                inverted = cv2.bitwise_not(scaled3)
                _, binary3 = cv2.threshold(inverted, 100, 255, cv2.THRESH_BINARY)
                
                text3 = pytesseract.image_to_string(binary3, config=config).strip()
                text3 = ''.join(c for c in text3 if c.isdigit())
                if text3 and len(text3) <= 6:
                    results.append(text3)
        
        if not results:
            return 0  # Default to 0 if no valid text
        
        # Majority voting
        counter = Counter(results)
        best = counter.most_common(1)[0][0]
        
        try:
            value = int(best)
            # Post-processing: If single digit 1 is detected, it's likely noise - return 0
            # Real healing/shields values are typically 0 or 4+ digits
            if value == 1:
                return 0
            if 0 <= value <= 99999:
                return value
            return value
        except ValueError:
            return 0
    
    def _ocr_screen4_damage_taken(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen4 damage taken stat (4-6 digit integers).
        
        Damage taken values are always positive integers, typically 5000-80000.
        Uses multi-pass voting with moderate center cropping.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Use center 50% of cell
        center_margin = int(w * 0.25)
        cropped = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
        
        # Convert to grayscale
        if len(cropped.shape) == 3:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped.copy()
        
        results = []
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        
        # Pass 1: Standard preprocessing
        scale = 3
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1 and 4 <= len(text1) <= 6:
            results.append(text1)
        
        # Pass 2: Higher scale with LANCZOS
        scale2 = 4
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(scaled2)
        _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2 and 4 <= len(text2) <= 6:
            results.append(text2)
        
        # Pass 3: Adaptive threshold
        binary3 = cv2.adaptiveThreshold(scaled2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        if np.mean(binary3) < 127:
            binary3 = cv2.bitwise_not(binary3)
        
        text3 = pytesseract.image_to_string(binary3, config=config).strip()
        text3 = ''.join(c for c in text3 if c.isdigit())
        if text3 and 4 <= len(text3) <= 6:
            results.append(text3)
        
        # Pass 4: White text mask
        if len(cell.shape) == 3:
            cropped_color = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
            hsv = cv2.cvtColor(cropped_color, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 150]), np.array([180, 50, 255]))
            masked = cv2.bitwise_and(gray, gray, mask=mask)
            scaled4 = cv2.resize(masked, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
            inverted = cv2.bitwise_not(scaled4)
            _, binary4 = cv2.threshold(inverted, 100, 255, cv2.THRESH_BINARY)
            
            text4 = pytesseract.image_to_string(binary4, config=config).strip()
            text4 = ''.join(c for c in text4 if c.isdigit())
            if text4 and 4 <= len(text4) <= 6:
                results.append(text4)
        
        if not results:
            return None
        
        # Majority voting
        counter = Counter(results)
        best = counter.most_common(1)[0][0]
        
        try:
            value = int(best)
            if 1000 <= value <= 999999:
                return value
            return value
        except ValueError:
            return None

    # ==========================================
    # SCREEN5 SPECIALIZED OCR FUNCTIONS
    # ==========================================
    
    def _ocr_screen5_total_gold(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen5 total gold stat (4-5 digit integers).
        
        Total gold values are typically 4000-12000.
        Uses tight center cropping to avoid adjacent column overlap.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Use center 40% of cell - tight crop to avoid overlap with jungle_gold
        center_margin = int(w * 0.30)
        cropped = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
        
        # Convert to grayscale
        if len(cropped.shape) == 3:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped.copy()
        
        results = []
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        
        # Pass 1: Standard preprocessing at 3x scale
        scale = 3
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1 and 3 <= len(text1) <= 5:
            results.append(text1)
        
        # Pass 2: Higher scale with LANCZOS
        scale2 = 4
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(scaled2)
        _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2 and 3 <= len(text2) <= 5:
            results.append(text2)
        
        # Pass 3: Adaptive threshold
        binary3 = cv2.adaptiveThreshold(scaled2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        if np.mean(binary3) < 127:
            binary3 = cv2.bitwise_not(binary3)
        
        text3 = pytesseract.image_to_string(binary3, config=config).strip()
        text3 = ''.join(c for c in text3 if c.isdigit())
        if text3 and 3 <= len(text3) <= 5:
            results.append(text3)
        
        # Pass 4: White text mask
        if len(cell.shape) == 3:
            cropped_color = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
            hsv = cv2.cvtColor(cropped_color, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 150]), np.array([180, 50, 255]))
            masked = cv2.bitwise_and(gray, gray, mask=mask)
            scaled4 = cv2.resize(masked, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
            inverted = cv2.bitwise_not(scaled4)
            _, binary4 = cv2.threshold(inverted, 100, 255, cv2.THRESH_BINARY)
            
            text4 = pytesseract.image_to_string(binary4, config=config).strip()
            text4 = ''.join(c for c in text4 if c.isdigit())
            if text4 and 3 <= len(text4) <= 5:
                results.append(text4)
        
        if not results:
            return None
        
        # Majority voting
        counter = Counter(results)
        best = counter.most_common(1)[0][0]
        
        try:
            value = int(best)
            if 1000 <= value <= 20000:
                return value
            return value
        except ValueError:
            return None

    def _ocr_screen5_jungle_gold(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen5 jungle gold stat (0-2000).
        
        Jungle gold can be 0, or 2-4 digit numbers. Many values are small (under 500).
        Uses moderate center cropping. No zero detection - rely on OCR.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Use center 60% of cell - more generous crop to preserve digits
        center_margin = int(w * 0.20)
        cropped = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
        
        # Convert to grayscale
        if len(cropped.shape) == 3:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped.copy()
        
        results = []
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        
        # Pass 1: Standard preprocessing
        scale = 3
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1 and len(text1) <= 4:
            results.append(text1)
        
        # Pass 2: Higher scale
        scale2 = 4
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(scaled2)
        _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2 and len(text2) <= 4:
            results.append(text2)
        
        # Pass 3: White text mask
        if len(cell.shape) == 3:
            cropped_color = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
            hsv = cv2.cvtColor(cropped_color, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 50, 255]))
            masked = cv2.bitwise_and(gray, gray, mask=mask)
            scaled3 = cv2.resize(masked, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
            inverted = cv2.bitwise_not(scaled3)
            _, binary3 = cv2.threshold(inverted, 100, 255, cv2.THRESH_BINARY)
            
            text3 = pytesseract.image_to_string(binary3, config=config).strip()
            text3 = ''.join(c for c in text3 if c.isdigit())
            if text3 and len(text3) <= 4:
                results.append(text3)
        
        if not results:
            return 0  # Default to 0 if no text found
        
        # Majority voting
        counter = Counter(results)
        best = counter.most_common(1)[0][0]
        
        try:
            value = int(best)
            if 0 <= value <= 5000:
                return value
            return value
        except ValueError:
            return 0

    def _ocr_screen5_kill_gold(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen5 kill gold stat (0-4000).
        
        Kill gold values are typically 3-4 digit numbers or 0.
        Uses moderate center cropping. No zero detection - rely on OCR.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Use center 60% of cell - more generous crop to preserve digits
        center_margin = int(w * 0.20)
        cropped = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
        
        # Convert to grayscale
        if len(cropped.shape) == 3:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped.copy()
        
        results = []
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        
        # Pass 1: Standard preprocessing
        scale = 3
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1 and len(text1) <= 4:
            results.append(text1)
        
        # Pass 2: Higher scale
        scale2 = 4
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(scaled2)
        _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2 and len(text2) <= 4:
            results.append(text2)
        
        # Pass 3: Adaptive threshold
        binary3 = cv2.adaptiveThreshold(scaled2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        if np.mean(binary3) < 127:
            binary3 = cv2.bitwise_not(binary3)
        
        text3 = pytesseract.image_to_string(binary3, config=config).strip()
        text3 = ''.join(c for c in text3 if c.isdigit())
        if text3 and len(text3) <= 4:
            results.append(text3)
        
        # Pass 4: White text mask
        if len(cell.shape) == 3:
            cropped_color = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
            hsv = cv2.cvtColor(cropped_color, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 50, 255]))
            masked = cv2.bitwise_and(gray, gray, mask=mask)
            scaled4 = cv2.resize(masked, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
            inverted = cv2.bitwise_not(scaled4)
            _, binary4 = cv2.threshold(inverted, 100, 255, cv2.THRESH_BINARY)
            
            text4 = pytesseract.image_to_string(binary4, config=config).strip()
            text4 = ''.join(c for c in text4 if c.isdigit())
            if text4 and len(text4) <= 4:
                results.append(text4)
        
        if not results:
            return 0  # Default to 0
        
        # Majority voting
        counter = Counter(results)
        best = counter.most_common(1)[0][0]
        
        try:
            value = int(best)
            if 0 <= value <= 5000:
                return value
            return value
        except ValueError:
            return 0

    def _ocr_screen5_minion_gold(self, cell: Any) -> Optional[int]:
        """Specialized OCR for screen5 minion gold stat (500-5000).
        
        Minion gold values are typically 3-4 digit numbers.
        Uses moderate center cropping to preserve all digits.
        """
        import numpy as np
        from collections import Counter
        
        h, w = cell.shape[:2]
        
        # Use center 60% of cell - more generous crop to preserve digits
        center_margin = int(w * 0.20)
        cropped = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
        
        # Convert to grayscale
        if len(cropped.shape) == 3:
            gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        else:
            gray = cropped.copy()
        
        results = []
        config = '--psm 7 -c tessedit_char_whitelist=0123456789'
        
        # Pass 1: Standard preprocessing
        scale = 3
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary1 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary1) < 127:
            binary1 = cv2.bitwise_not(binary1)
        
        text1 = pytesseract.image_to_string(binary1, config=config).strip()
        text1 = ''.join(c for c in text1 if c.isdigit())
        if text1 and len(text1) <= 4:
            results.append(text1)
        
        # Pass 2: Higher scale
        scale2 = 4
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        clahe2 = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(scaled2)
        _, binary2 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary2) < 127:
            binary2 = cv2.bitwise_not(binary2)
        
        text2 = pytesseract.image_to_string(binary2, config=config).strip()
        text2 = ''.join(c for c in text2 if c.isdigit())
        if text2 and len(text2) <= 4:
            results.append(text2)
        
        # Pass 3: Adaptive threshold
        binary3 = cv2.adaptiveThreshold(scaled2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        if np.mean(binary3) < 127:
            binary3 = cv2.bitwise_not(binary3)
        
        text3 = pytesseract.image_to_string(binary3, config=config).strip()
        text3 = ''.join(c for c in text3 if c.isdigit())
        if text3 and len(text3) <= 4:
            results.append(text3)
        
        # Pass 4: White text mask
        if len(cell.shape) == 3:
            cropped_color = cell[:, center_margin:w-center_margin] if w > center_margin * 2 else cell
            hsv = cv2.cvtColor(cropped_color, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 50, 255]))
            masked = cv2.bitwise_and(gray, gray, mask=mask)
            scaled4 = cv2.resize(masked, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_CUBIC)
            inverted = cv2.bitwise_not(scaled4)
            _, binary4 = cv2.threshold(inverted, 100, 255, cv2.THRESH_BINARY)
            
            text4 = pytesseract.image_to_string(binary4, config=config).strip()
            text4 = ''.join(c for c in text4 if c.isdigit())
            if text4 and len(text4) <= 4:
                results.append(text4)
        
        if not results:
            return None
        
        # Majority voting
        counter = Counter(results)
        best = counter.most_common(1)[0][0]
        
        try:
            value = int(best)
            if 100 <= value <= 5000:
                return value
            return value
        except ValueError:
            return None

    def _ocr_screen1_individual_rating(self, cell: Any) -> Optional[float]:
        """Specialized OCR for individual rating (decimal like 8.0, 10.3).
        
        The main issue is decimal point detection. Ratings are typically 0.0-16.0.
        Uses aggressive multi-pass with different PSM modes.
        """
        import numpy as np
        from collections import Counter
        
        results = []
        
        # Convert to grayscale
        if len(cell.shape) == 3:
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
        else:
            gray = cell.copy()
        
        # Config with decimal point
        config_decimal = '--psm 7 -c tessedit_char_whitelist=0123456789.'
        config_digits = '--psm 7 -c tessedit_char_whitelist=0123456789'
        config_psm6 = '--psm 6 -c tessedit_char_whitelist=0123456789.'
        config_psm8 = '--psm 8 -c tessedit_char_whitelist=0123456789.'
        
        def parse_rating(text: str) -> Optional[float]:
            """Parse rating text, handling missing decimal points."""
            if not text:
                return None
            # Clean text
            cleaned = ''.join(c for c in text if c.isdigit() or c == '.')
            if not cleaned:
                return None
            
            # Remove multiple dots
            if cleaned.count('.') > 1:
                parts = cleaned.split('.')
                cleaned = parts[0] + '.' + ''.join(parts[1:])
            
            try:
                # If there's a decimal, use it directly
                if '.' in cleaned:
                    val = float(cleaned)
                else:
                    # No decimal - assume last digit is after decimal
                    # e.g., "103" -> 10.3, "80" -> 8.0, "38" -> 3.8, "63" -> 6.3
                    if len(cleaned) >= 2:
                        val = float(cleaned[:-1] + '.' + cleaned[-1])
                    else:
                        val = float(cleaned)
                
                # Ratings are typically 0.0 to 16.0
                if 0.0 <= val <= 20.0:
                    return round(val, 1)
            except ValueError:
                pass
            return None
        
        # Pass 1: High scale with CLAHE for decimal detection
        scale = 6
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(scaled)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary) > 127:
            binary = cv2.bitwise_not(binary)
        
        for cfg in [config_decimal, config_digits, config_psm8]:
            text = pytesseract.image_to_string(binary, config=cfg).strip()
            val = parse_rating(text)
            if val is not None:
                results.append(val)
        
        # Pass 2: HSV white mask (ratings are white text)
        if len(cell.shape) == 3:
            hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 140]), np.array([180, 60, 255]))
            masked = cv2.bitwise_and(gray, gray, mask=mask)
            scaled2 = cv2.resize(masked, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            scaled2 = cv2.bitwise_not(scaled2)
            _, binary2 = cv2.threshold(scaled2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            for cfg in [config_decimal, config_digits]:
                text = pytesseract.image_to_string(binary2, config=cfg).strip()
                val = parse_rating(text)
                if val is not None:
                    results.append(val)
        
        # Pass 3: Higher scale with sharpening
        scale2 = 8
        scaled3 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(scaled3, -1, kernel)
        clahe2 = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced2 = clahe2.apply(sharpened)
        _, binary3 = cv2.threshold(enhanced2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary3) > 127:
            binary3 = cv2.bitwise_not(binary3)
        
        for cfg in [config_decimal, config_psm6]:
            text = pytesseract.image_to_string(binary3, config=cfg).strip()
            val = parse_rating(text)
            if val is not None:
                results.append(val)
        
        # Pass 4: Bilateral filter for noise reduction
        filtered = cv2.bilateralFilter(scaled, 9, 75, 75)
        _, binary4 = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary4) > 127:
            binary4 = cv2.bitwise_not(binary4)
        
        text = pytesseract.image_to_string(binary4, config=config_decimal).strip()
        val = parse_rating(text)
        if val is not None:
            results.append(val)
        
        # Pass 5: Adaptive threshold
        scaled5 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        binary5 = cv2.adaptiveThreshold(scaled5, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY_INV, 11, 2)
        
        text = pytesseract.image_to_string(binary5, config=config_digits).strip()
        val = parse_rating(text)
        if val is not None:
            results.append(val)
        
        if not results:
            return None
        
        # Return most common result
        counter = Counter(results)
        return counter.most_common(1)[0][0]
    
    def _ocr_screen1_hero_level(self, cell: Any) -> Optional[int]:
        """Specialized OCR for hero level (1-15).
        
        Hero level is a small white/yellow number overlaid on hero portrait.
        Requires aggressive preprocessing to isolate the number from busy background.
        
        Known issues:
        - First digit "1" often gets lost, making "12" appear as "2"
        - Two-digit numbers starting with "1" are tricky
        """
        import numpy as np
        from collections import Counter
        
        results = []
        raw_results = []  # Keep track of all raw OCR output before validation
        
        # Keep original for color processing
        original = cell.copy()
        
        # Add padding to left side to help capture first digit
        pad_left = 10
        pad_right = 5
        pad_top = 5
        pad_bottom = 5
        
        if len(original.shape) == 3:
            padded = cv2.copyMakeBorder(original, pad_top, pad_bottom, pad_left, pad_right,
                                        cv2.BORDER_CONSTANT, value=[0, 0, 0])
        else:
            padded = cv2.copyMakeBorder(original, pad_top, pad_bottom, pad_left, pad_right,
                                        cv2.BORDER_CONSTANT, value=0)
        
        # Convert to grayscale
        if len(padded.shape) == 3:
            gray = cv2.cvtColor(padded, cv2.COLOR_BGR2GRAY)
        else:
            gray = padded.copy()
        
        # Multiple configs for different scenarios
        config_single = '--psm 10 -c tessedit_char_whitelist=0123456789'
        config_line = '--psm 7 -c tessedit_char_whitelist=0123456789'
        config_word = '--psm 8 -c tessedit_char_whitelist=0123456789'
        config_sparse = '--psm 11 -c tessedit_char_whitelist=0123456789'
        # PSM 6 - block of text, good for small numbers
        config_block = '--psm 6 -c tessedit_char_whitelist=0123456789'
        
        def validate_level(text: str) -> Optional[int]:
            """Validate hero level is 1-15."""
            cleaned = ''.join(c for c in text if c.isdigit())
            if not cleaned:
                return None
            try:
                val = int(cleaned)
                if 1 <= val <= 15:
                    return val
                # Handle common misreads
                if val in [41, 42, 43, 44, 45]:  # 4 misread as 1
                    corrected = val - 30  # 41->11, 42->12, etc.
                    if 1 <= corrected <= 15:
                        return corrected
                if val in [71, 72, 73, 74, 75]:  # 7 misread as 1
                    corrected = val - 60  # 71->11, 72->12, etc.
                    if 1 <= corrected <= 15:
                        return corrected
            except ValueError:
                pass
            return None
        
        def extract_raw(img, cfg):
            """Extract raw OCR text and record it."""
            text = pytesseract.image_to_string(img, config=cfg).strip()
            cleaned = ''.join(c for c in text if c.isdigit())
            if cleaned:
                raw_results.append(cleaned)
            return validate_level(text)
        
        scale = 6  # Higher scale for small text
        
        # Pass 1: HSV mask for white/bright text (most hero levels are white)
        if len(padded.shape) == 3:
            hsv = cv2.cvtColor(padded, cv2.COLOR_BGR2HSV)
            # White text (high value, low saturation)
            mask_white = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([180, 50, 255]))
            # Also try yellow text (some levels show yellow)
            mask_yellow = cv2.inRange(hsv, np.array([15, 80, 180]), np.array([35, 255, 255]))
            mask = cv2.bitwise_or(mask_white, mask_yellow)
            
            gray_orig = cv2.cvtColor(padded, cv2.COLOR_BGR2GRAY)
            masked = cv2.bitwise_and(gray_orig, gray_orig, mask=mask)
            scaled = cv2.resize(masked, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            scaled = cv2.bitwise_not(scaled)
            _, binary = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            for cfg in [config_line, config_word, config_block]:
                val = extract_raw(binary, cfg)
                if val is not None:
                    results.append(val)
        
        # Pass 2: Standard CLAHE on grayscale
        scaled2 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(4, 4))
        enhanced = clahe.apply(scaled2)
        enhanced = cv2.bitwise_not(enhanced)
        _, binary2 = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        for cfg in [config_line, config_word, config_block]:
            val = extract_raw(binary2, cfg)
            if val is not None:
                results.append(val)
        
        # Pass 3: Adaptive threshold
        scaled3 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        binary3 = cv2.adaptiveThreshold(scaled3, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY_INV, 11, 2)
        
        for cfg in [config_line, config_block]:
            val = extract_raw(binary3, cfg)
            if val is not None:
                results.append(val)
        
        # Pass 4: Very high scale with bilateral filter
        scale2 = 8
        scaled4 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        filtered = cv2.bilateralFilter(scaled4, 9, 75, 75)
        filtered = cv2.bitwise_not(filtered)
        _, binary4 = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        for cfg in [config_line, config_word, config_block]:
            val = extract_raw(binary4, cfg)
            if val is not None:
                results.append(val)
        
        # Pass 5: Morphological cleanup
        kernel = np.ones((2, 2), np.uint8)
        morph = cv2.morphologyEx(binary2, cv2.MORPH_CLOSE, kernel)
        morph = cv2.morphologyEx(morph, cv2.MORPH_OPEN, kernel)
        
        val = extract_raw(morph, config_line)
        if val is not None:
            results.append(val)
        
        # Pass 6: Multiple threshold levels
        for thresh in [80, 100, 127, 150, 180, 200]:
            scaled6 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            _, binary6 = cv2.threshold(scaled6, thresh, 255, cv2.THRESH_BINARY_INV)
            
            val = extract_raw(binary6, config_line)
            if val is not None:
                results.append(val)
        
        # Pass 7: Dilation to thicken thin digits (especially "1")
        kernel_dilate = np.ones((2, 2), np.uint8)
        dilated = cv2.dilate(binary2, kernel_dilate, iterations=1)
        
        for cfg in [config_line, config_block]:
            val = extract_raw(dilated, cfg)
            if val is not None:
                results.append(val)
        
        # Pass 8: Sharpening filter
        sharpen_kernel = np.array([[-1, -1, -1],
                                   [-1,  9, -1],
                                   [-1, -1, -1]])
        scaled8 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        sharpened = cv2.filter2D(scaled8, -1, sharpen_kernel)
        sharpened = cv2.bitwise_not(sharpened)
        _, binary8 = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        for cfg in [config_line, config_block]:
            val = extract_raw(binary8, cfg)
            if val is not None:
                results.append(val)
        
        # Analyze raw results for inference
        if raw_results:
            # Count occurrences of each digit pattern
            digit_counts = Counter(raw_results)
            
            # If we consistently get single digits, try inferring double digits
            # This helps when "1" is lost from "11", "12", "13", etc.
            single_digits = [r for r in raw_results if len(r) == 1]
            double_digits = [r for r in raw_results if len(r) == 2]
            
            # Only infer 10+ values for digits 0-5 (which could be 10-15)
            # Digits 6-9 are likely actual single-digit levels
            if single_digits:
                single_counter = Counter(single_digits)
                for digit, count in single_counter.most_common():
                    if digit in '012345' and count >= 2:
                        # Likely missing first digit "1"
                        inferred = 10 + int(digit)
                        if 1 <= inferred <= 15:
                            # Add multiple times based on occurrence count
                            for _ in range(count):
                                results.append(inferred)
        
        if not results:
            return None
        
        # Use voting with preference for higher/double-digit values
        counter = Counter(results)
        most_common_list = counter.most_common()
        
        # Check for double digit candidates (10-15)
        doubles = [(v, c) for v, c in most_common_list if v >= 10]
        singles = [(v, c) for v, c in most_common_list if v <= 9]
        
        # For single digits 6-9, trust them more (unlikely to be 16-19 which don't exist)
        high_singles = [(v, c) for v, c in singles if v >= 6]
        low_singles = [(v, c) for v, c in singles if v <= 5]
        
        # If we have strong support for 6-9, trust it
        if high_singles:
            high_single_total = sum(c for v, c in high_singles)
            if high_single_total >= 3:
                return high_singles[0][0]
        
        # If we have double-digit candidates with reasonable support, prefer them
        if doubles:
            double_total = sum(c for v, c in doubles)
            low_single_total = sum(c for v, c in low_singles)
            
            # If doubles have at least 30% of low single digit support, trust doubles
            if double_total >= low_single_total * 0.3:
                return doubles[0][0]
        
        # If most common has strong consensus (3+ votes), trust it
        if most_common_list[0][1] >= 3:
            return most_common_list[0][0]
        
        # Otherwise return the max value (prefer larger)
        return max(results)
    
    def _ocr_screen1_kda(self, cell: Any, field_name: str) -> Optional[int]:
        """Specialized OCR for K/D/A values (kills, deaths, assists).
        
        These are typically 0-99 integers. Main issues:
        - "1" being read as "4" 
        - "0" being missed entirely
        - Single digits being tricky to detect
        """
        import numpy as np
        from collections import Counter
        
        results = []
        original = cell.copy()
        
        # Convert to grayscale
        if len(cell.shape) == 3:
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
        else:
            gray = cell.copy()
        
        config7 = '--psm 7 -c tessedit_char_whitelist=0123456789'
        config8 = '--psm 8 -c tessedit_char_whitelist=0123456789'
        config10 = '--psm 10 -c tessedit_char_whitelist=0123456789'  # Single char mode
        
        def validate_kda(text: str) -> Optional[int]:
            """Validate KDA value is 0-99."""
            cleaned = ''.join(c for c in text if c.isdigit())
            if not cleaned:
                return None
            try:
                val = int(cleaned)
                if 0 <= val <= 99:
                    return val
            except ValueError:
                pass
            return None
        
        scale = 5
        
        # Pass 1: CLAHE with multiple configs
        scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))
        enhanced = clahe.apply(scaled)
        enhanced = cv2.bitwise_not(enhanced)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        for cfg in [config7, config8]:
            text = pytesseract.image_to_string(binary, config=cfg).strip()
            val = validate_kda(text)
            if val is not None:
                results.append(val)
        
        # Pass 2: Higher scale with bilateral filter
        scale2 = 6
        scaled2 = cv2.resize(gray, None, fx=scale2, fy=scale2, interpolation=cv2.INTER_LANCZOS4)
        filtered = cv2.bilateralFilter(scaled2, 9, 75, 75)
        filtered = cv2.bitwise_not(filtered)
        _, binary2 = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        for cfg in [config7, config8]:
            text = pytesseract.image_to_string(binary2, config=cfg).strip()
            val = validate_kda(text)
            if val is not None:
                results.append(val)
        
        # Pass 3: HSV masking for white text
        if len(original.shape) == 3:
            hsv = cv2.cvtColor(original, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 60, 255]))
            masked_gray = cv2.bitwise_and(gray, gray, mask=mask)
            scaled3 = cv2.resize(masked_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            scaled3 = cv2.bitwise_not(scaled3)
            _, binary3 = cv2.threshold(scaled3, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            for cfg in [config7, config8]:
                text = pytesseract.image_to_string(binary3, config=cfg).strip()
                val = validate_kda(text)
                if val is not None:
                    results.append(val)
        
        # Pass 4: Morphological operations
        kernel = np.ones((2, 2), np.uint8)
        morph = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        morph = cv2.morphologyEx(morph, cv2.MORPH_OPEN, kernel)
        
        text = pytesseract.image_to_string(morph, config=config7).strip()
        val = validate_kda(text)
        if val is not None:
            results.append(val)
        
        # Pass 5: Adaptive threshold
        scaled5 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        binary5 = cv2.adaptiveThreshold(scaled5, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY_INV, 11, 2)
        
        for cfg in [config7, config8]:
            text = pytesseract.image_to_string(binary5, config=cfg).strip()
            val = validate_kda(text)
            if val is not None:
                results.append(val)
        
        # Pass 6: Multiple threshold levels for tricky values
        for thresh in [100, 127, 150, 180]:
            scaled6 = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            _, binary6 = cv2.threshold(scaled6, thresh, 255, cv2.THRESH_BINARY_INV)
            
            text = pytesseract.image_to_string(binary6, config=config7).strip()
            val = validate_kda(text)
            if val is not None:
                results.append(val)
        
        # Pass 7: Try PSM 10 (single character) for single-digit values
        text = pytesseract.image_to_string(binary, config=config10).strip()
        val = validate_kda(text)
        if val is not None:
            results.append(val)
        
        if not results:
            # Special case: if no results found, check if cell is mostly empty (likely 0)
            # Count non-zero pixels in binary image
            scaled_check = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            _, binary_check = cv2.threshold(scaled_check, 150, 255, cv2.THRESH_BINARY_INV)
            non_zero_ratio = np.count_nonzero(binary_check) / binary_check.size
            
            # If very few bright pixels, likely a 0 which has distinct shape
            # Return None and let caller decide
            return None
        
        # Use voting - most common result
        counter = Counter(results)
        return counter.most_common(1)[0][0]

    def _get_field_type(self, field_name: str) -> str:
        """Determine the OCR field type based on field name."""
        # Text fields
        if field_name in {"player_name"}:
            return "text"
        
        # Decimal/rating fields
        if field_name in {"individual_rating"}:
            return "decimal"
        
        # Percentage fields (teamfight_participation is a percentage without % sign)
        if "participation" in field_name:
            return "integer"
        
        # All other fields are integers (kills, deaths, assists, gold, damage, etc.)
        return "integer"
        
        return ocr_data
    
    def _parse_ocr_value(self, field_name: str, text: str) -> Any:
        """Parse OCR text into appropriate data type.
        
        Args:
            field_name: Name of the field being parsed
            text: Raw OCR text to parse
        """
        if not text or text.strip() == "":
            return None
        
        text = text.strip()
        
        # Text fields
        if field_name in {"player_name"}:
            return text
        
        # Decimal/rating fields
        if field_name in {"individual_rating"}:
            try:
                cleaned = ''.join(c for c in text if c.isdigit() or c == '.')
                return float(cleaned) if cleaned else None
            except ValueError:
                return None
        
        # Teamfight participation (0-99, max 2 digits)
        if "participation" in field_name:
            try:
                cleaned = ''.join(c for c in text if c.isdigit())
                # Only take first 2 digits max
                cleaned = cleaned[:2] if len(cleaned) > 2 else cleaned
                value = int(cleaned) if cleaned else None
                # Clamp to valid range
                if value is not None:
                    value = max(0, min(99, value))
                return value
            except ValueError:
                return None
        
        # All numeric fields (kills, deaths, assists, gold, damage stats)
        try:
            # Remove any non-digit characters except decimal point
            cleaned = ''.join(c for c in text if c.isdigit() or c == '.')
            if not cleaned:
                return None
            if '.' in cleaned:
                return int(float(cleaned))  # Round to int
            return int(cleaned)
        except ValueError:
            return None
    
    def extract_enemy_data(
        self, 
        img: Any, 
        row: tuple, 
        row_index: int,
        column_mappings: Dict
    ) -> Dict[str, Any]:
        """
        Extract all data for a single enemy player row.
        Uses enemy_* column mappings.
        
        Args:
            img: Normalized screenshot image
            row: (y_start, y_end) tuple for player row
            row_index: Enemy player number (0-4)
            column_mappings: Column coordinate mappings
            
        Returns:
            Dictionary with enemy player data including hero, items, and stats
        """
        y_start, y_end = row
        height, width = img.shape[:2]
        row_height = y_end - y_start
        
        player_data = {
            "player_number": row_index + 1,
            "team": "enemy",
            "row_coordinates": {"y_start": int(y_start), "y_end": int(y_end)}
        }
        
        # 1. Extract Enemy Hero Portrait (only if matchers are loaded)
        if self.hero_matcher and "enemy_hero_portrait" in column_mappings:
            hero_data = self._extract_hero(img, y_start, row_height, width, column_mappings["enemy_hero_portrait"])
            player_data["hero"] = hero_data
        
        # 2. Extract Enemy Items (6 slots) - only if matchers are loaded
        if self.item_matcher:
            items_data = self._extract_enemy_items(img, y_start, row_height, width, column_mappings)
            player_data["items"] = items_data
        
        # 3. Extract Enemy OCR Fields (dynamic based on mapping)
        ocr_fields = self._extract_enemy_ocr_fields(img, y_start, row_height, width, column_mappings)
        player_data.update(ocr_fields)
        
        return player_data
    
    def _extract_enemy_items(
        self, 
        img: Any, 
        y_start: int, 
        row_height: int, 
        width: int,
        column_mappings: Dict
    ) -> List[Dict[str, Any]]:
        """Extract and match all 6 enemy item slots.
        
        Note: Enemy items are visually arranged right-to-left on screen,
        with enemy_item1 (in column mapping) being the rightmost (closest to hero).
        We reverse the order so slot 1 in output = leftmost item visually.
        """
        items = []
        
        # Skip item matching if matcher not available (OCR-only mode)
        if self.item_matcher is None:
            return items
        
        # Extract in reverse order: enemy_item6 -> enemy_item1 
        # so that slot 1 = leftmost item visually
        for slot_idx in range(6, 0, -1):
            slot_key = f"enemy_item{slot_idx}"
            output_slot = 7 - slot_idx  # 6->1, 5->2, etc.
            
            if slot_key not in column_mappings:
                items.append({
                    "slot": output_slot,
                    "item_name": None,
                    "error": "Column mapping not found"
                })
                continue
            
            try:
                col_def = column_mappings[slot_key]
                
                # Calculate cell coordinates
                x_start = int(width * col_def['x_start_pct'])
                x_end = int(width * col_def['x_end_pct'])
                y_offset = int(row_height * col_def['y_offset_pct'])
                cell_height = int(row_height * col_def['height_pct'])
                
                cell_y_start = y_start + y_offset
                cell_y_end = cell_y_start + cell_height
                
                # Crop item slot
                item_cell = img[cell_y_start:cell_y_end, x_start:x_end]
                
                # Match item
                matches = self.item_matcher.match_item(item_cell, top_n=1)
                
                if matches and len(matches) > 0:
                    best_match = matches[0]
                    
                    if best_match.item_name == "EMPTY":
                        items.append({
                            "slot": output_slot,
                            "item_name": None,
                            "confidence": 0.0,
                            "is_empty": True
                        })
                    else:
                        items.append({
                            "slot": output_slot,
                            "item_name": best_match.item_name,
                            "confidence": round(best_match.confidence, 3),
                            "top_method": max(
                                best_match.method_scores.items(), 
                                key=lambda x: x[1]
                            )[0] if best_match.method_scores else None
                        })
                else:
                    items.append({
                        "slot": output_slot,
                        "item_name": None,
                        "confidence": 0.0,
                        "is_empty": True
                    })
                
            except Exception as e:
                items.append({
                    "slot": output_slot,
                    "item_name": None,
                    "error": str(e)
                })
        
        return items
    
    def _extract_enemy_ocr_fields(
        self, 
        img: Any, 
        y_start: int, 
        row_height: int, 
        width: int,
        column_mappings: Dict
    ) -> Dict[str, Any]:
        """Extract OCR-based fields for enemy players dynamically."""
        results = {}
        
        # Fields to skip (handled separately)
        skip_fields = {
            "enemy_hero_portrait",
            "enemy_item1", "enemy_item2", "enemy_item3", 
            "enemy_item4", "enemy_item5", "enemy_item6",
            "battle_id"
        }
        
        # Screen2 damage fields that need specialized OCR
        screen2_damage_fields = {
            "enemy_hero_damage", "enemy_turret_damage", 
            "enemy_damage_taken", "enemy_teamfight_participation"
        }
        
        # Screen3 fields that need specialized OCR
        screen3_hero_damage_fields = {"enemy_hero_damage"}
        screen3_consecutive_kills_fields = {"enemy_consecutive_kills"}
        
        # Screen1 KDA fields
        screen1_kda_fields = {"enemy_kills", "enemy_deaths", "enemy_assists"}
        
        # Find all enemy_* fields in the mapping
        for field_name, col_def in column_mappings.items():
            # Only process enemy_ prefixed fields
            if not field_name.startswith("enemy_"):
                continue
            
            # Skip non-OCR fields
            if field_name in skip_fields:
                continue
            
            # Output key removes the enemy_ prefix
            output_key = field_name.replace("enemy_", "")
            
            try:
                # Calculate cell coordinates
                x_start = int(width * col_def['x_start_pct'])
                x_end = int(width * col_def['x_end_pct'])
                y_offset = int(row_height * col_def['y_offset_pct'])
                cell_height = int(row_height * col_def['height_pct'])
                
                cell_y_start = y_start + y_offset
                cell_y_end = cell_y_start + cell_height
                
                # Crop cell
                cell = img[cell_y_start:cell_y_end, x_start:x_end]
                
                # Use specialized OCR based on screen type and field
                if self.screentype == "screen2" and field_name in screen2_damage_fields:
                    # Screen2 damage stats (95% accuracy - DO NOT MODIFY)
                    parsed_value = self._ocr_damage_stat(cell, field_name)
                elif self.screentype == "screen3":
                    # Screen3 specialized OCR functions
                    if field_name in screen3_hero_damage_fields:
                        parsed_value = self._ocr_screen3_hero_damage(cell)
                    elif field_name in screen3_consecutive_kills_fields:
                        parsed_value = self._ocr_screen3_consecutive_kills(cell)
                    else:
                        # Use standard OCR for other screen3 fields
                        field_type = self._get_field_type(output_key)
                        parsed_value = extract_field(cell, field_type, output_key)
                elif self.screentype == "screen1":
                    # Screen1 specialized OCR functions
                    if field_name == "enemy_individual_rating":
                        parsed_value = self._ocr_screen1_individual_rating(cell)
                    elif field_name == "enemy_hero_level":
                        parsed_value = self._ocr_screen1_hero_level(cell)
                    elif field_name in screen1_kda_fields:
                        parsed_value = self._ocr_screen1_kda(cell, output_key)
                    else:
                        # Standard OCR for other fields
                        field_type = self._get_field_type(output_key)
                        parsed_value = extract_field(cell, field_type, output_key)
                elif self.screentype == "screen4":
                    # Screen4 specialized OCR functions
                    if field_name == "enemy_crowd_control":
                        parsed_value = self._ocr_screen4_crowd_control(cell)
                    elif field_name == "enemy_healing_and_shields":
                        parsed_value = self._ocr_screen4_healing_and_shields(cell)
                    elif field_name == "enemy_damage_taken":
                        parsed_value = self._ocr_screen4_damage_taken(cell)
                    else:
                        # Standard OCR for other screen4 fields
                        field_type = self._get_field_type(output_key)
                        parsed_value = extract_field(cell, field_type, output_key)
                elif self.screentype == "screen5":
                    # Screen5 specialized OCR functions for gold breakdown
                    if field_name == "enemy_total_gold":
                        parsed_value = self._ocr_screen5_total_gold(cell)
                    elif field_name == "enemy_jungle_gold":
                        parsed_value = self._ocr_screen5_jungle_gold(cell)
                    elif field_name == "enemy_kill_gold":
                        parsed_value = self._ocr_screen5_kill_gold(cell)
                    elif field_name == "enemy_minion_gold":
                        parsed_value = self._ocr_screen5_minion_gold(cell)
                    else:
                        # Standard OCR for other screen5 fields
                        field_type = self._get_field_type(output_key)
                        parsed_value = extract_field(cell, field_type, output_key)
                else:
                    # Standard OCR
                    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
                    _, processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    text = pytesseract.image_to_string(processed, config='--psm 7').strip()
                    parsed_value = self._parse_ocr_value(output_key, text)
                
                results[output_key] = {
                    "value": parsed_value,
                    "confidence": 0.0
                }
                
            except Exception as e:
                results[output_key] = {
                    "value": None,
                    "error": str(e)
                }
        
        return results

    def process_screenshot(self, screenshot_path: str) -> Dict[str, Any]:
        """
        Process a screenshot and extract all data.
        
        Args:
            screenshot_path: Path to screenshot image
            
        Returns:
            Dictionary with complete extraction results
        """
        print(f"📸 Processing: {screenshot_path}")
        
        # Load and normalize image
        img = cv2.imread(screenshot_path)
        if img is None:
            raise ValueError(f"Could not load image: {screenshot_path}")
        
        height, width = img.shape[:2]
        print(f"  ✓ Loaded image: {width}x{height}")
        
        # Detect player rows
        rows = detect_player_rows(img, self.field_config)
        print(f"  ✓ Detected {len(rows)} player rows")
        
        # Get column mappings from the already-loaded field_config
        column_mappings = self.field_config.column_config.get('columns', {})
        
        # Extract battle_id if present - use screen-specific function
        battle_id = None
        if 'battle_id' in column_mappings:
            if self.screentype == "screen1":
                battle_id = self._ocr_screen1_battle_id(img, column_mappings['battle_id'])
            else:
                battle_id = self._extract_battle_id(img, column_mappings['battle_id'])
        
        # Extract data for each ally player
        allies = []
        for i, row in enumerate(rows):
            print(f"  ⏳ Processing ally {i+1}...")
            player_data = self.extract_player_data(img, row, i, column_mappings)
            player_data["team"] = "ally"
            allies.append(player_data)
        
        # Extract data for each enemy player (same rows, different columns)
        # Only if enemy columns exist in this mapping
        enemies = []
        has_enemy_columns = any(k.startswith('enemy_') for k in column_mappings.keys())
        if has_enemy_columns:
            for i, row in enumerate(rows):
                print(f"  ⏳ Processing enemy {i+1}...")
                enemy_data = self.extract_enemy_data(img, row, i, column_mappings)
                enemies.append(enemy_data)
        
        print(f"  ✓ Extraction complete!")
        
        # Combine all players
        all_players = allies + enemies
        
        # Build output
        result = {
            "metadata": {
                "screenshot_path": screenshot_path,
                "screentype": self.screentype,
                "mapping_file": self.mapping_file,
                "timestamp": datetime.now().isoformat(),
                "resolution": {"width": width, "height": height},
                "total_players": len(all_players),
                "ally_count": len(allies),
                "enemy_count": len(enemies)
            },
            "allies": allies,
            "enemies": enemies,
            "summary": self._generate_summary(all_players)
        }
        
        # Add battle_id if extracted
        if battle_id is not None:
            result["metadata"]["battle_id"] = battle_id
        
        return result
    
    def _generate_summary(self, players: List[Dict]) -> Dict[str, Any]:
        """Generate extraction summary statistics."""
        # Count items (exclude empty slots)
        total_items = sum(
            sum(1 for item in p.get("items", []) 
                if item.get("item_name") and not item.get("is_empty")) 
            for p in players
        )
        
        # Count total item slots
        total_slots = sum(len(p.get("items", [])) for p in players)
        
        # Count empty slots
        empty_slots = sum(
            sum(1 for item in p.get("items", []) if item.get("is_empty"))
            for p in players
        )
        
        summary = {
            "heroes_detected": sum(1 for p in players if p.get("hero", {}).get("hero_name")),
            "total_items_detected": total_items,
            "total_item_slots": total_slots,
            "empty_slots": empty_slots,
            "avg_hero_confidence": 0.0,
            "avg_item_confidence": 0.0
        }
        
        # Calculate average hero confidence
        hero_confidences = [
            p.get("hero", {}).get("confidence", 0) 
            for p in players 
            if p.get("hero", {}).get("hero_name")
        ]
        if hero_confidences:
            summary["avg_hero_confidence"] = round(sum(hero_confidences) / len(hero_confidences), 3)
        
        # Calculate average item confidence
        item_confidences = [
            item.get("confidence", 0)
            for p in players
            for item in p.get("items", [])
            if item.get("item_name") and not item.get("is_empty")
        ]
        if item_confidences:
            summary["avg_item_confidence"] = round(sum(item_confidences) / len(item_confidences), 3)
        
        return summary


def main():
    """Main entry point."""
    print("=" * 70)
    print("Squad STATS - Match Data Extraction")
    print("=" * 70)
    print()
    
    # Check arguments
    if len(sys.argv) < 2:
        print("❌ Error: No screenshot path provided")
        print("\nUsage:")
        print('  python main.py "path/to/screenshot.png" [screentype]')
        print('  python main.py "tests/fixtures/test (1).jpeg"              # defaults to screen1')
        print('  python main.py "tests/fixtures/Screen2.jpeg" screen2       # damage stats')
        print()
        print("Screen types:")
        print('  screen1 - KDA stats, items, ratings (default)')
        print('  screen2 - Damage stats (hero/turret/damage taken/teamfight participation)')
        sys.exit(1)
    
    screenshot_path = sys.argv[1]
    screentype = sys.argv[2] if len(sys.argv) > 2 else "screen1"
    
    # Check if file exists
    if not Path(screenshot_path).exists():
        print(f"❌ Error: File not found: {screenshot_path}")
        sys.exit(1)
    
    # Validate mapping file exists (full path for validation)
    if screentype in SCREEN_MAPPING_FILES:
        mapping_filename = SCREEN_MAPPING_FILES[screentype]
    else:
        mapping_filename = f"{screentype}_column_mapping.yaml"
    
    mapping_path = Path("config") / mapping_filename
    if not mapping_path.exists():
        print(f"❌ Error: Mapping file not found: {mapping_path}")
        print(f"\nValid screen types: {', '.join(SCREEN_MAPPING_FILES.keys())}")
        sys.exit(1)
    
    try:
        # Initialize extractor with screentype
        extractor = SquadStatsExtractor(screentype=screentype)
        
        # Process screenshot
        result = extractor.process_screenshot(screenshot_path)
        
        # Save to JSON
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        
        # Generate output filename
        screenshot_name = Path(screenshot_path).stem
        output_file = output_dir / f"{screenshot_name}_extraction.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print()
        print("=" * 70)
        print("✅ Extraction Complete!")
        print("=" * 70)
        print(f"📄 Output saved to: {output_file}")
        print()
        print("Summary:")
        summary = result["summary"]
        
        # Show different summary based on screentype
        if screentype in SCREENS_WITH_HERO_ITEMS:
            print(f"  Heroes detected: {summary['heroes_detected']}/{result['metadata']['total_players']}")
            print(f"  Items detected: {summary['total_items_detected']}/{summary['total_item_slots']} slots ({summary['empty_slots']} empty)")
            print(f"  Avg hero confidence: {summary['avg_hero_confidence']:.1%}")
            print(f"  Avg item confidence: {summary['avg_item_confidence']:.1%}")
        else:
            # OCR-only mode (screen2, etc.)
            print(f"  Players extracted: {result['metadata']['ally_count']} allies, {result['metadata']['enemy_count']} enemies")
            if result['metadata'].get('battle_id'):
                print(f"  Battle ID: {result['metadata']['battle_id']}")
        print("=" * 70)
        
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ Extraction Failed!")
        print("=" * 70)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
