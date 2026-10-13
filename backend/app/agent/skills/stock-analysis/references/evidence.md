# 股票证据

- get_stock_analysis_data：报价、最近一年复权收盘指标及公司资料摘要。行情失败、历史不足、公司概况缺失分别公开。
- 价格指标由日线代码计算，模型不得制造MACD/KDJ、历史估值分位、盈利增长或量化目标价。
- 市场背景仅覆盖主要A股指数，不可解释港美股整体行情；境外币种与行情时间按来源显示，不套用上海盘中判断。
- get_market_events为有界新闻，若无直接公司事件只能列背景，不能确认涨跌原因。
- research-chart仅含schema_version=1、type=stock_price、symbol。前端取 /markets/{symbol}/quote 和 /history，不执行模型代码。
