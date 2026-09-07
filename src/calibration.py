from dataclasses import dataclass
from typing import Union, Dict, Any

try:
    from src.coin_detector import CoinDetectionResult
except ImportError:
    CoinDetectionResult = Any

INDIAN_5_RUPEE_COIN_DIAMETER_MM = 21.9

@dataclass
class CalibrationResult:
    pixels_per_mm: float
    mm_per_pixel: float
    coin_pixel_diameter: float
    is_calibrated: bool
    message: str

def compute_calibration(coin_result: Union[CoinDetectionResult, Dict[str, Any], float]) -> CalibrationResult:
    pixel_diameter = 0.0
    
    if isinstance(coin_result, float):
        pixel_diameter = coin_result
    elif isinstance(coin_result, dict):
        pixel_diameter = coin_result.get('pixel_diameter', 0.0)
        if not coin_result.get('detected', True) and pixel_diameter <= 0:
            return CalibrationResult(0.0, 0.0, 0.0, False, "Calibration failed: Coin not detected.")
    else:
        try:
            if not getattr(coin_result, 'detected', True):
                return CalibrationResult(0.0, 0.0, 0.0, False, "Calibration failed: Coin not detected.")
            pixel_diameter = getattr(coin_result, 'pixel_diameter', 0.0)
        except Exception:
            pass

    if pixel_diameter <= 0:
        return CalibrationResult(0.0, 0.0, 0.0, False, "Calibration failed: Invalid coin pixel diameter.")
        
    pixels_per_mm = pixel_diameter / INDIAN_5_RUPEE_COIN_DIAMETER_MM
    mm_per_pixel = INDIAN_5_RUPEE_COIN_DIAMETER_MM / pixel_diameter
    
    return CalibrationResult(
        pixels_per_mm=pixels_per_mm,
        mm_per_pixel=mm_per_pixel,
        coin_pixel_diameter=pixel_diameter,
        is_calibrated=True,
        message="Calibration successful."
    )

def pixels_to_mm(px: float, pixels_per_mm: float) -> float:
    if pixels_per_mm <= 0:
        return 0.0
    return px / pixels_per_mm

def mm_to_pixels(mm: float, pixels_per_mm: float) -> float:
    if pixels_per_mm <= 0:
        return 0.0
    return mm * pixels_per_mm
