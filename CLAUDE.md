# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CurateAI is a multi-agent AI consultation system for personalized product recommendations. It uses LangGraph to orchestrate specialized agents, a knowledge graph (NetworkX + YAML) for domain intelligence, and hybrid search (pgvector + JSONB filters) over a polymorphic product catalog. The system is multi-tenant with API key authentication.

## Development Commands

```bash
# Start all services (PostgreSQL + pgvector, FastAPI app with hot-reload)
docker compose up -d

# Run migrations
docker compose exec app alembic upgrade head

# Seed sample data (Wellbeing Nutrition products)
docker compose exec app python -m app.db.seed

# Generate embeddings for seeded products
docker compose exec app python -m app.services.generate_embeddings

# Health check
curl http://localhost:8000/health

# View app logs
docker compose logs -f app

# Access database
docker compose exec db psql -U postgres -d curateai

# Create a new migration
docker compose exec app alembic revision --autogenerate -m "description"

# Reset database completely
docker compose down -v && docker compose up -d
```

### Linting & Type Checking

```bash
# Lint (ruff, line-length=100, py311)
ruff check app/
ruff check --fix app/

# Type check (strict mode, pydantic plugin)
mypy app/
```

### Testing

```bash
# Run all tests
docker compose exec app pytest

# Run a single test file
docker compose exec app pytest tests/unit/agents/test_router.py

# Run a specific test
docker compose exec app pytest tests/unit/agents/test_router.py::test_function_name -v

# Async mode is auto-configured (asyncio_mode = "auto" in pyproject.toml)
```

## Architecture

### LangGraph State Machine (10 nodes)

The `ConsultationGraph` (`app/agents/graph.py`) compiles a LangGraph `StateGraph` with conditional routing. All agent state flows through `AgentState` (`app/agents/state.py`).

```
Entry (should_route_to):
├─ status="active" → router
├─ status="awaiting_slot" → router (with safety override for slot answers)
├─ status="completed" → refinement
└─ status="fallback_conversation" → fallback

Router Decision (after_router):
├─ intent="fallback" → fallback
├─ intent="journey" → journey
├─ intent="ingredient_info" → ingredient_info
├─ intent="direct_product" → search (bypass interviewer)
├─ intent="filter" → refinement
└─ default → interviewer

Interviewer Decision (after_interviewer):
├─ problem just identified → initial_products → interviewer
├─ all slots filled → search → reranker → safety → END
├─ missing slots → END (status=awaiting_slot)
└─ user accepted initial products → safety → END
```

### Agent Responsibilities

| Agent | Purpose | LLM? |
|-------|---------|------|
| **Router** | Classify intent, map to domain, extract problem | Yes |
| **Interviewer** | Fill required slots via graph-driven questions | Yes |
| **Initial Products** | Fetch showcase products before interview completes | No (semantic search only) |
| **Search Architect** | Build query from graph ingredients, execute hybrid search | No |
| **Reranker** | Filter results by safety constraints (allergies, diet, pregnancy) | No (graph-based) |
| **Safety** | Generate final response with disclaimers | Yes |
| **Journey** | Match journey bundles, fetch products with usage guidance | Yes |
| **Refinement** | Detect post-completion intent (refine, re-personalize, new topic) | Yes |
| **Fallback** | Handle out-of-scope queries, search full catalog | Yes |
| **Ingredient Info** | Answer educational ingredient questions without disrupting flow | Yes |

### Knowledge Graph System

Domain intelligence lives in YAML files (`app/knowledge/graphs/{domain}.yaml`) loaded into NetworkX DiGraphs at app startup.

- **Graph Loader** (`app/knowledge/graph_loader.py`): YAML → NetworkX, cached at startup via FastAPI lifespan
- **Query Engine** (`app/knowledge/query_engine.py`): Problem matching, ingredient boosting, constraint filtering
- **Dynamic Questions** (`app/knowledge/dynamic_questions.py`): Generates interview questions from graph metadata

The graph drives: slot requirements, search query expansion (problem → ingredients), safety constraint checks, and interview question generation.

### Key State Fields in AgentState

- `extracted_context.graph_state.filled_attributes` — Slot values from interview
- `extracted_context.candidate_problem` — Unconfirmed problem for initial_products search
- `extracted_context.pending_slot_question` — Current question (used by router's awaiting-slot safety override)
- `extracted_context.inline_constraints` — Budget, diet, format from single message
- `intent_type` — "query", "journey", "direct_product", "ingredient_info", "filter"
- `status` — "active", "collecting_info", "awaiting_slot", "completed", "out_of_scope", "fallback_conversation"

### Multi-Tenancy & Auth

- **API key auth** (`app/api/middleware/auth.py`): X-API-Key header → SHA-256 hash → DB lookup with IP allowlist and expiry check
- **Rate limiting** (`app/api/middleware/rate_limit.py`): In-memory sliding window per tenant (single-instance; needs Redis for multi-instance)
- **Seed tenant** (UUID `00000000-0000-0000-0000-000000000001`): Fallback for requests without API key (backward compatibility)
- **TenantContext** dataclass flows through all layers: enabled_domains, rate_limit_rpm, daily_cost_cap_cents

### Database Layer

- **ORM**: SQLAlchemy 2.0 async with asyncpg (`app/db/session.py`)
- **Models** (`app/db/models.py`): Tenant, ApiKey, Product, ChatSession, ChatMessage, JourneyBundle, ProductEvent
- **Repositories** (`app/db/repositories/`): SessionRepository, ProductRepository, TenantRepository, JourneyBundleRepository
- **Hybrid search** (`ProductRepository.hybrid_search`): Cosine similarity on `description_embedding` (Vector 1024) + JSONB attribute filters + price filter, with fallback to lower similarity threshold if <3 results

### LLM Integration

- **Model**: Amazon Nova Pro via AWS Bedrock (`app/agents/llm.py`)
- **Embeddings**: Amazon Titan Embed v2, 1024 dimensions (`app/services/embeddings.py`)
- **Retry logic**: Tenacity with exponential backoff (1-8s, 4 attempts) for transient Bedrock errors
- **LLM factory**: `get_bedrock_llm()` returns a retrying runnable wrapper around ChatBedrock

## Design Decisions

| Aspect | Decision |
|--------|----------|
| **Domain Hierarchy** | 2 levels max (parent → child); child inherits + extends parent config |
| **Knowledge Graphs** | YAML + NetworkX (Phase 1); `use_db_graphs` setting for future DB-backed phase |
| **Vector Search** | Single description embedding per product (not multi-vector) |
| **Memory** | Session-only (`extracted_context` JSONB), no user profiles (privacy-friendly) |
| **Slot-filling** | Ask all required slots upfront; one more pass if missing, then proceed |
| **Reranker** | Graph-based constraint filtering, no LLM re-ranking |
| **Awaiting-slot safety** | Router overrides out_of_scope classification when pending_slot_question exists (protects single-word answers like "Vegetarian") |
| **Refinement UX** | Short contextual message for result filtering (no full LLM consultation repeat) |
| **Product attributes** | JSONB polymorphic per domain (no schema changes needed for new domains) |

## Configuration

Settings are in `app/config.py` (Pydantic BaseSettings, loaded from env vars / `.env`).

Key settings: `DATABASE_URL`, `AWS_REGION`, `BEDROCK_MODEL_ID` (default: `us.amazon.nova-pro-v1:0`), `EMBEDDING_MODEL_ID`, `EMBEDDING_DIMENSIONS` (1024), `ENVIRONMENT` (development/staging/production — controls docs visibility and log format).

## API Endpoints

- `POST /chat` — Main consultation endpoint. Takes `{message, session_id?}`, returns `{session_id, response, status, products, suggested_replies, journey_info?}`
- `POST /events` — Product event tracking (click, add_to_cart, purchase)
- `GET /health` — Database connectivity check
- `/admin` — Admin routes

## Middleware Stack (outermost → innermost)

RequestLogging → CORS → Auth/RateLimit (per-route dependency)
