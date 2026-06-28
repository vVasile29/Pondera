# Pondera

A **multi-criteria decision engine** that turns natural language questions into weighted scoring matrices.

Type "should I buy a house or an apartment?" — the system parses your question, suggests relevant criteria (Cost, Location, Space, etc.), lets you tweak weights and scores, and computes the winner with a radar chart.

## Features

- **Natural language input** — ask any comparison question, no predefined forms
- **Universal criteria framework** — 6 value dimensions (Financial, Quality, Time, Risk, Experience, Convenience) with 12 curated metrics
- **Interactive review** — see what the system parsed, add/remove alternatives, select criteria, adjust weights
- **Weighted scoring** — per-(alternative, criterion) weights with 0–100 sliders
- **Radar chart** — visualize how alternatives compare across all criteria
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
