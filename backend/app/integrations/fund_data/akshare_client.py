"""AKShare 导入隔离.

akshare 导入很慢，在某些环境里还会直接失败；沿用 cache.py 的做法，在模块加载
时导入一次并用可用性标记兜住，缺库时应用照样能启动.
"""

try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on environment
    ak = None  # pyright: ignore[reportAssignmentType]
    AKSHARE_AVAILABLE = False

__all__ = ["AKSHARE_AVAILABLE", "ak"]
