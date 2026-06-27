# MetricMatch — Dynamic Decision Engine

Multi-criteria decision analysis (MCDA) web app. Type a question, get a weighted scoring matrix, tweak, and see the winner.

---

## 1. Core Flow

1. User lands on dashboard with free-text input: *"What's your decision today?"*
2. System **parses** the question — extracts alternatives (from "or"/"vs") and maps to the decision ontology
3. Shows **review page** — user adds/removes alternatives and criteria, adjusts weights
4. **Scoring page** — rate each alternative on each criterion (sliders 0–100)
5. **Results page** — ranked alternatives + radar chart (Chart.js) + detailed scores table
6. **Monte Carlo / What-if** — sensitivity analysis on any criterion

**Notable:** No predefined seed data — everything is dynamically generated from the ontology.

---

## 2. Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python FastAPI |
| Database | SQLAlchemy + SQLite (dev) → PostgreSQL (prod) |
| Frontend | Jinja2 + Alpine.js + Chart.js (CDN, zero npm) |
| Testing | pytest + httpx |

---

## 3. Data Model

### Decision
Groups one decision session. `query` is the original question, `category` from ontology mapping.

### Activity
Decision alternatives (e.g. "House", "Apartment"). Scoped to a Decision via `decision_id`.

### Metric
Decision criteria (e.g. "Cost", "Location"). Scoped to a Decision via `decision_id`. Composite unique on `(name, decision_id)`.

### ActivityWeight
Per-(alternative, criterion) weight. How much this criterion matters for this alternative. 0–100.

### AlternativeScore
Score for an alternative on a criterion. 0–100. Unique per (activity, metric).

### Candidate + CandidateScore
Legacy models for person-based evaluation (used by Activities/Metrics/Candidates routes). Not used by the decision flow.

---

## 4. Scoring Algorithm

```
For each alternative:
  numerator   = Σ(score[criterion] × weight[criterion])
  denominator = Σ(weight[criterion])
  fit         = numerator / denominator / 100.0  → 0.0–1.0
```

---

## 5. Decision Ontology

13 categories with curated criteria and default weights:

| Category | Criteria |
|----------|----------|
| Housing | Cost (90), Location (85), Space (75), Maintenance (65), Privacy (60), Safety (80), Neighborhood (70), Commute (75) |
| Career | Salary (85), Growth (80), Work-Life (75), Security (65), Culture (70), Location (60), Benefits (70) |
| Fitness | Cardio (70), Strength (75), Flexibility (60), Time (65), Cost (55), Enjoyment (80), Social (50) |
| Education | Cost (80), Time (60), Career Outcome (90), Quality (75), Flexibility (65), Network (55) |
| Technology | Price (80), Performance (85), Build (70), Battery (70), Ecosystem (60), Support (55) |
| Vehicle | Price (85), Efficiency (75), Reliability (80), Safety (85), Space (65), Performance (60) |
| Investment | Return (85), Risk (80), Liquidity (65), Horizon (55), Complexity (60), Fees (70) |
| Health | Effectiveness (90), Cost (70), Convenience (65), Side Effects (75), Sustainability (80), Evidence (70) |
| Travel | Cost (80), Attractions (85), Safety (80), Weather (65), Food (70), Accessibility (55) |
| Entertainment | Enjoyment (90), Cost (60), Time (50), Quality (75), Replayability (40), Social (45) |
| Lifestyle | Cost of Living (85), Job Market (80), Quality of Life (90), Climate (60), Community (70), Amenities (65) |
| Business | Profit (90), Startup Cost (75), Risk (70), Time (65), Scalability (75), Passion (80) |
| Food | Taste (90), Price (75), Healthiness (65), Convenience (60), Variety (50), Service (55) |

Fallback: `GENERIC_CRITERIA` for unmatched queries.

---

## 6. Routes

```
GET    /                              → dashboard
POST   /decide                        → parse question, redirect to decision flow

GET    /decisions                     → list past decisions
POST   /decisions/{id}/refine         → update alternatives/criteria
GET    /decisions/{id}/score          → scoring page
POST   /decisions/{id}/score          → submit scores → results
GET    /decisions/{id}/result         → results page (ranking + radar chart)

GET    /activities                    → redirect to / (legacy)
POST   /activities                    → create activity (JSON API)
GET    /activities/{id}               → detail + weight sliders
PUT    /activities/{id}               → update
POST   /activities/{id}/weights       → bulk upsert weights
GET    /activities/{id}/mc            → Monte Carlo results

GET    /metrics                       → list all, grouped by category
POST   /metrics                       → create (JSON API)
PUT    /metrics/{id}                  → update
DELETE /metrics/{id}                  → delete cascade
POST   /metrics/{id}/sub              → add sub-metric
GET    /metrics/{id}/suggest          → suggest activities for metric

GET    /candidates                    → list saved candidates
POST   /candidates                    → create with scores
GET    /candidates/{id}               → detail + results
DELETE /candidates/{id}               → delete
GET    /candidates/random             → random candidate
POST   /candidates/compare            → side-by-side comparison

GET    /analysis/what-if              → query: candidate_id, metric_id, new_score
POST   /analysis/preview              → live preview fit scores (from unsaved scores)
```

---

## 7. File Tree

```
├── main.py                   # FastAPI app, lifespan, mount routers
├── models.py                 # Decision, Activity, Metric, ActivityWeight, AlternativeScore, Candidate, CandidateScore
├── schemas.py                # Pydantic models
├── database.py               # engine, session, get_db dependency
├── requirements.txt

├── routers/
│   ├── activities.py         # CRUD + MC
│   ├── metrics.py            # CRUD + sub-metrics + suggest
│   ├── candidates.py         # CRUD + random + compare
│   ├── analysis.py           # what-if + preview
│   └── decisions.py          # decision flow (review → score → result)

├── services/
│   ├── scoring.py            # fit_score, resolve_submetrics, compute_alternative_fit_scores, compute_preview_fit_scores
│   ├── monte_carlo.py        # 200 random candidates, variance analysis
│   ├── ontology.py           # 13-category decision ontology + suggest_criteria() + extract_alternatives()
│   ├── parser.py             # parse_question() — ties ontology to free-text parsing
│   └── suggestions.py        # on new metric: which activities might use it

├── templates/
│   ├── base.html             # layout + Alpine.js + Chart.js CDN
│   ├── index.html            # dashboard with question input + recent decisions
│   ├── decision_review.html  # review parsed alternatives/criteria (edit names, weights, add/remove)
│   ├── decision_score.html   # score each alternative on each criterion (sliders)
│   ├── decision_result.html  # ranking + radar chart + detailed scores table
│   ├── activity_detail.html  # legacy: weight sliders + sub-metrics
│   ├── activity_mc.html      # legacy: Monte Carlo results
│   ├── metric_manager.html   # legacy: CRUD table by category
│   ├── candidate_form.html   # legacy: all-metric sliders
│   ├── candidate_list.html   # legacy: saved candidates
│   ├── candidate_result.html # legacy: radar chart + ranking
│   └── compare.html          # legacy: side-by-side candidate charts

├── static/css/
│   └── app.css               # dark/light theme, responsive

└── tests/
    ├── test_scoring.py       # scoring algorithm (7 tests)
    ├── test_monte_carlo.py   # MC output shape + invariants (4 tests)
    └── test_routes.py        # route-level integration (33 tests)
```

---

## 8. Key Design Decisions

1. **Dynamic parsing** — no predefined activities/metrics; everything comes from the ontology + user input
2. **Per-(alternative, criterion) weights** — a criterion can matter more for one option than another
3. **13-category ontology** — comprehensive enough for common decisions, extensible
4. **Hybrid UI** — show parsed results first (review), then score, then results
5. **No npm/node** — Alpine.js + Chart.js from CDN
6. **Scores 0–100**, **Weights 0–100** — granular, industry standard
7. **Monte Carlo** — 200 random candidates, top-10% variance analysis
8. **Database: SQLite (dev) → PostgreSQL (prod)** — connection string swap
