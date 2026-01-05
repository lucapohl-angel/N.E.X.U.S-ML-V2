"""
Image preprocessor module.

Handles loading, resizing, and preprocessing images for OCR and detection.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Tuple, Optional


def load_image(image_path: str) -> np.ndarray:
    """
    Load an image from disk.
    
    Args:
        image_path: Path to image file
        
    Returns:
        Image as numpy array (BGR format)
        
    Raises:
        FileNotFoundError: If image doesn't exist
        ValueError: If image can't be loaded
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")
    
    return img


def resize_to_reference(img: np.ndarray, 
                       reference_width: int = 1920, 
                       reference_height: int = 1080) -> np.ndarray:
    """
    Resize image to reference resolution while preserving aspect ratio.
    
    Args:
        img: Input image
        reference_width: Target width
        reference_height: Target height
        
    Returns:
        Resized image
    """
    height, width = img.shape[:2]
    
    # If already at reference resolution, return as-is
    if width == reference_width and height == reference_height:
        return img
    
    # Calculate aspect ratios
    img_aspect = width / height
    ref_aspect = reference_width / reference_height
    
    # Determine scaling
    if abs(img_aspect - ref_aspect) < 0.01:  # Aspect ratios match
        # Simple resize
        return cv2.resize(img, (reference_width, reference_height), 
                         interpolation=cv2.INTER_CUBIC)
    else:
        # Aspect ratio mismatch - fit to reference
        # This shouldn't happen for game screenshots, but handle gracefully
        scale = min(reference_width / width, reference_height / height)
        new_width = int(width * scale)
        new_height = int(height * scale)
        return cv2.resize(img, (new_width, new_height), 
                         interpolation=cv2.INTER_CUBIC)


def convert_to_grayscale(img: np.ndarray) -> np.ndarray:
    """
    Convert image to grayscale.
    
    Args:
        img: Input image (BGR or already grayscale)
        
    Returns:
        Grayscale image
    """
    if len(img.shape) == 2:
        # Already grayscale
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def denoise(img: np.ndarray, method: str = "bilateral") -> np.ndarray:
    """
    Apply denoising filter.
    
    Args:
        img: Input image
        method: Denoising method ('bilateral', 'gaussian', 'median')
        
    Returns:
        Denoised image
    """
    if method == "bilateral":
        return cv2.bilateralFilter(img, d=5, sigmaColor=75, sigmaSpace=75)
    elif method == "gaussian":
        return cv2.GaussianBlur(img, (5, 5), 0)
    elif method == "median":
        return cv2.medianBlur(img, 5)
    else:
        return img


def enhance_contrast(img: np.ndarray, 
                     clip_limit: float = 2.0, 
                     tile_grid_size: Tuple[int, int] = (8, 8)) -> np.ndarray:
    """
    Enhance contrast using CLAHE (Contrast Limited Adaptive Histogram Equalization).
    
    Args:
        img: Input grayscale image
        clip_limit: Threshold for contrast limiting
        tile_grid_size: Size of grid for histogram equalization
        
    Returns:
        Contrast-enhanced image
    """
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
    return clahe.apply(img)


def binarize(img: np.ndarray, 
             method: str = "adaptive", 
             block_size: int = 11, 
             c: int = 2) -> np.ndarray:
    """
    Binarize image for OCR.
    
    Args:
        img: Input grayscale image
        method: Binarization method ('adaptive', 'otsu', 'simple')
        block_size: Block size for adaptive threshold (must be odd)
        c: Constant subtracted from mean
        
    Returns:
        Binary image
    """
    if method == "adaptive":
        return cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, block_size, c
        )
    elif method == "otsu":
        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary
    elif method == "simple":
        _, binary = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
        return binary
    else:
        return img


def load_and_normalize(image_path: str, 
                      reference_width: int = 1920, 
                      reference_height: int = 1080) -> np.ndarray:
    """
    Complete preprocessing pipeline: load, resize, denoise, enhance.
    
    This is the main entry point for image preprocessing.
    
    Args:
        image_path: Path to screenshot
        reference_width: Target width
        reference_height: Target height
        
    Returns:
        Preprocessed image ready for detection
    """
    # Load
    img = load_image(image_path)
    
    # Resize to reference resolution
    img = resize_to_reference(img, reference_width, reference_height)
    
    # Keep in color for now (needed for hero matching)
    # Individual column crops will be converted to grayscale as needed
    
    return img


def prepare_for_ocr(img: np.ndarray, enlarge: bool = True) -> np.ndarray:
    """
    Prepare a cropped region for OCR.
    
    Args:
        img: Cropped region (can be color or grayscale)
        enlarge: Whether to enlarge small text (improves OCR accuracy)
        
    Returns:
        OCR-ready image
    """
    # Convert to grayscale if needed
    if len(img.shape) == 3:
        img = convert_to_grayscale(img)
    
    # Enlarge for better OCR
    if enlarge:
        scale_factor = 2.0
        new_width = int(img.shape[1] * scale_factor)
        new_height = int(img.shape[0] * scale_factor)
        img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
    
    # Denoise
    img = denoise(img, method="bilateral")
    
    # Enhance contrast
    img = enhance_contrast(img)
    
    # Binarize
    img = binarize(img, method="adaptive")
    
    return img


if __name__ == "__main__":
    # Test preprocessing
    import sys
    if len(sys.argv) < 2:
        print("Usage: python preprocessor.py <image_path>")
        sys.exit(1)
    
    img_path = sys.argv[1]
    print(f"Loading: {img_path}")
    
    img = load_and_normalize(img_path)
    print(f"Normalized size: {img.shape[1]}x{img.shape[0]}")
    
    # Save preprocessed version
    output_path = "output/preprocessed.png"
    Path("output").mkdir(exist_ok=True)
    cv2.imwrite(output_path, img)
    print(f"Saved to: {output_path}")
