"""AKShare import isolation.

akshare is slow to import and hard-fails some environments; mirroring the
cache.py pattern, it is imported once at module load behind an availability
flag so the app still boots when the library is missing.
"""

try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on environment
    ak = None  # pyright: ignore[reportAssignmentType]
    AKSHARE_AVAILABLE = False

__all__ = ["AKSHARE_AVAILABLE", "ak"]
