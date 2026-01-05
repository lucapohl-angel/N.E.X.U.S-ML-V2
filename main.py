"""Squad STATS - Main Extraction Script

Central script that orchestrates all extraction components:
- Image preprocessing and row detection
- Hero portrait matching
- Item icon matching  
- OCR text extraction
- JSON output generation

Usage:
    python main.py <screenshot_path>
    python main.py "tests/fixtures/test (1).jpeg"
"""

import sys
import cv2
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Import core components
from app.parser.detector import detect_player_rows
from app.parser.hero_matcher import HeroMatcher
from app.parser.item_matcher import ItemMatcher
from app.parser.ocr import extract_field
from app.core.field_config import get_config


class SquadStatsExtractor:
    """Main extraction orchestrator."""
    
    def __init__(self):
        """Initialize all extraction components."""
        print("🔧 Initializing Squad STATS Extractor...")
        
        # Load configuration
        self.field_config = get_config()
        
        # Initialize matchers
        self.hero_matcher = HeroMatcher()
        self.item_matcher = ItemMatcher()
        
        print(f"  ✓ Loaded {len(self.hero_matcher.hero_database)} heroes")
        print(f"  ✓ Loaded {len(self.item_matcher.item_database)} items")
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
        
        # 1. Extract Hero Portrait
        if "hero_portrait" in column_mappings:
            hero_data = self._extract_hero(img, y_start, row_height, width, column_mappings["hero_portrait"])
            player_data["hero"] = hero_data
        
        # 2. Extract Items (6 slots)
        items_data = self._extract_items(img, y_start, row_height, width, column_mappings)
        player_data["items"] = items_data
        
        # 3. Extract OCR Fields
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
        """Extract OCR text fields (player name, level, K/D/A, gold, rating)."""
        ocr_data = {}
        
        # Define OCR fields to extract
        ocr_fields = [
            "player_name",
            "hero_level",
            "kills",
            "deaths",
            "assists",
            "total_gold",
            "individual_rating"
        ]
        
        for field_name in ocr_fields:
            if field_name not in column_mappings:
                ocr_data[field_name] = {"value": None, "error": "Column mapping not found"}
                continue
            
            try:
                col_def = column_mappings[field_name]
                
                # Calculate cell coordinates
                x_start = int(width * col_def['x_start_pct'])
                x_end = int(width * col_def['x_end_pct'])
                y_offset = int(row_height * col_def['y_offset_pct'])
                cell_height = int(row_height * col_def['height_pct'])
                
                cell_y_start = y_start + y_offset
                cell_y_end = cell_y_start + cell_height
                
                # Crop cell
                cell = img[cell_y_start:cell_y_end, x_start:x_end]
                
                # Determine field type for OCR
                if field_name == "player_name":
                    field_type = "text"
                elif field_name == "individual_rating":
                    field_type = "decimal"
                else:
                    field_type = "integer"
                
                # Extract text (using OCR)
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
    
    def _parse_ocr_value(self, text: str, field_name: str) -> Any:
        """Parse OCR text into appropriate data type."""
        if not text or text.strip() == "":
            return None
        
        text = text.strip()
        
        # Numeric fields
        if field_name in ["hero_level", "kills", "deaths", "assists", "total_gold"]:
            try:
                # Remove any non-digit characters except decimal point
                cleaned = ''.join(c for c in text if c.isdigit() or c == '.')
                if '.' in cleaned:
                    return float(cleaned)
                return int(cleaned)
            except ValueError:
                return None
        
        # Rating field (decimal)
        elif field_name == "individual_rating":
            try:
                cleaned = ''.join(c for c in text if c.isdigit() or c == '.')
                return float(cleaned)
            except ValueError:
                return None
        
        # Text fields (player name)
        else:
            return text
    
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
        
        # 1. Extract Enemy Hero Portrait
        if "enemy_hero_portrait" in column_mappings:
            hero_data = self._extract_hero(img, y_start, row_height, width, column_mappings["enemy_hero_portrait"])
            player_data["hero"] = hero_data
        
        # 2. Extract Enemy Items (6 slots) - uses enemy_item1 through enemy_item6
        items_data = self._extract_enemy_items(img, y_start, row_height, width, column_mappings)
        player_data["items"] = items_data
        
        # 3. Extract Enemy OCR Fields
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
        """Extract OCR-based fields for enemy players."""
        results = {}
        
        # Map enemy field names to their column keys
        enemy_ocr_fields = [
            ("enemy_player_name", "player_name"),
            ("enemy_hero_level", "hero_level"),
            ("enemy_kills", "kills"),
            ("enemy_deaths", "deaths"),
            ("enemy_assists", "assists"),
            ("enemy_total_gold", "total_gold"),
            ("enemy_individual_rating", "individual_rating"),
        ]
        
        for col_key, output_key in enemy_ocr_fields:
            if col_key not in column_mappings:
                continue
            
            try:
                col_def = column_mappings[col_key]
                
                # Calculate cell coordinates
                x_start = int(width * col_def['x_start_pct'])
                x_end = int(width * col_def['x_end_pct'])
                y_offset = int(row_height * col_def['y_offset_pct'])
                cell_height = int(row_height * col_def['height_pct'])
                
                cell_y_start = y_start + y_offset
                cell_y_end = cell_y_start + cell_height
                
                # Crop and preprocess for OCR
                cell = img[cell_y_start:cell_y_end, x_start:x_end]
                
                # Apply preprocessing
                preprocessing = col_def.get('preprocessing', 'binarize')
                if preprocessing == 'binarize':
                    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
                    _, processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                else:
                    processed = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
                
                # OCR
                text = pytesseract.image_to_string(processed, config='--psm 7').strip()
                
                # Parse based on field type
                parsed_value = self._parse_ocr_value(output_key, text)
                
                results[output_key] = {
                    "value": parsed_value,
                    "confidence": 0.0  # Tesseract confidence could be added
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
        
        # Load column mappings
        import yaml
        with open("config/column_mapping.yaml", 'r') as f:
            column_config = yaml.safe_load(f)
        
        column_mappings = column_config['columns']
        
        # Extract data for each ally player
        allies = []
        for i, row in enumerate(rows):
            print(f"  ⏳ Processing ally {i+1}...")
            player_data = self.extract_player_data(img, row, i, column_mappings)
            player_data["team"] = "ally"
            allies.append(player_data)
        
        # Extract data for each enemy player (same rows, different columns)
        enemies = []
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
        print('  python main.py "path/to/screenshot.png"')
        print('  python main.py "tests/fixtures/test (1).jpeg"')
        sys.exit(1)
    
    screenshot_path = sys.argv[1]
    
    # Check if file exists
    if not Path(screenshot_path).exists():
        print(f"❌ Error: File not found: {screenshot_path}")
        sys.exit(1)
    
    try:
        # Initialize extractor
        extractor = SquadStatsExtractor()
        
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
        print(f"  Heroes detected: {summary['heroes_detected']}/{result['metadata']['total_players']}")
        print(f"  Items detected: {summary['total_items_detected']}/{summary['total_item_slots']} slots ({summary['empty_slots']} empty)")
        print(f"  Avg hero confidence: {summary['avg_hero_confidence']:.1%}")
        print(f"  Avg item confidence: {summary['avg_item_confidence']:.1%}")
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
