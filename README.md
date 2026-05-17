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
