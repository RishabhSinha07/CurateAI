# Database Architecture

This document explains the database design decisions for CurateAI.

## Overview

CurateAI uses **PostgreSQL + pgvector** as a single unified database for:
- Relational data (domains, sessions, messages)
- Product catalog with flexible JSONB attributes
- Vector embeddings for semantic search

```
┌─────────────────────────────────────────────────────────┐
│                   PostgreSQL 16                         │
├─────────────────────────────────────────────────────────┤
│  pgvector extension                                     │
│  ├── Vector similarity search (cosine distance)        │
│  └── IVFFlat indexing for fast approximate search      │
├─────────────────────────────────────────────────────────┤
│  JSONB support                                          │
│  ├── Flexible product attributes per domain            │
│  └── GIN indexes for fast attribute queries            │
└─────────────────────────────────────────────────────────┘
```

---

## Why PostgreSQL + pgvector?

### The Core Requirement: Hybrid Search

CurateAI needs to combine **semantic search** with **hard filters** in a single query:

```sql
-- "Find soothing products for oily skin under $50"
SELECT p.name, p.price, p.attributes
FROM products p
WHERE p.domain_id = :skin_care_id
  AND p.attributes->'skin_type' ? 'oily'           -- JSONB filter
  AND p.attributes->>'is_fragrance_free' = 'true'  -- JSONB filter
  AND p.price < 50                                  -- SQL filter
  AND p.inventory_count > 0                         -- SQL filter
ORDER BY p.description_embedding <=> :query_vector  -- Vector similarity
LIMIT 5;
```

This single query performs:
1. Domain filtering (FK lookup)
2. JSONB attribute filtering (GIN index)
3. SQL column filtering (B-tree index)
4. Vector similarity ranking (pgvector)

### Alternatives Considered

| Database | Vector Search | Flexible Filters | Transactions | Verdict |
|----------|---------------|------------------|--------------|---------|
| **PostgreSQL + pgvector** | ✅ Native | ✅ JSONB + SQL | ✅ ACID | ✅ Chosen |
| Pinecone | ✅ Excellent | ⚠️ Metadata only | ❌ None | Need 2nd DB |
| Weaviate | ✅ Good | ⚠️ Limited | ❌ None | Need 2nd DB |
| MongoDB + Atlas Vector | ✅ Good | ✅ Flexible | ⚠️ Limited | Viable alternative |
| DynamoDB | ❌ None | ❌ Rigid | ⚠️ Limited | Need OpenSearch |
| Redis + RediSearch | ✅ Good | ⚠️ Limited | ❌ None | Better for caching |

### Decision Factors

| Factor | PostgreSQL Advantage |
|--------|---------------------|
| **Single system** | One database to manage, deploy, backup |
| **Hybrid queries** | Vector + SQL + JSONB in one query |
| **ACID transactions** | Session state consistency |
| **Cost** | pgvector is free; vector DBs charge per query |
| **Familiar tooling** | SQL, Alembic migrations, mature ecosystem |
| **Sufficient scale** | Handles 100K+ products easily |

---

## Schema Design

### Entity Relationship Diagram

```
┌─────────────┐       ┌─────────────┐
│   domains   │       │  products   │
├─────────────┤       ├─────────────┤
│ id (PK)     │◄──┐   │ id (PK)     │
│ name        │   │   │ domain_id (FK)──────┐
│ slug        │   │   │ sku         │       │
│ parent_id(FK)───┘   │ name        │       │
│ config      │       │ price       │       │
│ persona     │       │ attributes  │ JSONB │
└─────────────┘       │ embedding   │ vector│
       │              └─────────────┘
       │ current_domain_id
       ▼
┌─────────────┐       ┌─────────────┐
│chat_sessions│       │chat_messages│
├─────────────┤       ├─────────────┤
│ id (PK)     │◄──────│ session_id  │
│ domain_id   │       │ id (PK)     │
│ context     │ JSONB │ role        │
│ status      │       │ content     │
└─────────────┘       │ product_ids │ UUID[]
                      └─────────────┘
```

### Table Purposes

#### `domains` — AI Specialist Configuration

Stores how the AI should behave for each product category.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | Primary key |
| `name` | VARCHAR(50) | Display name ("Skin Care") |
| `slug` | VARCHAR(50) | URL-safe identifier ("skin-care") |
| `parent_domain_id` | UUID (FK) | Hierarchy (wellness → skin-care) |
| `config` | JSONB | Required slots, filters, disclaimers |
| `system_persona` | TEXT | LLM persona instructions |

**Config JSONB Structure:**
```json
{
  "required_slots": ["skin_type", "skin_concern"],
  "optional_slots": ["budget", "brand_preference"],
  "search_filters": ["is_fragrance_free", "is_vegan"],
  "safety_disclaimers": ["Consult a dermatologist for medical conditions."]
}
```

**Access Pattern:** Read-heavy, rarely updated. Loaded at startup or cached.

---

#### `products` — Universal Product Catalog

Single table for all products across all domains. Domain-specific data lives in JSONB.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | Primary key |
| `domain_id` | UUID (FK) | Which domain this belongs to |
| `sku` | VARCHAR(100) | Unique product identifier |
| `name` | VARCHAR(255) | Product name |
| `brand` | VARCHAR(100) | Brand name |
| `description` | TEXT | Full description (embedded) |
| `price` | DECIMAL(10,2) | Price in USD |
| `inventory_count` | INT | Stock level |
| `attributes` | JSONB | Domain-specific specs |
| `description_embedding` | vector(1024) | Titan v2 embedding |

**Attributes JSONB — Skin Care Example:**
```json
{
  "skin_type": ["oily", "combination"],
  "skin_concern": ["acne", "large_pores"],
  "active_ingredients": ["Niacinamide", "Zinc"],
  "texture": "serum",
  "is_fragrance_free": true,
  "is_vegan": true
}
```

**Attributes JSONB — Power Tools Example:**
```json
{
  "project_type": ["construction", "masonry"],
  "material": ["concrete", "wood", "metal"],
  "voltage": "18V",
  "is_brushless": true,
  "is_cordless": true,
  "torque_in_lbs": 1200
}
```

**Access Pattern:** Heavy reads with complex filtering. Updated via admin/import.

---

#### `chat_sessions` — Conversation State

Tracks the current state of a user's consultation.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | Session identifier |
| `user_id` | UUID | Optional user reference |
| `current_domain_id` | UUID (FK) | Active specialist |
| `extracted_context` | JSONB | Filled slots |
| `status` | VARCHAR(30) | active, collecting_info, completed |

**Extracted Context JSONB:**
```json
{
  "skin_type": "oily",
  "skin_concern": "dark_spots",
  "sensitivity": "low",
  "budget": "mid-range"
}
```

**Access Pattern:** Read + write on every message. Key-value style access by session ID.

---

#### `chat_messages` — Conversation History

Chronological log of all messages in a session.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | Message identifier |
| `session_id` | UUID (FK) | Parent session |
| `role` | VARCHAR(15) | user, assistant, system |
| `content` | TEXT | Message text |
| `suggested_product_ids` | UUID[] | Products recommended |
| `created_at` | TIMESTAMPTZ | For ordering |

**Access Pattern:** Append-only writes. Read last N messages by session_id.

---

## Indexing Strategy

### B-tree Indexes (Equality & Range)

```sql
-- Fast domain lookups
CREATE INDEX idx_products_domain ON products(domain_id);

-- Fast session message retrieval
CREATE INDEX idx_chat_messages_session ON chat_messages(session_id);
```

### GIN Index (JSONB Queries)

```sql
-- Fast attribute filtering
CREATE INDEX idx_products_attributes ON products USING GIN (attributes);

-- Enables queries like:
WHERE attributes->'skin_type' ? 'oily'
WHERE attributes->>'is_vegan' = 'true'
WHERE attributes @> '{"texture": "serum"}'
```

### Vector Index (Similarity Search)

```sql
-- IVFFlat for approximate nearest neighbor search
CREATE INDEX idx_products_embedding ON products
USING ivfflat (description_embedding vector_cosine_ops)
WITH (lists = 100);
```

**Note:** IVFFlat requires data to exist before index creation. Created after embeddings are generated.

**Index Selection Guide:**
| Data Size | Index Type | Trade-off |
|-----------|------------|-----------|
| < 10K vectors | None (exact search) | 100% recall, slower |
| 10K - 1M vectors | IVFFlat | 95%+ recall, fast |
| > 1M vectors | HNSW | 99% recall, fastest, more RAM |

---

## Query Patterns

### 1. Hybrid Search (Most Important)

Find semantically similar products with attribute filters:

```sql
SELECT
  p.id,
  p.name,
  p.brand,
  p.price,
  p.attributes,
  p.description_embedding <=> :query_embedding AS distance
FROM products p
WHERE p.domain_id = :domain_id
  AND p.is_active = true
  AND p.inventory_count > 0
  AND p.attributes->'skin_type' ? :skin_type
  AND (:max_price IS NULL OR p.price <= :max_price)
ORDER BY distance
LIMIT 10;
```

### 2. Slot Validation

Check if user's response matches valid attribute values:

```sql
SELECT DISTINCT jsonb_array_elements_text(attributes->'skin_type') as skin_type
FROM products
WHERE domain_id = :domain_id;
```

### 3. Session State Management

```sql
-- Get session with domain config
SELECT
  s.*,
  d.config,
  d.system_persona
FROM chat_sessions s
JOIN domains d ON s.current_domain_id = d.id
WHERE s.id = :session_id;

-- Update extracted context (atomic)
UPDATE chat_sessions
SET extracted_context = extracted_context || :new_context,
    updated_at = now()
WHERE id = :session_id;
```

### 4. Recent Messages for Context

```sql
SELECT role, content
FROM chat_messages
WHERE session_id = :session_id
ORDER BY created_at DESC
LIMIT 5;
```

---

## Data Flow

```
User Message
     │
     ▼
┌─────────────────┐
│ Load Session    │ ← chat_sessions (by session_id)
│ + Domain Config │ ← domains (by current_domain_id)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Load Recent     │ ← chat_messages (last 5)
│ Messages        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Agent Pipeline  │
│ (Router →       │
│  Interviewer → │
│  Search →      │ ← products (hybrid query)
│  Reranker →    │
│  Safety)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Save Message    │ → chat_messages (INSERT)
│ Update Context  │ → chat_sessions (UPDATE)
└─────────────────┘
```

---

## Scaling Considerations

### Current Setup (MVP)
- Single PostgreSQL instance
- Handles ~100K products, ~10K concurrent sessions
- pgvector IVFFlat index

### Future Scale Options

| Scale | Solution |
|-------|----------|
| **More products (1M+)** | HNSW index, read replicas |
| **More traffic** | Connection pooling (PgBouncer), read replicas |
| **Multi-region** | Aurora PostgreSQL Global Database |
| **Serverless** | Aurora Serverless v2 |
| **Extreme vector scale** | Offload to dedicated vector DB (Pinecone) |

### When to Consider Alternatives

| Trigger | Action |
|---------|--------|
| Vector search > 50ms p99 | Add HNSW index or dedicated vector DB |
| Write throughput bottleneck | Shard sessions by user_id |
| Global latency requirements | Multi-region Aurora |
| Cost optimization at scale | Evaluate DynamoDB for sessions |

---

## Backup & Recovery

```bash
# Backup
docker compose exec db pg_dump -U postgres curateai > backup.sql

# Restore
docker compose exec -T db psql -U postgres curateai < backup.sql

# Point-in-time recovery (production)
# Use Aurora/RDS with automated backups
```

---

## Local Development

```bash
# Connect to database
docker compose exec db psql -U postgres -d curateai

# Useful queries
\dt                              -- List tables
\d products                      -- Describe table
SELECT count(*) FROM products;   -- Count products
SELECT * FROM domains;           -- View domains
```

---

## Summary

| Aspect | Decision |
|--------|----------|
| **Database** | PostgreSQL 16 + pgvector |
| **Why** | Hybrid search, JSONB flexibility, ACID, single system |
| **Vector dims** | 1024 (AWS Titan v2) |
| **Indexing** | B-tree + GIN + IVFFlat |
| **Scale ceiling** | ~1M products before needing dedicated vector DB |
