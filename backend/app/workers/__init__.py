"""持久化后台任务的任务名常量.

服务层按任务名入队（`broker.kiq(TASK, ...)`），而不是去 import worker 模块：
worker 会 import 服务，直接反向 import 就形成了一个环——
这正是原先的调用点要把 import 藏进函数体内的原因。

本模块必须保持不 import 任何子模块。
"""

FUND_SYNC_TASK = "app.workers.fund_sync:sync_fund_task"
HOT_FUND_SYNC_TASK = "app.workers.fund_sync:sync_hot_funds_task"
SCREENSHOT_IMPORT_TASK = "app.workers.screenshot_import:process_screenshot_import_task"
