# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CurateAI is a multi-agent AI consultation system for product recommendations. It uses a polymorphic database schema to support multiple domains (wellness/skincare, tools, etc.) with domain-specific slot requirements and search filters.

## Architecture

### Multi-Agent System

Five specialized agents work together in a supervisor pattern:

1. **Router Agent** - Classifies user intent and maps to a domain (e.g., "dark spots" → skin-care)
2. **Interviewer Agent** - Fills required slots by asking clarifying questions before search
3. **Search Architect Agent** - Expands queries and executes hybrid search (vector + SQL filters)
4. **Reranker Agent** - Filters search results based on user constraints (budget, allergies, etc.)
5. **Safety Agent** - Monitors output for medical claims and adds appropriate disclaimers

### State Machine Flow

- `AWAITING_SLOT`: System asked a question, waiting for user response
- `collecting_info`: Gathering required slots before search
- `completed`: Consultation finished with recommendations

The Orchestrator checks session state before routing:
1. If awaiting slot answer → send to Interviewer (bypass Router)
2. If intent drift detected → trigger Re-Route
3. If new conversation → trigger Router

### Database Schema (PostgreSQL + pgvector)

- **`domains`** - AI persona config, required slots, search filters per category
- **`products`** - Universal catalog with JSONB `attributes` for domain-specific specs and `description_embedding` vector(1024) for semantic search
- **`chat_sessions`** - Active state with `current_domain_id` and `extracted_context` JSONB (short-term memory)
- **`chat_messages`** - Chronological history with `suggested_product_ids`

### Context Management

- **Long-term memory**: `extracted_context` JSONB in sessions (e.g., `{"skin_type": "oily"}`)
- **Short-term memory**: Last 3-5 messages from `chat_messages`
- **System prompt injection**: Current extracted facts to prevent repeated questions

## Design Decisions

| Aspect | Decision |
|--------|----------|
| **Domain Hierarchy** | 2 levels max (parent → child, e.g., wellness → skin-care) |
| **Config Inheritance** | Child domains inherit + extend parent's slots/persona/safety rules |
| **Vector Search** | Single description embedding per product (not multi-vector) |
| **Memory** | Session-only, no user profiles (privacy-friendly, guests welcome) |
| **Slot-filling** | Ask all required slots upfront, one more pass if missing, then proceed |
| **Reranker** | Separate from Search Architect for filtering based on constraints |

## Tech Stack

```
┌──────────────────────────────────────────────────┐
│                  FastAPI                         │
│            (async, Pydantic models)              │
├──────────────────────────────────────────────────┤
│                  LangGraph                       │
│         (state machine, checkpointing)           │
├──────────────────────────────────────────────────┤
│                 AWS Bedrock                      │
│   Claude 3.5 Haiku (agents)                      │
│   Titan Embed v2 (embeddings, 1024 dims)         │
├──────────────────────────────────────────────────┤
│          PostgreSQL + pgvector                   │
│     (products, domains, sessions, messages)      │
└──────────────────────────────────────────────────┘
```

### Dependencies

See `pyproject.toml` for full list. Key dependencies:
- **FastAPI** + **uvicorn** - Async web framework
- **SQLAlchemy 2.0** + **asyncpg** - Async database ORM
- **pgvector** - Vector similarity search
- **LangGraph** - Multi-agent state machine
- **langchain-aws** - AWS Bedrock integration
- **boto3** - AWS Bedrock for Titan embeddings
- **Alembic** - Database migrations

## Project Structure

```
curate-ai/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point ✅
│   ├── config.py               # Pydantic settings ✅
│   ├── api/
│   │   ├── routes/
│   │   │   └── chat.py         # POST /chat endpoint (TODO)
│   │   └── deps.py             # dependencies (TODO)
│   ├── agents/
│   │   ├── graph.py            # LangGraph state machine (TODO)
│   │   ├── router.py           # Router agent (TODO)
│   │   ├── interviewer.py      # Slot-filler agent (TODO)
│   │   ├── search.py           # Search Architect agent (TODO)
│   │   ├── reranker.py         # Reranker agent (TODO)
│   │   └── safety.py           # Safety agent (TODO)
│   ├── db/
│   │   ├── models.py           # SQLAlchemy models ✅
│   │   ├── session.py          # Async DB connection ✅
│   │   ├── seed_wellbeing.py   # Wellbeing Nutrition products ✅
│   │   └── repositories/       # data access layer (TODO)
│   └── services/
│       ├── embeddings.py       # AWS Titan v2 embedding service ✅
│       ├── generate_embeddings.py  # Script to embed products ✅
│       └── search.py           # hybrid search logic (TODO)
├── alembic/
│   ├── env.py                  # Async migration config ✅
│   ├── script.py.mako          # Migration template ✅
│   └── versions/
│       ├── 001_initial_schema.py  # Initial tables ✅
│       └── 002_change_embedding_dimension.py  # Titan v2 (1024 dims) ✅
├── tests/
├── .env.example                # Environment template ✅
├── .gitignore                  # Git ignores ✅
├── .dockerignore               # Docker ignores ✅
├── alembic.ini                 # Alembic config ✅
├── docker-compose.yml          # Local dev services ✅
├── Dockerfile                  # App container ✅
├── pyproject.toml              # Dependencies ✅
├── CLAUDE.md                   # Project guidance
└── Database.md                 # Database architecture docs ✅
```

## Database Schema

### domains table
```sql
CREATE TABLE domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) UNIQUE NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    parent_domain_id UUID REFERENCES domains(id),  -- NULL for root
    config JSONB NOT NULL,
    -- config: {"required_slots": [], "optional_slots": [], "search_filters": [], "safety_disclaimers": []}
    system_persona TEXT,
    is_active BOOLEAN DEFAULT TRUE
);
```

### Config merge logic (application layer)
Child domains inherit parent config arrays and extend them. Child's `system_persona` overrides parent if set.

## Configuration Decisions

| Setting | Value | Notes |
|---------|-------|-------|
| **AWS Bedrock Region** | `us-east-1` | Primary region for Claude API calls |
| **Authentication** | Open (none) | No auth for MVP; add later as needed |
| **Deployment** | Local Docker | MVP runs via docker-compose; AWS deployment planned for later |

## Quick Start

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env with your AWS credentials

# 2. Start services
docker compose up -d

# 3. Run migrations
docker compose exec app alembic upgrade head

# 4. Seed sample data
docker compose exec app python -m app.db.seed

# 5. Verify
curl http://localhost:8000/health
```

## Useful Commands

```bash
# View logs
docker compose logs -f app

# Access database
docker compose exec db psql -U postgres -d curateai

# Create new migration
docker compose exec app alembic revision --autogenerate -m "description"

# Reset database
docker compose down -v && docker compose up -d

# Run tests (when implemented)
docker compose exec app pytest
```

## Seed Data

Data sourced from [Wellbeing Nutrition](https://wellbeingnutrition.com/)

### Domain Hierarchy
```
Wellness (root)
├── Melts         → health_goal (oral thin strips)
├── Collagen      → skin_concern, collagen_preference
├── Slow Capsules → health_goal, gender
└── Effervescent  → health_goal
```

### Products (34 total)
| Domain | Count | Examples |
|--------|-------|----------|
| Melts | 11 | Vitamin B12, D3, Sleep, Energy, Hair, Iron, Calm |
| Collagen | 8 | Pure Marine, Glow, Beauty, Matcha, Vegan Pro |
| Slow Capsules | 10 | Magnesium, Multi for Her/Him, Probiotic, PCOS, Liver |
| Effervescent | 5 | Probiotic, Daily Greens, Glutathione, ACV, Vitamin C |

### Product Fields
Each product includes: `name`, `brand`, `description`, `price`, `product_url`, `image_url`, and domain-specific `attributes` (health_goal, ingredients, format, etc.)

## Implementation Progress

- [x] Database models (Domain, Product, ChatSession, ChatMessage)
- [x] Alembic migrations setup
- [x] Docker Compose (PostgreSQL + pgvector, FastAPI app)
- [x] Seed data script
- [x] FastAPI app skeleton with health check
- [x] Embeddings service (AWS Titan v2, 1024 dims)
- [ ] Generate embeddings for products (requires AWS creds)
- [ ] Repository layer (data access patterns)
- [ ] Router Agent
- [ ] Interviewer Agent
- [ ] Search Architect Agent
- [ ] Reranker Agent
- [ ] Safety Agent
- [ ] LangGraph orchestration
- [ ] POST /chat endpoint
- [ ] Integration tests
