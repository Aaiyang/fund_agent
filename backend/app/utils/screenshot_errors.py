"""将持仓 OCR 的内部原因映射成稳定错误码与可展示消息，不暴露路径或异常正文."""


def screenshot_failure_message(error: str | None) -> tuple[str, str]:
    """区分非持仓图、无法读取、未检测到持仓行以及识别服务故障."""
    reason = error or ""
    if "not_holding_screenshot" in reason:
        return (
            "NOT_HOLDING_SCREENSHOT",
            "图片中未识别出基金持仓列表，请上传正确的持仓截图，包含基金名称及持有金额或份额。持仓未更新。",
        )
    if "screenshot_unreadable" in reason:
        return (
            "SCREENSHOT_UNREADABLE",
            "图片文字为空或无法清晰识别，请上传清晰、完整的基金持仓截图，包含基金名称及持有金额或份额。持仓未更新。",
        )
    if "no_positions_detected" in reason:
        return (
            "NO_HOLDING_ROWS",
            "未识别到可导入的基金持仓行，请上传完整的持仓列表截图，包含基金名称及持有金额或份额。持仓未更新。",
        )
    return "IMPORT_PARSE_FAILED", "持仓截图识别服务暂时失败，请稍后重试；持仓未更新。"
