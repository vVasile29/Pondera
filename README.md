# MetricMatch

A **multi-criteria decision engine** that turns natural language questions into weighted scoring matrices.

Type "should I buy a house or an apartment?" — the system parses your question, suggests relevant criteria (Cost, Location, Space, etc.), lets you tweak weights and scores, and computes the winner with a radar chart.

## Features

- **Natural language input** — ask any comparison question, no predefined forms
- **Decision ontology** — 13+ categories (Housing, Career, Fitness, Education, Technology, Vehicle, Investment, Health, Travel, Entertainment, Lifestyle, Business, Food) with curated criteria and default weights
- **Interactive review** — see what the system parsed, add/remove alternatives and criteria, adjust weights
- **Weighted scoring** — per-(alternative, criterion) weights with 0–100 sliders
- **Radar chart** — visualize how alternatives compare across all criteria
- **Monte Carlo analysis** — sensitivity analysis to see which criteria really drive the result
- **What-if analysis** — adjust a score and see how rankings change
- **Zero signup** — no accounts, no data stored on servers

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 and type a question.

## Run Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python FastAPI |
| Database | SQLAlchemy + SQLite |
| Frontend | Jinja2 + Alpine.js + Chart.js (CDN, no build step) |
| Testing | pytest + httpx |

## License

MIT
