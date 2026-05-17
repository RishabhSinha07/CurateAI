# CurateAI

A multi-agent AI consultation system for personalized product recommendations. Users describe a health concern and the system identifies their problem, personalizes via clarifying questions, then recommends products using semantic search guided by a knowledge graph.

## Demo

[![CurateAI Demo](https://img.youtube.com/vi/svhhO4ivPEc/0.jpg)](https://youtu.be/svhhO4ivPEc)

## Tech Stack

- **FastAPI** + **LangGraph** — async API with state machine agent orchestration
- **AWS Bedrock** — Amazon Nova Pro (agents + embeddings)
- **PostgreSQL** + **pgvector** — product catalog + vector search
- **NetworkX** — knowledge graph loading/querying

## Getting Started

```bash
# Start services
docker compose up -d

# Run DB migrations
docker compose exec app alembic upgrade head

# Seed products
docker compose exec app python -m app.db.seed_wellbeing

# Generate embeddings
docker compose exec app python -m app.services.generate_embeddings
```

## TODO

### Router cost: stage-1 broad-bucket classifier

The dental router (and commerce router) pays a full LLM round-trip per turn even for follow-up slot answers — the only deterministic shortcut catches `awaiting_slot`, so every fresh message goes through the LLM.

Cheapest mitigation when volume picks up: a stage-1 LLM call with a tiny prompt that does broad bucketing ("question vs recommendation vs filter") and only escalates to the full router prompt for ambiguous cases. Worth doing once volume picks up, not now.

### Scrape additional dezy.com pages

`scripts/scrape_dezy` currently only walks the `/services/<slug>`, `/meet-your-dentists/<slug>`, and `/clinics/<city>/<slug>` URL patterns. The sitemap has more top-level content pages that would feed `content_qa` (UC2) directly:

- `/why-dezy-is-different`
- `/how-it-works-implants`, `/how-it-works-aligners`
- `/dental-implants-benefits`, `/dental-implants-results`
- `/cost-of-dental-implants`, `/dental-implants-cost-calculator`
- `/aligner-pricing`, `/aligner-results`
- `/full-mouth-dental-implants`
- `/faqs` (global FAQ, separate from per-service FAQs)
- The orthodontic-concern landing pages: `/crowded-teeth`, `/teeth-gap`, `/open-bite`, `/overbite`, `/cross-bite`, `/deep-bite`

Add a "content" page-kind to `scripts/scrape_dezy/main.py` (alongside `service`/`doctor`/`clinic`) and a parser that strips visible text → chunks of ~500 tokens. These pages don't reliably have Schema.org JSON-LD, so chunking from visible body text is the path.
