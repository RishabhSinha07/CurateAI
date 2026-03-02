# CurateAI — Post-MVP P0 Requirements

**Date:** 2026-03-01 | **Status:** Draft | **Author:** Engineering

**Scale target:** 1 company, ~5 active end-customers/day, single Fargate task. Build with tenant-awareness baked in so we don't have to rewrite when we add company #2.

---

## Current State Summary

Single-tenant MVP on Fargate Spot (0.5 vCPU, 1 GB RAM, 1 task). Cognito + API Gateway handle auth at the edge, but the app never extracts JWT claims — it doesn't know who's calling. No tenant concept, no session ownership, DB credentials hardcoded in CDK, no application metrics, no rate limiting. The product catalog is a single global pool.

---

## 1. Permissions & Access Control

### What exists
- Cognito User Pool + API Gateway JWT authorizer on `/chat`
- `user_id` field on `chat_sessions` (nullable, never populated)
- IAM task role for Bedrock

### What's missing
- App doesn't read JWT claims — can't tell users apart
- Any authenticated user can access any session by guessing the UUID
- No API key path for the company to embed CurateAI in their frontend
- No admin vs end-user distinction

### P0 Requirements

| # | Requirement | Notes |
|---|-------------|-------|
| 1.1 | **API key authentication with IP allowlisting** — `api_keys` table with `tenant_id`, `key_hash` (SHA-256), `allowed_ips TEXT[]`, `rate_limit_rpm`, `is_active`, `expires_at`. Middleware resolves tenant from `X-API-Key` header **and** validates the request source IP is in `allowed_ips`. | The company's PHP backend calls us server-to-server. The API key never reaches the browser. IP allowlisting ensures a leaked key is useless from any other machine. |
| 1.2 | **Extract user identity** — for Cognito-authenticated requests, parse `sub` + `email` from JWT. For API-key requests, accept an optional `X-User-ID` header (opaque string the company provides to identify their customer). Populate `user_id` on sessions. | Lets us track per-customer sessions without requiring their users to sign up with us |
| 1.3 | **Session ownership** — `get_or_create()` must check `session.tenant_id == request.tenant_id`. If the session belongs to a different tenant, return 404 (not 403, to avoid leaking existence). | Prevents cross-tenant session access. At 5 users/day the UUID collision risk is near-zero, but the guard costs nothing |
| 1.4 | **Restrict CORS** — store `allowed_origins[]` on the `tenants` table. Middleware reads it and sets `Access-Control-Allow-Origin` dynamically instead of `*`. | One company = one origin. Easy to configure, eliminates the wildcard |
| 1.5 | **Admin guard** — simple decorator that checks if the request came via Cognito JWT (not API key). Protect product upload and analytics routes with it. No full RBAC needed yet. | Two roles for now: `admin` (Cognito) and `widget` (API key). Add granular roles later |

### Integration Pattern: PHP Backend → CurateAI API

The API key is a **server-to-server secret**. The end-user's browser never sees it.

```
End User's Browser              Company's PHP Server              CurateAI API
       │                                │                              │
       │  POST /ask-recommendation      │                              │
       │  (session cookie, no API key)  │                              │
       │───────────────────────────────►│                              │
       │                                │  POST /chat                  │
       │                                │  X-API-Key: sk_live_xxx      │
       │                                │  X-User-ID: customer-123     │
       │                                │  (from server IP: 54.x.x.x) │
       │                                │─────────────────────────────►│
       │                                │                              │  ✓ Key valid
       │                                │                              │  ✓ IP in allowed_ips
       │                                │◄─────────────────────────────│
       │◄───────────────────────────────│                              │
       │  { recommendations... }        │                              │
```

**Security layers preventing unauthorized use:**

| Layer | What it stops | How |
|-------|---------------|-----|
| **Server-side only** | Browser users sniffing the key via DevTools / network inspector | Key lives in PHP `$_ENV['CURATEAI_API_KEY']`, never sent to browser. User only sees calls to the PHP server. |
| **IP allowlisting** | Stolen key used from a different machine | `api_keys.allowed_ips` stores the PHP server's IP(s). Middleware checks `request.client.host` against the list. Request from unknown IP → 403 even with valid key. |
| **HTTPS (API Gateway)** | Man-in-the-middle sniffing the key in transit | API Gateway enforces TLS. The `X-API-Key` header is encrypted on the wire between PHP server and our API. |
| **Key hashing** | Database breach exposing raw keys | We store `SHA-256(key)`, not the raw key. If our DB is compromised, the attacker gets hashes they can't use. |
| **Rate limiting** | Brute-force key guessing | 429 after N failures per IP per minute. |
| **Key rotation** | Long-lived compromised key | Company can create a new key, update their PHP config, then deactivate the old one. |

### Auth Flow

```
Request arrives
  ├─ Has X-API-Key header?
  │   └─ SHA-256(key) → lookup api_keys
  │      └─ Check request IP ∈ allowed_ips → reject if not
  │      └─ inject tenant_id + scopes
  │      └─ Optional X-User-ID header → store as session.user_id
  ├─ Has Authorization: Bearer <jwt>?
  │   └─ Decode JWT (already validated by API Gateway) → extract sub, email
  │      └─ Lookup user → inject tenant_id + user_id + admin=true
  └─ Neither → 401
```

---

## 2. Tenant-Aware Product Catalog

### What exists
- Products scoped by `domain_slugs[]` array
- `hybrid_search()` filters by domain_slug
- Single seed script for "Wellbeing Nutrition"

### What's missing
- No `tenant_id` on any table — products are globally shared
- Agents have no tenant context
- No way for the company to manage their own product catalog

### P0 Requirements

| # | Requirement | Notes |
|---|-------------|-------|
| 2.1 | **Create `tenants` table** — `(id UUID, name, slug, enabled_domains TEXT[], allowed_origins TEXT[], config JSONB, is_active, created_at)`. Seed one row for the launch company. | Lightweight table. `config` JSONB holds per-tenant settings (rate limits, feature flags) |
| 2.2 | **Add `tenant_id` to existing tables** — `products`, `chat_sessions`, `chat_messages`. Single Alembic migration. Backfill existing rows with the one tenant's ID. | Row-level isolation. One `WHERE tenant_id = ?` in every query. Simple, no schema-per-tenant complexity |
| 2.3 | **Update `hybrid_search()` to require `tenant_id`** — add `Product.tenant_id == tenant_id` as mandatory WHERE clause | The single most important isolation control. Without this, company #2 would see company #1's products |
| 2.4 | **Add `tenant_id` to AgentState** — inject at graph entry from authenticated request, flow through all agents | Agents need tenant context for search scoping and future tenant-specific behavior |
| 2.5 | **Tenant-scoped domain filtering (agent flow gating)** — see detailed section below | The single mechanism that prevents a wellness question from being answered on a hardware company's site |
| 2.6 | **Product upload endpoint** — `POST /admin/products` (admin-guarded) accepting JSON array, scoped to the authenticated tenant. Triggers embedding generation. | White-glove for now (we run it), but the endpoint exists for when we hand it off |

### How Agent Flow is Restricted Per Company

The Router agent's LLM prompt is built dynamically from available domains (`router.py:122`). The LLM can **only route to domains it sees in the prompt**. This is the chokepoint — filter the domain list and the entire downstream pipeline (Interviewer, Search, Reranker, Safety) is automatically scoped.

**Current flow (broken — all domains visible to everyone):**
```python
# router.py line 122
domains = get_all_active_domains()  # Returns ALL 13 domains from YAML files
```

**Fixed flow (tenant-scoped):**
```python
# router.py — after tenant_id is added to AgentState
all_domains = get_all_active_domains()
tenant_enabled = state.get("tenant_enabled_domains", [])  # e.g. ["tools", "electronics"]
domains = [d for d in all_domains if d['domain'] in tenant_enabled]
```

**What this controls — every agent downstream:**

```
Wellness company                          Hardware company
enabled_domains: [wellness,               enabled_domains: [tools,
  skin_health_radiance,                     electronics,
  gut_health_digestion]                     home_improvement]
         │                                         │
         ▼                                         ▼
Router sees 3 domains                     Router sees 3 domains
+ out_of_scope                            + out_of_scope
         │                                         │
   "I have dull skin"                        "I have dull skin"
         │                                         │
         ▼                                         ▼
   domain: skin_health_radiance            domain: out_of_scope
   → Interviewer → Search →                → Fallback
   Reranker → Safety                       → Searches hardware catalog
   (finds skin products)                   → "I couldn't find products
                                             matching your request"
```

**4 enforcement points (defense in depth):**

| Layer | What it does | Where |
|-------|-------------|-------|
| **1. Router prompt** | LLM only sees tenant's domains, so it can only classify into them. Anything else → `out_of_scope` → Fallback | `router.py` — filter `get_all_active_domains()` by `tenant_enabled_domains` |
| **2. Problem validation** | Router validates extracted problems against knowledge graphs. Only graphs for enabled domains are checked. | `router.py` — filter `list_available_graphs()` by `tenant_enabled_domains` |
| **3. Product search** | `hybrid_search()` already filters by `domain_slug` AND will filter by `tenant_id`. Even if routing is wrong, products are tenant-scoped. | `product.py` — `WHERE tenant_id = ? AND domain_slugs @> ?` |
| **4. Fallback search** | Fallback agent searches with `domain_slug=None` but will still have `tenant_id` filter. A wellness query on a hardware tenant only finds hardware products. | `fallback.py` — add `tenant_id` to `hybrid_search()` call |

**Configuration example for two companies:**

```sql
-- Wellness supplement company
INSERT INTO tenants (name, slug, enabled_domains) VALUES
('Wellbeing Nutrition', 'wellbeing', ARRAY[
    'wellness', 'skin_health_radiance', 'energy_stamina_vitality',
    'hair_growth_density', 'gut_health_digestion', 'hormonal_balance',
    'immunity_recovery', 'muscle_strength_recovery', 'sexual_wellness_vitality'
]);

-- Hardware tools company (future)
INSERT INTO tenants (name, slug, enabled_domains) VALUES
('ToolCo', 'toolco', ARRAY['power_tools', 'hand_tools', 'plumbing']);
-- (would need corresponding YAML knowledge graphs for these domains)
```

**What about entirely new verticals (e.g., hardware)?** New knowledge graphs need to be authored as YAML files in `app/knowledge/graphs/`. The graph structure (problems, attributes, ingredients/products, constraints, questions) is generic enough to model non-wellness domains — "ingredients" become "features", "problems" become "use cases", "constraints" become "compatibility requirements". But the graph content must be written per vertical.

### Schema Changes

```sql
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    enabled_domains TEXT[] NOT NULL,
    allowed_origins TEXT[] DEFAULT '{}',
    config JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    key_hash VARCHAR(64) NOT NULL,       -- SHA-256 of raw key; we never store the raw key
    name VARCHAR(100) NOT NULL,          -- "Production PHP Backend"
    allowed_ips TEXT[] NOT NULL,          -- e.g. {'54.23.x.x', '54.23.x.y'} — request must come from one of these
    rate_limit_rpm INT DEFAULT 60,
    is_active BOOLEAN DEFAULT true,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Backfill migration: add tenant_id to products, chat_sessions, chat_messages
-- 1. Add column as nullable
-- 2. UPDATE ... SET tenant_id = '<seed_tenant_uuid>'
-- 3. ALTER to NOT NULL + FK
```

### Isolation Strategy: Why Row-Level, Not Table-Per-Company

We evaluated three isolation strategies and chose **row-level (`tenant_id` column)** for the product catalog:

| Strategy | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Row-level (`tenant_id` column)** | Single code path, one migration, standard Alembic workflow, easy cross-tenant platform analytics | Must enforce `WHERE tenant_id = ?` on every query — one missed filter = data leak | **Do this** |
| **Table-per-company** (`products_<slug>`) | Physical separation, no accidental cross-query | Dynamic table names break SQLAlchemy ORM, every migration must be applied to N tables, `UNION ALL` for platform analytics, Alembic doesn't support this natively | Reject |
| **Schema/DB-per-company** | Strongest isolation, independent scaling | Highest ops burden, connection pool per schema, migration coordination across N schemas | Only if regulatory compliance demands it |

**Why row-level is safe enough:**

1. `tenant_id` is `NOT NULL` with a FK constraint — can't insert without it
2. `hybrid_search()` takes `tenant_id` as a **required** parameter (not optional) — calling code can't skip it
3. pgvector similarity search filtered by `tenant_id` is instant at <10k products per company
4. JSONB `attributes` field already handles per-company schema differences (no need for different table structures)
5. A single integration test (`assert all(p.tenant_id == expected for p in results)`) catches leaks

**When to revisit:** If a future company has a hard compliance requirement (e.g., healthcare demanding physical separation), migrate just their data to a separate schema at that point. Don't build the machinery now.

---

## 3. Monitoring & Customer Interaction Analytics

### What already exists in the database

We don't need a new events table — **`chat_messages` + `chat_sessions` already capture most analytics data:**

| Data Point | Where It Lives | How to Query |
|------------|---------------|--------------|
| **What customers search for** | `chat_messages.content WHERE role='user'` | Every user message is stored verbatim |
| **Which domain they land in** | `chat_sessions.current_domain_slug` | Set by the router agent |
| **What problem was identified** | `chat_sessions.extracted_context → 'graph_state' → 'identified_problem'` | e.g., `"dull_skin"`, `"hair_loss"` |
| **What attributes were collected** | `chat_sessions.extracted_context → 'graph_state' → 'filled_attributes'` | e.g., `{"skin_type": {"value": "oily"}}` |
| **How many questions were asked** | `chat_sessions.extracted_context → 'graph_state' → 'questions_asked'` | Integer count |
| **Which products were recommended** | `chat_messages.suggested_product_ids WHERE role='assistant'` | Array of product UUIDs |
| **Session outcome** | `chat_sessions.status` | `completed`, `active`, `fallback_conversation`, etc. |
| **Conversation length** | `COUNT(*) FROM chat_messages WHERE session_id = X` | Messages per session |
| **Timeline** | `chat_sessions.created_at`, `chat_messages.created_at` | When sessions started, how long they lasted |

### What's missing

- **No operational metrics** — can't see request latency, error rates, agent timing
- **No conversion signal** — we know what was recommended, but not if the user clicked/bought
- **No report scripts** — data exists but no one is querying it
- **3-day CloudWatch log retention** — too short for debugging
- **No search quality data** — similarity scores and filter counts are computed at runtime but not persisted

### P0 Requirements

| # | Requirement | Notes |
|---|-------------|-------|
| 3.1 | **Request logging middleware** — log every request with: `tenant_id`, `session_id`, `endpoint`, `status_code`, `latency_ms`, `agent_path` (comma-separated list of agents invoked). JSON to stdout → CloudWatch. | Operational monitoring. At 5 users/day this is ~20-50 requests/day. Structured logs are enough. |
| 3.2 | **Agent timing logs** — at entry and exit of each agent node in the graph, log `agent_name`, `duration_ms`, `session_id`. Already have loggers in each agent file; add timing. | If a consultation is slow, we need to know which agent is the bottleneck |
| 3.3 | **Persist search quality on session** — when search executes, write `search_metadata` into `extracted_context`: `{avg_similarity_score, total_candidates, after_safety_filter, final_count, search_query_tokens}` | Currently computed and discarded. Storing it lets us track search quality trends over time via the existing table |
| 3.4 | **Click/conversion webhook** — `POST /events/click` accepting `{session_id, product_id, action: "click"\|"add_to_cart"\|"purchase"}`. Store in a lightweight `product_events` table: `(id, session_id, product_id, action, created_at)` | The one thing we truly can't derive from existing tables — downstream user actions happen on the company's site |
| 3.5 | **Weekly report SQL scripts** — a set of `.sql` files that query `chat_sessions` + `chat_messages` + `product_events` to produce: session volume, completion rate, top searches, top domains, top recommended products, top identified problems, click-through rate, avg questions asked, fallback rate | No new tables needed for most of this. Just SQL against existing data. |
| 3.6 | **Extend CloudWatch log retention to 14 days** | 3 days is not enough to investigate a bug reported on Monday from Friday's session |

### Example Report Queries (from existing tables)

```sql
-- Top 10 things customers search for (first message per session)
SELECT m.content, COUNT(*) as frequency
FROM chat_messages m
JOIN (
    SELECT session_id, MIN(created_at) as first_msg
    FROM chat_messages WHERE role = 'user'
    GROUP BY session_id
) first ON m.session_id = first.session_id AND m.created_at = first.first_msg
WHERE m.role = 'user'
  AND m.created_at >= NOW() - INTERVAL '7 days'
GROUP BY m.content
ORDER BY frequency DESC
LIMIT 10;

-- Problem identification distribution
SELECT
    extracted_context->'graph_state'->>'identified_problem' as problem,
    current_domain_slug as domain,
    COUNT(*) as sessions
FROM chat_sessions
WHERE status = 'completed'
  AND created_at >= NOW() - INTERVAL '7 days'
GROUP BY problem, domain
ORDER BY sessions DESC;

-- Session completion funnel
SELECT
    COUNT(*) as total_sessions,
    COUNT(*) FILTER (WHERE current_domain_slug IS NOT NULL) as domain_identified,
    COUNT(*) FILTER (WHERE extracted_context->'graph_state'->>'questions_asked' IS NOT NULL) as interviewed,
    COUNT(*) FILTER (WHERE status = 'completed') as completed,
    COUNT(*) FILTER (WHERE status = 'fallback_conversation') as fallback
FROM chat_sessions
WHERE created_at >= NOW() - INTERVAL '7 days';

-- Most recommended products
SELECT p.name, p.brand, COUNT(*) as times_recommended
FROM chat_messages m,
     LATERAL unnest(m.suggested_product_ids) as pid
JOIN products p ON p.id = pid
WHERE m.role = 'assistant'
  AND m.suggested_product_ids IS NOT NULL
  AND m.created_at >= NOW() - INTERVAL '7 days'
GROUP BY p.name, p.brand
ORDER BY times_recommended DESC
LIMIT 10;
```

### What we're NOT doing yet
- No `interaction_events` table — existing `chat_sessions` + `chat_messages` cover 90% of analytics needs. Add a dedicated events table only if query complexity becomes unmanageable.
- No X-Ray / distributed tracing (overkill for 5 users/day)
- No real-time dashboard (weekly SQL is sufficient)
- No S3 export (14-day CloudWatch retention is enough for now)

---

## 4. Rate Limiting & Abuse Protection

### What exists
- API Gateway global throttle (10,000 req/sec default)
- Cognito account lockout

### What's missing
- No per-key rate limiting — a buggy client loop could rack up Bedrock costs
- No cost protection on LLM calls
- Session UUIDs are guessable (though collision probability is negligible)

### P0 Requirements

| # | Requirement | Notes |
|---|-------------|-------|
| 4.1 | **In-memory rate limiter** — sliding window per API key, stored in a Python dict (single process, no Redis needed). Default 30 RPM for `/chat`, configurable in `api_keys.rate_limit_rpm`. Return 429 with `Retry-After` header. | At 5 users/day on 1 Fargate task, in-memory is perfectly fine. No Redis needed. |
| 4.2 | **Daily cost cap** — track Bedrock invocations per tenant per day (in-memory counter, reset at midnight UTC). If a tenant exceeds `config.daily_bedrock_budget` (default: $5), return 429. Log the event. | $5/day = ~100-500 consultations. Protects against runaway costs from a compromised key or client bug |
| 4.3 | **Tighten API Gateway throttle** — set burst=50, rate=20/sec (instead of default 10,000). Plenty for 5 users. | Defense in depth at the edge |
| 4.4 | **API key rotation support** — allow creating a second key for a tenant before deactivating the first. No automated rotation, just the ability to do it manually. | If a key leaks, we need to rotate without downtime |

### What we're NOT doing yet
- No WAF ($6-10/mo, overkill for 1 company)
- No Redis-backed distributed rate limiting (single task = in-memory works)
- No per-user rate limiting (the company's 5 users won't abuse each other)
- No IP-based blocking (API key is the identity boundary)

---

## 5. Infrastructure Hardening

### What exists
- 1 Fargate Spot task (0.5 vCPU, 1 GB)
- API Gateway → direct Fargate IP (changes on restart)
- Pipeline auto-updates the IP on deploy
- DB credentials hardcoded in CDK

### What's missing
- Spot interruption = downtime (no fallback)
- No HTTPS at the app level (API Gateway provides it, but internal hop is HTTP)
- DB password in plaintext in CDK source and CloudFormation
- Health check doesn't verify DB or Bedrock connectivity

### P0 Requirements

| # | Requirement | Notes |
|---|-------------|-------|
| 5.1 | **Switch to Fargate on-demand** (not Spot) | Spot saves ~$5/mo but causes random downtime. For a paying customer, $5 isn't worth the reliability risk. Keep Spot for dev/staging. |
| 5.2 | **Move DB credentials to Secrets Manager** — reference via `SecretValue.secrets_manager()` in CDK. App reads from env var (injected by ECS from the secret). | Password is currently in CDK source code and CloudFormation templates in plaintext |
| 5.3 | **Enhanced health check** — `/health` should verify DB connectivity (`SELECT 1`) with a 2s timeout. Return `{"status": "healthy", "db": "ok"}` or `{"status": "degraded", "db": "unreachable"}`. | Current check only proves the HTTP server is up. A task can be "healthy" but unable to reach the DB. |
| 5.4 | **Bedrock retry with backoff** — wrap `invoke_model` calls with 3 retries, exponential backoff (1s, 2s, 4s) + jitter. | Bedrock occasionally throttles or returns transient errors. Without retries, the user sees a failure. |
| 5.5 | **Upgrade to 1 vCPU / 2 GB** — increase task size, keep 2 uvicorn workers. | 0.5 vCPU is tight when running multiple LLM calls per consultation. 1 vCPU gives headroom without over-provisioning. |

### What we're NOT doing yet
- No ALB (API Gateway handles HTTPS and routing; the dynamic IP problem is handled by the pipeline stack's IP updater. At 1 task, ALB's $20/mo fixed cost isn't justified)
- No auto-scaling (1 task handles 5 users comfortably; revisit at 20+ daily users)
- No Redis (in-memory caching and rate limiting work fine on a single task)
- No multi-AZ (accept the single-AZ risk at this scale)

### Target Architecture (Minimal)

```
  End User (company's website)
       │
       │  Browser loads curateai-widget.js
       │  Widget's apiUrl → company's PHP backend
       ▼
  Company PHP Server
  ├── Receives widget chat requests (session cookie auth)
  ├── Adds X-API-Key + X-User-ID headers
  ├── Proxies to CurateAI API
       │
       ▼
  API Gateway (HTTPS)
       │
       ▼
  Fargate Task (on-demand, 1 vCPU / 2 GB)
  ├── uvicorn (2 workers)
  ├── Auth middleware (API key + IP check → tenant)
  ├── Rate limiter (in-memory)
  └── Agent pipeline
       │
       ├──► Neon PostgreSQL (products, sessions, events)
       └──► AWS Bedrock (LLM + embeddings)
```

### Cost Estimate

| Component | Current | Post-P0 | Delta |
|-----------|---------|---------|-------|
| Fargate (on-demand, 1 vCPU) | $12 (spot) | $30 | +$18 |
| Secrets Manager | $0 | $1 | +$1 |
| CloudWatch (14-day retention) | $2 | $4 | +$2 |
| API Gateway | $0 | $0 | — (free tier covers this volume) |
| Bedrock | ~$2 | ~$2 | — (5 users/day) |
| **Total** | **~$16** | **~$37** | **+$21** |

---

## 6. Product Metrics & Business Intelligence

### What exists (more than we thought)

Between `chat_sessions` and `chat_messages`, we can already answer most product questions:

- **What do customers search for?** → first `role='user'` message per session
- **What problems are identified?** → `extracted_context → graph_state → identified_problem`
- **Which products get recommended?** → `suggested_product_ids` on assistant messages
- **Do users complete consultations?** → `chat_sessions.status = 'completed'`
- **Which domains are popular?** → `chat_sessions.current_domain_slug`
- **How many questions before results?** → `extracted_context → graph_state → questions_asked`

### What's missing
- **No conversion signal** — we know what was recommended, but not if the user acted on it. This data lives on the company's site.
- **No search quality persistence** — similarity scores are computed and discarded
- **No report scripts** — data exists but no one is querying it systematically

### P0 Requirements

| # | Requirement | Notes |
|---|-------------|-------|
| 6.1 | **`product_events` table** — `(id, session_id, product_id, action, created_at)`. Actions: `click`, `add_to_cart`, `purchase`. Populated via the webhook from 3.4. | The only new table needed. Everything else comes from existing data. |
| 6.2 | **Weekly report SQL bundle** — a set of `.sql` scripts covering the metrics below. Runnable via `psql` or a simple admin endpoint later. | See Section 3 for example queries. Ship as `scripts/reports/weekly_report.sql` |
| 6.3 | **Session funnel query** — SQL computing: started → domain_identified → interviewed → recommended → clicked → converted, with drop-off % at each step. Uses `chat_sessions` + `chat_messages` + `product_events`. | The core product health metric. Share with company weekly. |

### Key Metrics (all derivable from existing tables)

| Metric | Source Table(s) | Query Pattern |
|--------|----------------|---------------|
| **Top customer searches** | `chat_messages` (first user message per session) | `GROUP BY content ORDER BY COUNT(*) DESC` |
| **Identified problems distribution** | `chat_sessions.extracted_context` | `->>'identified_problem' GROUP BY` |
| **Domain popularity** | `chat_sessions.current_domain_slug` | `GROUP BY current_domain_slug` |
| **Consultation completion rate** | `chat_sessions.status` | `completed / total` |
| **Avg questions before search** | `chat_sessions.extracted_context` | `->>'questions_asked' AVG()` |
| **Most recommended products** | `chat_messages.suggested_product_ids` | `unnest() JOIN products GROUP BY` |
| **Fallback rate** | `chat_sessions.status` | `fallback_conversation / total` |
| **Click-through rate** | `product_events` + `chat_messages` | `clicks / products shown` (needs 3.4 webhook) |
| **Search quality** | `chat_sessions.extracted_context` | `->>'search_metadata'` (needs 3.3 to persist it) |
| **Conversation length** | `chat_messages` | `COUNT(*) per session_id` |
| **User attribute distribution** | `chat_sessions.extracted_context` | `->>'filled_attributes'` — e.g., "60% of users have oily skin" |

### What we're NOT doing yet
- No real-time analytics dashboard (weekly SQL reports are sufficient)
- No automated report delivery (run manually, share over email/slack)
- No A/B testing infrastructure (one company, one flow)
- No materialized views (raw queries are fast at this volume)

---

## Implementation Sequencing

### Phase 1 — Tenant Foundation + Security (Week 1-2)

Everything else depends on `tenant_id` existing in the system:

```
2.1  Create tenants + api_keys tables
2.2  Add tenant_id to products, sessions, messages (migration + backfill)
1.1  API key auth middleware
1.2  User identity extraction
2.3  Update hybrid_search to require tenant_id
2.4  Add tenant_id to AgentState
5.2  Move DB credentials to Secrets Manager
```

### Phase 2 — Protection + Reliability (Week 2-3)

```
1.3  Session ownership enforcement
1.4  CORS restriction
4.1  In-memory rate limiter
4.2  Daily cost cap
4.3  Tighten API Gateway throttle
5.1  Switch to Fargate on-demand
5.3  Enhanced health check
5.4  Bedrock retry with backoff
5.5  Upgrade to 1 vCPU / 2 GB
```

### Phase 3 — Observability + Metrics (Week 3-4)

```
3.1  Request logging middleware
3.2  Agent timing logs
3.3  Persist search quality metadata in extracted_context
3.4  Click/conversion webhook + product_events table
3.5  Weekly report SQL scripts (query existing tables)
3.6  Extend CloudWatch retention to 14 days
6.2  Weekly report SQL bundle (ships as scripts/reports/)
6.3  Session funnel query
```

### Phase 4 — Admin + Polish (Week 4-5)

```
1.5  Admin guard decorator
2.5  Tenant-scoped domain filtering
2.6  Product upload endpoint
4.4  API key rotation support
```

---

## Decisions (Resolved)

### 1. Widget Integration — CurateAI Widget via PHP Proxy

The **curateai-widget** (`/Documents/curateai-widget/`) is a Preact-based embeddable chatbot built as a single IIFE bundle (`curateai-widget.js`, ~60KB). It uses Shadow DOM for style isolation and is configured via `window.CurateAIConfig`.

**Current widget auth:** `Authorization: Bearer <Cognito JWT>` sent directly to our API from the browser.

**Production integration (PHP proxy):** The widget must NOT call our API directly — that would expose the API key in the browser. Instead:

```
Company embeds on their site:
┌──────────────────────────────────────────────────────┐
│  <script>                                            │
│    window.CurateAIConfig = {                         │
│      apiUrl: 'https://company.com/api/curateai',  ◄──── Points to THEIR PHP server, not us
│      title: 'Product Finder',                        │
│      primaryColor: '#brand-color',                   │
│    };                                                │
│  </script>                                           │
│  <script src="https://cdn.../curateai-widget.js">    │
│  </script>                                           │
└──────────────────────────────────────────────────────┘

Company's PHP proxy endpoint:
┌──────────────────────────────────────────────────────┐
│  // /api/curateai/chat (PHP)                         │
│  $response = Http::withHeaders([                     │
│      'X-API-Key' => env('CURATEAI_API_KEY'),      ◄──── Key stays on server
│      'X-User-ID' => auth()->user()->id,           ◄──── Their user identity
│      'Content-Type' => 'application/json',           │
│  ])->post(env('CURATEAI_API_URL') . '/chat', [       │
│      'message' => $request->message,                 │
│      'session_id' => $request->session_id,           │
│  ]);                                                 │
└──────────────────────────────────────────────────────┘
```

**Widget changes needed for production:**
- Remove Cognito auth flow from widget (not needed in B2B mode — the company's PHP server handles user auth)
- Widget only needs to send `message` and `session_id` to the PHP proxy
- The `onProductClick` callback fires when a user clicks a recommended product — the company can use this to track conversions on their side and call our `/events/click` webhook

### 2. Analytics — Manual SQL Reports

Weekly reports run manually via `psql` and shared over email/slack. No dashboard UI, no automated delivery. Build this when there's enough data volume to justify the investment.

### 3. Product Catalog — White-Glove via DB Access

We have access to the company's DB. We pull product data into our schema, seed it, and generate embeddings. The `POST /admin/products` endpoint exists for future self-service, but for now we run it ourselves.

### 4. Knowledge Graphs — We Manage Them

We author and maintain the YAML knowledge graphs. The company provides domain knowledge (what problems to solve, what attributes matter), we translate that into graph structure.

### 5. Database — Neon PostgreSQL

Stay with Neon for now. Free tier covers current volume. Reassess when we add company #2 or hit Neon's connection pooler limits (~100 concurrent connections).

---

## Appendix: Pricing Model Options

Our unit economics per consultation: **~$0.01–0.05** (Bedrock LLM calls) + negligible infra. The pricing model should cover costs, incentivize usage, and be simple to explain.

### Option A: Per-Consultation Pricing

Charge per completed consultation (session reaching `status = completed` with products recommended).

| Tier | Price per consultation | Included | Notes |
|------|----------------------|----------|-------|
| Starter | $0.15 | First 500 free/mo | Simple, usage-aligned. Company pays only when value is delivered. |
| Growth | $0.10 | First 1,000 free/mo | Volume discount |

**Pros:**
- Directly tied to value delivered — company pays when their customer gets a recommendation
- Easy to understand and justify ROI ("each consultation costs $0.10, avg order value is $40")
- Scales linearly with usage — no sticker shock, no overpaying for unused capacity
- Metering is trivial: `SELECT COUNT(*) FROM chat_sessions WHERE status = 'completed' AND tenant_id = ?`

**Cons:**
- Revenue is unpredictable for us month-to-month
- Company may hesitate to drive traffic if they're unsure of conversion rate
- Need to define "consultation" clearly (does an abandoned session count? a fallback with no products?)

**Billing definition:** A consultation = a session that reaches `status = 'completed'` with at least 1 product in `suggested_product_ids`. Abandoned sessions, fallbacks with no products, and ingredient_info queries are free.

---

### Option B: Monthly Subscription (Flat Fee + Consultation Cap)

Fixed monthly fee with a consultation cap. Overage charged per-consultation.

| Tier | Monthly Fee | Included Consultations | Overage |
|------|------------|----------------------|---------|
| Starter | $49/mo | 500 | $0.15 each |
| Growth | $149/mo | 2,000 | $0.10 each |
| Scale | $399/mo | 10,000 | $0.05 each |

**Pros:**
- Predictable revenue for us
- Company has a clear budget ("$49/mo for product recommendations")
- Encourages adoption — once you're paying the flat fee, every consultation feels free up to the cap
- Simple invoicing — one charge per month

**Cons:**
- Company may feel they're overpaying if usage is low in early months
- Need to handle overages gracefully (warning at 80%, hard limit or auto-upgrade?)
- Requires tracking consultation count in near-real-time for the company to see

---

### Option C: Revenue Share / Commission

Take a percentage of revenue generated from CurateAI recommendations.

| Model | Rate | Tracking Required |
|-------|------|-------------------|
| % of attributed sales | 3–5% of revenue from products recommended by CurateAI | Company reports purchases via `/events/click` webhook with `action: "purchase"` and order value |

**Pros:**
- Perfect alignment — we only earn when they earn
- Low barrier to entry — no upfront cost, company takes zero risk
- Strong incentive for us to improve recommendation quality (better recs = more revenue)

**Cons:**
- Requires trust and honest reporting from the company (or integration with their payment system)
- Revenue attribution is hard ("did the customer buy because of our recommendation, or would they have bought anyway?")
- Unpredictable revenue for us
- Delayed payment cycle (need to wait for purchase data)
- Complex to implement: need the conversion webhook (3.4), order value tracking, and a billing reconciliation process

---

### Option D: Hybrid — Base Fee + Per-Consultation

Small base fee for platform access + per-consultation pricing.

| Component | Price |
|-----------|-------|
| Platform fee | $29/mo (covers infra, support, graph maintenance) |
| Per consultation | $0.10 each, no cap |

**Pros:**
- Base fee covers our fixed costs (Fargate, Neon, maintenance time)
- Per-consultation aligns with value delivery
- No tier complexity — one simple model
- Company can predict costs: $29 + ($0.10 × estimated consultations)

**Cons:**
- Two line items on the invoice instead of one
- The base fee may deter very small companies from starting

---

### Recommendation for Launch

**Start with Option D (Hybrid)** for the first company:

- **$29/mo platform fee** — covers our Fargate + Neon + maintenance costs (~$37/mo infra)
- **$0.10 per completed consultation** — we're profitable at any volume above ~80 consultations/mo
- **First month free** — let them see value before paying

Why this works for the first customer:
1. Low enough that it's a no-brainer to try ($29 + ~$15/mo at 5 users/day ≈ **$44/mo total**)
2. We cover our infra costs from day 1
3. Per-consultation component means if they scale to 50 users/day, revenue grows automatically
4. Simple to meter: one SQL query against `chat_sessions`

**What we need to implement for billing:**
- Consultation counter per tenant (already available: `SELECT COUNT(*) FROM chat_sessions WHERE status = 'completed' AND tenant_id = ? AND created_at >= date_trunc('month', NOW())`)
- Monthly usage summary in the weekly report SQL
- Invoice manually for now (email with consultation count + total). Automate with Stripe when we have 3+ customers.

**Revisit at scale:** When we have 5+ companies, evaluate whether to move to Option B (subscription tiers) for revenue predictability, or Option C (revenue share) for enterprise customers who want zero-risk.
