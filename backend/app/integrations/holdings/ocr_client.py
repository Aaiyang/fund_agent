"""可选 OCR 运行时的导入隔离.

rapidocr 会拖进 ONNX Runtime 和 PP-OCR 权重，对从不导入截图的部署来说这份依赖
太重。照 akshare_client 的做法，在模块加载时导入一次并用可用性标记兜住，缺库时
应用照样能启动。
"""

try:
    from rapidocr import RapidOCR

    OCR_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on environment
    RapidOCR = None  # pyright: ignore[reportAssignmentType]
    OCR_AVAILABLE = False

__all__ = ["OCR_AVAILABLE", "RapidOCR"]
