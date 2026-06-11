# Widget Clients — Onboarding & Theming

How to register a new customer for the embedded chat widget and configure their per-tenant branding.

## Concept

Each customer that embeds the widget is identified by a **`client_id`** — a short slug you choose during onboarding (`re_001`, `acme_health`, etc.). It is the primary key of the `CurateAI-WidgetClients` DynamoDB table and serves two flows:

| Flow | How `client_id` is used |
|---|---|
| **Auth** | Customer's JWT minter puts it in the `client_id` claim → Lambda authorizer looks up JWKS URL + `tenant_id` |
| **Theming** | Widget sends it as `?client_id=...` to `/widget/config` → backend returns the row's `theme` map |

One identifier, two purposes. The customer sets it once on their page and both flows use it.

## Prerequisites

- AWS credentials for the CurateAI account (`558599919081`, `us-east-1`)
- Customer has provided their **JWKS URL** (the endpoint that publishes their public key)
- Customer has agreed on the **`iss`** claim their JWTs will use
- A `tenant_id` UUID for them (from the backend `tenants` table — create via `scripts/create_tenant.py` if new)

---

## Adding a new client

### 1. Register the client in DynamoDB

```bash
cd CurateAI

python -m scripts.create_widget_client \
  --client-id acme_001 \
  --tenant-id <tenant-uuid-from-tenants-table> \
  --jwks-url https://acme.com/.well-known/jwks.json \
  --origins https://acme.com,https://www.acme.com \
  --iss acme.com \
  --theme @theme.json    # optional — see "Theming" below
```

Required flags:

| Flag | Notes |
|---|---|
| `--client-id` | Slug you pick. Convention: lowercase, short, suffixed with a number if multiple per customer. |
| `--tenant-id` | UUID from the `tenants` table. Determines which knowledge graphs/data the widget can access. |
| `--jwks-url` | Where the Lambda authorizer fetches the customer's public keys. Customer-hosted. |
| `--origins` | Comma-separated list of domains allowed to call `/chat` *and* `/widget/config`. Enforced on every request. |
| `--iss` | Expected `iss` claim in the JWT. Must match what the customer's token endpoint mints. |

Optional flags:

| Flag | Default | Notes |
|---|---|---|
| `--rpm` | `60` | Rate limit (requests per minute) per client |
| `--theme` | none | JSON string or `@path/to/theme.json`. See "Theming" below. |
| `--profile` | `CurateAI` | AWS profile name |

The script writes one item to `CurateAI-WidgetClients` and prints the JWT claim shape the customer's token endpoint must produce.

### 2. Give the customer the embed snippet

```html
<script>
  window.CurateAIConfig = {
    apiUrl: 'https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com',
    clientId: 'acme_001',
    getAuthToken: async () => {
      const res = await fetch('/api/curateai-token');  // their token endpoint
      const data = await res.json();
      return data.token;
    },
  };
</script>
<script src="https://curateai-widget.vercel.app/curateai-widget.js"></script>
```

The `clientId` field is what triggers the widget to fetch `/widget/config` for tenant theming — leave it out and the widget uses local defaults only.

### 3. Verify

```bash
# Through API Gateway (production path)
curl "https://7c43mgwqr6.execute-api.us-east-1.amazonaws.com/widget/config?client_id=acme_001"
# Expected: 200 {"theme": {...}}  (or {"theme": {}} if no theme set yet)
```

If you see `403 Origin not allowed`, the request's `Origin` header isn't in the client's `allowed_origins` — the curl above has no Origin so it succeeds, but a browser request from an unlisted domain will be rejected.

---

## Theming

The `theme` field is a partial map of widget config keys. Anything you omit falls through to local config (set on the host page) and then to the widget's built-in defaults. So a minimal theme can be just `{"primaryColor": "#0A66C2"}`.

### Common keys

Full list: `curateai-widget/src/types.ts` → `CurateAIWidgetConfig`. The frequently used ones:

| Key | Example | Effect |
|---|---|---|
| `primaryColor` | `"#A57548"` | Bubble background, accents |
| `userBubbleColor` | `"#0A66C2"` *or* `"linear-gradient(135deg, #3B1F2B, #2A1620)"` | User message bubble |
| `assistantBubbleColor` | `"#F3F4F6"` | Assistant message bubble |
| `backgroundColor` | `"#F7F2EA"` | Chat panel background |
| `textColor` | `"#1F2937"` | Primary text |
| `textSecondaryColor` | `"rgba(31, 41, 55, 0.6)"` | Subtitles, timestamps |
| `headerGradient` | `"linear-gradient(180deg, #FFFDF9 0%, #F7F2EA 100%)"` | Header background |
| `fontFamily` | `"'Inter', sans-serif"` | All widget text |
| `borderRadius` | `24` | Bubble + panel corner radius (number, not string) |
| `title` | `"Acme Help"` | Header title |
| `subtitle` | `"Ask anything about our products"` | Header subtitle |
| `welcomeMessage` | `"Hi! How can I help?"` | First message shown |
| `placeholder` | `"Type your question..."` | Input placeholder |
| `poweredByText` | `"Powered by Acme"` | Footer text |
| `poweredByUrl` | `"https://acme.com"` | Footer link |

### Example `theme.json`

```json
{
  "primaryColor": "#0A66C2",
  "userBubbleColor": "#0A66C2",
  "assistantBubbleColor": "#F3F4F6",
  "backgroundColor": "#FFFFFF",
  "textColor": "#1F2937",
  "textSecondaryColor": "rgba(31, 41, 55, 0.6)",
  "title": "RuralEquip Help",
  "subtitle": "Ask anything about our equipment",
  "welcomeMessage": "Hi! How can I help with your equipment?",
  "placeholder": "Type your question...",
  "poweredByText": "Powered by RuralEquip",
  "poweredByUrl": "https://ruralequip.in"
}
```

### Precedence

When the widget resolves config, this is the order (lowest → highest):

```
DEFAULTS  ←  data-* attrs on script tag  ←  window.CurateAIConfig  ←  /widget/config response
```

Backend wins, but only for keys it sets — `""`, `null`, and `undefined` values from the backend are dropped, so unspecified keys fall through to local config / defaults.

---

## Updating an existing client's theme

The `create_widget_client.py` script uses `put_item` (full replace), so re-running it overwrites the whole row. Two safer ways to change just the theme:

### Option A — AWS Console (easiest)

1. DynamoDB → `CurateAI-WidgetClients` → Explore items
2. Click the row for the `client_id`
3. **Edit item** → JSON view
4. Edit or add the `theme` attribute
5. Save

Changes are live immediately — no deploy needed. The next browser load will fetch the new theme.

### Option B — CLI

```bash
aws dynamodb update-item \
  --table-name CurateAI-WidgetClients \
  --region us-east-1 \
  --key '{"client_id":{"S":"acme_001"}}' \
  --update-expression "SET #t = :theme" \
  --expression-attribute-names '{"#t":"theme"}' \
  --expression-attribute-values file://theme-update.json
```

Where `theme-update.json` is the DynamoDB-typed value:

```json
{
  ":theme": {
    "M": {
      "primaryColor": {"S": "#0A66C2"},
      "title": {"S": "Acme Help"}
    }
  }
}
```

### Removing the theme

To revert a client to defaults (or local config only):

```bash
aws dynamodb update-item \
  --table-name CurateAI-WidgetClients \
  --region us-east-1 \
  --key '{"client_id":{"S":"acme_001"}}' \
  --update-expression "REMOVE #t" \
  --expression-attribute-names '{"#t":"theme"}'
```

---

## Failure modes

| Symptom | Likely cause |
|---|---|
| `404 Client not found` | `client_id` doesn't exist in DynamoDB, or item has `is_active: false` |
| `403 Origin not allowed` | Request's `Origin` header isn't in `allowed_origins`. Add the domain via DynamoDB update. |
| `502 Config lookup failed` | DynamoDB call errored. Check ECS task logs; usually IAM (the task role needs `dynamodb:GetItem` on the table — granted in `infrastructure/stacks/ecs_stack.py`). |
| Widget renders with default colors | Either `clientId` isn't set in `window.CurateAIConfig`, or the row has no `theme` field. Both fail silently and fall back to local config. |

The widget *never* blocks on the config fetch — if `/widget/config` is unreachable, it logs a warning and renders with local config. So a backend outage degrades theming but doesn't hide the widget.

---

## Related files

- **Script**: `scripts/create_widget_client.py`
- **Backend route**: `app/api/routes/widget_config.py`
- **API Gateway wiring**: `infrastructure/stacks/auth_stack.py` (`widget_config_integration`)
- **IAM grant**: `infrastructure/stacks/ecs_stack.py` (task role `dynamodb:GetItem`)
- **Widget consumer**: `curateai-widget/src/api/widgetConfig.ts`, `src/index.ts`
- **Widget config schema**: `curateai-widget/src/types.ts` (`CurateAIWidgetConfig`)
