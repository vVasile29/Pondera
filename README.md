# Optium

Optium is a **deterministic multi-criteria decision analysis engine** for
transparent, repeatable decisions. Ask a decision question, review the parsed
alternatives, score each option against universal criteria, and inspect the
resulting tradeoffs.

It does not give domain-specific advice, fetch real-time facts, or make
black-box recommendations. The user supplies or reviews every score. Optium's
value is structure, transparency, robustness, and tradeoff analysis.

## Why This Exists

Most decisions are made with intuition, ad-hoc spreadsheets, or inconsistent
criteria. Optium makes criteria, weights, scores, tradeoffs, and robustness
explicit and inspectable — so you can see *why* one option ranks above another
and how stable that ranking is under uncertainty.

## What Optium Is Not

- **Not an expert system** — it does not encode domain knowledge or provide
  factual advice.
- **Not financial, medical, or legal advice** — it is a structured
  decision-framing tool.
- **Not a real-time data platform** — it does not fetch live prices, reviews,
  or third-party data.
- **Not an LLM reasoning wrapper** — its parser extracts structure from
  free-text prompts; the MCDA framework, not persuasive prose, drives the
  output.
- **Not a guarantee of correct outcomes** — results depend entirely on the
  criteria, weights, and scores the user provides.

## How It Works

```
Question Input
  → Parser (extracts alternatives / single subject / list structure)
  → Internal Routing (diagnosis / comparison / ranking)
  → Review (edit alternatives, select from pre-seeded criteria, adjust weights,
    set knock-out thresholds)
  → Score (rate each alternative on each criterion, 0–100)
  → Results (fit scores, radar chart, score table, KO evaluation,
    threshold filters, robustness analysis)
```

### 1. Unified Prompt Entry

The landing page asks a single question: *"What's your decision today?"* There
is no mode picker. The parser auto-detects the decision shape:

| Prompt shape | Internal flow | Example |
|---|---|---|
| One option or subject | Diagnosis | "How good is a Tesla for commuting?" |
| Two options | Comparison | "House or apartment?" |
| Three or more options | Ranking | "Rank Python, Java, Go" |

### 2. Universal Criteria Framework

Every decision uses the same 6 pre-seeded fit dimensions with 12 curated
metrics. Metrics are global and shared — no per-decision criteria creation.

| Dimension | Question | Metrics |
|---|---|---|
| Resource Fit | Is the required burden acceptable and worth it? | Affordability, Value |
| Objective Fit | Does this achieve the purpose of the decision? | Effectiveness, Quality |
| Time Fit | Does the timing work? | Timeliness, Efficiency |
| Assurance Fit | Can we trust this option to work without unacceptable downside? | Reliability, Protection |
| People Fit | Does this option fit the people affected? | Desirability, Acceptance |
| Practical Fit | Can this option realistically be done, used, accessed, operated, and adapted? | Feasibility, Flexibility |

### 3. Decision-Level Weights

Weights represent the decision-maker's priorities and are shared across all
alternatives. The scoring formula is a weighted additive MCDA model:

```
fit = Σ(score[criterion] × weight[criterion]) / Σ(weight[criterion]) / 100.0
```

Every slider is a 0–100 fit score. Higher always means better fit. Scores and
weights both use a 0–100 granular scale.

### 4. Results, Thresholds, and Robustness

- **Knock-out (KO) criteria** — set minimum score thresholds per criterion
  on the review page. Alternatives failing any KO criterion are eliminated
  before ranking. KO criteria act as a pre-scoring eligibility gate.
- **Radar chart** — visualize how alternatives compare across all criteria.
- **Post-hoc threshold filters** — apply must-have cutoffs (e.g.
  `Affordability >= 60`, `Protection >= 80`) after scoring to separate passing
  and failing alternatives. Thresholds operate on the displayed user-entered fit scores — the score
  you see on the slider is the score compared against the threshold.
- **Robustness analysis** — Monte Carlo sensitivity analysis that perturbs
  weights and scores within a plausible range, then reports how often the
  ranking holds. See [`docs/ROBUSTNESS.md`](docs/ROBUSTNESS.md) for the full
  algorithm.

## Features

- **Unified natural language input** — one prompt, no mode picker
- **Automatic flow detection** — diagnosis, comparison, or ranking inferred
  from the prompt structure
- **Universal criteria framework** — 6 value dimensions, 12 curated metrics,
  pre-seeded globally
- **Interactive review** — inspect and edit parsed alternatives, select
  from pre-seeded criteria, adjust decision-level weights, set knock-out
  thresholds per criterion
- **Weighted scoring** — 0–100 sliders, weighted additive MCDA model
- **Knock-out (KO) criteria** — define minimum score thresholds per criterion;
  alternatives that fail any KO criterion are eliminated before ranking
- **Decision robustness** — Monte Carlo sensitivity analysis with winner
  retention and rank acceptability
- **Post-hoc threshold filtering** — must-have cutoffs applied after scoring
- **Radar chart** — Chart.js visualization for multi-criteria comparison
- **Metrics management** — built-in page to create, edit, and delete criteria
  across the 6 universal dimensions
- **Zero signup** — no accounts required; decisions stored in the configured
  backend database (SQLite by default)
- **Dark/light mode** — toggleable theme with system preference detection

## Quick Start

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Optional AI draft assistance uses OpenAI on the backend only. Put your key in
`~/.openapi/secret_key`, then run:

```bash
python scripts/setup_openai_env.py
docker compose up --build
```

The script writes `OPENAI_API_KEY`, `OPENAI_MODEL`, and `AI_ENABLED` to the
root `.env` without printing the key. AI creates pending evidence and score
drafts only; final scores change only when you apply a draft.

Open http://localhost:8080. The nginx container serves the SPA and proxies
`/api/*` requests to the backend.

Smoke checks:

```bash
curl http://localhost:8080
curl http://localhost:8080/health
curl http://localhost:8080/api/metrics
```

Data persists in a named Docker volume (`optium-data`). Use
`docker compose down -v` to delete all saved decisions.

### Local Development

You need **two terminals** — one for the backend API and one for the frontend
dev server.

**Backend:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api/*` requests to
the backend on port 8000.

**Production build:**

```bash
cd frontend
npm run build
# Serve frontend/dist/ with nginx or another static file server
# (FastAPI does not serve static files by default)
```

## Run Tests

**Backend:**

```bash
source .venv/bin/activate
pytest tests/ -v
```

**Frontend:**

```bash
cd frontend
npx tsc --noEmit
npx vite build
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python FastAPI (REST JSON API) |
| Database | SQLAlchemy + SQLite (default); other SQL databases may be usable via `DATABASE_URL` |
| Frontend | React 18 + TypeScript + Vite + Shadcn UI + Chart.js |
| Testing | pytest + httpx (backend) / TypeScript + Vite (frontend) |

## Architecture

### Request Flow

```
Browser / API client
  → POST /api/decide (free-text question)
    → services/parser.py (extract alternatives, detect flow)
    → Internal routing (diagnose / compare / rank)
    → Review page (edit alternatives, select from pre-seeded criteria, adjust weights)
    → Scoring page (0–100 sliders per alternative × criterion)
    → Result page (fit scores, radar chart, score table)
    → Optional threshold filters + robustness analysis
```

The backend serves a RESTful JSON API under `/api/*`. The frontend is a
client-side React SPA that communicates exclusively with these API endpoints.

### Project Structure

```
├── main.py                       # FastAPI app, CORS, router mounts
├── models.py                     # SQLAlchemy models
├── database.py                   # Engine, session, get_db
├── routers/
│   └── api.py                    # JSON API endpoints (/api/*)
├── services/
│   ├── scoring.py                # Weighted MCDA score computation
│   ├── robustness.py             # Monte Carlo sensitivity analysis
│   ├── ontology.py               # Pre-seeded universal criteria dimensions
│   ├── parser.py                 # Free-text question parser
│   ├── export.py                 # Markdown decision brief export
│   └── decision_limits.py        # Workload guards for robustness
├── frontend/                     # React SPA
│   ├── src/
│   │   ├── components/           # Page and shared components (incl. MetricsManager)
│   │   ├── hooks/                # Custom React hooks
│   │   ├── lib/                  # API client, scoring utilities
│   │   └── types/                # TypeScript interfaces
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.ts
└── tests/
    ├── test_ontology.py
    ├── test_parser.py
    ├── test_robustness.py
    ├── test_scoring.py
    └── test_routes.py
```

### Notes

- **Thresholds** are a post-hoc result-page feature, not a separate entry mode.
- **Decision-level weights** (`DecisionWeight` model) are shared across all
  alternatives for a given decision.
- **Development schema resets** may be required after breaking model changes.
  This project uses SQLAlchemy `create_all` rather than migrations, so delete or
  recreate local SQLite databases when columns or constraints change.
- The database defaults to SQLite. Other `sqlalchemy`-compatible databases may
  work via the `DATABASE_URL` environment variable, but only SQLite is tested
  in development and Docker.

## License

MIT
