# B2C v1 — Backend (FastAPI)

10-rule product recommendation API. Reads from the live `b2c-v1` PostgreSQL DB.
**No `chatbot_*` tables are used** — only product, sales, inventory, and traffic tables.

Runs on **port 8000**.

---

## ⚡ Quick setup

**Requires Python 3.10+.** Install from [python.org/downloads](https://www.python.org/downloads/)
(on Windows, tick **"Add python.exe to PATH"** in the installer), then confirm:

```
python --version                                # should print Python 3.10 or higher
pip --version                                   # confirm pip is available
```
> If `python` isn't found on Windows, try `py --version`. On macOS / Linux use `python3 --version`.

```
1. cd b2c-ai-assistant                          # open the project folder
2. copy .env.example .env                       # then edit DB creds, topview creds, etc.
3. add google-credentials.json                  # place in this folder 
4. python -m venv .venv                          # create virtual env
5. .venv\Scripts\activate.bat                    # cmd     (PowerShell: .\.venv\Scripts\Activate.ps1)
6. pip install -r requirements.txt               # install deps
7. run the SQL setup scripts                     # create + seed tables (see below)
8. python run.py                                 # start the server
9. open http://127.0.0.1:8000/                   # check the API is running
```

**Step 7 — run the SQL setup scripts.** Create and seed the tables the API needs.
Run both files against your `b2c-v1` DB (uses the same creds you set in `.env`):

```
psql -h <hostname> -U <username> -d <database_name> -f sql/rules_table.sql
psql -h <hostname> -U <username> -d <database_name> -f sql/top_view_ai_creation_logs.sql
```
> `rules_table.sql` creates + upserts the `rules_tags` seed rows; `top_view_ai_creation_logs.sql`
> creates the video-creation log table. Both are safe to re-run.

---

## Step-by-step run

### Step 1 — open a terminal in this folder

**cmd:**
```cmd
cd /d "d:\B2C\_B2c_php\works\backend"
```
**PowerShell:**
```powershell
cd "d:\B2C\_B2c_php\works\backend"
```

Then copy the env template (it lives in this folder) and fill in your values:

**cmd:**
```cmd
copy .env.example .env
```
**PowerShell:**
```powershell
copy .env.example .env
```

Open `.env` and set your real `DB_PASSWORD` (and `PROJECT_ID` / `LOCATION` / `MODEL` if you want the Vertex AI layer on).

### Step 2 — install dependencies

Create a virtual environment first (recommended), then install:

**cmd:**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```
**PowerShell:**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
> If PowerShell blocks the activate script, run this once and retry:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

> macOS / Linux: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`

### Step 3 — start the server

```cmd
python run.py
```
_(Same command in cmd and PowerShell.)_

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

### Step 4 — verify it works

Open these in a browser (or `curl`):

- Health check → http://127.0.0.1:8000/health
- List of rules → http://127.0.0.1:8000/rules
- Companies (for the UI dropdown) → http://127.0.0.1:8000/companies
- API docs (Swagger) → http://127.0.0.1:8000/docs

Test the chat endpoint:

**cmd:**
```cmd
curl -X POST http://127.0.0.1:8000/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"message\":\"best profit margin products\",\"company_id\":2314}"
```
**PowerShell:**
```powershell
curl -X POST http://127.0.0.1:8000/chat `
  -H "Content-Type: application/json" `
  -d '{"message":"best profit margin products","company_id":2314}'
```

### Step 5 — the flow (codebase)

```
User Request
     ↓
Rule Classification
(Keyword Router → selects 1 rule)        →  classify() in app/rules/registry.py
Example: "viral"
     ↓
Run SQL Query                            →  rule_*() in app/rules/queries.py
- Apply rule condition
  CTR > 1.5 × Avg CTR
  PV  < 0.5 × Avg PV
- Rank products
- LIMIT 2 (PRODUCT_LIMIT)
     ↓
Top 2 Matching Products
(with PV, CTR, ATC, averages, etc.)
     ↓
Prepare Gemini Input                        →  RULE_AI_CONTEXT in app/rules/ai.py
- Rule definition
- Detection logic
- Recommendation reason
- KPI target
- Actual product metrics
     ↓
Gemini Analysis                             →  enrich_reason() / enrich_product_reason()
- Convert generic rule into store-specific insights
- Generate personalized reasons
     ↓
Output
- Store-level AI reason
- Product 1 AI reason
- Product 2 AI reason
     ↓
Final Response
(2 products + personalized recommendations)
```

> **SQL selects the products. Gemini does NOT pick, rank, or drop anything.** Gemini only
> rewrites the static detection/reason text using the store's real numbers. If Gemini is
> disabled (`IS_AI_ENABLE=false`) or fails, the static spec text is returned verbatim.
> Full detail: [docs/ai_recommendation_flow.md](docs/ai_recommendation_flow.md).

---

## The 10 rule formulas

Each rule's trigger formula is enforced in SQL ([queries.py](app/rules/queries.py)) and the
text version is fed to Gemini as grounding (`RULE_AI_CONTEXT` in [ai.py](app/rules/ai.py)).

| # | Tag | Label | Trigger formula |
|---|---|---|---|
| 1 | `viral` | 🔥 Potential Viral Product | CTR > (Store Avg × 1.5) **AND** PV < (Store Avg × 0.5) |
| 2 | `clearance` | Inventory Clearance Candidate | Current Inventory > 100 units **AND** 30-day Sales < 5 (or DOI > 90 days) |
| 3 | `hidden_gem` | Hidden Gem Product | CR > (Store Avg × 2.0) **AND** Impressions < Bottom 20% |
| 4 | `high_attention` | High Attention, Low Purchase | PV in Top 5% **AND** ATC < (Store Avg × 0.6) |
| 5 | `basket_magnet` | Shopping Basket Magnet | (Orders with Multiple Products / Total Orders) > 40% |
| 6 | `seasonal` | Seasonal / Trending Product | Google Trends keyword growth > 30% **AND** category matches seasonal tags |
| 7 | `loyalty` | Customer Loyalty Favorite | (Repeat Customers / Total Customers) > 20% |
| 8 | `profit` | Profit Protection Product | (Selling Price − Cost) / Selling Price > 50% |
| 9 | `engagement` | User Engagement Leader | Average Product Page Dwell Time > 90 seconds |
| 10 | `momentum` | New Product Momentum | (Today's Sales / 7-Day Avg Sales) > 2.0 **AND** Product Age < 7 days |

Acronyms: **CTR** Click-Through Rate · **PV** Page Views · **CR** Conversion Rate ·
**ATC** Add-to-Cart Rate · **AOV** Average Order Value · **LTV** Lifetime Value ·
**ROAS** Return on Ad Spend · **DOI** Days of Inventory.

---

## Environment variables

Set these in `.env` inside this `backend/` folder. See [.env.example](.env.example).

| Var | Default | Purpose |
|---|---|---|
| `DB_HOST` | `localhost` | Postgres host |
| `DB_PORT` | `5432` | Postgres port |
| `DB_NAME` | `b2c-v1` | Database name |
| `DB_USER` | `postgres` | DB user |
| `DB_PASSWORD` | `postgres` | DB password |
| `WINDOW_MULT` | `12` | Multiplies all 30d/7d/90d windows so rules return rows against the stale demo snapshot (data is Dec 2025 – Jan 2026). **Set to `1` in production.** |
| `IS_AI_ENABLE` | `false` | Turn the Vertex AI (Gemini) explanation layer on/off |
| `PROJECT_ID` | — | Google Cloud project ID; required when `IS_AI_ENABLE=true` |
| `LOCATION` | `us-central1` | Vertex AI region |
| `MODEL` | `gemini-2.5-flash` | Gemini model used for enrichment |

---

## Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET  | `/health` | — | `{"status":"ok"}` |
| GET  | `/rules` | — | `[{tag,label}, …]` (the 10 tags) |
| GET  | `/companies` | — | Companies with pixel/sales activity (for UI) |
| POST | `/chat` | `{message, company_id}` | `ChatResponse` with `tag`, `tag_label`, `kpi_target`, `reason`, `top_products[]`, `notes[]` |

---

## Project layout

```
backend/
├── run.py              # launcher — `python run.py` → :8000
├── requirements.txt
├── README.md           # this file
├── docs/               # per-rule specs + ai_recommendation_flow.md
└── app/
    ├── __init__.py
    ├── main.py         # FastAPI app, CORS, endpoints
    ├── db.py           # SQLAlchemy engine, reads ../.env
    ├── schemas.py      # Pydantic request/response models
    └── rules/
        ├── __init__.py
        ├── registry.py # keyword intent router + rule metadata
        ├── queries.py  # 10 rule SQL implementations
        └── ai.py       # RULE_AI_CONTEXT + Gemini enrichment
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'fastapi'`**
→ You skipped Step 2, or your venv isn't activated. Run `pip install -r requirements.txt`.

**`could not connect to server` / `password authentication failed`**
→ Check `.env` credentials. Verify Postgres is running:
```cmd
psql -h localhost -U postgres -d b2c-v1 -c "SELECT 1;"
```
_(Same command in cmd and PowerShell.)_

**Port 8000 already in use**
**cmd:**
```cmd
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```
**PowerShell:**
```powershell
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess
Stop-Process -Id <PID> -Force
```

**`/chat` returns matched=0 for every query**
→ Expected on this demo dataset for strict rules. Confirm `WINDOW_MULT=12` (or higher) is set. Try `best profit margin` against company `2314` — it returns 2 real products.
