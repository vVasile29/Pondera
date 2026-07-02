# Optium

Optium is a **deterministic multi-criteria decision analysis (MCDA) engine** for transparent, repeatable decisions. Type a decision question, review the parsed alternatives, choose and tune criteria, score each option on a 0–100 fit scale, and inspect the resulting tradeoffs.

The core engine is intentionally deterministic: the final ranking is driven by user-visible criteria, weights, scores, knock-out rules, and threshold filters. Optional AI assistance can draft criteria, evidence, score suggestions, and summaries, but those suggestions are stored as reviewable artifacts and do **not** change final scores until a user applies them.

## What Optium Is

- A structured decision-framing tool built around explicit criteria, weights, scores, and tradeoffs.
- A universal fit-scoring framework that works for diagnosis, comparison, and ranking decisions.
- A transparent MCDA workflow with robustness analysis, score tables, radar charts, threshold filters, and Markdown export.
- A local-first web app with a FastAPI backend, SQLite by default, and a React/Vite frontend.

## What Optium Is Not

- **Not an expert system** — it does not encode domain-specific expertise.
- **Not financial, medical, legal, or safety advice** — it helps structure judgment; it does not replace qualified advice.
- **Not a real-time data platform** — it does not fetch live prices, reviews, regulations, or third-party data.
- **Not a black-box recommendation engine** — the decision model remains inspectable and editable.
- **Not an autonomous AI scorer** — AI-generated evidence and score drafts are pending artifacts until reviewed or applied.
- **Not a guarantee of correct outcomes** — results depend on the alternatives, criteria, weights, scores, and assumptions supplied by the user.

## How It Works

```text
Question Input
  → Parser extracts alternatives / single subject / list structure
  → Internal routing selects diagnosis, comparison, or ranking flow
  → Criteria review: select built-in metrics, add custom metrics, optional AI suggestions
  → Weight review: tune decision-level metric weights, optional AI weight suggestions
  → Knock-out review: define true must-have score gates
  → Scoring: enter 0–100 fit scores, add evidence, optionally review AI score drafts
  → Results: ranking, radar chart, table, threshold filters, robustness, export, optional AI summary
```

### Unified Prompt Entry

The landing page asks one question: **“What’s your decision today?”** There is no public mode picker. Optium infers the internal decision shape from the prompt.

| Prompt shape | Internal flow | Example |
|---|---|---|
| One option or subject | Diagnosis | `How good is a Tesla for commuting?` |
| Two options | Comparison | `House or apartment?` |
| Three or more options | Ranking | `Rank Python, Java, and Go` |

### Universal Fit Criteria

Optium seeds 12 reusable metrics across 6 dimensions. Every metric is interpreted as a direct **0–100 fit score**: higher always means better fit.

| Dimension | Question | Built-in metrics |
|---|---|---|
| Resource Fit | Is the required burden acceptable and worth it? | Affordability, Value |
| Objective Fit | Does this achieve the purpose of the decision? | Effectiveness, Quality |
| Time Fit | Does the timing work? | Timeliness, Efficiency |
| Assurance Fit | Can we trust this option to work without unacceptable downside? | Reliability, Protection |
| People Fit | Does this option fit the people affected? | Desirability, Acceptance |
| Practical Fit | Can this option realistically be done, used, accessed, operated, and adapted? | Feasibility, Flexibility |

Users can also:

- create, update, and delete **global metrics** from the `/metrics` page;
- add **decision-scoped custom metrics** during review;
- accept AI-suggested metrics as decision-scoped custom metrics.

Reserved legacy metric names such as `Cost`, `Performance`, `Risk`, and `Safety` are reconciled to the current fit ontology on startup, preserving existing metric rows where possible.

### Scoring Model

Weights are decision-level priorities shared across all alternatives. Scores and weights both use a 0–100 scale.

```text
fit = Σ(score[metric] × weight[metric]) / Σ(weight[metric]) / 100.0
```

A score of `0` means the option is a very poor fit for that metric; `100` means it is an excellent fit. Optium does not invert scores for “lower is better” criteria. Instead, the metric name and question should be phrased as a positive fit, such as `Affordability`, `Efficiency`, or `Protection`.

## Current Features

- **Unified natural-language decision entry** with diagnosis/comparison/ranking detection.
- **Four-step review workflow** for criteria, weights, knock-outs, and scoring.
- **Universal fit ontology** with 6 dimensions, 12 built-in metrics, questions, anchors, and default weights.
- **Global metric management** via the `/metrics` page.
- **Decision-scoped custom metrics** in the review workflow.
- **Decision-level weights** shared across alternatives.
- **Knock-out criteria** that act as pre-ranking eligibility gates.
- **Post-hoc threshold filters** that split scored alternatives into pass/fail groups on the results page.
- **Evidence items** linked to decisions, alternatives, and/or metrics, with pending/approved/rejected review states.
- **Score drafts** with suggested score, optional human-adjusted score, rationale, evidence links, and apply/reject workflow.
- **Optional OpenAI assistance** for metric suggestions, weight recommendations, knock-out suggestions, evidence drafts, score drafts, and result summaries.
- **Robustness analysis** using Monte Carlo sensitivity analysis on weights and scores.
- **Radar chart** and detailed score table for visual comparison.
- **Markdown export** for decision briefs.
- **Saved decisions** with delete support.
- **Dark/light theme** with system preference support.
- **Docker Compose deployment** with nginx serving the SPA and proxying `/api/*` to FastAPI.
- **Development checks** for pytest, frontend tests, TypeScript typecheck, Vite build, and Ruff.

## Optional AI Assistance

AI is disabled by default. When enabled, AI runs only on the backend and uses the configured OpenAI model. It can suggest or draft, but it cannot silently overwrite final scores.

AI-supported actions:

| Area | What AI can produce | User control |
|---|---|---|
| Criteria | Suggested custom metrics and existing-metric inclusion guidance | User accepts/rejects suggestions |
| Weights | Recommended metric weights with rationale | User applies recommendations |
| Knock-outs | Suggested must-have thresholds | User applies only true gates |
| Evidence | Pending evidence items | User approves/rejects evidence |
| Scores | Pending score drafts linked to evidence | User edits/applies/rejects drafts |
| Results | Narrative summary | Display-only summary |

Relevant environment variables:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
AI_ENABLED=false
AI_MAX_METRIC_SUGGESTIONS=8
AI_MAX_SCORE_DRAFTS_PER_REQUEST=100
AI_MAX_EVIDENCE_ITEMS_PER_REQUEST=100
```

Local helper script:

```bash
python scripts/setup_openai_env.py
```

The script reads `~/.openapi/secret_key`, updates `.env` with `OPENAI_API_KEY`, `OPENAI_MODEL`, and `AI_ENABLED`, preserves unrelated `.env` values/comments, ensures `.env` is ignored by git, and does not print the key.

## Quick Start

### Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8080.

The `web` container serves the React SPA through nginx and proxies `/api/*` to the backend. The API stores data in a named Docker volume at `/data/optium.db` by default.

Smoke checks:

```bash
curl http://localhost:8080
curl http://localhost:8080/health
curl http://localhost:8080/api/metrics
```

Delete all persisted Docker data:

```bash
docker compose down -v
```

### Local Development

Use two terminals: one for the backend API and one for the frontend dev server.

Backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api/*` requests to the backend on port `8000`.

Production frontend build:

```bash
cd frontend
npm run build
```

FastAPI does not serve the frontend static files in local development. Use nginx, the provided frontend Docker image, or another static file server for `frontend/dist/`.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `WEB_PORT` | `8080` | Host port for the Docker nginx frontend |
| `DATABASE_URL` | `sqlite:///./optium.db` | SQLAlchemy database URL |
| `CORS_ORIGINS` | `http://localhost:5173` locally; empty in Compose | Comma-separated allowed frontend origins |
| `OPENAI_API_KEY` | empty | Enables OpenAI calls when `AI_ENABLED=true` |
| `OPENAI_MODEL` | `gpt-4o-mini` in `.env.example`; `gpt-4.1-mini` in Compose fallback/setup script | OpenAI model used by backend AI helpers |
| `AI_ENABLED` | `false` | Master switch for AI assistance |
| `AI_MAX_METRIC_SUGGESTIONS` | `8` | Max AI metric suggestions per request |
| `AI_MAX_SCORE_DRAFTS_PER_REQUEST` | `100` | Max AI score drafts per request |
| `AI_MAX_EVIDENCE_ITEMS_PER_REQUEST` | `100` | Max AI evidence items per request |

## Run Tests and Checks

Backend tests:

```bash
source .venv/bin/activate
pytest tests/ -q
```

Backend lint:

```bash
source .venv/bin/activate
ruff check .
```

Frontend tests and checks:

```bash
cd frontend
npm test
npm run typecheck
npm run build
```

## API Overview

The backend exposes a REST JSON API under `/api/*`.

### Core Decisions

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/decide` | Parse a free-text question and create a decision |
| `GET` | `/api/decisions` | List saved decisions |
| `GET` | `/api/decisions/{id}` | Get decision detail, scores, filters, KO results, and robustness |
| `POST` | `/api/decisions/{id}/refine` | Save alternatives, selected metrics, weights, and optional KO criteria |
| `POST` | `/api/decisions/{id}/ko-criteria` | Update knock-out criteria |
| `POST` | `/api/decisions/{id}/score` | Save scores and compute results |
| `POST` | `/api/decisions/{id}/thresholds` | Apply result-page threshold filters |
| `POST` | `/api/decisions/{id}/thresholds/clear` | Clear threshold filters |
| `GET` | `/api/decisions/{id}/export-markdown` | Export a Markdown decision brief |
| `POST` | `/api/decisions/{id}/delete` | Delete a decision and its owned records |

### Metrics

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/metrics` | List global metrics grouped by dimension |
| `POST` | `/api/metrics` | Create a global metric |
| `PUT` | `/api/metrics/{id}` | Update a global metric |
| `DELETE` | `/api/metrics/{id}` | Delete a global metric and related weights/scores |
| `POST` | `/api/decisions/{id}/custom-metrics` | Create a decision-scoped custom metric |
| `PUT` | `/api/decisions/{id}/custom-metrics/{metric_id}` | Update a decision-scoped custom metric |
| `DELETE` | `/api/decisions/{id}/custom-metrics/{metric_id}` | Delete a decision-scoped custom metric |

### Evidence, Drafts, and AI

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/ai/status` | Report whether AI is enabled and configured |
| `GET` | `/api/decisions/{id}/evidence` | List evidence items |
| `POST` | `/api/decisions/{id}/evidence` | Create evidence manually |
| `PATCH` | `/api/decisions/{id}/evidence/{evidence_id}` | Update evidence |
| `POST` | `/api/decisions/{id}/evidence/{evidence_id}/approve` | Approve evidence |
| `POST` | `/api/decisions/{id}/evidence/{evidence_id}/reject` | Reject evidence |
| `DELETE` | `/api/decisions/{id}/evidence/{evidence_id}` | Delete evidence |
| `GET` | `/api/decisions/{id}/score-drafts` | List score drafts |
| `POST` | `/api/decisions/{id}/score-drafts` | Create a score draft manually |
| `PATCH` | `/api/decisions/{id}/score-drafts/{draft_id}` | Edit a score draft |
| `POST` | `/api/decisions/{id}/score-drafts/{draft_id}/approve` | Approve a score draft |
| `POST` | `/api/decisions/{id}/score-drafts/{draft_id}/reject` | Reject a score draft |
| `POST` | `/api/decisions/{id}/score-drafts/{draft_id}/apply` | Apply one score draft to final scores |
| `POST` | `/api/decisions/{id}/score-drafts/apply` | Bulk-apply score drafts |
| `POST` | `/api/decisions/{id}/ai/suggest-metrics` | Suggest metrics and selection guidance |
| `POST` | `/api/decisions/{id}/ai/optimize-weights` | Suggest weight adjustments |
| `POST` | `/api/decisions/{id}/ai/suggest-ko` | Suggest knock-out criteria |
| `POST` | `/api/decisions/{id}/ai/draft-evidence` | Create pending AI evidence |
| `POST` | `/api/decisions/{id}/ai/suggest-scores` | Create pending AI score drafts |
| `POST` | `/api/decisions/{id}/ai/summary` | Generate a result summary |

## Architecture

```text
Browser / API client
  → React SPA routes
    → /                      Landing prompt
    → /decisions             Saved decision list
    → /decisions/:id/review  Criteria → weights → knock-outs → scoring
    → /decisions/:id/result  Results, thresholds, robustness, export
    → /metrics               Global metric management
  → FastAPI /api/*
    → parser                 Extract decision structure
    → ontology               Seed and serialize fit metrics
    → scoring                Fit scores, KO gates, thresholds, dimensions, gaps
    → robustness             Monte Carlo sensitivity analysis
    → export                 Markdown decision brief
    → ai_decision            Optional backend-only OpenAI JSON helper
  → SQLAlchemy models
    → SQLite by default, configurable with DATABASE_URL
```

### Project Structure

```text
├── main.py                       # FastAPI app, CORS, startup table creation, metric seed reconciliation
├── models.py                     # SQLAlchemy models for decisions, metrics, scores, evidence, drafts
├── database.py                   # Engine, session factory, get_db dependency
├── routers/
│   └── api.py                    # REST endpoints under /api/*
├── services/
│   ├── ai_decision.py            # Optional OpenAI integration and AI status/caps helpers
│   ├── decision_limits.py        # Guards for max alternatives/metrics and robustness workload
│   ├── export.py                 # Markdown decision brief export
│   ├── ontology.py               # Universal fit dimensions, metrics, metadata, parser helpers
│   ├── parser.py                 # Free-text prompt parser
│   ├── robustness.py             # Monte Carlo sensitivity analysis
│   └── scoring.py                # Weighted MCDA scoring, KO gates, thresholds, gap analysis
├── scripts/
│   └── setup_openai_env.py       # Local OpenAI .env setup helper
├── docs/
│   └── ROBUSTNESS.md             # Robustness algorithm details
├── frontend/
│   ├── src/
│   │   ├── components/           # React pages and shared UI components
│   │   ├── hooks/                # Decision/scoring hooks
│   │   ├── lib/                  # API client, scoring utilities, ontology constants
│   │   └── types/                # TypeScript API/domain interfaces
│   ├── tests/                    # Frontend scoring/static tests
│   ├── package.json
│   └── vite.config.ts
└── tests/                        # Backend pytest suite
```

## Data Model Notes

- `Decision` owns alternatives (`Activity`), decision weights, thresholds, and knock-out criteria.
- `Metric` can be global (`decision_id = null`) or decision-scoped (`decision_id = decision.id`).
- `DecisionWeight` stores one shared weight per selected metric for a decision.
- `AlternativeScore` stores final user-applied scores by alternative and metric.
- `EvidenceItem` stores claims and review state for human, LLM, API, document, or system evidence.
- `ScoreDraft` stores suggested scores separately from final scores until applied.
- `ScoreDraftEvidence` links score drafts to supporting evidence.

This project uses SQLAlchemy `create_all` rather than migrations. Breaking model changes require resetting local development databases. For SQLite, delete the local `optium.db` or run `docker compose down -v` for Docker volume-backed data.

Decision size is intentionally bounded: at most 20 alternatives and 20 selected metrics. Robustness analysis is skipped when the workload exceeds the configured guard.

## Robustness Analysis

Optium uses Monte Carlo sensitivity analysis on a weighted additive value model. Each simulation perturbs weights by ±10%, score values by ±5 points, clips values to `[0, 100]`, renormalizes sampled weights where possible, and tracks whether the base winner remains first.

The results include winner-retention percentage, winner-changed percentage, rank acceptability, and a top-two score-gap interval. See [`docs/ROBUSTNESS.md`](docs/ROBUSTNESS.md) for the full algorithm.

## Development Notes

- `.env` is ignored and should not be committed.
- CORS allows explicit origins only; Docker production is same-origin through nginx.
- Optional AI requests are capped by environment variables and validated at API boundaries.
- Existing persisted thresholds and KO criteria are sanitized defensively when read back from the database.
- Public API responses intentionally omit legacy public `mode`, `category`, and `higher_is_better` fields; internal routing still uses the decision shape where needed.

## License

MIT
