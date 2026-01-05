"""
Item Icon Matcher

Uses computer vision techniques to identify items from screenshot item slots
by comparing against a database of known item icons.

Methods used for high accuracy:
1. Template Matching - Direct pixel comparison with preprocessing
2. Histogram Comparison - Color distribution matching (HSV)
3. Feature Matching (ORB) - Keypoint descriptor matching
4. Structural Similarity - Perceptual similarity
5. Center-crop matching - Focus on item icon, ignore frame

Uses weighted ensemble with confidence boosting for best accuracy.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
import logging
import json

logger = logging.getLogger(__name__)

# Default icons directory
ICONS_DIR = Path("items/icons")


@dataclass
class ItemMatchResult:
    """Result of an item icon match."""
    item_name: str
    filename: str
    confidence: float
    method_scores: Dict[str, float]
    slot_index: int = 0


class ItemMatcher:
    """
    Matches screenshot item icons against known item database.
    
    Uses multiple computer vision techniques and ensemble scoring for accuracy:
    - Template matching with preprocessing variants
    - Histogram comparison (HSV color distribution)
    - ORB feature matching (keypoint descriptors)
    - Center-focused matching (ignore UI frame)
    """
    
    def __init__(self, icons_dir: Optional[Path] = None):
        """
        Initialize the item matcher.
        
        Args:
            icons_dir: Path to directory containing item icon images.
                      Expected filename format: item_<Name>.png
        """
        self.icons_dir = icons_dir or ICONS_DIR
        self.item_database: Dict[str, np.ndarray] = {}
        self.item_info: Dict[str, Dict[str, Any]] = {}
        self._load_item_database()
        
        # Initialize ORB detector for feature matching
        self.orb = cv2.ORB_create(nfeatures=500, scoreType=cv2.ORB_HARRIS_SCORE)
        self.bf_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        
        # Pre-compute features for all items
        self.item_features: Dict[str, Tuple[Any, Any]] = {}
        self.item_center_crops: Dict[str, np.ndarray] = {}
        self.item_histograms: Dict[str, np.ndarray] = {}
        self._precompute_features()
    
    def _load_item_database(self) -> None:
        """Load all item icons from the icons directory."""
        if not self.icons_dir.exists():
            logger.warning(f"Icons directory not found: {self.icons_dir}")
            return
        
        for icon_path in self.icons_dir.glob("item_*.png"):
            try:
                # Parse filename: item_<Name>.png
                filename = icon_path.stem  # e.g., "item_Blade of Despair"
                item_name = filename.replace("item_", "")
                
                # Load image
                img = cv2.imread(str(icon_path))
                if img is None:
                    continue
                
                self.item_database[filename] = img
                self.item_info[filename] = {
                    "item_name": item_name,
                    "path": str(icon_path)
                }
                
            except Exception as e:
                logger.debug(f"Error loading icon {icon_path}: {e}")
        
        logger.info(f"Loaded {len(self.item_database)} item icons")
        print(f"✓ Loaded {len(self.item_database)} item icons")
    
    def _precompute_features(self) -> None:
        """Pre-compute ORB features, center crops, and histograms for all item icons."""
        for filename, img in self.item_database.items():
            try:
                # ORB features
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                keypoints, descriptors = self.orb.detectAndCompute(gray, None)
                self.item_features[filename] = (keypoints, descriptors)
                
                # Center crop (60% of image - more aggressive to match query preprocessing)
                # This ensures reference and query crops compare similar icon regions
                h, w = img.shape[:2]
                margin_x = int(w * 0.2)  # 20% margin each side = 60% center
                margin_y = int(h * 0.2)
                center_crop = img[margin_y:h-margin_y, margin_x:w-margin_x]
                self.item_center_crops[filename] = center_crop
                
                # HSV histogram for color matching - USE CENTER CROP for histogram
                # This avoids the icon border affecting color distribution
                hsv = cv2.cvtColor(center_crop, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
                self.item_histograms[filename] = hist
                
            except Exception as e:
                logger.debug(f"Error computing features for {filename}: {e}")
                self.item_features[filename] = (None, None)
                self.item_center_crops[filename] = img
                self.item_histograms[filename] = None
    
    def _is_empty_slot(self, query_img: np.ndarray) -> bool:
        """
        Detect if an item slot is empty using multiple methods.
        
        Empty slots typically have:
        - Low color variance (mostly uniform dark/gray)
        - Low brightness overall
        - Few edges or features
        - Mostly blue/gray tones (UI background)
        
        Args:
            query_img: Image of item slot from screenshot
            
        Returns:
            True if slot appears empty, False otherwise
        """
        try:
            h, w = query_img.shape[:2]
            
            # Method 1: Check mean brightness
            gray = cv2.cvtColor(query_img, cv2.COLOR_BGR2GRAY)
            mean_brightness = np.mean(gray)
            
            # Very dark slots are empty
            if mean_brightness < 25:
                return True
            
            # Method 2: Check color variance
            std_brightness = np.std(gray)
            if std_brightness < 15:  # Very uniform = likely empty
                return True
            
            # Method 3: Check edge content (empty slots have few edges)
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = np.count_nonzero(edges) / edges.size
            if edge_ratio < 0.02:  # Less than 2% edges = likely empty
                return True
            
            # Method 4: Check dominant color (empty slots are bluish/grayish)
            # Get the center region to avoid frame
            margin = max(2, min(h, w) // 5)
            center = query_img[margin:h-margin, margin:w-margin]
            if center.size > 0:
                hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
                mean_hue = np.mean(hsv[:, :, 0])
                mean_sat = np.mean(hsv[:, :, 1])
                mean_val = np.mean(hsv[:, :, 2])
                
                # Empty slots: low saturation, low value, often blueish hue (100-130)
                if mean_sat < 30 and mean_val < 60:
                    return True
                if mean_sat < 50 and mean_val < 40:
                    return True
            
            # Method 5: Compare with template if we have an empty reference
            if "item_EMPTY" in self.item_database:
                empty_template = self.item_database["item_EMPTY"]
                empty_resized = cv2.resize(empty_template, (w, h), interpolation=cv2.INTER_AREA)
                
                # Calculate similarity to empty template
                diff = cv2.absdiff(query_img, empty_resized)
                diff_score = np.mean(diff)
                if diff_score < 25:  # Very similar to empty template
                    return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error in empty slot detection: {e}")
            return False
    
    # Standard reference size for comparison (icons are 100x100)
    REFERENCE_SIZE = 100
    
    def _resize_to_match(self, img: np.ndarray, target: np.ndarray) -> np.ndarray:
        """Resize image to match target dimensions."""
        return cv2.resize(img, (target.shape[1], target.shape[0]), 
                         interpolation=cv2.INTER_AREA)
    
    def _upscale_query(self, query: np.ndarray) -> np.ndarray:
        """
        Upscale small query images to reference size for better matching.
        Small screenshots (~35px) lose detail when templates are downscaled.
        Instead, upscale the query to match the 100x100 reference icons.
        """
        h, w = query.shape[:2]
        
        # If query is smaller than reference size, upscale it
        if w < self.REFERENCE_SIZE or h < self.REFERENCE_SIZE:
            # Use INTER_CUBIC for better quality upscaling
            upscaled = cv2.resize(query, (self.REFERENCE_SIZE, self.REFERENCE_SIZE), 
                                 interpolation=cv2.INTER_CUBIC)
            return upscaled
        return query
    
    def _preprocess_query(self, query: np.ndarray) -> np.ndarray:
        """
        Preprocess query image from screenshot.
        Removes UI frame by center-cropping and enhances for matching.
        Uses 20% margins to remove borders that affect color analysis.
        """
        h, w = query.shape[:2]
        
        # Center crop to remove item frame/border (keep 60% center - more aggressive)
        # Item icons in screenshots have a colored border that throws off matching
        margin_x = int(w * 0.2)
        margin_y = int(h * 0.2)
        cropped = query[margin_y:h-margin_y, margin_x:w-margin_x]
        
        # If crop is too small, use less aggressive margins
        if cropped.shape[0] < 15 or cropped.shape[1] < 15:
            margin_x = int(w * 0.1)
            margin_y = int(h * 0.1)
            cropped = query[margin_y:h-margin_y, margin_x:w-margin_x]
        
        return cropped
    
    def _normalize_colors(self, img: np.ndarray) -> np.ndarray:
        """Normalize image colors using CLAHE for better matching."""
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        l = clahe.apply(l)
        lab = cv2.merge([l, a, b])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    def _template_match_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """Calculate template matching score with multi-scale and preprocessing."""
        try:
            best_score = 0.0
            
            # Try multiple preprocessing variants
            for preprocess in ['none', 'normalize', 'equalize']:
                # Resize template to query size (not vice versa - preserve query details)
                template_resized = cv2.resize(template, (query.shape[1], query.shape[0]), 
                                             interpolation=cv2.INTER_AREA)
                
                query_proc = query.copy()
                template_proc = template_resized.copy()
                
                if preprocess == 'normalize':
                    query_proc = self._normalize_colors(query_proc)
                    template_proc = self._normalize_colors(template_proc)
                elif preprocess == 'equalize':
                    query_proc = cv2.cvtColor(query_proc, cv2.COLOR_BGR2GRAY)
                    template_proc = cv2.cvtColor(template_proc, cv2.COLOR_BGR2GRAY)
                    query_proc = cv2.equalizeHist(query_proc)
                    template_proc = cv2.equalizeHist(template_proc)
                
                # Convert to grayscale if not already
                if len(query_proc.shape) == 3:
                    query_gray = cv2.cvtColor(query_proc, cv2.COLOR_BGR2GRAY)
                    template_gray = cv2.cvtColor(template_proc, cv2.COLOR_BGR2GRAY)
                else:
                    query_gray = query_proc
                    template_gray = template_proc
                
                # Template matching
                result = cv2.matchTemplate(query_gray, template_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                
                best_score = max(best_score, max_val)
            
            return max(0.0, best_score)
        except Exception:
            return 0.0
    
    def _histogram_match_score(self, query: np.ndarray, template_hist: np.ndarray) -> float:
        """Calculate histogram comparison score using center-cropped query."""
        try:
            if template_hist is None:
                return 0.0
            
            # Center crop query to match how template histograms were computed
            query_cropped = self._preprocess_query(query)
            
            # Calculate histogram for cropped query
            hsv = cv2.cvtColor(query_cropped, cv2.COLOR_BGR2HSV)
            query_hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
            cv2.normalize(query_hist, query_hist, 0, 1, cv2.NORM_MINMAX)
            
            # Compare histograms using correlation
            score = cv2.compareHist(query_hist, template_hist, cv2.HISTCMP_CORREL)
            
            return max(0.0, score)
        except Exception:
            return 0.0
    
    def _orb_match_score(self, query: np.ndarray, template_features: Tuple) -> float:
        """Calculate ORB feature matching score."""
        try:
            keypoints, descriptors = template_features
            if descriptors is None:
                return 0.0
            
            # Detect features in query
            query_gray = cv2.cvtColor(query, cv2.COLOR_BGR2GRAY)
            query_kp, query_desc = self.orb.detectAndCompute(query_gray, None)
            
            if query_desc is None or len(query_desc) < 2:
                return 0.0
            
            # Match features
            matches = self.bf_matcher.knnMatch(query_desc, descriptors, k=2)
            
            # Apply Lowe's ratio test
            good_matches = []
            for m_n in matches:
                if len(m_n) == 2:
                    m, n = m_n
                    if m.distance < 0.75 * n.distance:
                        good_matches.append(m)
            
            # Score based on ratio of good matches
            if len(query_desc) == 0:
                return 0.0
            
            score = len(good_matches) / max(len(query_desc), len(descriptors))
            return min(1.0, score * 2)  # Scale up, cap at 1.0
            
        except Exception:
            return 0.0
    
    def _center_crop_match_score(self, query: np.ndarray, template_center: np.ndarray) -> float:
        """Calculate match score using center crops only."""
        try:
            # Get center crop of query
            h, w = query.shape[:2]
            margin_x = int(w * 0.1)
            margin_y = int(h * 0.1)
            query_center = query[margin_y:h-margin_y, margin_x:w-margin_x]
            
            # Resize and compare
            query_resized = self._resize_to_match(query_center, template_center)
            
            query_gray = cv2.cvtColor(query_resized, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template_center, cv2.COLOR_BGR2GRAY)
            
            result = cv2.matchTemplate(query_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            
            return max(0.0, max_val)
        except Exception:
            return 0.0
    
    def _color_match_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """Calculate color-based matching score using mean colors of center regions."""
        try:
            # Use center crops to avoid border colors affecting the comparison
            query_center = self._preprocess_query(query)
            
            h, w = template.shape[:2]
            margin_x = int(w * 0.2)
            margin_y = int(h * 0.2)
            template_center = template[margin_y:h-margin_y, margin_x:w-margin_x]
            
            # Resize template center to match query center
            template_resized = cv2.resize(template_center, 
                                         (query_center.shape[1], query_center.shape[0]))
            
            # Compare mean colors in LAB space
            query_lab = cv2.cvtColor(query_center, cv2.COLOR_BGR2LAB)
            template_lab = cv2.cvtColor(template_resized, cv2.COLOR_BGR2LAB)
            
            query_mean = np.mean(query_lab, axis=(0, 1))
            template_mean = np.mean(template_lab, axis=(0, 1))
            
            # Euclidean distance in LAB space
            distance = np.linalg.norm(query_mean - template_mean)
            
            # Convert distance to similarity score
            score = max(0.0, 1.0 - (distance / 100.0))
            
            return score
        except Exception:
            return 0.0
    
    def _edge_match_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """Calculate edge-based matching score - robust to color differences."""
        try:
            # Resize template to query size
            template_resized = cv2.resize(template, (query.shape[1], query.shape[0]))
            
            # Convert to grayscale
            query_gray = cv2.cvtColor(query, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template_resized, cv2.COLOR_BGR2GRAY)
            
            # Apply Gaussian blur to reduce noise
            query_blur = cv2.GaussianBlur(query_gray, (3, 3), 0)
            template_blur = cv2.GaussianBlur(template_gray, (3, 3), 0)
            
            # Edge detection
            query_edges = cv2.Canny(query_blur, 30, 100)
            template_edges = cv2.Canny(template_blur, 30, 100)
            
            # Template match on edges
            result = cv2.matchTemplate(query_edges, template_edges, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            
            return max(0.0, max_val)
        except Exception:
            return 0.0
    
    def _ssim_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """Calculate SSIM (Structural Similarity Index) score."""
        try:
            # Resize template to query size
            template_resized = cv2.resize(template, (query.shape[1], query.shape[0]))
            
            # Convert to grayscale
            query_gray = cv2.cvtColor(query, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template_resized, cv2.COLOR_BGR2GRAY)
            
            # Calculate SSIM manually (simplified version)
            c1 = 6.5025  # (0.01 * 255)^2
            c2 = 58.5225  # (0.03 * 255)^2
            
            query_f = query_gray.astype(np.float64)
            template_f = template_gray.astype(np.float64)
            
            mu1 = cv2.GaussianBlur(query_f, (11, 11), 1.5)
            mu2 = cv2.GaussianBlur(template_f, (11, 11), 1.5)
            
            mu1_sq = mu1 * mu1
            mu2_sq = mu2 * mu2
            mu1_mu2 = mu1 * mu2
            
            sigma1_sq = cv2.GaussianBlur(query_f * query_f, (11, 11), 1.5) - mu1_sq
            sigma2_sq = cv2.GaussianBlur(template_f * template_f, (11, 11), 1.5) - mu2_sq
            sigma12 = cv2.GaussianBlur(query_f * template_f, (11, 11), 1.5) - mu1_mu2
            
            ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / \
                       ((mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2))
            
            return float(np.mean(ssim_map))
        except Exception:
            return 0.0
    
    def match_item(self, query_img: np.ndarray, top_n: int = 3) -> List[ItemMatchResult]:
        """
        Match a query image against the item database.
        
        Args:
            query_img: Image of item slot from screenshot
            top_n: Number of top matches to return
            
        Returns:
            List of ItemMatchResult sorted by confidence (highest first)
        """
        if query_img is None or query_img.size == 0:
            return []
        
        # Check if slot is empty using multiple methods
        if self._is_empty_slot(query_img):
            # Return special "EMPTY" result
            return [ItemMatchResult(
                item_name="EMPTY",
                filename="item_EMPTY",
                confidence=0.95,
                method_scores={"empty_detection": 0.95}
            )]
        
        # IMPORTANT: Upscale small query images to reference size
        # Screenshot crops are ~35x35px, but icons are 100x100px
        # Matching works better when we upscale query than downscale template
        query_img = self._upscale_query(query_img)
        
        results = []
        
        for filename in self.item_database:
            template = self.item_database[filename]
            
            # Calculate scores using multiple methods
            scores = {}
            
            # Template matching (multi-scale, multi-preprocess)
            scores['template'] = self._template_match_score(query_img, template)
            
            # Histogram matching
            scores['histogram'] = self._histogram_match_score(query_img, self.item_histograms[filename])
            
            # ORB feature matching
            scores['orb'] = self._orb_match_score(query_img, self.item_features[filename])
            
            # Center crop matching
            scores['center'] = self._center_crop_match_score(query_img, self.item_center_crops[filename])
            
            # Color matching
            scores['color'] = self._color_match_score(query_img, template)
            
            # Edge-based matching (robust to color differences)
            scores['edge'] = self._edge_match_score(query_img, template)
            
            # SSIM structural similarity
            scores['ssim'] = self._ssim_score(query_img, template)
            
            # Weighted ensemble score
            # Increased histogram weight - it's very discriminating for similar-colored items
            # Reduced template/ssim - they often match wrong items with similar shapes
            weights = {
                'template': 0.15,     # Reduced - too generic
                'histogram': 0.25,    # Increased - very discriminating
                'orb': 0.05,
                'center': 0.10,       # Reduced
                'color': 0.15,        # Increased - good for overall color
                'edge': 0.15,
                'ssim': 0.15
            }
            
            confidence = sum(scores[k] * weights[k] for k in weights)
            
            # Boost confidence if multiple methods agree
            high_scores = sum(1 for s in scores.values() if s > 0.35)
            if high_scores >= 4:
                confidence *= 1.2
            elif high_scores >= 3:
                confidence *= 1.1
            
            # Additional boost if edge matching is strong (shape similarity)
            if scores['edge'] > 0.5:
                confidence *= 1.1
            
            confidence = min(1.0, confidence)
            
            results.append(ItemMatchResult(
                item_name=self.item_info[filename]['item_name'],
                filename=filename,
                confidence=confidence,
                method_scores=scores
            ))
        
        # Sort by confidence
        results.sort(key=lambda x: x.confidence, reverse=True)
        
        return results[:top_n]
    
    def match_all_slots(self, slot_images: List[np.ndarray], confidence_threshold: float = 0.15) -> List[Optional[ItemMatchResult]]:
        """
        Match all item slots from a player row.
        
        Args:
            slot_images: List of 6 item slot images
            confidence_threshold: Minimum confidence to accept a match (default 0.15)
            
        Returns:
            List of best match for each slot (None if empty or not in database)
        """
        results = []
        
        for i, slot_img in enumerate(slot_images):
            if slot_img is None or slot_img.size == 0:
                results.append(None)
                continue
            
            # Check if slot is empty (very dark)
            gray = cv2.cvtColor(slot_img, cv2.COLOR_BGR2GRAY)
            if np.mean(gray) < 20:
                results.append(None)
                continue
            
            matches = self.match_item(slot_img)
            
            if matches and matches[0].confidence > confidence_threshold:
                match = matches[0]
                match.slot_index = i + 1
                results.append(match)
            else:
                # Item exists but not in database
                results.append(None)
        
        return results


def test_item_matching(screenshot_path: str, output_dir: str = "output"):
    """
    Test item matching on a screenshot.
    
    Args:
        screenshot_path: Path to screenshot image
        output_dir: Directory to save debug output
    """
    import yaml
    from pathlib import Path
    
    print("=" * 70)
    print("Item Matcher Test")
    print("=" * 70)
    
    # Load screenshot
    img = cv2.imread(screenshot_path)
    if img is None:
        print(f"❌ Could not load image: {screenshot_path}")
        return
    
    h, w = img.shape[:2]
    print(f"✓ Loaded screenshot: {w}x{h}")
    
    # Load column mapping
    config_path = Path("config/column_mapping.yaml")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Initialize matcher
    matcher = ItemMatcher()
    
    # Get row regions
    row_region = config['rows']['row_region']
    y_start = int(h * row_region['y_start_pct'])
    y_end = int(h * row_region['y_end_pct'])
    row_height = (y_end - y_start) // 5
    
    # Item columns
    item_columns = ['item1', 'item2', 'item3', 'item4', 'item5', 'item6']
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Debug image
    debug_img = img.copy()
    
    all_results = []
    
    # Process each player row
    for row_idx in range(5):
        row_y_start = y_start + (row_idx * row_height)
        row_y_end = row_y_start + row_height
        
        print(f"\n{'='*50}")
        print(f"Player {row_idx + 1}")
        print(f"{'='*50}")
        
        slot_images = []
        
        # Extract each item slot
        for col_idx, col_name in enumerate(item_columns):
            col_config = config['columns'][col_name]
            
            x_start = int(w * col_config['x_start_pct'])
            x_end = int(w * col_config['x_end_pct'])
            y_offset = int(row_height * col_config['y_offset_pct'])
            cell_height = int(row_height * col_config['height_pct'])
            
            cell_y_start = row_y_start + y_offset
            cell_y_end = cell_y_start + cell_height
            
            # Crop item slot
            slot_img = img[cell_y_start:cell_y_end, x_start:x_end]
            slot_images.append(slot_img)
            
            # Draw rectangle on debug image
            cv2.rectangle(debug_img, (x_start, cell_y_start), (x_end, cell_y_end), (0, 255, 0), 2)
            
            # Save individual slot image
            slot_filename = f"player{row_idx+1}_slot{col_idx+1}.png"
            cv2.imwrite(str(output_path / slot_filename), slot_img)
        
        # Match all slots for this player
        matches = matcher.match_all_slots(slot_images)
        
        player_items = []
        for slot_idx, match in enumerate(matches):
            if match:
                print(f"  Slot {slot_idx + 1}: {match.item_name} ({match.confidence:.1%})")
                player_items.append({
                    'slot': slot_idx + 1,
                    'item': match.item_name,
                    'confidence': match.confidence,
                    'scores': match.method_scores
                })
            else:
                print(f"  Slot {slot_idx + 1}: (empty or unknown)")
                player_items.append({'slot': slot_idx + 1, 'item': None})
        
        all_results.append({
            'player': row_idx + 1,
            'items': player_items
        })
    
    # Save debug image
    debug_path = output_path / "item_detection_debug.png"
    cv2.imwrite(str(debug_path), debug_img)
    print(f"\n✓ Debug image saved: {debug_path}")
    
    # Save results JSON
    results_path = output_path / "item_detection_results.json"
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"✓ Results saved: {results_path}")
    
    print("\n" + "=" * 70)
    print("✅ Item detection test complete!")
    print("=" * 70)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        screenshot = sys.argv[1]
    else:
        screenshot = "tests/fixtures/sample_screenshot.png"
    
    test_item_matching(screenshot)
