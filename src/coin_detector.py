import cv2
import numpy as np
from dataclasses import dataclass
from typing import Union, Tuple, Optional
from PIL import Image
import os

@dataclass
class CoinDetectionResult:
    detected: bool
    center: Optional[Tuple[int, int]]
    radius: float
    pixel_diameter: float
    confidence: float
    annotated_image: Optional[np.ndarray]
    message: str

def load_image(image_input) -> np.ndarray:
    if isinstance(image_input, str):
        if not os.path.exists(image_input):
            raise ValueError(f"Image path does not exist: {image_input}")
        img = cv2.imread(image_input)
        if img is None:
            raise ValueError("Failed to load image from path")
        return img
    elif isinstance(image_input, Image.Image):
        return cv2.cvtColor(np.array(image_input), cv2.COLOR_RGB2BGR)
    elif isinstance(image_input, np.ndarray):
        return image_input.copy()
    else:
        raise ValueError("Unsupported image input type")

def detect_coin(image_input, dp=1.0, minDist=100, param1=50, param2=30, minRadius=20, maxRadius=300) -> CoinDetectionResult:
    try:
        img = load_image(image_input)
    except Exception as e:
        return CoinDetectionResult(False, None, 0.0, 0.0, 0.0, None, str(e))
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    cl_gray = clahe.apply(gray)
    
    # Blurring
    blurred = cv2.medianBlur(cl_gray, 5)
    blurred = cv2.GaussianBlur(blurred, (5, 5), 0)
    
    # Multi-pass HoughCircles
    best_circles = None
    for p2 in range(param2, 10, -5):
        circles = cv2.HoughCircles(
            blurred, 
            cv2.HOUGH_GRADIENT, 
            dp=dp, 
            minDist=minDist, 
            param1=param1, 
            param2=p2, 
            minRadius=minRadius, 
            maxRadius=maxRadius
        )
        if circles is not None:
            best_circles = circles[0]
            break
            
    if best_circles is None:
        return CoinDetectionResult(False, None, 0.0, 0.0, 0.0, img, "No circles detected.")
        
    best_candidate = None
    best_score = -1
    
    edges = cv2.Canny(blurred, param1 // 2, param1)
    
    for circle in best_circles:
        x, y, r = map(float, circle)
        if r <= 0:
            continue
            
        mask = np.zeros_like(gray)
        cv2.circle(mask, (int(x), int(y)), int(r), 255, 2)
        edge_overlap = cv2.bitwise_and(edges, mask)
        
        circumference = 2 * np.pi * r
        edge_pixels = np.count_nonzero(edge_overlap)
        
        score = edge_pixels / circumference
        
        if score > best_score:
            best_score = score
            best_candidate = (int(x), int(y), r)
            
    if best_candidate is None or best_score < 0.5:
        return CoinDetectionResult(False, None, 0.0, 0.0, 0.0, img, "No valid coin candidates found.")
        
    x, y, r = best_candidate
    confidence = min(1.0, best_score)
    pixel_diameter = 2.0 * r
    
    annotated = img.copy()
    cv2.circle(annotated, (x, y), int(r), (0, 255, 0), 2)
    cv2.drawMarker(annotated, (x, y), (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=10, thickness=2)
    cv2.putText(annotated, f"D: {pixel_diameter:.1f}px", (x - 40, y - int(r) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
    
    return CoinDetectionResult(
        detected=True,
        center=(x, y),
        radius=float(r),
        pixel_diameter=float(pixel_diameter),
        confidence=float(confidence),
        annotated_image=annotated,
        message="Coin detected successfully."
    )
