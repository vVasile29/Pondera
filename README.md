# Pondera

A **multi-criteria decision engine** that turns natural language questions into weighted scoring matrices.

Type a question like "should I buy a house or an apartment?", "rank Python, Java, Go", or "how good is a Tesla for commuting?". Pondera parses the prompt, infers whether you are evaluating one option, comparing two, or ranking many, suggests universal criteria, lets you tweak weights and scores, and shows the result with charts and score tables.

## Features

- **Unified natural language input** — ask one question, no mode picker or predefined forms
- **Automatic flow detection** — one option becomes a diagnosis, two options become a comparison, and three or more become a ranking
- **Universal criteria framework** — 6 value dimensions (Financial, Quality, Time, Risk, Experience, Convenience) with 12 curated metrics
- **Interactive review** — see what the system parsed, add/remove alternatives, select criteria, adjust weights
- **Weighted scoring** — per-(alternative, criterion) weights with 0–100 sliders
- **Post-hoc threshold filtering** — apply must-have thresholds on the result page to see pass/fail alternatives and ranked survivors
- **Radar chart** — visualize how alternatives compare across all criteria
- **Zero signup** — no accounts required; development uses local SQLite storage

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
