# CurateAI — End-to-End Architecture

## 1. Deployment & Infrastructure

```mermaid
flowchart TB
    subgraph CLIENT["Client Layer"]
        Widget["Widget / Frontend"]
    end

    subgraph CICD["CI/CD Pipeline (CodePipeline)"]
        direction LR
        GH["GitHub<br/>main branch"]
        Build["CodeBuild<br/>Docker Build"]
        ECR["ECR<br/>curateai-app"]
        Deploy["ECS Deploy<br/>Blue/Green"]
        UpdateGW["CodeBuild<br/>Update API GW IPs"]
        GH -->|"CodeStar<br/>Connection"| Build
        Build -->|"Push image"| ECR
        ECR -->|"Pull image"| Deploy
        Deploy -->|"New task IP"| UpdateGW
    end

    subgraph AWS["AWS Cloud (us-east-1)"]
        subgraph AUTH["Authentication"]
            Cognito["Cognito User Pool<br/>JWT Tokens"]
            APIGW["API Gateway HTTP API<br/>Throttle: 50 burst / 20 rps"]
        end

        subgraph VPC["VPC (10.0.0.0/16) — Public Subnets"]
            subgraph FARGATE["ECS Fargate (1 task, On-Demand)"]
                Container["curateai-app<br/>1 vCPU / 2 GB<br/>Port 8000"]
            end
            VPCE["VPC Endpoints<br/>ECR | Logs | S3 | Bedrock"]
        end

        SM["Secrets Manager<br/>curateai/database-url"]

        subgraph OBS["Observability"]
            CWLogs["CloudWatch Logs<br/>14-day retention"]
            CWAlarms["CloudWatch Alarms<br/>CPU > 80% | Mem > 85%<br/>Tasks < 1"]
            CWDash["CloudWatch Dashboard"]
            SNS["SNS → Email Alerts"]
        end
    end

    subgraph EXTERNAL["External Services"]
        Bedrock["AWS Bedrock (us-east-2)<br/>Nova Pro v1 (LLM)<br/>Titan Embed v2 (1024d)"]
        NeonDB[("Neon PostgreSQL<br/>+ pgvector")]
    end

    Widget -->|"HTTPS"| APIGW
    Cognito -.->|"JWT Validation"| APIGW
    APIGW -->|"HTTP → Task IP:8000"| Container
    UpdateGW -->|"Update Integration URIs"| APIGW
    Container -->|"IAM Role"| Bedrock
    Container -->|"asyncpg"| NeonDB
    SM -.->|"Inject DATABASE_URL"| Container
    Container -->|"Structured Logs"| CWLogs
    CWAlarms --> SNS
    Container -.-> VPCE

    style CLIENT fill:#e8f5e9,stroke:#2e7d32
    style CICD fill:#fff3e0,stroke:#e65100
    style AUTH fill:#e3f2fd,stroke:#1565c0
    style VPC fill:#fce4ec,stroke:#c62828
    style OBS fill:#f3e5f5,stroke:#6a1b9a
    style EXTERNAL fill:#fffde7,stroke:#f57f17
```

## 2. Application Architecture (Request Flow)

```mermaid
flowchart TB
    subgraph REQUEST["Incoming Request"]
        Client["Client"]
    end

    subgraph APIGW["API Gateway"]
        Routes["Routes<br/>GET /health<br/>POST /chat<br/>POST /events<br/>POST /admin/*"]
        CogAuth["Cognito Authorizer<br/>(JWT on protected routes)"]
    end

    subgraph MIDDLEWARE["FastAPI Middleware Stack"]
        direction TB
        ReqLog["RequestLoggingMiddleware<br/>X-Request-ID, duration_ms"]
        CORS["CORSMiddleware"]
        AuthMW["get_tenant_context<br/>X-API-Key → hash → lookup<br/>IP allowlist + expiry check<br/>Fallback: seed tenant"]
        RateLimit["check_rate_limit<br/>Sliding window per tenant<br/>429 + Retry-After: 60"]
        AdminGuard["require_admin<br/>(Cognito JWT only)"]
    end

    subgraph ROUTES["API Endpoints"]
        Health["/health<br/>DB connectivity check<br/>healthy | degraded"]
        Chat["POST /chat<br/>ChatRequest → ChatResponse<br/>Session mgmt + Agent graph"]
        Events["POST /events<br/>click | add_to_cart | purchase"]
        AdminProd["POST /admin/products<br/>Upload + auto-embedding"]
        AdminKeys["POST /admin/api-keys/rotate<br/>Key rotation"]
    end

    subgraph AGENTS["Multi-Agent System<br/>(LangGraph State Machine)"]
        AgentGraph["ConsultationGraph<br/>see Agent Flow diagram"]
    end

    subgraph DATA["Data Layer"]
        SessionRepo["SessionRepository<br/>Tenant-scoped ownership"]
        ProductRepo["ProductRepository<br/>Hybrid search (vector + JSONB)"]
        TenantRepo["TenantRepository<br/>API key lookup"]
        JourneyRepo["JourneyBundleRepository<br/>Keyword matching"]
        KnowledgeGraph["Knowledge Graphs<br/>YAML + NetworkX<br/>9 domains"]
    end

    subgraph DB["PostgreSQL + pgvector"]
        Tenants[("tenants")]
        ApiKeys[("api_keys")]
        Products[("products<br/>+ vector(1024)")]
        Sessions[("chat_sessions")]
        Messages[("chat_messages")]
        JourneyBundles[("journey_bundles")]
        ProductEvents[("product_events")]
    end

    Client -->|"HTTPS"| Routes
    Routes --> CogAuth
    CogAuth --> ReqLog
    ReqLog --> CORS
    CORS --> AuthMW
    AuthMW --> RateLimit
    RateLimit --> Chat
    RateLimit --> Events
    AuthMW --> Health
    RateLimit --> AdminGuard
    AdminGuard --> AdminProd
    AdminGuard --> AdminKeys

    Chat -->|"create_initial_state()"| AgentGraph
    AgentGraph --> ProductRepo
    AgentGraph --> KnowledgeGraph
    Chat --> SessionRepo

    ProductRepo --> Products
    SessionRepo --> Sessions
    SessionRepo --> Messages
    TenantRepo --> Tenants
    TenantRepo --> ApiKeys
    JourneyRepo --> JourneyBundles
    AuthMW --> TenantRepo
    Events --> ProductEvents
    AdminProd --> Products

    style REQUEST fill:#e8f5e9,stroke:#2e7d32
    style APIGW fill:#e3f2fd,stroke:#1565c0
    style MIDDLEWARE fill:#fff3e0,stroke:#e65100
    style ROUTES fill:#e8eaf6,stroke:#283593
    style AGENTS fill:#fce4ec,stroke:#c62828
    style DATA fill:#f3e5f5,stroke:#6a1b9a
    style DB fill:#fffde7,stroke:#f57f17
```

## 3. Multi-Agent System (LangGraph State Machine)

```mermaid
stateDiagram-v2
    [*] --> EntryRouter: New message

    state EntryRouter <<choice>>
    EntryRouter --> Router: status = active / new
    EntryRouter --> Interviewer: status = awaiting_slot
    EntryRouter --> Fallback: status = fallback_conversation
    EntryRouter --> Refinement: status = completed

    state Router {
        direction LR
        Classify: Classify intent<br/>+ map domain
        FilterDomains: Filter by<br/>tenant_enabled_domains
        Classify --> FilterDomains
    }

    Router --> Interviewer: intent = query
    Router --> Journey: intent = journey
    Router --> Search: intent = direct_product
    Router --> Fallback: out_of_scope
    Router --> Safety: simple greeting / chitchat

    state Interviewer {
        direction LR
        IdentifyProblem: Identify problem<br/>via knowledge graph
        AskSlots: Ask clarifying Qs<br/>(max 3, search_impact > 0)
        IdentifyProblem --> AskSlots
    }

    Interviewer --> InitialProducts: First turn<br/>(fetch 4 samples)
    InitialProducts --> END_IP: Return to user<br/>status = awaiting_slot

    Interviewer --> Search: All slots filled<br/>or max questions reached

    state Search {
        direction LR
        BuildQuery: Build query from<br/>graph treating ingredients
        HybridSearch: pgvector similarity<br/>+ JSONB attribute filters<br/>+ tenant_id scope
        BuildQuery --> HybridSearch
    }

    Search --> Reranker

    state Reranker {
        direction LR
        SafetyFilter: Apply graph<br/>contraindications
        MatchReasons: Generate<br/>match reasons
        SafetyFilter --> MatchReasons
    }

    Reranker --> Safety

    state Safety {
        direction LR
        Response: Generate response<br/>with medical disclaimers
    }

    Safety --> END_SAFE: status = completed

    state Journey {
        direction LR
        MatchBundle: Match journey<br/>by keywords
        FetchProducts: Fetch bundle<br/>products
        MatchBundle --> FetchProducts
    }

    Journey --> Safety
    Journey --> Interviewer: Needs more info

    state Refinement {
        direction LR
        DetectIntent: Intent drift<br/>vs refinement?
    }
    Refinement --> Search: Refine results
    Refinement --> Router: New topic
    Refinement --> Interviewer: New domain
    Refinement --> IngredientInfo: Ingredient question

    state Fallback {
        direction LR
        CatalogSearch: Catalog-wide<br/>hybrid search
    }

    Fallback --> END_FB: Response with<br/>best-effort results

    state IngredientInfo {
        direction LR
        Educate: Educational<br/>ingredient response
    }

    IngredientInfo --> END_II: status = completed

    END_IP: [Return to user]
    END_SAFE: [Return to user]
    END_FB: [Return to user]
    END_II: [Return to user]
```

## 4. Data Model (Entity Relationships)

```mermaid
erDiagram
    TENANTS {
        uuid id PK
        string name UK
        string slug UK
        array enabled_domains
        array allowed_origins
        bool is_active
        int daily_bedrock_cost_cap_cents
    }

    API_KEYS {
        uuid id PK
        uuid tenant_id FK
        string key_hash UK
        string key_prefix
        string label
        array allowed_ips
        int rate_limit_rpm
        bool is_active
        timestamp expires_at
        timestamp last_used_at
    }

    PRODUCTS {
        uuid id PK
        uuid tenant_id FK
        array domain_slugs
        string sku UK
        string name
        string brand
        float price
        jsonb attributes
        vector description_embedding
        bool is_active
    }

    CHAT_SESSIONS {
        uuid id PK
        uuid tenant_id FK
        uuid user_id
        string current_domain_slug
        jsonb extracted_context
        string status
    }

    CHAT_MESSAGES {
        uuid id PK
        uuid tenant_id FK
        uuid session_id FK
        string role
        text content
        array suggested_product_ids
    }

    JOURNEY_BUNDLES {
        uuid id PK
        uuid tenant_id FK
        string domain_slug
        string journey_id
        string name
        array keywords
        jsonb guidance_templates
        bool is_active
    }

    PRODUCT_EVENTS {
        uuid id PK
        uuid tenant_id FK
        uuid session_id FK
        uuid product_id FK
        string event_type
        jsonb metadata
    }

    TENANTS ||--o{ API_KEYS : "has"
    TENANTS ||--o{ PRODUCTS : "owns"
    TENANTS ||--o{ CHAT_SESSIONS : "owns"
    TENANTS ||--o{ JOURNEY_BUNDLES : "owns"
    TENANTS ||--o{ PRODUCT_EVENTS : "tracks"
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : "contains"
    CHAT_SESSIONS ||--o{ PRODUCT_EVENTS : "generates"
    PRODUCTS ||--o{ PRODUCT_EVENTS : "receives"
```

## 5. CI/CD Pipeline (Detailed)

```mermaid
flowchart LR
    subgraph SOURCE["Stage 1: Source"]
        GH["GitHub<br/>main branch"]
    end

    subgraph BUILD["Stage 2: Build"]
        CB["CodeBuild<br/>Ubuntu 7.0<br/>2 vCPU / 3 GB"]
        ECR["ECR<br/>curateai-app"]
        CB -->|"docker build<br/>docker push<br/>:latest + :commit"| ECR
    end

    subgraph DEPLOY["Stage 3: Deploy"]
        ECS["ECS Fargate<br/>Update task def<br/>Circuit breaker<br/>rollback"]
    end

    subgraph UPDATEGW["Stage 4: Update API GW"]
        GetIP["Get new task<br/>public IP"]
        UpdateInt["Update ALL<br/>integration URIs<br/>dynamically"]
        GetIP --> UpdateInt
    end

    GH -->|"CodeStar<br/>OAuth"| CB
    ECR -->|"Pull image"| ECS
    ECS -->|"Task running"| GetIP
    UpdateInt -->|"http://NEW_IP:8000/*"| APIGW["API Gateway"]

    style SOURCE fill:#e8f5e9
    style BUILD fill:#fff3e0
    style DEPLOY fill:#e3f2fd
    style UPDATEGW fill:#fce4ec
```

## 6. Authentication & Tenant Resolution

```mermaid
flowchart TB
    Request["Incoming Request"] --> HasKey{"X-API-Key<br/>header?"}

    HasKey -->|"Yes"| HashKey["SHA-256 hash key"]
    HasKey -->|"No"| SeedTenant["Fallback to<br/>Seed Tenant<br/>00000000-...-000001"]

    HashKey --> Lookup["DB Lookup<br/>api_keys JOIN tenants"]
    Lookup --> Found{"Key found<br/>& active?"}

    Found -->|"No"| Err401["401 Unauthorized"]
    Found -->|"Yes"| CheckIP{"IP in<br/>allowed_ips?"}

    CheckIP -->|"No"| Err403["403 Forbidden"]
    CheckIP -->|"Yes / No restriction"| CheckExpiry{"Key<br/>expired?"}

    CheckExpiry -->|"Yes"| Err401_2["401 Expired"]
    CheckExpiry -->|"No"| RateCheck{"Under<br/>rate limit?<br/>(RPM)"}

    RateCheck -->|"No"| Err429["429 Too Many Requests<br/>Retry-After: 60"]
    RateCheck -->|"Yes"| TenantCtx["TenantContext<br/>tenant_id, slug,<br/>enabled_domains,<br/>allowed_origins,<br/>rate_limit_rpm,<br/>cost_cap"]

    SeedTenant --> TenantCtx

    TenantCtx --> Route["Route Handler<br/>/chat, /events, etc."]

    style Request fill:#e3f2fd
    style TenantCtx fill:#e8f5e9,stroke:#2e7d32
    style Err401 fill:#ffcdd2,stroke:#c62828
    style Err403 fill:#ffcdd2,stroke:#c62828
    style Err401_2 fill:#ffcdd2,stroke:#c62828
    style Err429 fill:#fff3e0,stroke:#e65100
```
