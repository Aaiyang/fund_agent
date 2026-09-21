"""Durable background task names.

Services enqueue by name (`broker.kiq(TASK, ...)`) instead of importing a worker
module: workers import services, so a direct import back would close a cycle —
that is why the call sites previously hid imports inside functions.

Keep this module free of submodule imports.
"""

FUND_SYNC_TASK = "app.workers.fund_sync:sync_fund_task"
HOT_FUND_SYNC_TASK = "app.workers.fund_sync:sync_hot_funds_task"
SCREENSHOT_IMPORT_TASK = "app.workers.screenshot_import:process_screenshot_import_task"
