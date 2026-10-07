"""持仓导入适配层：OCR 流水线、provider、归一化.

导入能力通过 `HoldingImportProvider` 协议与 PortfolioService 解耦（MVP spec 3.7）：
每个 provider 把各自的输入洗成同一份"待确认草稿"，只有用户显式确认才会写进
权威的 `portfolio_position` 表.

本包刻意不 import 任何东西：`screenshot_provider` 要用 `fund_service` 把名称解析
成基金，一旦在本包做包级再导出，service 侧只要从这里导入就会闭合出循环依赖。
要哪个就直接导入哪个子模块.
"""
