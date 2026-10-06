"""估值能力的数据适配层：把「业绩比较基准」这段话读成可计算的结构.

本包只做外部事实的读取与解析，不做任何投资决策：判定与算术在
`app.analytics.valuation` 里，编排与缓存在 `app.services.valuation_service` 里。
"""
