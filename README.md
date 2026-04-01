# Agentic AI — LangGraph + FastAPI

A production-ready conversational AI service built on [LangGraph](https://github.com/langchain-ai/langgraph), served via [FastAPI](https://fastapi.tiangolo.com/), with PostgreSQL persistence, Alembic migrations, and Redis rate limiting + caching.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI (port 8000)                  │
│                                                             │
│  POST /api/v1/threads/{id}/messages                         │
│        │                                                    │
│        ├─► Redis rate limiter (sliding window / IP)         │
│        ├─► Redis response cache (SHA-256 key + TTL)         │
│        │                                                    │
│        └─► LangGraph graph.ainvoke()                        │
│                  │                                          │
│                  ├─► ChatAnthropic (claude-3-5-sonnet)      │
│                  └─► AsyncPostgresSaver (checkpoint tables) │
│                                                             │
│  Thread metadata ──► SQLAlchemy ORM ──► PostgreSQL          │
│  (title, timestamps)    (threads table, Alembic-managed)    │
└─────────────────────────────────────────────────────────────┘
```

### Persistence Strategy

| Data | Where | How |
|---|---|---|
| Message history | PostgreSQL (`checkpoint_*` tables) | LangGraph `AsyncPostgresSaver` — automatic per `thread_id` |
| Thread metadata | PostgreSQL (`threads` table) | SQLAlchemy async ORM, Alembic-managed |
| Rate limit counters | Redis sorted set | Lua sliding-window script (atomic) |
| Response cache | Redis string | SHA-256 key, configurable TTL |

---

## API Endpoints

![Swagger Documentation](./static/swagger_docs.svg)

Interactive docs available at `http://localhost:8000/docs` (development mode only).

### Threads

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/threads` | Create a new conversation thread |
| `GET` | `/api/v1/threads` | List threads (paginated, newest first) |
| `GET` | `/api/v1/threads/{thread_id}` | Get thread metadata + full message history |
| `DELETE` | `/api/v1/threads/{thread_id}` | Delete thread and its checkpoint data |
| `POST` | `/api/v1/threads/{thread_id}/messages` | Send a message, get agent response |

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Check DB + Redis connectivity |

---

## Project Structure

```
.
├── src/agent/
│   ├── graph.py              # LangGraph workflow (ChatAnthropic node)
│   ├── state.py              # State: messages list with add_messages reducer
│   ├── configuration.py      # Runtime config: model, system_prompt
│   ├── settings.py           # Pydantic-Settings singleton (all env vars)
│   │
│   ├── db/
│   │   ├── base.py           # SQLAlchemy DeclarativeBase
│   │   ├── engine.py         # Async engine + session factory
│   │   ├── models.py         # Thread ORM model
│   │   └── repositories.py   # ThreadRepository (create/get/list/delete)
│   │
│   ├── cache/
│   │   └── redis_client.py   # Connection pool, rate limiter, response cache
│   │
│   └── api/
│       ├── app.py            # FastAPI factory + lifespan
│       ├── schemas.py        # Pydantic v2 request/response models
│       ├── middleware.py     # RequestIDMiddleware (X-Request-ID + access log)
│       ├── dependencies.py   # DI: get_db(), get_thread_repo(), rate_limit()
│       └── routers/
│           ├── health.py     # GET /health
│           └── threads.py    # All /api/v1/threads/* endpoints
│
├── alembic/                  # Database migrations
│   ├── env.py                # Async-aware Alembic environment
│   └── versions/
│       └── 20260401_0001_initial_schema.py
│
├── Dockerfile                # Multi-stage production image
├── docker-compose.yml        # App + PostgreSQL 16 + Redis 7
└── langgraph.json            # LangGraph Studio configuration
```

---

## Quick Start

### Option A — Docker (recommended)

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env — only ANTHROPIC_API_KEY is required; DB/Redis are wired by Compose

# 2. Start everything
make docker-up

# 3. Verify
curl http://localhost:8000/health
# → {"status":"ok","database":"ok","redis":"ok"}
```

### Option B — Local development

**Prerequisites:** Python 3.11+, PostgreSQL, Redis

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Edit DATABASE_URL, CHECKPOINT_DATABASE_URL, REDIS_URL, ANTHROPIC_API_KEY

# 3. Run migrations
make migrate

# 4. Start server
make serve
# → Uvicorn running on http://0.0.0.0:8000
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the required values.

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key |
| `DATABASE_URL` | Yes | — | `postgresql+asyncpg://user:pass@host/db` |
| `CHECKPOINT_DATABASE_URL` | Yes | — | `postgresql://user:pass@host/db` (LangGraph uses plain DSN) |
| `REDIS_URL` | Yes | — | `redis://host:6379/0` |
| `APP_ENV` | No | `development` | `development` or `production` |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `RATE_LIMIT_REQUESTS` | No | `60` | Max requests per window per IP |
| `RATE_LIMIT_WINDOW_SECONDS` | No | `60` | Rate limit window in seconds |
| `CACHE_TTL_SECONDS` | No | `300` | Redis response cache TTL |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | Allowed CORS origins (JSON array) |

---

## Usage Examples

### Create a thread

```bash
curl -X POST http://localhost:8000/api/v1/threads \
  -H "Content-Type: application/json" \
  -d '{"title": "My first conversation"}'
```

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "My first conversation",
  "metadata": null,
  "created_at": "2026-04-01T10:00:00Z",
  "updated_at": "2026-04-01T10:00:00Z"
}
```

### Send a message

```bash
curl -X POST http://localhost:8000/api/v1/threads/550e8400.../messages \
  -H "Content-Type: application/json" \
  -d '{"content": "What is the capital of France?"}'
```

```json
{
  "thread_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_message": "What is the capital of France?",
  "assistant_message": "The capital of France is Paris.",
  "cached": false
}
```

### Get thread with history

```bash
curl http://localhost:8000/api/v1/threads/550e8400...
```

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "My first conversation",
  "messages": [
    {"role": "human",     "content": "What is the capital of France?"},
    {"role": "assistant", "content": "The capital of France is Paris."}
  ],
  ...
}
```

### Override model / system prompt per request

```bash
curl -X POST http://localhost:8000/api/v1/threads/550e8400.../messages \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Explain quantum entanglement.",
    "model": "claude-3-opus-20240229",
    "system_prompt": "You are a physics professor. Use analogies."
  }'
```

---

## Development

### Make targets

```bash
make serve                      # Start FastAPI dev server with hot reload
make test                       # Run unit tests
make integration_tests          # Run integration tests
make lint                       # Run ruff + mypy
make format                     # Auto-format with ruff
make migrate                    # alembic upgrade head
make migrate-down               # alembic downgrade -1
make migrate-autogenerate MSG="add_users"  # Autogenerate a new migration
make docker-up                  # Build + start all Docker services
make docker-down                # Stop all Docker services
make docker-logs                # Tail app container logs
```

### Adding a new Alembic migration

```bash
# 1. Edit src/agent/db/models.py
# 2. Generate migration
make migrate-autogenerate MSG="describe_your_change"
# 3. Review alembic/versions/<timestamp>_<rev>_<slug>.py
# 4. Apply
make migrate
```

---

## Production Notes

- **Docs disabled**: `/docs` and `/redoc` are only available when `APP_ENV != production`
- **Non-root Docker**: the runtime image runs as `appuser` (non-root)
- **Migrations on startup**: `docker-compose.yml` runs `alembic upgrade head` before starting uvicorn
- **LangGraph checkpoint tables** (`checkpoint`, `checkpoint_blobs`, `checkpoint_writes`) are created idempotently by `checkpointer.setup()` at startup — not managed by Alembic
- **Rate limiting** is per-IP using a Redis sorted-set sliding window; safe under horizontal scaling because the Lua script is executed atomically

---

## LangGraph Studio

The agent is still compatible with [LangGraph Studio](https://github.com/langchain-ai/langgraph-studio). Open this folder directly in Studio — it uses the module-level `graph` (compiled without a checkpointer) defined in `langgraph.json`.

```json
{
  "graphs": {
    "agent": "./src/agent/graph.py:graph"
  }
}
```
