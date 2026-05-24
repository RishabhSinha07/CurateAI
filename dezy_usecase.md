# Dezy CX Regression Test Cases

Manual regression checklist for the `dental_services` vertical against the Dezy tenant.

## Setup

1. Backend running: `docker compose up -d` in `CurateAI/`
2. UI running: `npm run dev` in `CurateAI-UI/`
3. Dezy tenant exists in the local DB with `vertical='dental_services'`. Seed if missing:
   ```sql
   INSERT INTO tenants (id, name, slug, vertical, enabled_domains, allowed_origins, is_active)
   VALUES ('11111111-1111-1111-1111-111111111111', 'Dezy', 'dezy', 'dental_services', '{*}', '{*}', true)
   ON CONFLICT (slug) DO UPDATE SET vertical = EXCLUDED.vertical;
   ```
4. Catalog ingested (run once, idempotent):
   ```bash
   docker compose exec app python -m scripts.scrape_dezy.main
   docker compose exec app python -m scripts.ingest_dezy \
     --snapshot /app/scripts/scrape_dezy/output/dezy_scrape.json \
     --tenant-id 11111111-1111-1111-1111-111111111111

   docker compose exec app python -m scripts.dezy_brand.build_snapshot
   docker compose exec app python -m scripts.ingest_dezy \
     --snapshot /app/scripts/dezy_brand/output/brand_snapshot.json \
     --tenant-id 11111111-1111-1111-1111-111111111111
   ```
5. Open in browser:
   - Dental (Dezy): `http://localhost:3000/chat?tenant=11111111-1111-1111-1111-111111111111`
   - Commerce (regression sanity): `http://localhost:3000/chat`

## Use the legend

- ✅ = expected; record actual outcome in PR / test run
- 🟠 = expected with some LLM variability (Bedrock can phrase differently — check intent, not exact words)
- ❌ = should NOT happen
- Each case is independent unless the description says "after UC1" etc.

---

## Section 1: Core 5 use cases (Dezy CX brief)

### UC1 — Problem-led treatment recommendation (multi-turn slot fill)

**Trigger:** `I have a missing tooth on the lower left, what should I do?`

Expected:
- ✅ Turn 1: agent asks for tooth location with quick replies `[Upper front, Upper back, Lower front, Lower back]`, status `awaiting_slot`
- ✅ Turn 2 (answer: `Lower back`): asks `missing_duration` with quick replies
- ✅ Turn 3 (answer: `1-3 years`): asks `bone_health_known`
- ✅ Turn 4 (answer: `Not sure`): asks `permanence_preference`
- 🟠 Turn 5 (answer: `Permanent`): recommends **Single Tooth Implant**, returns 3 service cards (implant + bridge + denture), `Learn more about Single Tooth Implant` + `Book a Free Consultation` CTAs, ~3 follow-up suggested replies
- ❌ Should not ask any clarifying question after permanence is set

### UC2 — Procedural / educational Q&A grounded in Dezy content

**Trigger A:** `How long is recovery after a full mouth implant?`
- ✅ Single-turn answer
- 🟠 Response mentions 1-2 sittings, 3-6 months healing, soft foods 2-4 weeks
- ✅ CTAs include `Open Cost Calculator` + `Book a Free Consultation`
- ✅ Status `completed`, 0 item cards

**Trigger B:** `How painful is the implant procedure?`
- ✅ Routes to `content_qa` (not fallback)
- 🟠 Mentions local anaesthesia, minimal/mild discomfort, manageable swelling

**Trigger C:** `Is teeth whitening safe?`
- ✅ Routes to content_qa, answers based on scraped whitening FAQ chunks

### UC3 — Side-by-side comparison

**Trigger A:** `Aligners vs metal braces — I have 8 months and mild crowding`
- ✅ Renders a markdown table with criteria as rows (Timeline, Cost, Visibility, etc.)
- ✅ Winners marked with `**bold** ✓` cells
- 🟠 Recommends Clear Aligners ("for your situation") because of the 8-month + mild context
- ✅ Returns 2 service items (Clear Aligners + Metal Braces)
- ✅ `Learn more about Clear Aligners` CTA + Book CTA

**Trigger B:** `Implant vs bridge at age 52`
- ✅ Comparison table
- 🟠 Recommends Single Tooth Implant for durability / jawbone preservation

### UC4 — Multi-attribute doctor search

**Trigger A:** `Show me female implant specialists in Bangalore`
- ✅ Returns ≥3 doctor cards
- ✅ Each card has badges including `Female`, experience years, credentials (MDS/BDS)
- ✅ Subtitle shows `Implants` (or "Implants, ...") and city
- ✅ Top result's `View {Name}'s profile` CTA + Book CTA
- ✅ Response leads with `Here's who I found at Dezy matching: female implants specialist in Bangalore.`

**Trigger B:** `Female orthodontist in Delhi` (no Dezy doctors in Delhi)
- ✅ Relaxes the city filter
- ✅ Response leads with `I didn't find a … exactly, but here are matching clinicians at Dezy (in other locations):`
- ✅ Returns orthodontists from Mumbai / Bangalore

**Trigger C:** `Best implantologist in Pune`
- ✅ Returns Pune-based implant doctors (city + spec filter, no gender constraint)

### UC5 — Treatment plan / sequencing

**Trigger:** `I want my teeth cleaned, want them whiter, and have a small gap to fix`
- ✅ Returns a numbered markdown plan (`**1. ...** — why ...`)
- ✅ Order respects clinical `precedes`: cleaning first, whitening second, then bonding or aligners for the gap
- ✅ Each step has rationale
- ✅ Returns 2-3 service items (one per step)
- ✅ `Book all of these together` CTA

---

## Section 2: Multi-turn follow-up flows

After completing UC1, on the **same session**, try each:

### Service detail follow-up

**Trigger:** `How long does the implant procedure take?`
- ✅ Routes via refinement → `service_detail`
- 🟠 Grounded answer from the Single Tooth Implant record (1-2 sittings, 3-6 months total)
- ✅ Returns the implant as a detail card (attributes.detail=true on the item)

### Refinement to a new concern

**Trigger:** `Actually I also want whiter teeth`
- ✅ Refinement classifies as `new_topic` → router re-classifies as `treatment_query`
- ✅ Matches `stained_teeth` concern
- ✅ Starts a fresh slot loop (asks `sensitivity_known`)

### Refinement on a previously shown option

**Trigger (after UC1):** `Tell me more about the bridge option`
- ✅ Service detail picks the Dental Bridge (one of the alternates shown by recommender)
- 🟠 Grounded answer using bridge's pros/cons/duration

---

## Section 3: Brand / policy questions (powered by brand-doc seeder)

Each is a single-turn content_qa question. Response should cite the brand chunk noted.

| # | Trigger | Cites | Expected |
|---|---------|-------|----------|
| B1 | `What technology does Dezy use?` | `tech_overview` | Lists Digital Scanning, Intra-Oral Scanner, Digital X-Ray, Treatment Planning Software, Pricing Engine, AI Smile Simulation, 3D Printing, Treatment Monitoring |
| B2 | `Do you have AI smile simulation?` | `tech_ai_smile_simulation` | Affirms; mentions preview before treatment |
| B3 | `Do you offer a refund if I'm not happy?` | `outcome_assurance_refund` | Cites 100% Outcome Assurance, full refund |
| B4 | `Why should I choose Dezy?` | `why_dezy` | Mentions honesty, digital-first, low price, MDS specialists, 100% Outcome Assurance, accessibility |
| B5 | `How experienced are your doctors?` | `doctor_network_standards` | Mentions MDS, 7+ years minimum, 2,000-3,000+ implants per doctor, audits |
| B6 | `Who are your most senior implant doctors?` | `senior_implantologists` | Names Dr Faiz (15k+), Dr Vinay (10k+), Dr Jatin (10k+) |
| B7 | `Do you have EMI?` | `accessibility_home_scan_emi` | Mentions 0% EMI, free home/clinic scans, 7-day clinics |
| B8 | `Tell me about Dezy` | `company_overview` | Founded 2019, IIT/IIM alumni, institutional investors, city list |
| B9 | `What awards has Dezy won?` | `awards_recognition` | Economic Times Best Dental Care South India, WEF Top 10 Startups, Voice of Healthcare 2024 |
| B10 | `How does Dezy price treatments?` | `transparent_pricing` | Upfront pricing, pricing engine, no hidden charges, EMI |

---

## Section 4: Clinical safety net (deterministic — no LLM)

Each should route to fallback **without** producing a treatment recommendation.

| # | Trigger | Expected response includes |
|---|---------|---------------------------|
| S1 | `I'm 5 months pregnant with severe tooth pain` | Pregnancy + x-ray precautions; "clinician should review your case directly" |
| S2 | `I have a heart condition, can I get an implant?` | Cardiac history; treatment planning + anaesthesia choices |
| S3 | `I'm on blood thinners and need a tooth out` | Cardiac/blood-thinner caution path |
| S4 | `My 4 year old needs a dental check` | Paediatric care — direct booking |
| S5 | `I have a bleeding disorder, can I get my tooth extracted?` | Bleeding disorders need special protocols |
| S6 | `I have uncontrolled bleeding right now` | Acute symptom; visit hospital / clinic immediately |

All:
- ✅ `Book a Free Consultation` CTA present
- ❌ NO treatment recommendations / service items returned
- ❌ NO comparison or doctor search even if other keywords are in the message

---

## Section 5: Out-of-scope handling

| # | Trigger | Expected |
|---|---------|----------|
| O1 | `What's the weather in Mumbai?` | Fallback message explaining Dezy's scope (dental); offers help with dental topics |
| O2 | `I have a headache` | Fallback (no dental keyword to anchor) — invites dental-specific question |
| O3 | `Recommend me a good Bollywood movie` | Fallback |

---

## Section 6: Doctor search variations (extended UC4 coverage)

| # | Trigger | Expected |
|---|---------|----------|
| D1 | `Female dentists in Mumbai` | Mumbai-based female doctors, any specialization |
| D2 | `Dezy doctors who do aligners` | Aligners/orthodontics specialists across all cities |
| D3 | `Senior implantologist in Bangalore` | Should return Dr Vinay Pavan and/or Dr Jatin Kakrani (brand-tier doctors) among top results |
| D4 | `Doctor for veneers in Hyderabad` | Cosmetic-specialty doctors filtered by city, or relaxed if none |

---

## Section 7: Comparison variations

| # | Trigger | Expected |
|---|---------|----------|
| C1 | `Veneers vs whitening for stained teeth` | Cosmetic comparison; whitening probably wins for cost/non-invasive, veneers for durability/transformation |
| C2 | `Should I get aligners or braces for severe crowding?` | Comparison flags that braces handle severity better |
| C3 | `Bridge vs partial denture` | Restorative comparison; bridge typically wins for stability |

---

## Section 8: Edge / robustness

| # | Trigger | Expected |
|---|---------|----------|
| E1 | `hi` | Fallback (out of scope) |
| E2 | `yes` (fresh session, no awaiting_slot) | Fallback |
| E3 | `lower back` (fresh session) | Fallback (not interpreted as a slot answer) |
| E4 | `I have a missing tooth` then `cancel` mid-flow | Slot loop continues — refinement happens after `completed`, not during awaiting_slot |
| E5 | Open dental URL in two tabs, start different conversations | Each gets a separate session_id; state doesn't leak |
| E6 | Reload page mid-conversation | Session persists if `persistSession` is on (commerce UI default), new session otherwise (current dental setup) |

---

## Section 9: Vertical regression (commerce must keep working)

At the commerce URL `http://localhost:3000/chat` (no `?tenant=` param):

| # | Trigger | Expected |
|---|---------|----------|
| CM1 | `I have dry skin` | Status `awaiting_slot`, 10 product cards (skin_health_radiance domain), suggested replies |
| CM2 | After CM1, answer `oily` | Continues the slot flow; `vertical_context.domain_slug` = `skin_health_radiance` |
| CM3 | `Vitamin C serum under ₹1000` | Direct product / inline-constraints filter — returns vitamin C products under ₹1000 |
| CM4 | `Tell me about collagen` | Ingredient info path |

Any commerce regression here means a kernel-level break — should be fixed before shipping any dental work.

---

## How to run as a regression suite

1. Walk down sections 1-9 in order. The categories are roughly cheapest → most LLM-variable.
2. For each case, record:
   - **Pass** if expected behaviour fired (allow LLM phrasing variation on 🟠 items)
   - **Partial** if intent was right but content was off (note what went wrong)
   - **Fail** if intent was wrong (e.g., routed to fallback when content_qa was expected)
3. After all sections, also run the backend unit/integration tests:
   ```bash
   docker compose exec app pytest tests/ --ignore=tests/integration/knowledge
   ```
4. Known pre-existing failures (8) are flaky LLM-classification tests; don't gate ship on them.

---

## Where to find each agent

If a case fails, the agent is at:

| Behaviour | File |
|-----------|------|
| Intent classification | `app/agents/verticals/dental_services/router.py` |
| Slot loop (UC1) | `app/agents/verticals/dental_services/interviewer.py` |
| Treatment recommendation (UC1) | `app/agents/verticals/dental_services/treatment_recommender.py` |
| Content RAG (UC2 + brand) | `app/agents/verticals/dental_services/content_qa.py` |
| Comparison (UC3) | `app/agents/verticals/dental_services/comparison.py` |
| Doctor search (UC4) | `app/agents/verticals/dental_services/doctor_search.py` |
| Treatment plan (UC5) | `app/agents/verticals/dental_services/treatment_planner.py` |
| Service detail | `app/agents/verticals/dental_services/service_detail.py` |
| Refinement routing | `app/agents/verticals/dental_services/refinement.py` |
| Clinical escalation | `app/agents/verticals/dental_services/router.py` (deterministic check at top) + `fallback.py` |
| Disclaimers / persona / Book CTA | `app/agents/verticals/dental_services/safety.py` |
| Knowledge (concerns, treatments, slots, triggers) | `app/agents/verticals/dental_services/knowledge.py` |
| Brand content | `scripts/dezy_brand/content.py` |
