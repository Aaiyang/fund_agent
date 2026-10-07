"""联网搜索工具（DuckDuckGo）.

执行网页搜索并返回最多 10 条结果；搜索失败时会把错误信息作为
结果返回，而不是抛出异常。
"""

from langchain_community.tools import DuckDuckGoSearchResults

duckduckgo_search_tool = DuckDuckGoSearchResults(num_results=10, handle_tool_error=True)
# 覆盖为中文描述：这是直接发给 LLM 的工具说明
duckduckgo_search_tool.description = (
    "联网搜索最新资讯、新闻与公开网页内容。仅用于新闻、公开信息和无法通过"
    "业务数据获取的补充信息；基金净值、持仓、行情等结构化数据请使用对应的"
    "业务工具，不要用本工具替代。"
)
