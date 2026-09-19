# LLM 服务

## 概览

LLM 服务（`app/services/llm/`）负责所有语言模型调用，并提供自动重试、循环模型回退和总超时预算。智能体代码只需调用 `llm_service.call(messages)`，其余工作全部由该服务处理。

该包分为两个模块：

- `app/services/llm/registry.py`——`LLMRegistry`：定义可用模型
- `app/services/llm/service.py`——`LLMService`：调用逻辑、重试、回退和结构化输出

## 模型注册表

模型按优先级顺序定义在 `LLMRegistry.LLMS` 中：

| 名称 | 模型 | 说明 |
| -------------- | ------------ | -------------------------------------- |
| `gpt-5-mini` | gpt-5-mini | 默认模型，推理强度较低。 |
| `gpt-5.4` | gpt-5 | 中等推理强度。 |
| `gpt-5.4-nano` | gpt-5.4-nano | 速度快，推理强度较低。 |
| `gpt-5` | gpt-5 | 完整模型，采样参数针对生产环境调优。 |

在 `.env` 中设置 `DEFAULT_LLM_MODEL` 以选择起始模型。

如需添加或更改模型，请编辑 `app/services/llm/registry.py` 中的 `LLMRegistry.LLMS`。

## 重试与回退行为

```mermaid
flowchart TD
    Call["llm_service.call(messages)"]
    TotalTimeout["asyncio.wait_for\nLLM_TOTAL_TIMEOUT 秒"]
    Try["尝试当前模型"]
    Retry{"可重试错误？\n（限流、超时、API 错误）"}
    MaxRetries{"已达到\nMAX_LLM_CALL_RETRIES？"}
    NextModel{"还有其他模型\n可尝试？"}
    Backoff["指数退避\n2 秒 → 4 秒 → 8 秒"]
    Switch["切换到下一个模型\n（循环）"]
    Success["返回响应"]
    Fail["抛出 RuntimeError"]

    Call --> TotalTimeout --> Try
    Try --> Retry
    Retry -->|是| Backoff --> MaxRetries
    MaxRetries -->|否| Try
    MaxRetries -->|是| NextModel
    Retry -->|否| Fail
    NextModel -->|是| Switch --> Try
    NextModel -->|否| Fail
    Try -->|成功| Success
```

**重试配置**（每个模型）：

- 最大尝试次数：`MAX_LLM_CALL_RETRIES`（默认值：3）
- 等待策略：指数退避，最短 2 秒，最长 10 秒
- 对以下异常进行重试：`RateLimitError`、`APITimeoutError`、`APIError`

**总超时**：`LLM_TOTAL_TIMEOUT` 秒（默认值：60 秒）会限制整个循环的执行时间。若没有此限制，最坏情况将是“重试次数 × 模型数 × 最大等待时间”，可能超过 2 分钟。

**回退顺序**：按照 `LLMRegistry.LLMS` 循环遍历。到达最后一个模型后，会回到第一个模型，并在完成一整轮后停止。

## 工具

工具在启动时绑定到 LLM：

```python
llm_service.bind_tools(tools)
```

在回退期间切换模型时，工具会自动重新绑定到新模型。

## 结构化输出

将 Pydantic 模型作为 `response_format` 传入，即可返回经过验证的模型实例，而非原始 `BaseMessage`：

```python
from app.schemas.my_schema import MySchema

result: MySchema = await llm_service.call(
    messages,
    model_name="gpt-5.4-nano",   # 可选——省略时使用当前默认模型
    response_format=MySchema,
    temperature=0.2,
)
```

该服务会在已解析的模型上链接 `.with_structured_output(schema)`，并在每次回退尝试时重新包装，因此重试和模型切换都能透明地工作。

## 添加新模型

```python
# app/services/llm/registry.py — LLMRegistry.LLMS
{
    "name": "gpt-5.4",
    "llm": ChatOpenAI(
        model="gpt-5.4",
        api_key=settings.OPENAI_API_KEY,
        max_tokens=settings.MAX_TOKENS,
    ),
},
```

可以将其添加到列表中的任意位置。回退顺序与列表顺序一致。
