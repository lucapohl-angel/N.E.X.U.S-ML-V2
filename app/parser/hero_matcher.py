"""
Hero Portrait Matcher

Uses computer vision techniques to identify heroes from screenshot portraits
by comparing against a database of known hero portraits.

Methods used for high accuracy:
1. Template Matching - Direct pixel comparison with multiple preprocessing
2. Histogram Comparison - Color distribution matching (HSV + LAB)
3. Feature Matching (ORB + SIFT-like) - Keypoint descriptor matching
4. Structural Similarity (SSIM) - Perceptual similarity
5. Edge-based matching - Shape comparison using Canny edges
6. Center-crop matching - Focus on inner portrait, ignore frame

Uses weighted ensemble with confidence boosting for best accuracy.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Default portraits directory
PORTRAITS_DIR = Path("heroes/portraits")


@dataclass
class MatchResult:
    """Result of a hero portrait match."""
    hero_id: int
    hero_name: str
    filename: str
    confidence: float
    method_scores: Dict[str, float]


class HeroMatcher:
    """
    Matches screenshot hero portraits against known hero database.
    
    Uses multiple computer vision techniques and ensemble scoring for accuracy:
    - Template matching with preprocessing variants
    - Histogram comparison (HSV color distribution)
    - ORB feature matching (keypoint descriptors)
    - SSIM structural similarity
    - Center-focused matching (ignore UI frame)
    - Edge-based shape matching
    """
    
    def __init__(self, portraits_dir: Optional[Path] = None):
        """
        Initialize the hero matcher.
        
        Args:
            portraits_dir: Path to directory containing hero portrait images.
                          Expected filename format: hero_XXX_name.png
        """
        self.portraits_dir = portraits_dir or PORTRAITS_DIR
        self.hero_database: Dict[str, np.ndarray] = {}
        self.hero_info: Dict[str, Dict[str, Any]] = {}
        self._load_hero_database()
        
        # Initialize ORB detector for feature matching
        self.orb = cv2.ORB_create(nfeatures=1000, scoreType=cv2.ORB_HARRIS_SCORE)
        self.bf_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        
        # Pre-compute features and variants for all heroes
        self.hero_features: Dict[str, Tuple[Any, Any]] = {}
        self.hero_center_crops: Dict[str, np.ndarray] = {}
        self.hero_edges: Dict[str, np.ndarray] = {}
        self._precompute_features()
    
    def _load_hero_database(self) -> None:
        """Load all hero portraits from the portraits directory."""
        if not self.portraits_dir.exists():
            logger.warning(f"Portraits directory not found: {self.portraits_dir}")
            return
        
        for portrait_path in self.portraits_dir.glob("hero_*.png"):
            try:
                # Parse filename: hero_XXX_name.png
                filename = portrait_path.stem  # e.g., "hero_128_kalea"
                parts = filename.split("_", 2)  # Split into ["hero", "128", "kalea"]
                
                if len(parts) >= 3:
                    hero_id = int(parts[1])
                    hero_name = parts[2].replace("_", " ").title()
                else:
                    continue
                
                # Load image
                img = cv2.imread(str(portrait_path))
                if img is None:
                    continue
                
                self.hero_database[filename] = img
                self.hero_info[filename] = {
                    "hero_id": hero_id,
                    "hero_name": hero_name,
                    "path": str(portrait_path)
                }
                
            except Exception as e:
                logger.debug(f"Error loading portrait {portrait_path}: {e}")
        
        logger.info(f"Loaded {len(self.hero_database)} hero portraits")
    
    def _precompute_features(self) -> None:
        """Pre-compute ORB features, center crops, and edges for all hero portraits."""
        for filename, img in self.hero_database.items():
            try:
                # ORB features
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                keypoints, descriptors = self.orb.detectAndCompute(gray, None)
                self.hero_features[filename] = (keypoints, descriptors)
                
                # Center crop (70% of image, ignore border/frame)
                h, w = img.shape[:2]
                margin_x = int(w * 0.15)
                margin_y = int(h * 0.15)
                center_crop = img[margin_y:h-margin_y, margin_x:w-margin_x]
                self.hero_center_crops[filename] = center_crop
                
                # Edge detection for shape matching
                edges = cv2.Canny(gray, 50, 150)
                self.hero_edges[filename] = edges
                
            except Exception as e:
                logger.debug(f"Error computing features for {filename}: {e}")
                self.hero_features[filename] = (None, None)
                self.hero_center_crops[filename] = img
                self.hero_edges[filename] = np.zeros_like(img[:,:,0]) if len(img.shape) == 3 else np.zeros_like(img)
    
    def _resize_to_match(self, img: np.ndarray, target: np.ndarray) -> np.ndarray:
        """Resize image to match target dimensions."""
        return cv2.resize(img, (target.shape[1], target.shape[0]), 
                         interpolation=cv2.INTER_AREA)
    
    def _preprocess_query(self, query: np.ndarray) -> np.ndarray:
        """
        Preprocess query image from screenshot.
        Removes UI frame by center-cropping and enhances for matching.
        """
        h, w = query.shape[:2]
        
        # Center crop to remove potential UI frame (keep 75% center)
        margin_x = int(w * 0.125)
        margin_y = int(h * 0.125)
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
    
    def _extract_center_region(self, img: np.ndarray, ratio: float = 0.6) -> np.ndarray:
        """Extract center region of image, ignoring borders."""
        h, w = img.shape[:2]
        margin_x = int(w * (1 - ratio) / 2)
        margin_y = int(h * (1 - ratio) / 2)
        return img[margin_y:h-margin_y, margin_x:w-margin_x]
    
    def _apply_circular_mask(self, img: np.ndarray) -> np.ndarray:
        """
        Apply circular mask to focus on the center of the portrait.
        Hero portraits are typically circular in-game.
        """
        h, w = img.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        center = (w // 2, h // 2)
        radius = min(h, w) // 2 - 2
        cv2.circle(mask, center, radius, 255, -1)
        
        # Apply mask
        if len(img.shape) == 3:
            masked = cv2.bitwise_and(img, img, mask=mask)
        else:
            masked = cv2.bitwise_and(img, img, mask=mask)
        
        return masked

    def _template_match_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """
        Calculate template matching score using multiple methods.
        Tries center-focused matching and full matching, takes best.
        
        Args:
            query: Query image (from screenshot)
            template: Template image (from database)
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            scores = []
            
            # Method 1: Full image template matching
            query_resized = self._resize_to_match(query, template)
            query_gray = cv2.cvtColor(query_resized, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            
            result = cv2.matchTemplate(query_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            scores.append((max_val + 1) / 2)
            
            # Method 2: Center-focused matching (ignore UI frame)
            query_center = self._extract_center_region(query, 0.7)
            template_center = self._extract_center_region(template, 0.7)
            
            if query_center.size > 0 and template_center.size > 0:
                query_c_resized = self._resize_to_match(query_center, template_center)
                query_c_gray = cv2.cvtColor(query_c_resized, cv2.COLOR_BGR2GRAY)
                template_c_gray = cv2.cvtColor(template_center, cv2.COLOR_BGR2GRAY)
                
                result_c = cv2.matchTemplate(query_c_gray, template_c_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val_c, _, _ = cv2.minMaxLoc(result_c)
                scores.append((max_val_c + 1) / 2)
            
            # Method 3: Color-normalized matching
            query_norm = self._normalize_colors(query_resized)
            template_norm = self._normalize_colors(template)
            query_norm_gray = cv2.cvtColor(query_norm, cv2.COLOR_BGR2GRAY)
            template_norm_gray = cv2.cvtColor(template_norm, cv2.COLOR_BGR2GRAY)
            
            result_n = cv2.matchTemplate(query_norm_gray, template_norm_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val_n, _, _ = cv2.minMaxLoc(result_n)
            scores.append((max_val_n + 1) / 2)
            
            # Return weighted combination (prefer center match)
            if len(scores) >= 3:
                return scores[0] * 0.25 + scores[1] * 0.50 + scores[2] * 0.25
            return max(scores) if scores else 0.0
            
        except Exception as e:
            logger.debug(f"Template match error: {e}")
            return 0.0
    
    def _histogram_match_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """
        Calculate histogram comparison score using multiple color spaces.
        Compares color distribution in HSV and LAB spaces.
        
        Args:
            query: Query image (from screenshot)
            template: Template image (from database)
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            # Resize and extract center regions
            query_center = self._extract_center_region(query, 0.7)
            template_center = self._extract_center_region(template, 0.7)
            query_resized = self._resize_to_match(query_center, template_center)
            
            scores = []
            
            # HSV histogram comparison (H and S channels)
            query_hsv = cv2.cvtColor(query_resized, cv2.COLOR_BGR2HSV)
            template_hsv = cv2.cvtColor(template_center, cv2.COLOR_BGR2HSV)
            
            hist_size_hs = [50, 60]
            h_ranges = [0, 180]
            s_ranges = [0, 256]
            
            query_hist_hs = cv2.calcHist([query_hsv], [0, 1], None, hist_size_hs, h_ranges + s_ranges)
            template_hist_hs = cv2.calcHist([template_hsv], [0, 1], None, hist_size_hs, h_ranges + s_ranges)
            
            cv2.normalize(query_hist_hs, query_hist_hs, 0, 1, cv2.NORM_MINMAX)
            cv2.normalize(template_hist_hs, template_hist_hs, 0, 1, cv2.NORM_MINMAX)
            
            score_hsv = cv2.compareHist(query_hist_hs, template_hist_hs, cv2.HISTCMP_CORREL)
            scores.append((score_hsv + 1) / 2)
            
            # LAB histogram comparison (a and b channels for color)
            query_lab = cv2.cvtColor(query_resized, cv2.COLOR_BGR2LAB)
            template_lab = cv2.cvtColor(template_center, cv2.COLOR_BGR2LAB)
            
            hist_size_ab = [32, 32]
            a_ranges = [0, 256]
            b_ranges = [0, 256]
            
            query_hist_ab = cv2.calcHist([query_lab], [1, 2], None, hist_size_ab, a_ranges + b_ranges)
            template_hist_ab = cv2.calcHist([template_lab], [1, 2], None, hist_size_ab, a_ranges + b_ranges)
            
            cv2.normalize(query_hist_ab, query_hist_ab, 0, 1, cv2.NORM_MINMAX)
            cv2.normalize(template_hist_ab, template_hist_ab, 0, 1, cv2.NORM_MINMAX)
            
            score_lab = cv2.compareHist(query_hist_ab, template_hist_ab, cv2.HISTCMP_CORREL)
            scores.append((score_lab + 1) / 2)
            
            # BGR histogram (3D)
            hist_size_bgr = [16, 16, 16]
            bgr_ranges = [0, 256, 0, 256, 0, 256]
            
            query_hist_bgr = cv2.calcHist([query_resized], [0, 1, 2], None, hist_size_bgr, bgr_ranges)
            template_hist_bgr = cv2.calcHist([template_center], [0, 1, 2], None, hist_size_bgr, bgr_ranges)
            
            cv2.normalize(query_hist_bgr, query_hist_bgr, 0, 1, cv2.NORM_MINMAX)
            cv2.normalize(template_hist_bgr, template_hist_bgr, 0, 1, cv2.NORM_MINMAX)
            
            score_bgr = cv2.compareHist(query_hist_bgr, template_hist_bgr, cv2.HISTCMP_CORREL)
            scores.append((score_bgr + 1) / 2)
            
            # Weighted average (LAB is often more perceptually accurate)
            return scores[0] * 0.35 + scores[1] * 0.40 + scores[2] * 0.25
            
        except Exception as e:
            logger.debug(f"Histogram match error: {e}")
            return 0.0
    
    def _feature_match_score(self, query: np.ndarray, template_filename: str) -> float:
        """
        Calculate ORB feature matching score with ratio test.
        Compares keypoint descriptors between images.
        
        Args:
            query: Query image (from screenshot)
            template_filename: Filename of template in database
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            # Get pre-computed template features
            template_kp, template_desc = self.hero_features.get(template_filename, (None, None))
            if template_desc is None or len(template_desc) < 5:
                return 0.0
            
            # Resize query to template size
            template = self.hero_database[template_filename]
            query_resized = self._resize_to_match(query, template)
            
            # Compute query features
            query_gray = cv2.cvtColor(query_resized, cv2.COLOR_BGR2GRAY)
            # Enhance contrast for better feature detection
            query_gray = cv2.equalizeHist(query_gray)
            
            query_kp, query_desc = self.orb.detectAndCompute(query_gray, None)
            
            if query_desc is None or len(query_desc) < 5:
                return 0.0
            
            # Use knnMatch with ratio test (Lowe's ratio test)
            bf = cv2.BFMatcher(cv2.NORM_HAMMING)
            matches = bf.knnMatch(query_desc, template_desc, k=2)
            
            # Apply ratio test
            good_matches = []
            for match_pair in matches:
                if len(match_pair) == 2:
                    m, n = match_pair
                    if m.distance < 0.75 * n.distance:
                        good_matches.append(m)
            
            if len(good_matches) == 0:
                return 0.0
            
            # Score based on ratio of good matches and quality
            max_possible = min(len(query_desc), len(template_desc))
            match_ratio = len(good_matches) / max_possible if max_possible > 0 else 0.0
            
            # Also consider match quality (lower distance = better)
            if good_matches:
                avg_distance = np.mean([m.distance for m in good_matches])
                quality_score = max(0, 1 - avg_distance / 100)  # Normalize distance
            else:
                quality_score = 0.0
            
            # Combine match ratio and quality
            score = match_ratio * 0.6 + quality_score * 0.4
            
            return min(score, 1.0)
            
        except Exception as e:
            logger.debug(f"Feature match error: {e}")
            return 0.0
    
    def _ssim_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """
        Calculate Structural Similarity Index (SSIM).
        Measures perceptual similarity between images.
        Focuses on center region to ignore UI frame.
        
        Args:
            query: Query image (from screenshot)
            template: Template image (from database)
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            # Extract center regions to focus on hero, not frame
            query_center = self._extract_center_region(query, 0.7)
            template_center = self._extract_center_region(template, 0.7)
            
            # Resize query to template size
            query_resized = self._resize_to_match(query_center, template_center)
            
            # Convert to grayscale
            query_gray = cv2.cvtColor(query_resized, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template_center, cv2.COLOR_BGR2GRAY)
            
            # Calculate SSIM manually (since we might not have skimage)
            C1 = (0.01 * 255) ** 2
            C2 = (0.03 * 255) ** 2
            
            query_f = query_gray.astype(np.float64)
            template_f = template_gray.astype(np.float64)
            
            mu1 = cv2.GaussianBlur(query_f, (11, 11), 1.5)
            mu2 = cv2.GaussianBlur(template_f, (11, 11), 1.5)
            
            mu1_sq = mu1 ** 2
            mu2_sq = mu2 ** 2
            mu1_mu2 = mu1 * mu2
            
            sigma1_sq = cv2.GaussianBlur(query_f ** 2, (11, 11), 1.5) - mu1_sq
            sigma2_sq = cv2.GaussianBlur(template_f ** 2, (11, 11), 1.5) - mu2_sq
            sigma12 = cv2.GaussianBlur(query_f * template_f, (11, 11), 1.5) - mu1_mu2
            
            ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / \
                       ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))
            
            score = float(np.mean(ssim_map))
            
            # Normalize to 0-1 (SSIM can be -1 to 1)
            return (score + 1) / 2
            
        except Exception as e:
            logger.debug(f"SSIM error: {e}")
            return 0.0
    
    def _edge_match_score(self, query: np.ndarray, template_filename: str) -> float:
        """
        Calculate edge-based shape matching score.
        Compares Canny edge maps between images.
        
        Args:
            query: Query image (from screenshot)
            template_filename: Filename of template in database
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            template = self.hero_database[template_filename]
            template_edges = self.hero_edges.get(template_filename)
            
            if template_edges is None:
                return 0.0
            
            # Resize query and compute edges
            query_resized = self._resize_to_match(query, template)
            query_gray = cv2.cvtColor(query_resized, cv2.COLOR_BGR2GRAY)
            query_edges = cv2.Canny(query_gray, 50, 150)
            
            # Resize template edges to match
            template_edges_resized = cv2.resize(template_edges, 
                                                (query_edges.shape[1], query_edges.shape[0]))
            
            # Compare edge maps using normalized correlation
            result = cv2.matchTemplate(query_edges, template_edges_resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            
            return (max_val + 1) / 2
            
        except Exception as e:
            logger.debug(f"Edge match error: {e}")
            return 0.0
    
    def _hu_moments_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """
        Calculate Hu Moments similarity score.
        Hu Moments are shape descriptors invariant to translation, scale, and rotation.
        
        Args:
            query: Query image (from screenshot)
            template: Template image (from database)
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            # Extract center and resize
            query_center = self._extract_center_region(query, 0.7)
            template_center = self._extract_center_region(template, 0.7)
            query_resized = self._resize_to_match(query_center, template_center)
            
            # Convert to grayscale
            query_gray = cv2.cvtColor(query_resized, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template_center, cv2.COLOR_BGR2GRAY)
            
            # Calculate Hu Moments
            query_moments = cv2.HuMoments(cv2.moments(query_gray)).flatten()
            template_moments = cv2.HuMoments(cv2.moments(template_gray)).flatten()
            
            # Log transform to handle scale differences
            query_hu = -np.sign(query_moments) * np.log10(np.abs(query_moments) + 1e-10)
            template_hu = -np.sign(template_moments) * np.log10(np.abs(template_moments) + 1e-10)
            
            # Calculate distance (lower = more similar)
            distance = np.sum(np.abs(query_hu - template_hu))
            
            # Convert to similarity score (empirically, distances typically range 0-50)
            score = max(0, 1 - distance / 50)
            
            return score
            
        except Exception as e:
            logger.debug(f"Hu moments error: {e}")
            return 0.0
    
    def _color_moments_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """
        Calculate color moments similarity.
        Compares mean, std, and skewness of color channels.
        
        Args:
            query: Query image (from screenshot)
            template: Template image (from database)
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            # Extract center and resize
            query_center = self._extract_center_region(query, 0.7)
            template_center = self._extract_center_region(template, 0.7)
            query_resized = self._resize_to_match(query_center, template_center)
            
            def calc_color_moments(img):
                """Calculate color moments for an image."""
                # Convert to HSV for better color representation
                hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                moments = []
                for channel in cv2.split(hsv):
                    ch = channel.flatten().astype(np.float64)
                    # Mean
                    mean = np.mean(ch)
                    # Standard deviation
                    std = np.std(ch)
                    # Skewness
                    skew = np.mean(((ch - mean) / (std + 1e-10)) ** 3)
                    moments.extend([mean / 255, std / 128, skew / 10])  # Normalize
                return np.array(moments)
            
            query_moments = calc_color_moments(query_resized)
            template_moments = calc_color_moments(template_center)
            
            # Euclidean distance
            distance = np.linalg.norm(query_moments - template_moments)
            
            # Convert to similarity (distances typically 0-5)
            score = max(0, 1 - distance / 5)
            
            return score
            
        except Exception as e:
            logger.debug(f"Color moments error: {e}")
            return 0.0
    
    def _phash_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """
        Calculate perceptual hash (pHash) similarity.
        Resistant to minor changes in color, brightness, and scale.
        
        Args:
            query: Query image (from screenshot)
            template: Template image (from database)
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            def calc_phash(img, hash_size=8):
                """Calculate perceptual hash of image."""
                # Resize to hash_size x hash_size
                resized = cv2.resize(img, (hash_size + 1, hash_size))
                gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else resized
                
                # Calculate DCT
                dct = cv2.dct(np.float32(gray))
                dct_low = dct[:hash_size, :hash_size]
                
                # Calculate median and create hash
                median = np.median(dct_low)
                return (dct_low > median).flatten()
            
            # Extract center regions
            query_center = self._extract_center_region(query, 0.7)
            template_center = self._extract_center_region(template, 0.7)
            
            query_hash = calc_phash(query_center)
            template_hash = calc_phash(template_center)
            
            # Hamming distance
            hamming_dist = np.sum(query_hash != template_hash)
            
            # Convert to similarity (64 bits total for 8x8 hash)
            score = 1 - hamming_dist / 64
            
            return score
            
        except Exception as e:
            logger.debug(f"pHash error: {e}")
            return 0.0
    
    def _contour_match_score(self, query: np.ndarray, template: np.ndarray) -> float:
        """
        Calculate contour-based shape matching score.
        Uses cv2.matchShapes for shape comparison.
        
        Args:
            query: Query image (from screenshot)
            template: Template image (from database)
            
        Returns:
            Score between 0 and 1 (higher = better match)
        """
        try:
            # Extract center and resize
            query_center = self._extract_center_region(query, 0.7)
            template_center = self._extract_center_region(template, 0.7)
            query_resized = self._resize_to_match(query_center, template_center)
            
            # Convert to grayscale and threshold
            query_gray = cv2.cvtColor(query_resized, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template_center, cv2.COLOR_BGR2GRAY)
            
            _, query_thresh = cv2.threshold(query_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            _, template_thresh = cv2.threshold(template_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Find contours
            query_contours, _ = cv2.findContours(query_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            template_contours, _ = cv2.findContours(template_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not query_contours or not template_contours:
                return 0.5
            
            # Get largest contours
            query_contour = max(query_contours, key=cv2.contourArea)
            template_contour = max(template_contours, key=cv2.contourArea)
            
            # Match shapes (I1 method - returns 0 for identical)
            match_value = cv2.matchShapes(query_contour, template_contour, cv2.CONTOURS_MATCH_I1, 0)
            
            # Convert to similarity (values typically 0-1, but can be higher)
            score = max(0, 1 - match_value)
            
            return score
            
        except Exception as e:
            logger.debug(f"Contour match error: {e}")
            return 0.0

    def match_hero(self, query_img: np.ndarray, top_n: int = 5) -> Optional[MatchResult]:
        """
        Match a hero portrait from screenshot against the database.
        
        Uses 9 different methods for maximum accuracy:
        1. Template matching (multi-variant)
        2. Histogram comparison (HSV + LAB + BGR)
        3. ORB feature matching with ratio test
        4. SSIM structural similarity (center-focused)
        5. Edge-based shape matching
        6. Hu Moments shape matching
        7. Color moments comparison
        8. Perceptual hash (pHash)
        9. Contour shape matching
        
        Args:
            query_img: Hero portrait cropped from screenshot
            top_n: Number of top candidates to consider
            
        Returns:
            MatchResult with best matching hero, or None if no match found
        """
        if len(self.hero_database) == 0:
            logger.warning("Hero database is empty")
            return None
        
        if query_img is None or query_img.size == 0:
            logger.warning("Query image is empty")
            return None
        
        # Calculate scores for each hero using all methods
        all_scores: Dict[str, Dict[str, float]] = {}
        
        for filename, template in self.hero_database.items():
            scores = {
                "template": self._template_match_score(query_img, template),
                "histogram": self._histogram_match_score(query_img, template),
                "features": self._feature_match_score(query_img, filename),
                "ssim": self._ssim_score(query_img, template),
                "edges": self._edge_match_score(query_img, filename),
                "hu_moments": self._hu_moments_score(query_img, template),
                "color_moments": self._color_moments_score(query_img, template),
                "phash": self._phash_score(query_img, template),
                "contour": self._contour_match_score(query_img, template)
            }
            all_scores[filename] = scores
        
        # Use Borda count ranking + strong signal boosting
        # Each method ranks all heroes, points based on rank position
        n_heroes = len(all_scores)
        borda_scores: Dict[str, float] = {fn: 0.0 for fn in all_scores}
        
        # Rebalanced weights - trust color/structure more than features
        method_weights = {
            "template": 1.5,        # Direct pixel match - reliable
            "histogram": 1.2,       # Color distribution
            "features": 1.0,        # ORB features - can be unreliable
            "ssim": 1.5,            # Structural similarity - very reliable
            "edges": 0.5,
            "hu_moments": 0.5,
            "color_moments": 1.5,   # Color stats - very reliable for heroes
            "phash": 1.2,           # Perceptual hash
            "contour": 0.8
        }
        
        # Removed over-reliance on features - let all methods vote fairly
        
        for method, weight in method_weights.items():
            # Sort heroes by this method's score
            sorted_heroes = sorted(all_scores.keys(), 
                                  key=lambda f: all_scores[f][method],
                                  reverse=True)
            
            # Check for strong signal (large margin between #1 and #2)
            if len(sorted_heroes) >= 2:
                top1_score = all_scores[sorted_heroes[0]][method]
                top2_score = all_scores[sorted_heroes[1]][method]
                margin = top1_score - top2_score
                
                # If margin > 0.05, boost weight for this method's winner
                strong_signal_boost = 1.0 + min(margin * 5, 0.5)  # Up to 50% boost
            else:
                strong_signal_boost = 1.0
            
            # Assign Borda points (n-1 for first, n-2 for second, etc.)
            for rank, filename in enumerate(sorted_heroes):
                points = (n_heroes - 1 - rank) / (n_heroes - 1)  # Normalize to 0-1
                
                # Apply strong signal boost only to top 3
                if rank < 3:
                    points *= strong_signal_boost
                
                borda_scores[filename] += points * weight
        
        # Normalize borda scores
        max_borda = max(borda_scores.values())
        for fn in borda_scores:
            borda_scores[fn] /= max_borda
        
        # Sort by borda score
        ranked = sorted(borda_scores.items(), key=lambda x: x[1], reverse=True)
        
        if not ranked:
            return None
        
        # Get the best match
        best_filename, best_score = ranked[0]
        hero_info = self.hero_info[best_filename]
        
        # Log top candidates for debugging
        logger.debug(f"Top 3 matches: {ranked[:3]}")
        
        return MatchResult(
            hero_id=hero_info["hero_id"],
            hero_name=hero_info["hero_name"],
            filename=best_filename,
            confidence=best_score,
            method_scores=all_scores[best_filename]
        )
        
        # Log top candidates for debugging
        logger.debug(f"Top 3 matches: {ranked[:3]}")
        
        return MatchResult(
            hero_id=hero_info["hero_id"],
            hero_name=hero_info["hero_name"],
            filename=best_filename,
            confidence=best_score,
            method_scores=all_scores[best_filename]
        )
    
    def match_hero_voting(self, query_img: np.ndarray) -> Optional[MatchResult]:
        """
        Match hero using voting across methods.
        Each method votes for its top candidate, best voted hero wins.
        Uses top-3 voting per method for robustness.
        
        Args:
            query_img: Hero portrait cropped from screenshot
            
        Returns:
            MatchResult with best matching hero
        """
        if len(self.hero_database) == 0:
            return None
        
        if query_img is None or query_img.size == 0:
            return None
        
        # Calculate all scores first (all 9 methods)
        all_scores: Dict[str, Dict[str, float]] = {}
        
        for filename, template in self.hero_database.items():
            all_scores[filename] = {
                "template": self._template_match_score(query_img, template),
                "histogram": self._histogram_match_score(query_img, template),
                "features": self._feature_match_score(query_img, filename),
                "ssim": self._ssim_score(query_img, template),
                "edges": self._edge_match_score(query_img, filename),
                "hu_moments": self._hu_moments_score(query_img, template),
                "color_moments": self._color_moments_score(query_img, template),
                "phash": self._phash_score(query_img, template),
                "contour": self._contour_match_score(query_img, template)
            }
        
        # Check for strong feature signal FIRST
        # If Features method has a clear winner, trust it heavily
        features_ranked = sorted(all_scores.keys(), 
                                key=lambda f: all_scores[f]["features"],
                                reverse=True)
        features_top1 = all_scores[features_ranked[0]]["features"]
        features_top2 = all_scores[features_ranked[1]]["features"] if len(features_ranked) > 1 else 0
        
        # If top feature match is >0.25 and has significant margin (>0.04), trust it
        if features_top1 > 0.25 and (features_top1 - features_top2) > 0.04:
            logger.debug(f"Strong feature signal (voting): {features_ranked[0]} with score {features_top1:.3f}")
            # Return feature winner directly
            hero_info = self.hero_info[features_ranked[0]]
            return MatchResult(
                hero_id=hero_info["hero_id"],
                hero_name=hero_info["hero_name"],
                filename=features_ranked[0],
                confidence=features_top1,
                method_scores=all_scores[features_ranked[0]]
            )
        
        # Weighted voting: each method gives points to its top-5 candidates
        # Points: 1st place = 5, 2nd place = 4, etc.
        method_weights = {
            "template": 1.0,
            "histogram": 1.2,       # Colors are important for heroes
            "features": 2.0,        # Good for unique visual patterns
            "ssim": 1.0,
            "edges": 0.6,
            "hu_moments": 0.7,
            "color_moments": 0.9,
            "phash": 1.0,
            "contour": 0.6
        }
        
        votes: Dict[str, float] = {}
        vote_scores: Dict[str, List[float]] = {}
        
        for method in method_weights.keys():
            # Sort heroes by this method's score
            sorted_by_method = sorted(all_scores.keys(), 
                                     key=lambda f: all_scores[f][method], 
                                     reverse=True)
            
            # Give weighted votes to top 5 (expanded from top 3)
            weight = method_weights[method]
            for rank, filename in enumerate(sorted_by_method[:5]):
                points = (5 - rank) * weight  # 5, 4, 3, 2, 1 points scaled by method weight
                votes[filename] = votes.get(filename, 0) + points
                
                if filename not in vote_scores:
                    vote_scores[filename] = []
                vote_scores[filename].append(all_scores[filename][method])
        
        # Find hero with most votes (tie-break by average score)
        best_filename = max(votes.keys(), 
                          key=lambda f: (votes[f], np.mean(vote_scores.get(f, [0]))))
        
        hero_info = self.hero_info[best_filename]
        
        # Calculate confidence based on votes and scores
        max_possible_votes = sum((5 + 4 + 3 + 2 + 1) * w for w in method_weights.values())
        vote_ratio = votes[best_filename] / max_possible_votes
        avg_score = np.mean([all_scores[best_filename][m] for m in method_weights.keys()])
        confidence = vote_ratio * 0.4 + avg_score * 0.6
        
        logger.debug(f"Voting results (top 5): {sorted(votes.items(), key=lambda x: x[1], reverse=True)[:5]}")
        logger.debug(f"Winner: {best_filename} with {votes[best_filename]:.1f} votes")
        
        return MatchResult(
            hero_id=hero_info["hero_id"],
            hero_name=hero_info["hero_name"],
            filename=best_filename,
            confidence=confidence,
            method_scores=all_scores[best_filename]
        )


# Global instance for convenience
_matcher_instance: Optional[HeroMatcher] = None


def get_hero_matcher(portraits_dir: Optional[Path] = None) -> HeroMatcher:
    """Get or create the global HeroMatcher instance."""
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = HeroMatcher(portraits_dir)
    return _matcher_instance


def match_hero_portrait(img: np.ndarray, use_voting: bool = True) -> Optional[Dict[str, Any]]:
    """
    Convenience function to match a hero portrait.
    
    Args:
        img: Hero portrait cropped from screenshot
        use_voting: If True, use voting method; otherwise use weighted average
        
    Returns:
        Dictionary with hero_id, hero_name, filename, confidence
    """
    matcher = get_hero_matcher()
    
    if use_voting:
        result = matcher.match_hero_voting(img)
    else:
        result = matcher.match_hero(img)
    
    if result is None:
        return None
    
    return {
        "hero_id": result.hero_id,
        "hero_name": result.hero_name,
        "filename": result.filename,
        "confidence": round(result.confidence, 3),
        "method_scores": {k: round(v, 3) for k, v in result.method_scores.items()}
    }
