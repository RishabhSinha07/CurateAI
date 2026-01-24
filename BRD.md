# HLD: CurateAI

Requirements as part of this doc:

1. Multi agent consulatnat workflow
2. Short term memory
3. Single Query

Requuirements not part of this doc:

1. Long term context memory
2. Complex or complicated queries

![image.png](attachment:ee67e9dc-fda4-45c5-a4ae-309b0c44824f:image.png)

# Agents

## 1. The Gateway Router (The "Triage" Agent)

This is the first brain that touches the user's message.

- **Role:** Identifies the user's intent and maps it to a **Domain**.
- **Input:** Raw user text (e.g., *"My face is always red after a shower."*)
- **Action:** It consults the `domains` table. It realizes this is a `skin_care` issue. It sets the session context to "Skin Specialist."

## 2. The Interviewer (The "Slot-Filler" Agent)

This agent manages the "Consultation" phase.

- **Role:** Cross-references the `extracted_context` in the DB with the `required_slots` in the `domain_config`.
- **Action:** If the domain is "Skin Care" and we don't know the **skin type**, this agent suppresses product search and instead generates a clarifying question: *"To help you best, could you tell me if your skin feels tight or oily after washing?"*
- **Goal:** Ensure the system has enough data to make a **safe** and **accurate** recommendation.

## 3. The Search Architect (The "RAG" Agent)

Once all slots are filled, this agent takes over.

- **Role:** Translates human needs into technical queries.
- **Action:** It doesn't just search for "Red skin." It expands the query into: *"Soothing ingredients, anti-inflammatory, fragrance-free, niacinamide, ceramides."*
- **Output:** It generates the API call for the Hybrid Search (Vector + SQL).

## 4. The Product Critic (The "Reranker" Agent)

The search might return 20 products; this agent picks the top 3.

- **Role:** Performs a final check against the user's specific constraints (e.g., budget or allergies).
- **Action:** If a product contains "Vitamin C" and the user mentioned "Extremely sensitive skin," the Critic may demote that product in favor of a gentler one.
- **Why it's separate:** Search is about **relevance**; the Critic is about **suitability**.

## 5. The Safety Officer (The "Guardrail" Agent)

In Wellness, this is your most important agent.

- **Role:** Monitors the final output for medical claims or dangerous advice.
- **Action:** If the AI sounds too much like a doctor (e.g., "This will cure your eczema"), the Safety Officer intercepts and appends: *"This product is designed for cosmetic support. For medical conditions like eczema, please consult a dermatologist."*

| **Agent** | **Core Responsibility** | **Success Metric** |
| --- | --- | --- |
| **Router** | Pick the right specialist. | 99% Domain Accuracy. |
| **Interviewer** | Fill the required data slots. | Minimized turns to "Search." |
| **Searcher** | Retrieve relevant products. | High recall from Vector DB. |
| **Critic** | Filter for user constraints. | Zero "bad-fit" recommendations. |
| **Safety** | Legal/Health compliance. | No unauthorized medical claims. |

# Multi Turn Logic

## 1. The Decision Logic (The "Supervisor" Pattern)

When a message comes in, the **Orchestrator** follows a specific hierarchy of checks:

1. **Is this an answer to a previous question?** If the state is `AWAITING_SLOT` (e.g., we just asked for skin type) and the user says "It's oily," we bypass the Router and send the data straight to the **Interviewer Agent**.
2. **Is there a "Pivot" detected?** If the user suddenly says, "Actually, forget skin, my hair is the real issue," the Interviewer detects a high **Intent Drift** and triggers a **Re-Route**.
3. **Is the conversation starting fresh?** Trigger the Router.

## 2. Multi-Turn State Machine

To handle this, we use the `chat_sessions` table we designed earlier. The `status` and `current_domain_id` columns tell the system where it left off.

### The Turn-by-Turn Flow:

- **Turn 1:** User says "I have dandruff."
    - *System:* Router sets domain to `hair_care`. Orchestrator sees `required_slots` for hair are empty.
- **Turn 2:** System asks "Is your scalp dry?"
    - *User:* "Yes, very dry."
    - *System:* Orchestrator sees we are in `hair_care`. It doesn't call the Router. It sends "Yes, very dry" to the **Interviewer**, who updates the `extracted_context` in the DB.
- **Turn 3:** User says "Actually, can you help with my dry skin too?"
    - *System:* The Interviewer sees the word "skin." It flags a **Domain Conflict** and hands control back to the **Router** to create a multi-domain session.

## 3. The "Context Window" Management

For multi-turn, we don't send the entire database history to the LLM every time. We use **Summarized Context**:

- **Long-Term Memory:** Stored in the `extracted_context` JSONB (e.g., `{"skin_type": "oily"}`).
- **Short-Term Memory:** The last 3–5 messages of the `chat_messages` table.
- **System Prompt:** Injected with the *current* extracted facts so the AI doesn't ask the same question twice.

| **Feature** | **How it's handled** |
| --- | --- |
| **Persistence** | The `chat_sessions` table acts as the "Brain" between API calls. |
| **Efficiency** | Router is only called on **New Intent** or **Detected Drift**. |
| **Consistency** | The `extracted_context` ensures the AI remembers facts even if the LLM "forgets" earlier parts of a long chat. |

# Database

To build a system that scales from **Wellness** to **Tools**, the database schema must be "polymorphic." We want a core set of columns that every product shares, combined with a flexible storage area for category-specific details.

| **Table** | **One-Line Description** |
| --- | --- |
| **`domains`** | Defines the **AI Specialist's persona**, what questions it must ask (slots), and where it sits in the category tree. |
| **`products`** | The **Universal Catalog** storing core data (price, SKU) and a flexible JSON block for domain-specific specs. |
| **`chat_sessions`** | Tracks the **active state** of a consultation, including the detected domain and the user's filled "slots." |
| **`chat_messages`** | Stores the **chronological history** of the chat to provide context for the AI's reasoning. |

### A. The `domains` Table (Hierarchy & Config)

This data tells the system: "If the user is in Skin Care, make sure you know their skin type before recommending anything."

```jsx
{
  "id": "d1",
  "name": "Skin Care",
  "slug": "skin-care",
  "parent_domain_id": "wellness-root-id",
  "config": {
    "required_slots": ["skin_type", "sensitivity"],
    "system_persona": "You are a dermatological consultant focusing on ingredient safety.",
    "search_filters": ["is_fragrance_free", "is_vegan"]
  }
}
```

### B. The `products` Table (The Flex-Schema)

Notice how the `attributes` change based on the domain, but the table structure remains identical.

```jsx
{
  "id": "p101",
  "name": "Hydrating B5 Gel",
  "domain_id": "d1",
  "price": 85.00,
  "attributes": {
    "skin_type": ["dry", "normal"],
    "active_ingredients": ["Hyaluronic Acid", "Vitamin B5"],
    "size": "30ml"
  }
}
```

```jsx
{
  "id": "p999",
  "name": "M18 Fuel Hammer Drill",
  "domain_id": "d50",
  "price": 199.00,
  "attributes": {
    "voltage": "18V",
    "motor_type": "Brushless",
    "chuck_size": "1/2 inch"
  }
}
```

### C. The `chat_sessions` Table (Short-Term Memory)

This is what the AI "remembers" about the current user during the conversation.

```jsx
{
  "id": "session_abc_123",
  "current_domain_id": "d1",
  "extracted_context": {
    "skin_type": "oily",
    "sensitivity": "low",
    "budget_preference": "luxury"
  },
  "status": "collecting_info"
}
```

- The **Orchestrator** checks the `chat_sessions` to see what we already know.
- It looks at the `domains` config to see if any `required_slots` are missing.
- Once all slots are filled, it generates a query against the `products` table, filtering the `attributes` JSONB column for matches (e.g., `attributes->'skin_type' ? 'oily'`).

### `products` (The Universal Catalog)

This table stores the "Source of Truth." Notice the `attributes` column; this is where we store domain-specific data like "ingredients" for wellness or "torque" for tools.

```jsx
CREATE TABLE products (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
domain_id UUID REFERENCES domains(id),
sku TEXT UNIQUE NOT NULL,
name TEXT NOT NULL,
brand TEXT,
description TEXT,
price DECIMAL(10, 2),
currency VARCHAR(3) DEFAULT 'USD',
inventory_count INT DEFAULT 0,
product_url TEXT,
image_url TEXT,

-- Domain-specific data (ingredients, voltage, etc.)
    attributes JSONB NOT NULL DEFAULT '{}', 
    
    -- Vector for semantic search (1536 is standard for OpenAI embeddings)
    description_embedding vector(1536),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fast category-based filtering
CREATE INDEX idx_products_domain ON products(domain_id);
-- GIN index for fast searching inside the JSONB attributes
CREATE INDEX idx_products_attributes ON products USING GIN (attributes);
```

### `domains` (The AI Configuration)

This table tells the AI how to behave for different categories. It stores the "Questionnaire" logic.

```jsx
CREATE TABLE domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) UNIQUE, -- e.g., 'wellness', 'tools'
    
    -- Stores the 'slots' the AI needs to fill
    -- e.g., {"required": ["skin_type", "concerns"], "optional": ["budget"]}
    config JSONB NOT NULL, 
    
    system_prompt_extension TEXT, -- Persona-specific instructions
    is_active BOOLEAN DEFAULT TRUE
);
```

To ensure the AI doesn't forget that the user has "oily skin" three messages later, we need to persist the **State**.

### `chat_sessions`

```jsx
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID, -- Optional for guests
    current_domain_id UUID REFERENCES domains(id),
    
    -- The "Slot" state: e.g., {"skin_type": "oily", "budget": 50}
    extracted_context JSONB DEFAULT '{}', 
    
    status VARCHAR(20) DEFAULT 'active', -- active, completed, referred_to_human
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### `chat_message`

```jsx
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES chat_sessions(id),
    role VARCHAR(10), -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    
    -- Links to products suggested in this specific message
    suggested_product_ids UUID[], 
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

| **Challenge** | **How this Schema Solves It** |
| --- | --- |
| **New Categories** | You simply add a row to `domains` and a new set of `products`. No code changes required to the DB structure. |
| **Attribute Search** | The `JSONB` GIN index allows the AI to filter by "Voltage" for tools as easily as "Allergens" for wellness. |
| **Hybrid Search** | The `description_embedding` allows for "Vibe/Goal" searches, while `price` and `inventory_count` allow for hard logic filters. |
| **Memory** | The `extracted_context` in the session table acts as a "Short-Term Memory" cache for the AI. |

---

# Example

![image.png](attachment:ee67e9dc-fda4-45c5-a4ae-309b0c44824f:image.png)

**Use Case: "I want to get rid of my dark spots."**

---

### **Step 1: The Entry (Superviser)**

- **User Action:** Types *"I want to get rid of my dark spots."*
- **System Action:** The **Superviser** checks the `chat_sessions` table. No active session exists.
- **Decision:** Trigger **New Flow** $\rightarrow$ Hand off to **Router Agent**.

### **Step 2: Intent Classification (Router Agent)**

- **Action:** The Router analyzes "dark spots" and "skin."
- **Mapping:** * **Detected Domain:** `skin-care` (ID: `d102`)
    - **Parent Context:** `wellness` (ID: `d101`)
- **DB Update:** Creates a new row in `chat_sessions` with `current_domain_id = d102` and `status = 'collecting_info'`.

### **Step 3: Information Gathering (Interviewer Agent)**

- **Action:** The Interviewer pulls the `required_slots` for `d102`: `[skin_type, sensitivity, current_routine]`.
- **System Response:** *"I can certainly help you brighten those dark spots. To recommend the right active ingredients, could you tell me your **skin type** (oily, dry, or combo) and if you have **sensitive skin**?"*
- **User Response:** *"I have oily skin and I'm not really sensitive."*
- **DB Update:** `extracted_context` updated to `{"skin_type": "oily", "sensitivity": "low"}`.

### **Step 4: Retrieval & Architecture (Search Architect Agent)**

- **Action:** All slots are now fetched. The Search Architect generates a **Hybrid Search Query**.
- **Query Expansion:** * **Keywords:** "hyperpigmentation," "dark spots," "brightening serum."
    - **Filters:** `attributes->'skin_type' ? 'oily'` AND `domain_id = d102`.
- **Search Execution:** Performs a cosine similarity search on the `description_embedding` in the **Product DB**.

### **Step 5: Refinement (Reranker Agent)**

- **Action:** The Search Architect returned 5 serums. The **Reranker** looks at the `extracted_context`.
- **Logic:** It notices the user has **oily skin**. It prioritizes a lightweight "Gel-based" serum over a "Heavy Cream" version. It checks the `inventory_count` and sees the top choice is in stock.

### **Step 6: Final Delivery (Response Generation Agent)**

- **Action:** Formulates the final recommendation using the `system_persona` from the `domains` table.
- **Final Output:** *"Since you have oily skin and are looking to target dark spots, I recommend a **Tranexamic Acid Serum**. It’s lightweight and won't clog your pores. Would you like to see how to incorporate this into your routine?"*

---

### **The Database State After the Flow**

Table: chat_sessions

| id | current_domain_id | extracted_context | status |

| :--- | :--- | :--- | :--- |

| sess_99 | d102 (Skin) | {"skin_type": "oily", "sensitivity": "low", "goal": "dark spots"} | completed |

Table: products (The Resulting Match)

| name | attributes (JSONB) | price |

| :--- | :--- | :--- |

| Brightening Gel | {"active": "Tranexamic Acid", "texture": "gel", "skin_type": ["oily"]} | $38.00 |

---

### **Why this works for your "Tools" requirement:**

If the user had said *"I want to hang a heavy mirror,"* the **Superviser** would have sent them to the **Router**, who would have selected the `power-tools` domain. The **Interviewer** would then have asked about the **wall material** (drywall vs. brick) instead of skin type. The logic remains identical; only the **data in the tables** changes.

Would you like me to provide the **Python Pydantic models** for these database tables so you can start coding the backend?
