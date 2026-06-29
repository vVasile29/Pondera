# Pondera

A **multi-criteria decision engine** that turns natural language questions into weighted scoring matrices.

Type a question like "should I buy a house or an apartment?", "rank Python, Java, Go", or "how good is a Tesla for commuting?". Pondera parses the prompt, infers whether you are evaluating one option, comparing two, or ranking many, suggests universal criteria, lets you tweak weights and scores, and shows the result with radar charts and score tables.

## Features

- **Unified natural language input** — ask one question, no mode picker or predefined forms
- **Automatic flow detection** — one option becomes a diagnosis, two options become a comparison, and three or more become a ranking
- **Universal criteria framework** — 6 value dimensions (Financial, Quality, Time, Risk, Experience, Convenience) with 12 curated metrics
- **Interactive review** — see what the system parsed, add/remove alternatives, select criteria, adjust weights
- **Weighted scoring** — per-(alternative, criterion) weights with 0–100 sliders
- **Post-hoc threshold filtering** — apply must-have thresholds on the result page to see pass/fail alternatives and ranked survivors
- **Radar chart** — visualize how alternatives compare across all criteria
- **Zero signup** — no accounts required; development uses local SQLite storage
- **Dark/light mode** — toggleable theme with system preference detection

## Quick Start

You need **two terminals** — one for the backend API and one for the frontend dev server.

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and type a question. The Vite dev server proxies `/api` requests to the backend on port 8000.

### Production Build

```bash
cd frontend
npm run build
# Serve frontend/dist/ from FastAPI or nginx
```

## Run Tests

### Backend

```bash
source .venv/bin/activate
pytest tests/ -v
```

### Frontend

```bash
cd frontend
npx tsc --noEmit
npx vite build  # also verifies the build succeeds
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python FastAPI (pure REST JSON API) |
| Database | SQLAlchemy + SQLite (dev) / PostgreSQL (prod) |
| Frontend | React 18 + TypeScript + Vite + Shadcn UI + Chart.js |
| Testing | pytest + httpx (backend) / TypeScript + Vite (frontend) |

## Architecture

The backend serves a RESTful JSON API under the `/api/` prefix. The frontend is a client-side React SPA that communicates with the API. During development, Vite proxies `/api/*` requests to `http://localhost:8000`.

Decision mode routing is automatic:
- **Diagnosis** — single option → `/evaluate/:id/`
- **Comparison** — two options → choose flow `/decisions/:id/`
- **Ranking** — three or more options → `/rank/:id/`

## Project Structure

```
├── main.py                  # FastAPI app, CORS, router mounts
├── routers/
│   ├── api.py               # JSON API endpoints (/api/*)
│   ├── decisions.py         # Compare flow (backward compat)
│   ├── evaluate.py          # Diagnosis flow (backward compat)
│   ├── metrics.py           # Metric CRUD (backward compat)
│   ├── rank.py              # Ranking flow (backward compat)
│   └── screen.py            # Legacy screen flow (backward compat)
├── models.py                # SQLAlchemy models
├── schemas.py               # Pydantic schemas
├── services/
│   ├── scoring.py           # Score computation logic
│   ├── ontology.py          # Universal criteria dimensions
│   └── parser.py            # Free-text question parser
├── frontend/                # React SPA
│   ├── src/
│   │   ├── components/      # Page & shared components
│   │   ├── hooks/           # Custom React hooks
│   │   ├── lib/             # API client, scoring utils
│   │   └── types/           # TypeScript interfaces
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.ts
└── tests/
    ├── test_ontology.py
    ├── test_parser.py
    ├── test_scoring.py
    └── test_routes.py
```

## License

MIT
