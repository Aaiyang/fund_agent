"""Optional OCR runtime isolation.

rapidocr pulls in an ONNX Runtime and the PP-OCR weights, which is a heavy
dependency for a deployment that never imports screenshots. Mirroring
akshare_client, it is imported once at module load behind an availability
flag so the app still boots without it.
"""

try:
    from rapidocr import RapidOCR

    OCR_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on environment
    RapidOCR = None  # pyright: ignore[reportAssignmentType]
    OCR_AVAILABLE = False

__all__ = ["OCR_AVAILABLE", "RapidOCR"]
