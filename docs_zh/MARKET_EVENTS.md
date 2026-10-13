# 市场事件与持仓关联工具

工具集 `v9`，提示词 `fund-agent-v13`。公开事件工具在 `market`，私有持仓关联在 `portfolio`。普通和流式Agent共用注册，重启后端生效，无数据库迁移、额外LLM调用或持仓写入。

## get_market_events

代码请求[财联社电报](https://www.cls.cn/telegraph)，固定参数及公开签名参考 [AKShare原始实现](https://github.com/akfamily/akshare/blob/main/akshare/stock_feature/stock_info.py)。不使用联网搜索或任意URL。网络错误使用Tenacity指数退避，最多两次。

| 参数 | 默认与范围 |
| --- | --- |
| scope | all，可选macro/industry/market |
| lookback_hours | 24，范围1–168小时 |
| keyword | 可选1–80字，仅本地筛选 |
| important_only | true，筛来源A/B重点标记 |
| limit | 20，范围1–30 |
| refresh | false，允许60秒内完整成功缓存 |

最多扫描5页，每页20条。requested_from/to是筛选区间，coverage_from/to是实际报道发布时间窗口，可能远短于请求范围。来源单一、条数有限，不能保证全天、全球或所有重大事件覆盖；秒游标可能漏掉边界同秒条目。page_limit_reached、partial、invalid_count、scanned_count、truncated明确上限、缺页、无效和截断。

每条保留event_id、title、最多240字excerpt、source_url、published_at（Asia/Shanghai）、source_priority、categories、topics、factors。A/B只是来源重点标记。分类是词表规则、仅为研究线索，不验证真实性；发布时间不是发生/生效时间。短英文需要边界，人民银行不按银行行业匹配。

完整成功窗口缓存60秒；部分、无效或失败不缓存。空匹配不代表没有事件，无有效来源报道返回错误。as_of取返回事件最早发布时间，逐条日期与原始fetched_at保留。节假日仍专用get_calendar，本工具不作兜底。

## identify_event_portfolio_links

输入工具1返回的1–5个event_id。account_id可选、必须属于本人，默认全部账户；position_limit默认20、最多50行，按真实市值检查。

公共引用快照与内容指纹12小时有效。共享缓存故障时有最多1000条的进程引用兜底。缺失/过期/不一致返回EVENT_NOT_AVAILABLE，需重新查事件；不接受模型提交用户ID、任意正文或URL。

身份来自认证运行时，持仓服务按用户读取并验证账户归属。金额仅本地排序，公开资讯请求不含身份、持仓、金额或查询词，基金资料请求仅发送公开基金代码。私有关联不缓存、不落库，每次重查本人持仓，保留holdings_checked_at。

| basis | 依据与局限 |
| --- | --- |
| disclosed_industry | 历史披露行业名称匹配，保留行业与披露日期，不证明当前暴露 |
| fund_name_hint | 名称主题匹配，仅为线索 |
| macro_context | 利率、流动性、汇率、贸易、数据、财政背景，具体敏感性未确认 |
| market_context | 市场背景，地区/基准一致性尚未核验 |

不强行将制造业/金融业映射成半导体/银行。最多50条关联，保留总关联数、持仓检查/跳过行数、不可用基金与截断。无匹配或缺资料不代表无影响；不覆盖股票穿透、完整地区、久期、汇率暴露。impact_direction固定unknown，不提供因果证明、方向、收益预测或买卖建议。

例如用户问“近期芯片行业大事与我的持仓有关吗”：先查询报道，再把选定ID交给关联工具；答案附来源、发布时间，区分行业证据、名称线索、背景及缺失证据。

## 验证

tests/test_market_events.py覆盖请求/分页/失败、规则、缓存与引用一致性/期限、账户和用户隔离、私有分析不缓存、缺资料、截断，以及普通/流式真实Agent图连续三轮调用。使用模拟LLM及持仓，不代表生产数据库集成或真实模型服从率。

开发公开源验证获取100条、覆盖约两小时，说明100条不等于全天事件。回答以每次实际窗口为准。
