# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CurateAI is a multi-agent AI consultation system for personalized product recommendations. It uses LangGraph to orchestrate specialized agents, a knowledge graph (NetworkX + YAML) for domain intelligence, and hybrid search (pgvector + JSONB filters) over a polymorphic product catalog. The system is multi-tenant with JWT authentication.

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

# Create an admin user for the dashboard
docker compose exec app python -m scripts.create_admin_user \
  --email admin@company.com --password secret --tenant-slug default --role owner
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

Authentication uses a two-layer approach: JWT verification at API Gateway, tenant resolution at the backend.

**JWT Authentication (primary — widget `/chat` route):**

```
Customer site loads → customer backend mints JWT (15 min TTL, RS256)
  → Widget sends Bearer token to API Gateway
  → Lambda authorizer (CurateAI-JWTAuthorizer):
      1. Decode JWT, extract client_id
      2. Look up DynamoDB (CurateAI-WidgetClients) → get JWKS URL, tenant_id
      3. Fetch customer's JWKS (cached in Lambda memory)
      4. Verify signature, check exp/aud/iss, validate Origin
      5. Pass tenant_id to backend via authorizer context
  → API Gateway caches result ~5 min
  → FastAPI backend resolves tenant from authorizer context
```

- **DynamoDB table** (`CurateAI-WidgetClients`): Stores per-customer config — `client_id` (PK), `jwks_url`, `allowed_origins`, `tenant_id`, `expected_iss`, `expected_aud`, `is_active`
- **Lambda authorizer** (`infrastructure/lambda/jwt-authorizer/index.mjs`): Verifies RS256/ES256 JWTs, caches JWKS and client configs in memory
- **Onboarding scripts**: `scripts/generate_jwks.py` (key pair generation), `scripts/create_widget_client.py` (DynamoDB registration)

**Admin Dashboard Authentication (self-signed JWT):**

Dashboard endpoints use email + password authentication with self-signed JWTs. No external auth provider required.

```
Admin calls POST /admin/dashboard/login {email, password}
  → Backend verifies bcrypt hash against admin_users table
  → Returns HS256 JWT (signed with JWT_SECRET, 24hr TTL)
  → Admin sends Bearer token on all /admin/dashboard/* requests
  → Middleware decodes JWT, looks up admin_users → resolves tenant_id
```

- **Model**: `AdminUser` (`app/db/models.py`) — maps email + password_hash to a tenant
- **Middleware**: `app/api/middleware/cognito.py` — `get_admin_context` dependency decodes JWT → returns `AdminContext(admin_id, tenant_id, email, role)`
- **Config**: `JWT_SECRET` (required in production), `JWT_EXPIRY_HOURS` (default: 24)

**Admin onboarding:**

```bash
# Register an admin user for a tenant
docker compose exec app python -m scripts.create_admin_user \
  --email admin@company.com \
  --password secure-password \
  --tenant-slug acme \
  --role owner
```

**API key auth (fallback for local dev):**

- `app/api/middleware/auth.py` checks: (1) Lambda authorizer context → (2) X-API-Key header → (3) seed tenant fallback
- **Rate limiting** (`app/api/middleware/rate_limit.py`): In-memory sliding window per tenant (single-instance; needs Redis for multi-instance)
- **TenantContext** dataclass flows through all layers: enabled_domains, rate_limit_rpm, daily_cost_cap_cents

**Customer onboarding flow:**

```bash
# 1. Generate RSA key pair for the customer
python3 -m scripts.generate_jwks --kid key-1 --out-dir ./keys/<customer-name>

# 2. Register in DynamoDB
python3 -m scripts.create_widget_client \
  --client-id <id> \
  --tenant-id <tenant-uuid> \
  --jwks-url https://<domain>/.well-known/jwks.json \
  --origins https://<domain> \
  --iss <domain>

# 3. Give customer: private.pem, jwks.json, integration guide
```

### Database Layer

- **ORM**: SQLAlchemy 2.0 async with asyncpg (`app/db/session.py`)
- **Models** (`app/db/models.py`): Tenant, ApiKey, AdminUser, Product, ChatSession, ChatMessage, JourneyBundle, ProductEvent
- **Repositories** (`app/db/repositories/`): SessionRepository, ProductRepository, TenantRepository, JourneyBundleRepository, DashboardRepository
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
| **Widget auth** | Customer-signed JWTs (RS256) verified via Lambda authorizer + DynamoDB JWKS lookup. Each customer hosts their own JWKS. No shared secrets — asymmetric signing means leaked keys only affect one customer. |
| **API Gateway auth** | Lambda JWT authorizer on `/chat` (widget), Cognito on `/events` and `/admin` (product upload, key rotation). API key kept as fallback for local dev. |
| **Dashboard auth** | Self-signed HS256 JWTs via `admin_users` table (email + bcrypt password). No Cognito dependency. `JWT_SECRET` env var required in production. |

## Configuration

Settings are in `app/config.py` (Pydantic BaseSettings, loaded from env vars / `.env`).

Key settings: `DATABASE_URL`, `AWS_REGION`, `BEDROCK_MODEL_ID` (default: `us.amazon.nova-pro-v1:0`), `EMBEDDING_MODEL_ID`, `EMBEDDING_DIMENSIONS` (1024), `ENVIRONMENT` (development/staging/production — controls docs visibility and log format), `JWT_SECRET` (signs admin dashboard tokens — **change in production**), `JWT_EXPIRY_HOURS` (default: 24).

## API Endpoints

- `POST /chat` — Main consultation endpoint. Takes `{message, session_id?}`, returns `{session_id, response, status, products, suggested_replies, journey_info?}`
- `POST /events` — Product event tracking (click, add_to_cart, purchase)
- `GET /health` — Database connectivity check
- `/admin/products` — Product upload (Cognito auth)
- `/admin/api-keys/rotate` — API key rotation (Cognito auth)
- `/admin/dashboard/*` — Dashboard analytics (self-signed JWT auth, see below)

### Dashboard API (`app/api/routes/dashboard.py`)

All dashboard endpoints require `Authorization: Bearer <token>` from the login endpoint. All query endpoints take `start_date` and `end_date` query params (format: `YYYY-MM-DD`). Data is scoped to the authenticated admin's tenant.

**Authentication:**

```
POST /admin/dashboard/login
  Body: {"email": "...", "password": "..."}
  Returns: {access_token, token_type, admin_id, email, role, tenant_id}
```

**Endpoints:**

| Endpoint | Extra Params | Returns |
|----------|-------------|---------|
| `GET /admin/dashboard/overview` | — | KPI cards: total_sessions, unique_users, total_messages, avg_messages_per_session, avg_session_duration_seconds, completion_rate_pct, drop_off_rate_pct, status_breakdown, domain_breakdown |
| `GET /admin/dashboard/traffic` | `granularity` (day/week/month) | daily_sessions (line chart data), peak_hours (heatmap: day_of_week x hour) |
| `GET /admin/dashboard/funnel` | — | Conversion funnel: total_sessions → sessions_with_recommendations → clicks → add_to_cart → purchases (each with total + unique_sessions). Daily event trend. |
| `GET /admin/dashboard/products` | `sort_by` (recommended/clicked/conversion), `limit` | Top products table: name, brand, price, times_recommended, clicks, add_to_cart, purchases, conversion_pct. Plus never_recommended_count. |
| `GET /admin/dashboard/products/{id}` | — | Single product drill-down: recommendation count, event breakdown (click/add_to_cart/purchase), daily event trend. |

**Data sources (no extra tables needed):**

| Metric Category | Source Tables |
|----------------|--------------|
| Traffic & sessions | `chat_sessions` (status, domain, created_at, updated_at) |
| Message counts | `chat_messages` (role, created_at) |
| Recommendations | `chat_messages.suggested_product_ids` (UUID array, unnested) |
| Conversion events | `product_events` (event_type: click/add_to_cart/purchase) |
| Product info | `products` (name, brand, price) |

## Middleware Stack (outermost → innermost)

RequestLogging → CORS → Auth/RateLimit (per-route dependency)

## Widget Integration

The CurateAI widget (`curateai-widget` repo) is an embeddable chatbot that third-party sites add to their pages. Hosted on Vercel at `https://curateai-widget.vercel.app/curateai-widget.js`.

**Architecture:**
```
Customer's site → widget JS loads → calls customer's /api/token endpoint
  → gets JWT → widget sends JWT to API Gateway → Lambda authorizer verifies
  → request reaches FastAPI backend → products returned
```

**Widget config supports:** `apiUrl`, `apiKey` (legacy), `getAuthToken` (JWT), `welcomeTopics`, theme customization, and callbacks (`onProductClick`, `onMessage`, etc.).

**Current clients:**
| Client | client_id | Tenant |
|--------|-----------|--------|
| CurateAI Dashboard | `curateai_dashboard` | (deferred to API key) |
| Rural Equip | `re_001` | `6a77550b-...` (rural-equipment) |
