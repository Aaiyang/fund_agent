# 操作证据

- get_portfolio_snapshot：完整同账户范围账本；缺失市值不填零。未登记现金不表示现金为零。
- get_fund_snapshot / get_fund_analysis_data：公开表现与观察风险；未复权净值变化不是含分红总回报。
- get_fund_managers / get_fund_holdings：经理团队及季度披露，不是实时穿透。
- get_fund_sectors → get_sector_market：真实板块代码与实际报价日期，不能直接归因基金收益。
- get_market_events → identify_event_portfolio_links：有界事件及历史披露关联，不证明未来方向。
- 金额情景仅由 app.analytics.allocation 计算。新资金进入、赎回离开基金资产桶；转换、费用、现金总资产没有被建模。
- 图表引用只能复制服务端生成的 JSON；禁止URL、脚本、序列、身份字段和模型推测成本。
