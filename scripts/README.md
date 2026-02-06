# CurateAI Scripts

Utility scripts for deployment, data management, and maintenance.

## 🚀 Deployment Scripts

### `update_api_gateway.sh` / `update_api_gateway.py` ⭐ NEW

**Purpose**: Update API Gateway backend URL after ECS deployment

**When to use**: After pipeline deployment or manual ECS task restart (task IP changes)

**What it does**:
1. Gets current Fargate task public IP
2. Updates Auth stack with new backend URL
3. Tests health endpoints

**Usage**:
```bash
# Bash version (recommended)
./scripts/update_api_gateway.sh

# Python version (alternative)
python scripts/update_api_gateway.py
```

**Typical workflow**:
```bash
# 1. Push code (triggers pipeline)
git push origin main

# 2. Wait for pipeline (~8-10 min)
# https://console.aws.amazon.com/codesuite/codepipeline/pipelines/CurateAI-Pipeline

# 3. Update API Gateway
./scripts/update_api_gateway.sh
```

---

### `get_task_ip.sh` ⭐ NEW

**Purpose**: Quickly get the current ECS task public IP

**When to use**:
- After deployments to find the new task IP
- For direct API testing
- When troubleshooting connectivity

**What it does**:
1. Finds the running ECS task
2. Extracts the public IP address
3. Displays direct API endpoint

**Usage**:
```bash
./scripts/get_task_ip.sh
```

**Output**:
```
Getting current Fargate task IP...
Task ARN: arn:aws:ecs:us-east-1:558599919081:task/CurateAI-Cluster/22adcc21...

✅ Current Task IP: 44.203.0.146

Direct API endpoint: http://44.203.0.146:8000

Test with:
  curl http://44.203.0.146:8000/health
```

---

### `migrate_local_to_prod.py`

**Purpose**: Migrate products from local Docker DB to production Neon DB

**When to use**: Initial setup or syncing local products to production

**What it does**:
1. Exports all products from local PostgreSQL
2. Imports to production Neon database
3. Preserves embeddings and attributes

**Usage**:
```bash
pip install asyncpg
python scripts/migrate_local_to_prod.py
```

---

## 📦 Data Scripts

Scripts for scraping product data and seeding the database.

## Scripts Overview

### 1. `seed_from_scrape.py` ⭐ (RECOMMENDED)

**Comprehensive all-in-one script** that:
- ✅ Clears the database (clean state)
- ✅ Creates domain hierarchy (Wellness → Melts, Collagen, etc.)
- ✅ Scrapes products from **actual website collections** (not keyword guessing!)
- ✅ Generates embeddings for all product descriptions
- ✅ Inserts products into database
- ✅ Verifies data integrity and prints statistics

**New in v2:** Uses actual Shopify collections from the website navigation instead of keyword-based classification!

**Usage:**
```bash
# Make sure Docker containers are running
docker compose up -d

# Run the script from project root
docker compose exec app python -m scripts.seed_from_scrape
```

**What it does:**
1. Asks for confirmation before clearing database
2. Scrapes ~100+ products from Wellbeing Nutrition
3. Generates embeddings using AWS Titan (takes ~5-10 minutes)
4. Shows progress and statistics
5. Verifies everything is working

**Output:**
```
WELLBEING NUTRITION DATABASE SEEDER
====================================
✓ Cleared all tables
✓ Created 6 domains
✓ Fetched 150 raw products
✓ Valid products after filtering: 120
✓ Inserted 120 products

Products by domain:
  melts: 35
  collagen: 28
  slow-capsules: 30
  effervescent: 18
  protein: 9
```

---

### 2. `scrape_products_v2.py` ⭐ (NEW - Collection-based)

**Improved standalone scraper** that uses actual website collections!

**How it works:**
1. Fetches collections from `/collections.json`
2. Maps Shopify collections to our domains:
   - `adult-melts` → melts
   - `marine-collagen`, `vegan-collagen` → collagen
   - `whey-protein`, `plant-protein` → protein
   - `effervescent-tablets` → effervescent
   - etc.
3. Fetches products from each collection endpoint
4. Avoids duplicate products across collections

**Usage:**
```bash
python -m scripts.scrape_products_v2
```

**Output:**
- `data/scraped_products_v2.json` - Full product data with accurate categories
- `data/scrape_summary_v2.json` - Summary statistics

---

### 3. `scrape_products.py` (OLD - Keyword-based)

**Legacy scraper** using keyword matching. Use v2 instead for better accuracy.

**Output:**
- `data/scraped_products.json`
- `data/scrape_summary.json`

---

### 3. `seed_scraped_products.py`

**Old script** - Seeds from pre-scraped JSON file. Not recommended (use `seed_from_scrape.py` instead).

---

## Quick Start Guide

### Step 1: Ensure Services are Running
```bash
cd /Users/rishabhsinha/Documents/CurateAI
docker compose up -d
```

### Step 2: Check Database is Accessible
```bash
docker compose exec db psql -U postgres -d curateai -c "SELECT COUNT(*) FROM products;"
```

### Step 3: Run the Comprehensive Seeder
```bash
docker compose exec app python -m scripts.seed_from_scrape
```

Type `yes` when prompted to confirm database reset.

### Step 4: Verify Data
```bash
# Check product count
docker compose exec db psql -U postgres -d curateai -c "SELECT COUNT(*) FROM products;"

# Check domains
docker compose exec db psql -U postgres -d curateai -c "SELECT slug, name FROM domains;"

# Sample products
docker compose exec db psql -U postgres -d curateai -c "SELECT name, domain_id, price FROM products LIMIT 5;"
```

---

## Environment Requirements

Make sure your `.env` file has:
```
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=us-east-1
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/curateai
```

---

## Troubleshooting

### Rate Limiting Errors
The script includes 1.5s delays between product detail fetches to respect Shopify's rate limits. If you get errors, the script will skip problematic products and continue.

### Embedding Errors
If AWS Titan embedding fails:
1. Check AWS credentials in `.env`
2. Verify `AWS_REGION=us-east-1`
3. Ensure your AWS account has Bedrock access

### Database Errors
If database connection fails:
```bash
# Restart database
docker compose restart db

# Check logs
docker compose logs db
```

---

## Data Sources

- **Products:** https://wellbeingnutrition.com/collections/shop-all-1
- **API:** Shopify JSON endpoints (`/products.json`, `/products/{handle}.js`)

---

## Notes

- The scraper respects rate limits (1.5s delay per product)
- Filters out test products, freebies, and invalid items
- Generates embeddings using AWS Bedrock Titan Embed v2 (1024 dims)
- Products are categorized into domains based on tags and product type
- All prices are in INR (Indian Rupees)
