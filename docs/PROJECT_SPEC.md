# 个人基金管理应用 MVP 需求与技术规范

> 版本：V5
> 当前阶段：MVP / Agent 预留
> 产品定位：个人自选基金 + 个人持仓管理 + 手动/截图导入持仓 + 基金数据展示 + Agent 页面占位

---

## 1. 项目目标

本项目第一阶段目标是实现一个简单、稳定、可持续扩展的个人基金管理应用，优先完成以下闭环：

1. 管理个人自选基金。
2. 管理个人基金持仓。
3. 支持通过手动录入和第三方应用持仓截图识别的方式导入持仓。
4. 展示基金基础信息、净值、涨跌和基础收益数据。
5. 支持 Android、iOS 和 Web 共用一套前端技术体系。
6. 后端基于现有 FastAPI + LangGraph Production Ready Template 扩展。
7. 第一阶段暂不实现正式 Agent 业务能力，但预留独立 Agent 页面、API 路由、LangGraph 基础设施和后续 Tool 接入位置。
8. MVP 基金数据源使用 AKShare，通过 `FundDataProvider` 隔离并落库 PostgreSQL；正式发布前切换到具备商业授权的 Choice 或 iFinD。

当前阶段核心原则：

> 先完成“基金数据 + 自选 + 持仓 + 手动/截图导入 + 基金详情 + 前端展示”的完整闭环，再扩展 Agent、智能分析、RAG、基金筛选和投资决策能力。

---

# 2. 产品信息架构

第一版产品采用四个一级 Tab，并提供基金详情等二级页面。

```text
基金 App
│
├── ① 持有
│   ├── 账户切换
│   ├── 总资产
│   ├── 当日收益
│   ├── 持仓基金列表
│   ├── 持仓收益
│   ├── 导入持仓
│   └── 市场指数简览（可选）
│
├── ② 自选
│   ├── 自选分组
│   ├── 自选基金列表
│   ├── 当日涨跌
│   ├── 关联板块（数据源支持时）
│   ├── 搜索基金
│   └── 添加 / 删除自选
│
├── ③ Agent
│   ├── Agent 页面占位
│   ├── 后续 AI 对话入口
│   ├── 我的持仓上下文入口
│   ├── 我的自选上下文入口
│   └── 后续 Tool Calling 扩展
│
├── ④ 我的
│   ├── 账户管理
│   ├── 持仓来源管理
│   ├── 导入记录
│   ├── 用户信息
│   └── App 设置
│
└── 基金详情
    ├── 基金概览
    ├── 我的持仓数据
    ├── 关联板块
    ├── 业绩走势
    ├── 我的收益
    ├── 修改持仓
    ├── 交易记录
    ├── 添加 / 删除自选
    └── 问 Agent（预留）
```

底部导航建议：

```text
┌─────────┬─────────┬─────────┬─────────┐
│  持有   │  自选   │ Agent   │  我的   │
└─────────┴─────────┴─────────┴─────────┘
```

UI 信息密度和交互逻辑可参考用户提供的基金管理应用截图，但不要求复制其具体视觉样式、图标、配色或品牌元素。

---

# 3. 第一阶段功能范围

## 3.1 用户与认证

需要支持基础用户体系。

### 功能要求

- 用户注册。
- 用户登录。
- 用户退出。
- JWT Access Token / Refresh Token。
- 获取当前用户信息。
- 用户数据隔离。

### 暂不实现

- 社交账号登录。
- 多因素认证。
- 复杂权限系统。
- 机构 / 团队账号。

---

## 3.2 持有 / 我的持仓

“持有”是第一版核心首页之一，用于展示用户真实基金资产。

### 页面结构

顶部支持账户视角：

```text
账户汇总 | 支付宝 | 其他账户 | + 添加账户
```

资产摘要区域：

- 账户资产 / 总资产。
- 当日总收益。
- 累计收益。
- 数据更新时间。

持仓列表建议展示：

- 基金名称。
- 基金代码。
- 当前持有金额。
- 当日收益。
- 当日涨跌幅。
- 关联板块 / 主题（可选）。
- 持有收益。
- 持有收益率。
- 是否已更新。

### 功能要求

- 查看全部账户汇总。
- 切换单个持仓账户。
- 查看当前基金持仓。
- 查看基金持有份额。
- 查看持仓成本。
- 查看当前市值。
- 查看持仓盈亏。
- 查看持仓收益率。
- 查看持仓占比。
- 查看总资产。
- 查看总收益。
- 查看当日收益。
- 支持手工录入持仓。
- 支持手工修改持仓。
- 支持点击持仓基金进入基金详情页。
- 支持手动录入持仓。
- 支持上传第三方应用持仓截图，通过图像识别解析后导入。
- 截图识别结果必须经过用户确认后才能写入正式持仓。

### 持仓核心字段

- user_id。
- account_id。
- source / provider。
- fund_code。
- shares。
- cost_amount。
- average_cost_nav（可选）。
- market_value。
- profit_loss。
- profit_loss_rate。
- daily_profit_loss（可计算）。
- position_ratio（可计算）。
- updated_at。

### 暂不实现

- 真实交易下单。
- 自动调仓。
- 组合优化。
- 复杂税务计算。
- 多币种资产管理。

---

## 3.3 自选基金管理

“自选”用于管理用户关注但不一定持有的基金。

### 页面结构

顶部可提供自选分组：

```text
全部 | CPO | 创新药 | 机器人 | 有色金属 | ...
```

基金列表建议展示：

- 基金名称。
- 基金代码。
- 是否已更新。
- 是否已持有。
- 收藏状态。
- 当日涨跌幅。
- 最新净值。
- 关联板块 / 主题涨跌（如数据源支持）。

### 功能要求

- 搜索基金。
- 添加基金到自选。
- 从自选中删除基金。
- 查看自选基金列表。
- 查看最新净值。
- 查看当日涨跌幅。
- 点击进入基金详情。
- 显示该基金是否同时存在于用户持仓中。
- 支持自选分组。
- 支持基金在分组中的排序。

### 自选分组要求

第一版至少支持：

- 默认分组“全部”。
- 用户创建自定义分组。
- 用户修改分组名称。
- 用户删除自定义分组。
- 将基金加入一个或多个分组。

### 可选增强

- 星级 / 收藏优先级。
- 标签。
- 拖拽排序。

### 暂不实现

- 基金自动推荐。
- 智能排序模型。
- 自选价格 / 收益预警。

---

## 3.4 基金搜索

需要提供统一基金搜索能力。

### 支持查询

- 基金代码。
- 基金完整名称。
- 基金简称。
- 模糊名称。

### 返回信息

- fund_code。
- fund_name。
- fund_type。
- latest_nav。
- nav_date。
- daily_return。
- is_watchlisted。
- is_held。

### 要求

基金实体解析应由 FundService 完成，前端和 Agent 后续均复用同一套搜索接口。

---

## 3.5 基金详情页

基金详情页是“持有”和“自选”的共同二级页面。

### 3.5.1 基金概览

展示：

- 基金名称。
- 基金代码。
- 基金类型。
- 最新净值。
- 净值日期。
- 当日涨跌幅。
- 近 1 月 / 3 月 / 6 月 / 1 年收益。
- 更新时间。

示意：

```text
华泰柏瑞质量成长混合C
011452

当日涨幅              近1年
+0.72%                +114.62%
```

### 3.5.2 我的持仓信息

只有用户实际持有该基金时显示。

建议展示：

```text
持有金额        持有份额        持仓占比
881.99          295.1           53.98%

持有收益        持有收益率      持仓成本
-137.20         -13.46%         3.4537

当日收益        昨日收益        持有天数
+6.34           -8.23           90
```

对应字段：

- market_value。
- shares。
- position_ratio。
- profit_loss。
- profit_loss_rate。
- average_cost_nav。
- daily_profit_loss。
- previous_day_profit_loss（可选）。
- holding_days（可选，可由交易记录计算）。

### 3.5.3 详情 Tab

第一版建议设计三个 Tab：

```text
关联板块 | 业绩走势 | 我的收益
```

#### 关联板块

数据源支持时展示：

- 基金主要关联行业 / 主题。
- 行业 / 主题当日涨跌。
- 简单走势图。

若数据源暂不支持，可先隐藏该 Tab 或显示占位状态。

#### 业绩走势

至少支持时间区间：

```text
1月 | 3月 | 6月 | 1年 | 3年 | 成立以来
```

第一版至少展示：

- 基金净值 / 收益曲线。
- 当前区间收益率。

后续可叠加：

- 基准指数。
- 同类平均。
- 同类排名。

#### 我的收益

用户持有该基金时显示：

- 累计投入金额。
- 当前市值。
- 累计收益。
- 累计收益率。
- 持有天数。
- 用户真实收益曲线（后续）。

### 3.5.4 底部操作栏

建议提供：

```text
修改持仓 | 交易记录 | 问 Agent | 加/删自选
```

第一阶段：

- “修改持仓”正常实现。
- “交易记录”正常实现基础查看。
- “加/删自选”正常实现。
- “问 Agent”保留入口，可跳转到 Agent 占位页，并携带 `fund_code` 上下文。

---

## 3.6 持仓账户管理

用户可以维护多个基金账户。

例如：

- 支付宝。
- 天天基金。
- 银行渠道。
- 手工账户。
- 后续新增的数据源。

### PortfolioAccount 字段建议

- id。
- user_id。
- name。
- source_app（例如支付宝、天天基金、银行、手工账户等，仅作为来源标签）。
- account_type。
- import_mode。
- last_imported_at。
- created_at。
- updated_at。

### 功能要求

- 添加账户。
- 删除账户。
- 修改账户名称。
- 查看账户最近导入状态。
- 手动录入或截图导入持仓。
- 查看最后导入时间。

---

## 3.7 持仓导入：手动录入 + 截图识别

第一阶段不直接接入第三方账户 API，也不保存第三方应用登录凭据。第三方持仓数据通过以下两种方式进入系统：

1. **手动录入**：用户直接填写当前持仓信息。
2. **截图识别导入**：用户上传其他基金应用的持仓截图，系统识别持仓字段并生成待确认结果。

这里使用“导入（Import）”而不是“同步（Sync）”作为领域概念。截图只能代表某一时点的持仓快照，不应被解释为与第三方账户建立了持续、双向或实时同步。

### 核心设计原则

持仓导入能力与 PortfolioService 解耦。统一定义导入接口：

```python
class HoldingImportProvider(Protocol):
    async def parse(
        self,
        payload: HoldingImportPayload,
    ) -> HoldingImportDraft:
        ...
```

第一版提供两个 Provider：

```text
HoldingImportProvider
│
├── ManualImportProvider
│   └── 用户手工填写持仓
│
└── ScreenshotImportProvider
    └── 第三方应用截图识别
```

Provider 只负责把不同输入转换为统一的“待确认持仓草稿”，不直接写入正式持仓表。

### 统一导入流程

```text
手动输入 / 第三方应用截图
          ↓
HoldingImportProvider
          ↓
HoldingImportDraft
          ↓
Fund Resolver
基金名称 / 基金代码标准化与匹配
          ↓
Normalizer + Validator
          ↓
用户确认页面
          ↓
Confirm Import
          ↓
PortfolioService
          ↓
PortfolioRepository
          ↓
PostgreSQL
```

所有导入必须经过“解析 → 预览 → 用户确认 → 正式写入”四个阶段。禁止截图识别完成后直接修改用户持仓。

### 3.7.1 手动录入

手动录入至少支持：

- 选择或创建持仓账户。
- 搜索基金并确定标准基金代码。
- 输入持有金额。
- 输入持有份额（可选，但建议支持）。
- 输入持仓成本 / 平均成本净值（可选）。
- 输入累计持有收益或收益率（可选，用于外部数据迁移）。
- 设置数据日期。
- 编辑已有持仓。
- 删除已有持仓。

若用户只提供部分字段，系统允许保存“部分持仓快照”，但不得推导无法可靠计算的数据。

例如只有“持有金额 + 持有收益”时，不应自动伪造交易记录或持有份额。

### 3.7.2 截图识别导入

用户可以从支付宝、天天基金、银行或其他应用截取持仓页面并上传。

建议交互：

```text
选择账户
   ↓
上传一张或多张截图
   ↓
识别中
   ↓
展示识别结果
   ↓
用户检查 / 修正
   ↓
确认导入
   ↓
更新持仓
```

截图识别模块至少尝试提取：

- 基金名称。
- 基金代码（截图中存在时）。
- 持有金额。
- 持有份额。
- 持仓成本 / 平均成本净值。
- 持有收益。
- 持有收益率。
- 当日收益（可选）。
- 截图中的数据日期（可识别时）。
- 来源应用名称（可识别或由用户选择）。

截图中的字段并不总是完整，因此以上字段均应允许为空，并由后续 Fund Resolver 和 Validator 判断可用性。

### 截图识别组件拆分

不要将截图识别逻辑直接写入 `ScreenshotImportProvider`。建议再抽象一层：

```text
ScreenshotImportProvider
          ↓
ScreenshotPositionExtractor
          ↓
Vision / OCR Adapter
          ↓
RawExtractedPosition[]
          ↓
Fund Resolver
          ↓
NormalizedImportPosition[]
```

其中：

- `ScreenshotPositionExtractor` 负责从图片抽取结构化字段。
- `OCR Engine` 负责本地文字识别，输出带坐标与置信度的文字块（PP-OCR 模型跑在 ONNX Runtime 上，图片不出本机）。
- `页面结构解析` 读截图自己的表头（如「金额/昨日收益」「持有收益/率」）来定每列含义，并划掉状态栏、页签、资讯卡片、底部导航这些不是持仓的区域。
- `持仓行聚类` 按纵坐标把文字块归成行，判定哪些行是持仓，把名称下方的标签（金选、定投等）留在元数据里而不是并进基金名。
- `字段解析` 按列内上下位置把数字映射成金额/昨日收益/持有收益/收益率；读不出来的填 null，不补 0。
- `Fund Resolver` 根据名称、代码和候选结果匹配系统中的标准基金实体。
- `Normalizer` 负责金额、百分比、日期、小数格式等统一。
- `Validator` 负责检测异常字段、缺失字段和冲突。

识别引擎用本地 OCR，不调用云端视觉大模型：截图里是他全部的真实持仓，不出机器优先；而且版面解析是确定性的几何判断，同一张图每次结果一致，不会出现把「昨日收益」读成「持有收益」这类采样抖动。缺 OCR 依赖时该路径明确报错，不静默返回空列表。

### 识别置信度与人工确认

每个识别字段或基金匹配结果应允许携带 `confidence`：

```json
{
  "fund_name": "华泰柏瑞质量成长混合C",
  "fund_code": "011452",
  "market_value": 881.99,
  "profit_loss": -137.20,
  "confidence": 0.96
}
```

前端确认页应重点标识：

- 低置信度基金匹配。
- 无法识别基金代码。
- 金额格式异常。
- 同一基金出现多次。
- 与现有持仓差异过大的记录。
- 缺失关键字段的记录。

用户可以在确认前修改识别结果。

### 多截图导入

截图可能只能显示部分持仓，因此第一版应允许一次导入多张截图。

系统需处理：

- 多张截图中的重复基金。
- 同一基金跨截图重复出现。
- 截图顺序无关。
- 部分截图识别失败时，其余结果仍可继续确认。

建议通过 `image_hash` 或导入批次内的标准基金代码进行去重。

### 持仓更新语义

截图导入属于“当前持仓快照导入”，不是交易流水同步。

因此必须遵循：

1. 用户确认后的数据用于更新当前 `portfolio_positions`。
2. 不根据截图自动生成 BUY / SELL 交易。
3. 不根据两次截图之间的差额推测用户发生了什么交易。
4. 若需要精确计算资金加权收益、真实交易收益或持有天数，应由未来的交易记录功能提供数据。
5. 截图导入造成的持仓覆盖，可记录一条 `IMPORT_ADJUSTMENT` 审计记录，但它不是实际交易记录。

### 导入冲突处理

当待导入基金已经存在于当前账户时，确认页必须显示：

```text
当前持仓        本次识别        导入后
¥800.00   →    ¥881.99    →    ¥881.99
```

默认采用“确认后覆盖当前快照”的策略。

第一版不做复杂自动合并。用户必须能看到差异并决定：

- 更新该持仓。
- 跳过该持仓。
- 手工修改后更新。

### 导入状态

持仓导入建议具有以下状态：

```text
UPLOADED
   ↓
PARSING
   ↓
REVIEW_REQUIRED
   ↓
CONFIRMED
   ↓
APPLIED
```

异常状态：

```text
PARSE_FAILED
CANCELLED
```

### 截图隐私和安全要求

持仓截图属于敏感财务数据，第一版必须满足：

- 全程 HTTPS 传输。
- 不在普通应用日志中记录图片内容或完整识别文本。
- 原图默认只作为临时解析文件使用。
- 识别和确认完成后默认删除原图，除非后续明确需要用户授权保存。
- 若使用对象存储，应使用私有 Bucket、短时签名访问和生命周期自动删除。
- 不把截图原图写入 PostgreSQL。
- 识别服务调用应避免传递与持仓解析无关的用户个人信息。
- 后端需要限制文件类型、文件大小和图片数量。

### 第一版明确不做

- 支付宝账号授权登录。
- 天天基金账号授权登录。
- 银行账号授权登录。
- 抓取第三方 App 登录态。
- 保存第三方 App 用户名或密码。
- 后台定时自动同步第三方账户。
- 根据截图自动推断真实交易流水。

### 后续预留

如未来获得官方或稳定的第三方账户 API，可新增：

```text
ApiHoldingImportProvider
```

但仍应输出相同的 `HoldingImportDraft`，确保 PortfolioService 无需理解具体数据来源。

---

## 3.8 交易记录

第一版不提供交易执行，但需要保留基础交易记录模型，以支持真实持仓收益计算和手工修正。

### 支持类型

- BUY / 买入。
- SELL / 卖出。
- DIVIDEND / 分红（可选）。
- IMPORT_ADJUSTMENT / 导入修正。
- MANUAL_ADJUSTMENT / 手工修正。

### 字段建议

- id。
- user_id。
- account_id。
- fund_code。
- transaction_type。
- trade_date。
- shares。
- nav / price。
- amount。
- fee（可选）。
- source。
- external_transaction_id（可选）。
- created_at。

### 第一版要求

- 查看某基金交易记录。
- 查看某账户交易记录。
- 手工新增 / 修正记录可后置；至少支持由持仓导入模块写入审计型调整记录。

---

# 4. Agent 第一阶段处理方式

第一阶段不实现正式 Agent 业务能力。

## 4.1 前端保留独立 Agent Tab

路径建议：

```text
/(tabs)/agent.tsx
```

页面第一版可以只展示：

```text
AI 基金助手

Agent 功能开发中

后续将支持：
- 分析我的持仓
- 查看我的自选
- 分析指定基金
- 基金对比
```

若从基金详情页点击“问 Agent”，可以通过路由参数携带：

```text
fund_code=011452
```

当前阶段只展示上下文提示，不执行真实 Agent 推理。

## 4.2 后端需要保留

- 原有 LangGraph 基础设施。
- LangGraph Checkpointer。
- 会话模型。
- LLM Service。
- Tool 注册机制。
- Langfuse / tracing。
- Agent API 扩展位置。

建议预留：

```text
POST /api/v1/agent/chat
```

第一阶段可以不对外启用，或返回明确的 `not_implemented` 状态。

## 4.3 第一阶段明确不实现

- 基金分析 Agent。
- 持仓分析 Agent。
- 基金比较 Agent。
- 基金筛选 Agent。
- 新闻 / 研报 Agent。
- RAG。
- Multi-Agent。
- 投资建议。
- 自动调仓。

## 4.4 后续架构约束

Agent 后续必须通过 Tool / Service 访问业务数据：

```text
Agent
  ↓
Tool
  ↓
Domain Service
  ↓
Repository
  ↓
Database / External Provider
```

禁止 Agent 直接访问数据库。

---

# 5. 基金基础数据

系统需要具备统一基金基础数据能力。

## 5.1 基础基金数据

- 基金代码。
- 基金名称。
- 基金类型。
- 基金公司。
- 基金经理。
- 成立日期。
- 最新净值。
- 累计净值。
- 净值日期。
- 历史净值。

## 5.2 第一阶段指标

所有确定性指标由后端 Python 计算，不由 LLM 计算。

包括：

- 单日涨跌幅。
- 近 1 月收益率。
- 近 3 月收益率。
- 近 6 月收益率。
- 近 1 年收益率。
- 最大回撤（可作为详情增强项）。
- 波动率（可作为详情增强项）。

## 5.3 数据接口原则

Agent、API 和业务代码不得直接绑定具体基金数据提供商。

统一通过：

```text
FundDataProvider
      ↓
FundDataGateway
      ↓
Normalizer
      ↓
FundRepository / FundService
```

实现数据源解耦。

## 5.4 基金数据源技术决策

当前项目的数据源策略正式确定为：

### MVP 阶段

- 使用 **AKShare** 作为主要基金外部数据采集源。
- 使用 **PostgreSQL** 建立项目自己的基金基础数据库和历史净值数据库。
- App 不直接访问 AKShare，也不直接访问其他第三方基金数据接口。
- FastAPI API 层不得直接调用 AKShare。
- 所有外部基金数据必须经过统一的 `FundDataProvider` 接口进入系统。
- AKShare 定位为 MVP / 开发阶段数据源，不作为未来正式商业版本唯一事实来源。

### 正式发布阶段

正式公开发布或商业化前，评估并采购具备明确商业授权的数据源。优先评估：

- **Choice**。
- **iFinD**。

根据以下因素选择其中一个作为生产主数据源：

- 商业授权范围。
- 基金数据覆盖范围。
- API 稳定性。
- 历史净值完整性。
- 基金经理、持仓、规模等扩展数据覆盖。
- 调用限额。
- 成本。
- SLA / 技术支持。

如后续有更高等级机构数据需求，可继续增加 Wind 等 Provider，但不得改变上层业务接口。

### 生产切换目标

```text
MVP
AKShareFundProvider
        │
        ▼
FundDataProvider
        │
        ▼
Normalizer / Repository / PostgreSQL

正式发布
ChoiceFundProvider 或 IFinDFundProvider
        │
        ▼
FundDataProvider
        │
        ▼
Normalizer / Repository / PostgreSQL
```

切换生产数据源时，以下模块原则上不需要修改：

- React Native / Expo App。
- FastAPI 对外 API。
- FundService。
- WatchlistService。
- PortfolioService。
- AnalyticsService。
- 后续 LangGraph Agent / Tools。

## 5.5 `FundDataProvider` 统一接口

禁止在业务层直接出现 AKShare、Choice、iFinD 的 SDK/API 调用。

建议基础接口：

```python
class FundDataProvider(Protocol):
    async def search_funds(self, keyword: str) -> list[FundExternalRecord]:
        ...

    async def get_fund_profile(self, fund_code: str) -> FundExternalProfile:
        ...

    async def get_latest_nav(self, fund_code: str) -> FundExternalNav:
        ...

    async def get_nav_history(
        self,
        fund_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[FundExternalNav]:
        ...

    async def get_fund_manager(self, fund_code: str) -> FundExternalManager | None:
        ...

    async def get_holdings(self, fund_code: str) -> list[FundExternalHolding]:
        ...
```

MVP 实现：

```text
FundDataProvider
       │
       └── AKShareFundProvider
```

生产环境可增加：

```text
FundDataProvider
       │
       ├── AKShareFundProvider       # 开发 / 辅助
       ├── ChoiceFundProvider        # 生产候选
       └── IFinDFundProvider         # 生产候选
```

Provider 返回的数据必须先转换为项目内部统一 Domain Model，不允许将第三方字段结构直接透传给前端。

## 5.6 基金数据落库与查询原则

基金数据采用“采集后落库、业务查询读本地”的方式。

```text
External Fund Provider
        │
        ▼
FundDataProvider
        │
        ▼
Normalizer
        │
        ▼
FundRepository
        │
        ▼
PostgreSQL
        │
        ├── Redis Cache
        │
        ▼
FundService
        │
        ▼
FastAPI / App / Agent
```

约束：

1. 用户打开 App 时，不应直接实时穿透到 AKShare。
2. 基金基础资料、净值、历史净值等核心事实数据优先从 PostgreSQL 读取。
3. Redis 只承担热点缓存，不作为金融事实的唯一持久化来源。
4. 第三方接口异常时，允许继续提供最近一次成功落库的数据，并明确数据日期。
5. 外部数据必须保留来源和时间信息，至少包括 `source`、`as_of`、`fetched_at`。
6. 区间收益、持有收益、最大回撤、波动率等派生指标由系统自己的 Python Analytics 计算。
7. 后续 Agent 只能通过 FundService / Tool 读取这些标准化后的数据，不直接调用 AKShare。

## 5.7 MVP 数据采集范围

第一阶段至少同步以下数据：

- 基金代码与名称。
- 基金类型。
- 基金公司。
- 基金经理基础信息。
- 成立日期。
- 最新单位净值。
- 最新累计净值。
- 净值日期。
- 历史净值。

可根据开发进度增加：

- 基金规模。
- 股票持仓。
- 债券持仓。
- 基金经理任职信息。

基金“关联板块”不是第一阶段对外部数据源的硬依赖，后续可基于基金持仓与股票行业/概念映射自行计算。

---

# 6. 整体技术架构

系统采用 **Async API + Async Database + Redis/Valkey + Durable Worker Queue + 有界并发 Provider** 的整体模型。

```text
                         Android / iOS / Web
                                 │
                       React Native + Expo
                                 │
                          REST API / SSE
                                 │
                         ┌───────▼───────┐
                         │    FastAPI    │
                         │  async/await  │
                         └───────┬───────┘
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
     WatchlistService     PortfolioService      FundService
             │                   │                   │
             │            HoldingImportService      │
             │                   │                   │
             └───────────────────┼───────────────────┘
                                 │
                       Repository Layer
                                 │
                       ┌─────────┴─────────┐
                       │                   │
                 Redis / Valkey       PostgreSQL
                 Cache / Lock /       asyncpg Pool
                 Task Broker              │
                       │                   │
                       └─────────┬─────────┘
                                 │
                           Taskiq Workers
                        ┌────────┴────────┐
                        │                 │
                 Fund Sync Worker   Screenshot Worker
                        │                 │
                FundDataProvider     Vision / OCR
                        │
              AKShare / Choice / iFinD
```

在线请求优先读取 PostgreSQL / Redis；第三方基金数据采集、截图识别、批量分析等耗时任务进入持久化 Worker Queue，不长期占用 FastAPI request。

Agent 作为后续扩展层：

```text
FastAPI
   │
LangGraph Agent
   │
Tools
   │
Domain Services
```

---

# 7. 后端技术要求

后端继续采用当前 FastAPI + LangGraph Production Ready Template。

## 7.1 核心技术

- Python 3.12+。
- FastAPI。
- Pydantic。
- SQLAlchemy Async。
- asyncpg。
- PostgreSQL。
- Alembic。
- Redis / Valkey。
- Taskiq + Redis/Valkey Broker（后台任务）。
- LangGraph（保留）。
- LangGraph Checkpointer（保留）。
- Langfuse（保留）。
- Prometheus / Grafana（沿用框架能力）。

## 7.2 后端目录建议

```text
backend/
└── app/
    ├── api/
    │   └── v1/
    │       ├── auth.py
    │       ├── funds.py
    │       ├── watchlist.py
    │       ├── portfolio.py
    │       ├── accounts.py
    │       ├── transactions.py
    │       ├── imports.py
    │       └── agent.py          # 占位
    │
    ├── agents/
    │   └── fund_agent/
    │       ├── graph.py          # 保留基础图
    │       ├── state.py
    │       └── tools.py          # 后续扩展
    │
    ├── domain/
    │   ├── fund/
    │   ├── watchlist/
    │   └── portfolio/
    │
    ├── integrations/
    │   ├── fund_data/
    │   └── holdings/
    │       ├── base.py
    │       ├── extractors/
    │       └── providers/
    │
    ├── analytics/
    │   ├── returns.py
    │   ├── drawdown.py
    │   └── volatility.py
    │
    ├── repositories/
    ├── models/
    ├── schemas/
    ├── services/
    ├── workers/
    │   ├── fund_sync.py
    │   ├── screenshot_import.py
    │   └── analytics.py
    └── core/
        ├── database.py
        ├── redis.py
        ├── task_queue.py
        └── concurrency.py
```

## 7.3 分层约束

统一遵循：

```text
API
 ↓
Service
 ↓
Repository / Integration
 ↓
Database / Provider
```

API 不直接执行复杂 SQL。

前端不直接访问第三方基金数据源。

## 7.4 异步与并发总体原则

后端默认采用异步优先设计，但不把“异步”理解为所有工作都直接运行在 FastAPI Event Loop 中。

统一划分三类并发：

| 类型 | 实现方式 | 主要用途 |
|---|---|---|
| Request Concurrency | `async/await` | FastAPI、PostgreSQL、Redis、未来 Agent Tool |
| Bounded I/O Concurrency | `asyncio.Semaphore` + `TaskGroup/gather` | 批量基金数据采集、多个外部 I/O 请求 |
| Background Parallelism | Taskiq Worker Queue | 截图识别、基金同步、批量计算、耗时任务 |

若未来出现明显 CPU 密集任务（大规模回测、组合优化、复杂图像处理），应进入独立 Process Worker，不在 Event Loop 内执行。

硬性约束：

1. API 路径不得执行长时间阻塞任务。
2. 重要后台任务不得使用裸 `asyncio.create_task()` 作为可靠执行机制。
3. 需要重试、状态追踪、失败恢复的任务必须进入持久化 Worker Queue。
4. 批量外部调用必须做有界并发，不允许无上限 `gather`。
5. 第三方同步失败不得阻塞用户查看最近一次已落库数据。

## 7.5 FastAPI 在线请求模型

所有在线 API、Service、Repository 默认使用 `async/await`：

```text
FastAPI Endpoint
       ↓ await
Domain Service
       ↓ await
Repository
       ↓ await
SQLAlchemy Async / asyncpg
       ↓
PostgreSQL
```

在线请求允许执行：

- PostgreSQL 查询与短事务。
- Redis 查询。
- 轻量业务计算。
- 创建后台任务并立即返回任务 ID。

在线请求禁止直接执行：

- `requests.get()` 等阻塞网络请求。
- `time.sleep()`。
- 大量 Pandas / NumPy CPU 计算。
- AKShare 长耗时同步调用。
- Vision / OCR 长耗时识别。

## 7.6 AKShare Provider 的阻塞隔离

`FundDataProvider` 对业务层暴露异步接口，但 AKShare 底层存在同步阻塞调用，因此必须在 Adapter 内隔离。

推荐模式：

```python
async def get_nav_history(self, fund_code: str):
    async with self._semaphore:
        return await asyncio.to_thread(
            self._fetch_nav_history_sync,
            fund_code,
        )
```

AKShare Provider 必须支持以下配置：

```text
AKSHARE_MAX_CONCURRENCY=5
AKSHARE_TIMEOUT_SECONDS=20
AKSHARE_MAX_RETRIES=2
```

以上数值属于默认开发配置，必须通过环境变量可调，不得写死在业务逻辑中。

Provider 层必须同时具备：

- Semaphore。
- Timeout。
- Retry。
- Rate Limit / 节流。
- 统一异常转换。
- 数据源追踪字段。

## 7.7 基金批量同步采用有界并发

批量同步基金数据时使用 Bounded Concurrency。

```text
待同步基金列表
      ↓
Semaphore(N)
      ↓
有限数量并发请求 Provider
      ↓
Normalizer
      ↓
PostgreSQL
```

禁止：

```python
await asyncio.gather(*[sync_fund(f) for f in thousands_of_funds])
```

必须通过 Semaphore / Worker 并发度限制保护：

- 第三方数据源。
- 本地线程池。
- 数据库连接池。
- 应用自身内存。

## 7.8 后台任务队列

MVP 使用 **Taskiq + Redis/Valkey Broker** 作为可靠后台任务机制。

至少定义三个任务类型：

```text
FundSyncWorker
├── 基金基础资料同步
├── 最新净值同步
└── 历史净值补全

ScreenshotImportWorker
├── 图片读取
├── Vision / OCR
├── 基金实体匹配
├── 数据标准化
└── 生成待确认 Import Item

AnalyticsWorker
└── 后续批量指标计算 / 数据预计算
```

任务至少记录：

- job_id。
- job_type。
- status。
- retry_count。
- created_at。
- started_at。
- finished_at。
- error_code / error_message。

如 Taskiq 自身状态后端不能覆盖完整业务审计要求，业务状态仍以 PostgreSQL 中的 Import / Sync 记录为准。

## 7.9 截图识别异步流程

截图识别不得在上传请求中同步完成。

```text
POST /holding-imports/screenshots
            ↓
保存临时文件
            ↓
创建 holding_imports 记录
            ↓
enqueue ScreenshotImportWorker
            ↓
HTTP 202 + import_id
```

后台处理：

```text
Screenshot Worker
      ↓
Vision / OCR
      ↓
结构化字段提取
      ↓
Fund Resolver
      ↓
Normalizer / Validator
      ↓
holding_import_items
      ↓
WAITING_CONFIRMATION
```

前端通过轮询或后续 SSE/Push 获取任务状态。只有用户确认后，才允许更新 `portfolio_positions`。

## 7.10 数据库并发与事务

PostgreSQL 统一通过 SQLAlchemy Async Engine + asyncpg connection pool 访问。

要求：

- 不为每个请求重新创建物理数据库连接。
- 连接池参数通过环境变量配置。
- 数据库事务保持短小。
- 外部 Provider / Vision 调用不得放在数据库事务中等待。
- 批量写入优先使用批处理方式。

错误模式：

```text
BEGIN
  ↓
调用 AKShare / Vision 等待数秒
  ↓
COMMIT
```

正确模式：

```text
外部调用完成
   ↓
BEGIN
   ↓
快速校验 / 写入
   ↓
COMMIT
```

## 7.11 持仓并发写与乐观锁

`portfolio_positions` 建议增加：

- `version`。
- `updated_at`。

修改持仓时采用 Optimistic Lock。

场景：

```text
客户端读取 version=8
       ↓
截图导入先更新持仓
       ↓
数据库 version=9
       ↓
客户端提交 expected_version=8
       ↓
HTTP 409 Conflict
```

不允许静默覆盖用户较新的持仓数据。

## 7.12 基金同步去重与分布式锁

基金数据属于全局共享事实数据，同一只基金不能因为多个用户持有或自选而重复请求第三方 Provider。

使用 Redis / Valkey Distributed Lock，例如：

```text
fund_sync:{fund_code}:{business_date}
```

同一基金、同一业务日期只允许一个 Worker 执行同步。其他 Worker 应跳过、等待或复用已完成结果。

同步任务还必须提供业务幂等键，确保 Worker 重试不会产生重复数据。

## 7.13 Hot / Cold Fund 同步策略

基金分为：

### Hot Funds

- 用户当前持有的基金。
- 用户自选的基金。

特点：优先同步，净值公布后尽快更新。

### Cold Funds

- 当前无用户持有或自选的基金。

特点：基金 Master 信息低频更新；NAV 按需或低频同步。

MVP 不要求每天对全部公募基金执行全量历史数据刷新。

## 7.14 Cache-Aside 并发策略

在线查询使用 Cache-Aside：

```text
Request
   ↓
Redis Cache
   ├── Hit ──→ Response
   │
   └── Miss
          ↓
     PostgreSQL
          ↓
      Response
          ↓
       Redis SET
```

基金数据更新完成后：

```text
UPDATE PostgreSQL
        ↓
DELETE / INVALIDATE Redis Key
```

第一阶段不设计复杂双写缓存一致性协议。PostgreSQL 始终是持久化事实来源。

## 7.15 Agent 后续并发兼容

当前 Agent 不实现正式业务能力，但所有 Service / Repository 必须保持 async 接口，以便后续 LangGraph Tool 直接复用：

```python
async def get_my_positions(...):
    return await portfolio_service.get_positions(...)
```

未来 Agent 可以在受控并发下同时调用：

- Watchlist Tool。
- Portfolio Tool。
- Fund Tool。
- Performance / Analytics Tool。

Agent 不得绕过 Service / Repository 直接访问数据库或第三方 Provider。

---

# 8. 前端技术要求

前端采用统一跨平台方案。

## 8.1 技术栈

- React Native。
- Expo。
- TypeScript。
- Expo Router。
- TanStack Query。
- Zustand。
- Expo SecureStore。

## 8.2 平台目标

同一套前端代码支持：

- Android。
- iOS。
- Web。

第一阶段优先保证 Android 真机开发体验，同时保证 Web 版本可运行。

## 8.3 页面目录建议

```text
frontend/
├── app/
│   ├── _layout.tsx
│   │
│   ├── (tabs)/
│   │   ├── _layout.tsx
│   │   ├── index.tsx           # 持有
│   │   ├── watchlist.tsx       # 自选
│   │   ├── agent.tsx           # Agent 占位
│   │   └── profile.tsx         # 我的
│   │
│   ├── fund/
│   │   └── [code].tsx          # 基金详情
│   │
│   ├── account/
│   │   ├── index.tsx
│   │   ├── add.tsx
│   │   └── [id].tsx
│   │
│   ├── position/
│   │   └── edit.tsx
│   │
│   ├── holding-import/
│   │   ├── index.tsx          # 选择手动录入 / 截图导入
│   │   ├── manual.tsx         # 手动录入
│   │   ├── screenshots.tsx    # 截图上传
│   │   └── [importId].tsx     # 识别结果确认 / 差异预览
│   │
│   └── transactions/
│       └── index.tsx
│
├── features/
│   ├── fund/
│   ├── watchlist/
│   ├── portfolio/
│   ├── account/
│   ├── holding-import/
│   └── agent/
│
├── components/
├── api/
├── hooks/
├── stores/
├── types/
└── utils/
```

## 8.4 状态管理

### Server State

使用 TanStack Query 管理：

- Fund 数据。
- Watchlist。
- Portfolio。
- Accounts。
- Transactions。
- Import Status。

负责：

- cache。
- refetch。
- loading。
- error。
- invalidate。
- optimistic update。

### Local / UI State

使用 Zustand 管理：

- 当前选择的持仓账户。
- 当前自选分组。
- 页面筛选条件。
- UI preferences。
- Agent 临时上下文（后续）。

## 8.5 图表

第一版需要：

- 基金净值 / 收益折线图。
- 我的收益曲线（可后置）。
- 简单资产占比图（可选）。

暂不做专业交易 K 线系统。

## 8.6 安全存储

以下数据不得放普通 AsyncStorage：

- Access Token。
- Refresh Token。
- 第三方敏感凭据。

移动端统一使用 Expo SecureStore。

---

# 9. REST API 规划

## 9.1 Fund API

```text
GET /api/v1/funds/search?q={query}
GET /api/v1/funds/{fund_code}
GET /api/v1/funds/{fund_code}/nav
GET /api/v1/funds/{fund_code}/performance
GET /api/v1/funds/{fund_code}/related-sectors      # 可选
```

## 9.2 Watchlist API

```text
GET    /api/v1/watchlist
POST   /api/v1/watchlist
DELETE /api/v1/watchlist/{fund_code}
PATCH  /api/v1/watchlist/{fund_code}

GET    /api/v1/watchlist/groups
POST   /api/v1/watchlist/groups
PATCH  /api/v1/watchlist/groups/{group_id}
DELETE /api/v1/watchlist/groups/{group_id}
```

## 9.3 Portfolio API

```text
GET   /api/v1/portfolio/summary
GET   /api/v1/portfolio/positions
GET   /api/v1/portfolio/positions/{fund_code}
PATCH /api/v1/portfolio/positions/{fund_code}
```

可根据账户筛选：

```text
GET /api/v1/portfolio/positions?account_id={account_id}
```

## 9.4 Account API

```text
GET    /api/v1/accounts
POST   /api/v1/accounts
GET    /api/v1/accounts/{account_id}
PATCH  /api/v1/accounts/{account_id}
DELETE /api/v1/accounts/{account_id}
```

## 9.5 Transaction API

```text
GET /api/v1/transactions
GET /api/v1/transactions?fund_code={fund_code}
GET /api/v1/transactions?account_id={account_id}
```

## 9.6 Holding Import API

手动录入：

```text
POST /api/v1/holding-imports/manual
```

截图识别导入：

```text
POST /api/v1/holding-imports/screenshots
```

建议使用 `multipart/form-data` 上传一张或多张图片。接口返回导入批次 ID，识别结果进入待确认状态。

导入批次：

```text
GET    /api/v1/holding-imports/{import_id}
PATCH  /api/v1/holding-imports/{import_id}/items/{item_id}
POST   /api/v1/holding-imports/{import_id}/confirm
DELETE /api/v1/holding-imports/{import_id}
GET    /api/v1/holding-imports/history
```

`confirm` 才允许调用 PortfolioService 修改正式持仓。

## 9.7 Agent API

第一阶段保留：

```text
POST /api/v1/agent/chat
```

但可以暂不启用正式 Agent 能力。

---

# 10. API 类型同步

FastAPI 生成 OpenAPI Schema。

建议通过 OpenAPI 自动生成 TypeScript Client / Types：

```text
FastAPI
   ↓
OpenAPI
   ↓
TypeScript Client
   ↓
React Native / Web
```

目标：避免 Python Schema 与 TypeScript Interface 长期漂移。

---

# 11. Android 真机开发要求

开发阶段必须支持 Android 真机同步调试。

## 11.1 推荐方式

优先使用 Expo Development Build。

```bash
npx expo run:android --device
```

之后启动：

```bash
npx expo start --dev-client
```

## 11.2 本地 FastAPI

FastAPI 监听：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

手机不能使用：

```text
http://localhost:8000
```

应通过电脑局域网 IP，例如：

```text
http://192.168.1.100:8000
```

---

# 12. 核心数据库模型

第一阶段建议至少包含以下表。

## 12.1 users

用户基础信息。

---

## 12.2 funds

基金基础信息。

建议字段：

- fund_code。
- fund_name。
- fund_type。
- company。
- manager_name。
- inception_date。
- source。
- source_as_of。
- fetched_at。
- updated_at。

---

## 12.3 fund_nav

基金历史净值。

建议字段：

- fund_code。
- nav_date。
- unit_nav。
- accumulated_nav。
- source。
- fetched_at。

建议唯一约束：

```text
(fund_code, nav_date)
```

---

## 12.4 watchlists

用户自选基金。

建议字段：

- id。
- user_id。
- fund_code。
- sort_order。
- created_at。

推荐唯一约束：

```text
(user_id, fund_code)
```

---

## 12.5 watchlist_groups

用户自选分组。

字段：

- id。
- user_id。
- name。
- sort_order。
- created_at。

---

## 12.6 watchlist_group_items

基金与自选分组的关联表。

字段：

- group_id。
- watchlist_id。
- sort_order。

---

## 12.7 portfolio_accounts

用户持仓账户，可标记数据来源应用，但不代表已连接第三方账号。

字段：

- id。
- user_id。
- name。
- source_app（例如支付宝、天天基金、银行、手工账户等，仅作为来源标签）。
- account_type。
- import_mode。
- last_imported_at。
- created_at。
- updated_at。

---

## 12.8 portfolio_positions

当前基金持仓。

字段：

- id。
- account_id。
- fund_code。
- shares。
- cost_amount。
- average_cost_nav。
- market_value。
- profit_loss。
- updated_at。

建议唯一约束：

```text
(account_id, fund_code)
```

`profit_loss_rate`、`daily_profit_loss`、`position_ratio` 等可按查询时计算，避免重复保存不一致的数据。

---

## 12.9 transactions

持仓交易 / 调整记录。

字段：

- id。
- user_id。
- account_id。
- fund_code。
- transaction_type。
- trade_date。
- shares。
- nav。
- amount。
- fee。
- source。
- external_transaction_id。
- created_at。

---

## 12.10 holding_imports

记录一次手动或截图持仓导入批次。

字段建议：

- id。
- user_id。
- account_id。
- import_type：MANUAL / SCREENSHOT。
- source_app。
- status。
- image_count。
- items_detected。
- items_confirmed。
- started_at。
- confirmed_at。
- applied_at。
- error_message。

截图原图不存入该表。

---

## 12.11 holding_import_items

保存截图识别或手动录入产生的待确认持仓条目。

字段建议：

- id。
- import_id。
- raw_fund_name。
- matched_fund_code。
- market_value。
- shares。
- cost_amount。
- average_cost_nav。
- profit_loss。
- profit_loss_rate。
- confidence。
- validation_status。
- user_action：UPDATE / SKIP / EDIT。
- created_at。

该表用于审计和确认流程，不直接作为当前持仓事实表。

---

# 13. 主要数据关系

```text
User
│
├── Watchlists
│      ├── WatchlistGroups
│      └── Fund
│
└── PortfolioAccounts
       │
       ├── Positions
       │      └── Fund
       │
       ├── Transactions
       └── HoldingImports
              └── HoldingImportItems
```

---

# 14. 数据与业务边界要求

## 14.1 基金事实数据

以下数据只能来自 FundService / FundDataProvider：

- 基金净值。
- 收益率。
- 基金名称。
- 基金经理。
- 基金规模。
- 基金基础信息。

不得依赖聊天上下文或 LLM Memory 作为事实来源。

## 14.2 用户数据

以下数据来自用户数据库：

- 自选基金。
- 自选分组。
- 持仓账户。
- 当前持仓。
- 交易记录。
- 手工修正数据。

## 14.3 金融指标

所有确定性指标由 Python 代码计算，包括：

- 收益率。
- 持有收益率。
- 最大回撤。
- 波动率。
- 后续 Sharpe / Alpha / Beta 等。

---

# 15. 缓存要求

Redis / Valkey 主要用于：

- 最新基金净值缓存。
- 基金基础资料缓存。
- 高频基金搜索结果缓存。
- 基金数据接口结果缓存。
- 防止重复提交同一导入批次的幂等锁。
- 基金同步 Distributed Lock。
- Taskiq Broker / Worker Queue。
- 后台任务临时状态与节流控制。
- 后续 Agent session / tool cache（如需要）。

第一阶段不把 Redis 作为核心业务持久化存储。

所有持久数据以 PostgreSQL 为准。

---

# 16. 安全要求

至少满足：

- JWT 鉴权。
- 用户数据隔离。
- 后端接口鉴权。
- Refresh Token 管理。
- 密码 Hash 存储。
- API 日志不得记录密码和 Token。
- 移动端 Token 使用 Expo SecureStore。
- 数据库迁移统一使用 Alembic。

持仓截图属于敏感财务信息：原图默认临时保存并在解析/确认完成后删除，识别结果按最小必要原则持久化。

---

# 17. 可观测性要求

继续使用当前 FastAPI/LangGraph 模板已有能力。

## 17.1 日志

至少记录：

- API 请求。
- 用户 ID。
- Request ID / Trace ID。
- 持仓导入任务。
- 外部接口错误。

## 17.2 Metrics

至少监控：

- API latency。
- API error rate。
- 持仓导入成功率。
- 截图识别成功率 / 失败率。
- 截图识别耗时。
- 低置信度条目比例。
- PostgreSQL 连接状态。
- Redis 连接状态。

## 17.3 Agent

正式开发 Agent 后使用 Langfuse 做：

- Prompt trace。
- Tool trace。
- Token usage。
- Agent latency。
- Agent evaluation。

第一阶段只保留基础设施。

---

# 18. 第一阶段明确不做的功能

以下能力不属于当前 MVP：

- Multi-Agent。
- 基金智能推荐。
- 基金筛选系统。
- 新闻搜索。
- 研报 RAG。
- 公告 RAG。
- 智能投资建议。
- 自动调仓。
- 组合优化。
- 情景模拟。
- 复杂基金归因分析。
- 交易下单。
- 实时行情交易系统。
- 社交功能。
- 复杂消息 / 评论社区。

这些能力后续在现有 Service / Tool / Agent 基础上逐步扩展。

---

# 19. 推荐开发顺序

## Phase 1：项目基础

- 整理现有 FastAPI 模板。
- 建立 Expo 前端工程。
- 建立四个一级 Tab。
- 完成 Android 真机调试。
- 完成登录 / Token 流程。
- 建立 PostgreSQL migration。
- 建立 SQLAlchemy Async / asyncpg connection pool。
- 建立 Redis / Valkey。
- 建立 Taskiq Worker Queue。
- 建立 API / Worker 独立启动方式。
- Agent 页面占位。

## Phase 2：基金数据

- Fund 数据模型。
- FundDataProvider 抽象。
- 实现 `AKShareFundProvider`。
- AKShare 阻塞调用统一通过 `asyncio.to_thread` / Worker 隔离。
- Provider 增加 Semaphore、Timeout、Retry 和并发配置。
- 实现基金批量同步的有界并发。
- 实现基金同步幂等键与 Redis Distributed Lock。
- 实现 Hot / Cold Fund 同步策略。
- 建立第三方数据 Normalizer。
- 建立基金基础数据与历史净值落库流程。
- 为核心数据记录 `source`、`as_of`、`fetched_at`。
- 基金搜索。
- 基金详情。
- 历史净值。
- 最新净值 / 当日涨跌。
- 区间收益由 AnalyticsService 自行计算。
- App 查询优先读取 PostgreSQL / Redis，不直接穿透 AKShare。
- 为未来 `ChoiceFundProvider` / `IFinDFundProvider` 保留实现位置。

## Phase 3：自选基金

- Watchlist 数据模型。
- Watchlist Group 数据模型。
- Watchlist Service。
- Watchlist API。
- 自选列表页面。
- 自选分组。
- 添加 / 删除自选。
- 持有标识。

## Phase 4：持仓

- PortfolioAccount。
- PortfolioPosition。
- Transaction。
- Portfolio Service。
- 持有页面。
- 基金详情中的“我的持仓”。
- 手工持仓录入 / 修改。

## Phase 5：持仓导入

- HoldingImportProvider 接口。
- ManualImportProvider。
- ScreenshotImportProvider。
- ScreenshotImportWorker。
- 截图上传接口返回 `202 Accepted + import_id`。
- ScreenshotPositionExtractor。
- Vision / OCR Adapter。
- Fund Resolver。
- 图片上传与临时存储。
- 多截图识别。
- 识别结果确认页面。
- 导入差异预览。
- HoldingImport / HoldingImportItem 数据模型。
- 确认后更新当前持仓。
- 原图生命周期删除策略。


## Phase 6：体验完善

- 基金详情图表。
- 我的收益页面。
- 账户管理页面。
- Cache-Aside 缓存。
- 缓存失效策略。
- 后台任务失败 / 重试状态展示。
- 错误状态。
- 空状态。
- 加载骨架屏。
- Web 适配。

## Phase 7：Agent 扩展（后续阶段）

业务 MVP 稳定后再开发：

- Agent Tools。
- 查询自选。
- 查询持仓。
- 查询基金。
- 单基金分析。
- 基金比较。
- 持仓分析。

---

# 20. MVP 验收标准

满足以下条件即可认为第一阶段 MVP 完成：

1. Android App 可以在真机正常启动、登录和使用。
2. Web 版本可以使用同一 Expo 前端代码运行。
3. App 底部包含“持有 / 自选 / Agent / 我的”四个一级入口。
4. 用户可以搜索基金。
5. 用户可以添加 / 删除自选基金。
6. 用户可以创建和切换自选分组。
7. 自选列表可以显示基金最新净值和当日涨跌。
8. 自选列表可以标记基金是否属于用户持仓。
9. 用户可以进入基金详情页。
10. 基金详情可以查看基本信息、最新净值和历史走势。
11. 持有基金时，基金详情可以展示持有金额、份额、成本、持有收益和持仓占比。
12. 用户可以查看多个持仓账户及账户汇总。
13. 用户可以手工录入或修改持仓。
14. 用户可以查看基础交易 / 调整记录。
15. 系统具备统一 `HoldingImportProvider` 接口。
16. 完成 `ManualImportProvider` 和 `ScreenshotImportProvider`。
17. 用户可以上传一张或多张持仓截图，查看结构化识别结果，修正后确认导入。
18. 截图识别不得直接修改正式持仓；只有用户确认后才能写入。
19. 持仓导入具有状态、更新时间、错误记录和审计条目。
20. 原始持仓截图默认在识别/确认完成后自动删除。
21. 基金数据和持仓数据具有明确的数据来源和更新时间。
22. 后端业务逻辑通过 Service / Repository / Integration 分层实现。
23. FastAPI、Repository、PostgreSQL 和 Redis 在线链路采用异步接口。
24. AKShare 阻塞调用不会直接阻塞 FastAPI Event Loop。
25. 批量基金同步具有可配置的有界并发限制。
26. 截图识别通过持久化 Worker Queue 执行，上传接口不等待完整识别过程。
27. 后台任务支持状态追踪、失败记录和有限重试。
28. 同一基金同步具有幂等控制和 Redis Distributed Lock。
29. 持仓修改具备乐观锁或等效并发冲突保护。
30. Agent Tab 和后端扩展位置已经保留，但不影响当前业务正常运行。

---

# 21. 第一阶段最终技术栈

```text
Frontend
├── React Native
├── Expo
├── TypeScript
├── Expo Router
├── TanStack Query
├── Zustand
└── Expo SecureStore

Backend
├── Python 3.12+
├── FastAPI
├── Pydantic
├── SQLAlchemy Async
├── asyncpg
├── Alembic
├── PostgreSQL
├── Redis / Valkey
├── Taskiq
├── LangGraph（保留，暂不重点开发）
├── LangGraph Checkpointer（保留）
└── Langfuse（保留）

Architecture
├── API Layer
├── Domain Service Layer
├── Repository Layer
├── Integration Layer
├── Analytics Layer
├── Async Worker Layer
├── Bounded Concurrency
└── Agent Extension Layer
```

---

# 22. 当前项目定位

当前版本不是“智能投顾系统”，也不是“全功能基金研究平台”。

当前产品定位为：

> **一个以个人自选基金、个人持仓和手动/截图识别导入为核心的跨平台基金管理应用；后端采用 Async API + Async Database + Redis/Valkey + Taskiq Worker + 有界并发架构，并在现有 FastAPI + LangGraph 框架上预留后续 AI Agent 扩展能力。**

第一阶段优先保证：

> **数据正确、账户清晰、持仓导入可核验、自选好用、基金详情完整、跨端可用、后续可扩展。**
