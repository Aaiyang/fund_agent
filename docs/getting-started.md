# Getting Started

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- PostgreSQL (local or remote; the app connects via `POSTGRES_*` vars)
- OpenAI API key
- Langfuse account (optional — set `LANGFUSE_TRACING_ENABLED=false` to skip)

## Local setup

```bash
git clone <repo-url> my-agent
cd my-agent/backend

cp .env.example .env.development
# Fill in: OPENAI_API_KEY, JWT_SECRET_KEY, POSTGRES_* (point to your DB)

make install       # installs deps + pre-commit hooks
make migrate       # creates tables via Alembic
make dev           # starts server with hot reload on port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs).

## Your first API call

### 1. Register a user

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "Secret123!", "username": "you"}'  # pragma: allowlist secret
```

Returns a `user_id` and a JWT token.

### 2. Create a session

```bash
curl -X POST http://localhost:8000/api/v1/auth/session \
  -H "Authorization: Bearer <token from step 1>"
```

Returns a `session_id` and a session-scoped JWT.

### 3. Chat

```bash
curl -X POST http://localhost:8000/api/v1/chatbot/chat \
  -H "Authorization: Bearer <session token>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

Or use the streaming endpoint for real-time responses:

```bash
curl -X POST http://localhost:8000/api/v1/chatbot/chat/stream \
  -H "Authorization: Bearer <session token>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

## Customising the agent

The parts you'll most likely change:

| What | Where |
|---|---|
| Agent personality & instructions | `app/core/prompts/system.md` |
| Available tools | `app/core/langgraph/tools.py` |
| LLM models & fallback order | `app/services/llm.py` → `LLMRegistry.LLMS` |
| Memory collection name | `LONG_TERM_MEMORY_COLLECTION_NAME` in `.env` |

## Running pre-commit hooks

Hooks run automatically on `git commit`. To run manually:

```bash
make pre-commit
```

Hooks include: trailing whitespace, YAML/TOML/JSON validation, secret detection, ruff lint + format.

## Troubleshooting

**Database connection error on startup**
Make sure PostgreSQL is running and `POSTGRES_*` vars in your `.env` match.

**`could not translate host name "db"`**
`POSTGRES_HOST=db` only resolves inside a container network (it's the Compose
service name). For local development, set `POSTGRES_HOST=localhost` in your `.env`.

**`detect-secrets` blocking a commit**
If it's a false positive, add `# pragma: allowlist secret` to the end of the flagged line.

**Langfuse errors**
Set `LANGFUSE_TRACING_ENABLED=false` in your `.env` to disable tracing entirely during development.
