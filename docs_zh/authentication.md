# 身份认证

## 流程

```mermaid
sequenceDiagram
    participant C as 客户端
    participant A as API

    C->>A: POST /auth/register<br/>{email, password, username?}
    A-->>C: {user_id, email, username, token}

    C->>A: POST /auth/login<br/>表单：email + password
    A-->>C: {access_token, refresh_token, expires_at}

    C->>A: POST /auth/refresh<br/>表单：refresh_token
    A-->>C: {access_token, refresh_token, expires_at}

    C->>A: POST /auth/session<br/>Bearer：用户令牌
    A-->>C: {session_id, token}

    C->>A: POST /chatbot/chat<br/>Bearer：会话令牌
    A-->>C: {messages}

    C->>A: POST /auth/logout<br/>Bearer：用户令牌
    A-->>C: 204（撤销刷新令牌）
```

API 使用**两种令牌作用域**：

- **用户令牌**——注册或登录时签发，用于标识用户，以及创建和列出会话。
- **会话令牌**——为每个对话会话签发。所有聊天端点都要求提供此令牌，并且它仅对单个 `session_id` 有效。

两种令牌都带 `typ: "access"`，鉴权依赖只接受这一类。**刷新令牌带 `typ: "refresh"`，除 `POST /auth/refresh` 外任何端点都不能使用。**

Access 令牌有效期很短（`JWT_ACCESS_TOKEN_EXPIRE_DAYS`，默认 1 天），刷新令牌有效期为 `JWT_REFRESH_TOKEN_EXPIRE_DAYS`（默认 90 天）。两者都是无状态的，因此登出无法撤销已签发的 access 令牌——登出撤销的是刷新令牌（见 `/auth/logout`）。

基金业务端点（`/funds`、`/watchlist`、`/portfolio`、`/holding-imports` 等）使用 `get_current_identity`，**用户令牌和会话令牌都可访问**，客户端不必为了查持仓先创建聊天会话。

---

## 端点

### `POST /api/v1/auth/register`

创建新账户。

```json
{
  "email": "you@example.com",
  "password": "Secret123!",  // pragma: allowlist secret
  "username": "you"
}
```

密码要求：至少 8 个字符，且包含大写字母、小写字母、数字和特殊字符。

`username` 为可选项。提供后，它会传入智能体的系统提示词，让 LLM 知道用户的姓名。

---

### `POST /api/v1/auth/login`

使用凭据换取用户令牌。该端点使用 OAuth2 密码授权表单字段。

```bash
curl -X POST /api/v1/auth/login \
  -F "email=you@example.com" \
  -F "password=Secret123!" \
  -F "grant_type=password"
```

返回 `access_token`、`refresh_token` 和 `expires_at`。

---

### `POST /api/v1/auth/refresh`

用刷新令牌（`typ: "refresh"`）换取新的 access 令牌与轮转后的刷新令牌。表单编码请求体。

```bash
curl -X POST /api/v1/auth/refresh   -F "refresh_token=<刷新令牌>"
```

令牌格式非法、已过期、类型不是刷新令牌，或在此之前已被登出撤销时返回 401。

---

### `POST /api/v1/auth/logout`

撤销调用者的刷新令牌：此后该时刻之前签发的刷新令牌一律失效。需要用户令牌，返回 `204` 无响应体。已签发的 access 令牌在自己的过期时间前仍然有效。

---

### `GET /api/v1/auth/me`

返回当前登录用户资料（`id`、`email`、`username`、`created_at`）。接受用户令牌或会话令牌。

---

### `POST /api/v1/auth/session`

创建新的聊天会话。需要有效的用户令牌。

```bash
curl -X POST /api/v1/auth/session \
  -H "Authorization: Bearer <用户令牌>"
```

返回 `session_id` 和仅限该会话使用的 `token`。后续所有聊天请求都应使用此会话令牌。

---

### `PATCH /api/v1/auth/session/{session_id}/name`

重命名会话。

```bash
curl -X PATCH /api/v1/auth/session/{session_id}/name \
  -H "Authorization: Bearer <会话令牌>" \
  -F "name=我的研究会话"
```

---

### `DELETE /api/v1/auth/session/{session_id}`

删除会话及其聊天历史记录。

---

### `GET /api/v1/auth/sessions`

列出已认证用户的所有会话。需要用户令牌。

---

## 安全说明

- 密码在存储前使用 bcrypt 进行哈希处理，绝不会持久化明文密码。
- JWT 包含 `typ`（access / refresh）与 `jti` 声明；日志不记录令牌内容、密码或识别出的持仓文本。
- 所有字符串输入在使用前都会经过清理。
- 限流可保护注册端点（10 次/小时）和登录端点（20 次/分钟），防止暴力破解。
- 在生产环境中，应将 `JWT_SECRET_KEY` 设置为较长的随机字符串，长度至少为 32 个字符。
