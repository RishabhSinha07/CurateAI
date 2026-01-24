# Multi-Agent System Implementation Plan

## Overview

Build 5 specialized agents using LangGraph with AWS Bedrock Claude 3.5 Haiku:
1. **Router** - Domain classification
2. **Interviewer** - Slot filling
3. **Search Architect** - Hybrid search (vector + SQL)
4. **Reranker** - Result filtering
5. **Safety** - Disclaimer injection

## Files to Create

```
app/
├── agents/
│   ├── state.py          # LangGraph state schema
│   ├── router.py         # Domain classification
│   ├── interviewer.py    # Slot filling
│   ├── search.py         # Query expansion + search
│   ├── reranker.py       # Constraint filtering
│   ├── safety.py         # Guardrails
│   └── graph.py          # LangGraph orchestration
├── db/
│   └── repositories/
│       ├── __init__.py
│       ├── domain.py     # Domain queries
│       ├── product.py    # Hybrid search
│       └── session.py    # Session CRUD
├── services/
│   └── search.py         # Hybrid search logic
└── api/
    └── routes/
        └── chat.py       # POST /chat endpoint
```

## Implementation Order

### Phase 1: State & Repositories

**1. `app/agents/state.py`** - LangGraph TypedDict
```python
class AgentState(TypedDict):
    session_id: str
    user_message: str
    domain_id: str | None
    domain_config: dict | None
    extracted_context: dict
    missing_slots: list[str]
    search_results: list[dict]
    final_products: list[dict]
    response: str
    status: str  # active, collecting_info, awaiting_slot, completed
    next_agent: str
```

**2. `app/db/repositories/`** - Data access layer
- `domain.py`: `get_all_domains()`, `get_domain_by_id()`
- `session.py`: `get_or_create_session()`, `update_context()`, `add_message()`
- `product.py`: `hybrid_search()` with vector + JSONB filters

### Phase 2: Core Agents

**3. `app/agents/router.py`** - Domain classification
- Input: user_message, list of domains
- Output: domain_id, confidence score
- Prompt: Classify intent to domain slug

**4. `app/agents/interviewer.py`** - Slot filling
- Input: domain_config.required_slots, extracted_context
- Output: missing_slots, extracted_values, question (if needed)
- Logic: Extract slots from message, ask for missing ones

**5. `app/agents/search.py`** - Query expansion + hybrid search
- Input: extracted_context, domain_id
- Output: search_results (up to 20 products)
- Actions: Expand query terms, call hybrid_search()

**6. `app/agents/reranker.py`** - Constraint-based filtering
- Input: search_results, extracted_context
- Output: final_products (top 3-5)
- Logic: Filter by budget, allergies, preferences

**7. `app/agents/safety.py`** - Guardrail agent
- Input: response, domain safety_disclaimers
- Output: final response with disclaimers
- Logic: Check for medical claims, append warnings

### Phase 3: Orchestration

**8. `app/agents/graph.py`** - LangGraph state machine
```
Entry → Router → Interviewer → [loop if missing slots]
                            ↓
                      Search Architect
                            ↓
                        Reranker
                            ↓
                         Safety → Output
```

Conditional edges:
- If `status == awaiting_slot` → Interviewer (skip Router)
- If `missing_slots` not empty → Generate question, end turn
- If all slots filled → Search Architect

### Phase 4: API Integration

**9. `app/services/search.py`** - Hybrid search service
```python
async def hybrid_search(
    domain_id: UUID,
    query_embedding: list[float],
    filters: dict,  # from extracted_context
    limit: int = 20
) -> list[Product]
```

**10. `app/api/routes/chat.py`** - POST /chat endpoint
```python
@router.post("/chat")
async def chat(request: ChatRequest):
    # 1. Load or create session
    # 2. Add user message
    # 3. Run agent graph
    # 4. Save assistant message
    # 5. Return response
```

## State Machine Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     User Message                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Check session.status == "awaiting_slot"?                   │
│  YES → Skip to Interviewer                                  │
│  NO  → Continue to Router                                   │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   ROUTER AGENT                               │
│  • Classify user intent                                      │
│  • Map to domain (skin-care, melts, etc.)                   │
│  • Set session.current_domain_id                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                 INTERVIEWER AGENT                            │
│  • Load domain.config.required_slots                        │
│  • Check extracted_context for filled slots                 │
│  • Extract new slots from user message                      │
│  • If missing: generate question, set awaiting_slot         │
│  • If complete: proceed to search                           │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        │ Missing slots?            │
        │ YES → Return question     │
        │ NO  → Continue            │
        └─────────────┬─────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              SEARCH ARCHITECT AGENT                          │
│  • Expand query with synonyms/related terms                 │
│  • Generate embedding for expanded query                    │
│  • Execute hybrid search (vector + JSONB + SQL)             │
│  • Return top 20 candidates                                 │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                 RERANKER AGENT                               │
│  • Apply user constraints (budget, allergies)               │
│  • Score products against extracted_context                 │
│  • Select top 3-5 products                                  │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  SAFETY AGENT                                │
│  • Check response for medical claims                        │
│  • Append domain-specific disclaimers                       │
│  • Return final safe response                               │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   Final Response                             │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

1. **Structured outputs** - Use Pydantic models for agent responses
2. **Single LLM** - AWS Bedrock Claude 3.5 Haiku for all agents
3. **Async throughout** - All DB and Bedrock calls async
4. **Session-based memory** - No user profiles, guest-friendly
5. **Config inheritance** - Child domains extend parent slots/disclaimers

## Verification

1. Start containers: `docker compose up -d`
2. Generate embeddings: `docker compose exec app python -m app.services.generate_embeddings`
3. Test endpoint:
```bash
# Start conversation
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want something for better sleep"}'

# Continue with slot answer
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<returned-id>", "message": "I prefer capsules"}'
```







## Implemented
### Phase 1: What's implemented:
- Product Embeddings: Successfully generated 1024-dimensional vectors for all 34 products using AWS Titan v2 and stored them in the products table.
- Domain Repository: Created 
app/db/repositories/domain.py
 to handle AI personas and category configurations.
- Product Repository: Created 
app/db/repositories/product.py
 containing the core Hybrid Search logic. It seamlessly combines vector similarity (semantic search) with PostgreSQL JSONB filters (metadata filtering).
- Session Repository: Created 
app/db/repositories/session.py
 to manage chat history and the "short-term memory" (extracted context) for multi-turn conversations.