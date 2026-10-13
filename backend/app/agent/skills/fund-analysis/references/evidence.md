# 基金分析证据与输出协议

## 工具能力

| 工具 | 可用事实 | 不能证明 |
| --- | --- | --- |
| get_portfolio / get_positions | 本人账户、市值、成本、成本净值、盈亏和持仓占比 | 当前全市场/穿透暴露、他人持仓、未来收益 |
| get_fund_snapshot | 最新净值与业务日期、类型、公司、经理、规模和Python计算的业绩/风险指标 | 同类排名、经理个人超额、可靠估值分位；指标口径仍需核对 |
| get_fund_analysis_data | 请求一年窗口、实际覆盖、未复权净值变化/回撤、历史高低区间位置、原始日点计算指标及基金图表引用 | 分红复权总回报、估值便宜程度、目标价或完整市场历史 |
| get_fund_managers | 团队区间和个人连续任职段、现任标记、原始链接 | 任职回报或经理能力排名，不把共管回报分给个人 |
| get_fund_holdings | 最近季度前十大、行业权重、较上期变化；可用时有个股最新报价与时间 | 当前全部持仓、历史同期股价、精确收益贡献 |
| get_fund_sectors → get_sector_market | 披露行业/名称主题与真实A股板块目录；板块报价时间 | 单一归属、境外/债基板块、板块涨跌等于基金收益 |
| get_market_context / get_realtime_market | 日线收盘背景 / 最新主要A股指数 | 指数位置等于基金估值、全市场个股涨跌家数或资金流 |
| get_market_events → identify_event_portfolio_links | 有限报道窗口、来源重点/规则标签；与本人持仓的行业/名称/背景线索 | 官方政策已实施、全部新闻覆盖、确定影响方向 |
| get_fund_announcements | 按代码公告/报告索引、来源链接、标题变更线索 | 已读正文、政策生效日期、报告细节 |

比例：持仓收益率/占比与净值变化指标为比值，0.1代表10%；披露权重、个股/板块涨跌通常为百分点，1.2代表1.2%。保留字段语义；不要跨单位相加。snapshot当前业绩/风险也是未复权单位净值计算，不是含分红总回报，且历史指标不自动等于当前一年观察窗指标。

## 数据与归因

- 优先实际nav_date、quote_time、披露日期，不用获取时间冒充业务日期。净值与当前板块报价日期不同就分开说。
- 净值单位、币种和份额类别要一致。单位净值未经分红复权，不可作为投资者总收益：来源[Investor.gov基金分配说明](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/fund-distributions-investor-bulletin)指出分配会使净值降低。这里只借用数学口径，不据此推断中国基金税费。
- 历史表现不证明未来结果；参考[Investor.gov基金基础说明](https://www.investor.gov/introduction-investing/investing-basics/investment-products/mutual-funds-and-exchange-traded-funds-etfs/mutual-funds)。研究模型和情景不是收益保证。
- 只有真实完整时期数据、可比基准和计算服务支持时才陈述超额收益、个人经理贡献或精确归因。否则明确无法量化，不能从已披露权重乘今日涨幅猜过去月收益。
- FOF、债基、货币、QDII、场内ETF要按类型解释。股票前十大不可用不是基金无资产；货币基金单位净值接近常数不等于无收益，QDII还可能有披露和时区滞后。

## fund-chart v2

只复制get_fund_analysis_data返回的chart_code_block，纯JSON引用，不执行代码。

- 栅栏语言fund-chart；只含schema_version=2、type=fund_performance、fund_code六位字符串。
- 不包含points、日期序列、URL、私人成本、身份或可执行表达式。
- 移动端复用基金详情组件，使用现有认证API请求基金详情、净值历史、指数目录与指数历史。区间和基准切换由客户端发起，不需要额外LLM调用。
- 模型研究指标仍由工具在真实日点上计算，保留覆盖日期、缺口和过时提示。图表查询时数据可能比回答更新，客户端显示实际区间和指标日期，不把更新后的图表冒充回答时证据。
- 仅完整闭合且通过严格字段验证的块成为卡片；半截/无效块保持文本。旧v1历史块仍识别，只取基金代码重新查询后端，忽略其嵌入序列。
- 个人成本不由模型提交。详情页可继续传入当前认证用户的真实持仓成本；Agent卡片默认只显示公共业绩与真实指数基准。
- 数据不足、加载失败、基准不可用由组件显示空状态或重试入口，不能伪造曲线。同类平均、排名及总回报没有数据时不补造。

## fund-holdings v1

get_fund_holdings返回holdings_code_block时可逐字嵌入，语言为fund-holdings。固定schema_version=1、type=holdings、source=fund_service，包含fund_code、report_date、items和warnings。每条items仅含stock_code、stock_name与weight；weight为占基金净值的百分点，9.45表示9.45%，不再乘100。最多10条，权重缺失/无效或重复的记录不进入卡片，原研究数据仍保留；没有可用权重则不生成卡片。披露期未知须明示，不把行业配置日期当作股票披露日期。该卡片不是当前用户的私人持仓，不含成本或交易按钮。渲染端只显示经过校验的完整块，无法验证则保留代码文本。

## 最小报告形状

结论与实际范围 → 1持仓现状 → 2潜力与一年图 → 3近期涨跌证据链 → 4三期限条件方案 → 5政策利好/利空条件 → 关键缺口和复核日期。多基金可用并排表，但不要在一个密集表里混淆各基金经理、时期或账户成本。
