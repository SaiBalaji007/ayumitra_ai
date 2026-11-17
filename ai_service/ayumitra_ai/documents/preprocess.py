"""
Image clean-up for OCR of phone photos and scans (prescriptions, reports).

enhance(): grayscale -> denoise -> contrast (CLAHE) -> sharpen -> deskew -> upscale small images.
blur_score(): variance of the Laplacian; low values mean a blurry photo.

Used only as a second attempt: OCR runs on the original first and the enhanced image is kept only if
it reads with higher confidence, so a clean image is never made worse.
"""

from __future__ import annotations

import numpy as np

BLURRY_BELOW = 60.0  # Laplacian variance; typical sharp phone photos of paper are well above 100


def _cv2():
    import cv2  # opencv-python (installed with rapidocr)

    return cv2


def blur_score(image: np.ndarray) -> float:
    cv2 = _cv2()
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _deskew(gray: np.ndarray) -> np.ndarray:
    cv2 = _cv2()
    inv = cv2.bitwise_not(gray)
    _, bw = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(bw > 0))
    if len(coords) < 200:
        return gray
    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if angle > 45:
        angle -= 90
    if abs(angle) < 0.5 or abs(angle) > 15:  # nothing to fix, or not a skew (rotated page)
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def enhance(image: np.ndarray) -> np.ndarray:
    cv2 = _cv2()
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    h, w = gray.shape
    if max(h, w) < 1600:  # small photos: upscale so strokes are several pixels wide
        f = 1600 / max(h, w)
        gray = cv2.resize(gray, (int(w * f), int(h * f)), interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
    gray = cv2.addWeighted(gray, 1.6, blur, -0.6, 0)  # unsharp mask
    gray = _deskew(gray)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
