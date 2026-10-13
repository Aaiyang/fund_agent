# 板块证据边界

- get_sector_market：真实目录匹配后的报价；change_pct单位百分点，逐项核对quote_time、stale、error_code。多个候选不是一个板块。
- get_market_context：日线收盘；get_realtime_market：主要A股指数快照，两者不可替代。
- get_market_events：仅已扫描来源范围，不代表没有其他事件；政策报道不是官方实施证明。
- get_fund_sectors：披露行业匹配或名称线索，季度配置不能视为即时暴露。
- 板块历史OHLC、成分股全量、资金流和行业估值暂未接入，禁止生成这些数据或相应图形。
- 卡片只携带已核验sector_code和sector_type，后端重新读取报价。
