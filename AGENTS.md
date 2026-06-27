# MetricMatch — Build Instructions

This file is the single source of truth for building MetricMatch. The pipeline orchestrator reads this to plan, debate, implement, review, test, lint, and commit.

---

## 1. Project Description

MetricMatch is a **multi-attribute decision engine** web app. It helps users make decisions when there are too many variables to keep in their head.

**Core flow:**
1. User lands on a welcoming dashboard with a free-text input: *"What's your decision today?"*
2. System parses the input and suggests relevant **activities** with sensible default **metrics** and **weights**
3. User tweaks metric weights per activity (sliders, 0–100)
4. User creates a **candidate** (themselves or a hypothetical person), scores them on each metric (sliders, 0–100)
5. System computes best-fit activities, shows a radar chart + ranked list
6. **Monte Carlo mode** generates random candidates to reveal which metrics *really* discriminate for an activity
7. Users can save candidates, compare side-by-side, and drill into sub-metrics

**Philosophy:** The app should be useful *instantly* — seeded with real-life activities and metrics so the user tweaks, not creates from scratch.

---

## 2. Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Backend | Python FastAPI | Async, auto-OpenAPI, familiar |
| Database | SQLAlchemy + SQLite (dev) → PostgreSQL (prod) | Connection string swap |
| Frontend | Jinja2 + Alpine.js + Chart.js | Zero build step, no npm, CDN-loaded scripts |
| Testing | pytest + httpx | FastAPI TestClient |

**Constraint:** The frontend must work with zero node/npm dependencies. Load Alpine.js and Chart.js from CDN via `<script>` tags.

---

## 3. Data Model (SQLAlchemy)

### Metric
```python
class Metric(Base):
    __tablename__ = "metrics"

    id: int (PK, auto)
    name: str (unique, indexed)
    category: str  # e.g. "Physical", "Mental", "Environmental"
    description: str | None
    unit: str | None  # "cm", "kg", "points", "seconds", etc.
    higher_is_better: bool  # default True
    parent_id: int | None (FK → Metric.id, nullable)
```

**Sub-metrics:** A metric with `parent_id` set is a sub-metric. Depth is exactly 1 (no grandchild sub-metrics). When sub-metrics exist, the parent's score is the weighted average of its children. The parent retains its own weight for the activity.

### Activity
```python
class Activity(Base):
    __tablename__ = "activities"

    id: int (PK, auto)
    name: str (unique, indexed)
    category: str  # e.g. "Sport", "Strategy", "Profession", "Combat"
    description: str | None
```

### ActivityWeight
```python
class ActivityWeight(Base):
    __tablename__ = "activity_weights"

    id: int (PK, auto)
    activity_id: int (FK → Activity.id)
    metric_id: int (FK → Metric.id)
    weight: float  # 0.0–100.0, how much this metric matters for this activity
    # UniqueConstraint(activity_id, metric_id)
```

### Candidate
```python
class Candidate(Base):
    __tablename__ = "candidates"

    id: int (PK, auto)
    name: str
    created_at: datetime (auto)
```

### CandidateScore
```python
class CandidateScore(Base):
    __tablename__ = "candidate_scores"

    id: int (PK, auto)
    candidate_id: int (FK → Candidate.id)
    metric_id: int (FK → Metric.id)
    score: float  # 0.0–100.0
    # UniqueConstraint(candidate_id, metric_id)
```

---

## 4. Scoring Algorithm

### Fit Score (candidate → activity)

```
weights = {metric_id: weight} for activity
scores  = {metric_id: score}  for candidate

numerator   = Σ(score[m] × w)  for each m in weights ∩ scores
denominator = Σ(w)              for each m in weights

fit = numerator / denominator / 100.0  → 0.0–1.0
```

### Sub-metric resolution

When computing a candidate's score for a metric that has children:
- Load the children's scores and weights
- Compute weighted average of children → this IS the parent's score
- Use the parent's weight for the activity-level calculation

### Metric importance (from Monte Carlo)

Generate 200 random candidates. Score against target activity. Take top 10%. For each metric, compute the variance within the top 10%. Lower variance = more discriminating = more important for that activity.

---

## 5. Seed Data

On first run (or via `seed.py`), populate the database with these activities and their metric weights. This makes the app useful immediately.

| Activity | Category | Metrics (weight: 0–100) |
|----------|----------|------------------------|
| Bodybuilder (aesthetic) | Fitness | Muscle Symmetry: 85, Discipline: 70, Diet Adherence: 75, Recovery: 50, Height: 30, Weight: 60 |
| Linebacker (NFL) | Sport | Height: 60, Weight: 80, Speed: 85, Explosive Power: 90, Aggression: 75, Endurance: 50 |
| Chess Grandmaster | Strategy | Analytical Thinking: 90, Pattern Recognition: 85, Memory: 70, Endurance: 60, Patience: 80, Stress Tolerance: 40 |
| Marathon Runner | Fitness | Cardiovascular: 95, Endurance: 95, Weight: 60, Discipline: 80, Recovery: 65, Speed: 40 |
| Sumo Wrestler | Sport | Weight: 95, Height: 70, Explosive Power: 75, Balance: 80, Aggression: 65, Flexibility: 30 |
| Pilot | Profession | Reaction Time: 90, Stress Tolerance: 85, Vision: 80, Discipline: 85, Analytical Thinking: 70, Communication: 65 |
| Software Engineer | Profession | Analytical Thinking: 85, Problem Solving: 90, Attention to Detail: 80, Collaboration: 60, Creativity: 55, Discipline: 50 |

**Metrics to create** (linked to categories):
- Physical: Height, Weight, Speed, Endurance, Flexibility, Balance, Explosive Power, Aggression, Reaction Time, Vision, Recovery, Muscle Symmetry, Cardiovascular
- Mental: Analytical Thinking, Pattern Recognition, Memory, Patience, Creativity, Attention to Detail, Problem Solving
- Professional: Discipline, Communication, Collaboration, Stress Tolerance, Diet Adherence

Each metric gets a `category`, optional `unit`, and `higher_is_better: True` (default).

---

## 6. Route Table

```
GET    /                              → index.html (dashboard)
POST   /decide                        → parse free-text, suggest/create activities

GET    /activities                    → list all
POST   /activities                    → create
GET    /activities/{id}               → detail + weight sliders + sub-metrics
PUT    /activities/{id}               → update name/category/description
POST   /activities/{id}/weights       → bulk upsert metric weights
GET    /activities/{id}/mc            → monte carlo results page

GET    /metrics                       → list all, grouped by category
POST   /metrics                       → create
PUT    /metrics/{id}                  → update
DELETE /metrics/{id}                  → delete (cascade weights & scores)
POST   /metrics/{id}/sub              → add sub-metric (creates child Metric linked to parent)
GET    /metrics/{id}/suggest          → "this metric might affect these activities"

GET    /candidates                    → list saved candidates
POST   /candidates                    → create with scores dict
GET    /candidates/{id}               → detail + results (fit scores per activity)
DELETE /candidates/{id}               → delete
GET    /candidates/random             → generate random candidate + show results
POST   /candidates/compare            → accept list of IDs → comparison page

GET    /analysis/what-if              → query params: candidate_id, metric_id, new_score → recompute
```

---

## 7. File Tree

```
/home/vvasile/workspace/metricmatch/
├── main.py                   # FastAPI app, lifespan, mount routers
├── models.py                 # SQLAlchemy: Metric, Activity, ActivityWeight, Candidate, CandidateScore
├── schemas.py                # Pydantic request/response models
├── database.py               # engine, SessionLocal, Base, get_db dependency
├── seed.py                   # seed data function (call on startup if tables empty)

├── routers/
│   ├── __init__.py
│   ├── activities.py         # CRUD + weights + MC
│   ├── metrics.py            # CRUD + sub-metrics + suggest
│   ├── candidates.py         # CRUD + random + compare
│   └── analysis.py           # what-if endpoint

├── services/
│   ├── __init__.py
│   ├── scoring.py            # fit_score, normalize, resolve_submetrics
│   ├── monte_carlo.py        # generate random candidates, compute importance
│   └── suggestions.py        # on new metric: which activities might use it

├── templates/
│   ├── base.html             # layout: nav, Alpine + Chart.js CDN, custom CSS
│   ├── index.html            # dashboard: "What's your decision?" + activity cards
│   ├── activity_detail.html  # sliders per metric-weight, inline sub-metric expand
│   ├── activity_mc.html      # monte carlo results: importance table + ranges
│   ├── metric_manager.html   # CRUD table, grouped by category
│   ├── candidate_form.html   # all-metric sliders, live preview of top activities
│   ├── candidate_result.html # radar chart + ranked activity fits
│   └── compare.html          # side-by-side candidate radar charts

├── static/
│   └── css/
│       └── app.css           # clean, minimal styles (dark/light friendly)

├── tests/
│   ├── __init__.py
│   ├── test_scoring.py       # unit tests for scoring algorithm
│   ├── test_monte_carlo.py   # MC generates expected output shapes
│   └── test_routes.py        # FastAPI TestClient route tests

├── requirements.txt
├── README.md
├── AGENTS.md                 # this file
└── .gitignore
```

---

## 8. UI Design Guidelines

### Dashboard (`index.html`)
- Full-width text input: "What's your decision today?" with placeholder examples
- Below: grid of existing activity cards (icon + name + category)
- "Quick compare" button that lets you select 2–3 activities

### Activity Detail (`activity_detail.html`)
- Left: activity name, category, description (editable)
- Right: scrollable list of metric-weight pairs. Each row:
  - Metric name with category badge
  - Weight slider 0–100 (Alpine.js, updates without page reload)
  - [expand] button for sub-metrics (if any)
- When a new metric is created without weights assigned, show "needs calibration" badge

### Candidate Form (`candidate_form.html`)
- All metrics across all activities shown as sliders
- Categorized sections (Physical, Mental, Professional) — collapsible
- As sliders change, the top-3 activity fits update live (Alpine.js calls `/analysis/what-if`)
- [Save] button persists candidate

### Candidate Result (`candidate_result.html`)
- Radar/Spider chart (Chart.js) plotting candidate scores against the top-3 activity profiles
- Ranked list with fit percentage
- "Compare with another candidate" button
- "Surprise me" button

### Monte Carlo (`activity_mc.html`)
- "Generate 200 candidates" button
- Results table: Metric | Avg | Min | Max | StdDev | Importance (low stddev = high)
- Insight callout: "The most discriminating metric for {activity} is {metric}"

### Compare (`compare.html`)
- 2–4 candidates side by side with their radar charts
- Table of metric scores for direct comparison

---

## 9. Pipeline Execution Order

The pipeline orchestrator follows these phases:

### Phase 1: Planner
- Read this entire AGENTS.md
- The spec is comprehensive — only ask questions if something is genuinely ambiguous
- Write a plan with file-by-file breakdown to `.opencode-workflow-state.md`
- Set next agent: `debater`

### Phase 2: Debater
- Read the state file + this spec
- Critique: data model correctness, missing edge cases (e.g. what if a metric has no parent but children? what if weight is 0?), seed data sensibleness
- If approved, set next agent: `implementer`

### Phase 3: Implementer
- THIS IS WHERE ALL CODE IS WRITTEN
- Create every file listed in the file tree above
- `main.py` must call `seed.seed_data()` at startup if tables are empty
- Use Jinja2 templates with Alpine.js for interactivity
- Chart.js radar chart for candidate comparison
- No npm/node — CDN scripts only
- Write test files alongside source
- After writing, run `python3 -m pytest tests/ -v` to verify
- Record changes in state file
- Set next agent: `reviewer`

### Phase 4: Reviewer
- Read `git diff` and inspect all files
- Check: data model integrity, scoring correctness, UI responsiveness, test coverage
- If issues → set next agent back to `implementer`
- If clean → set next agent: `tester`

### Phase 5: Tester
- Run `python3 -m pytest tests/ -v`
- Report pass/fail and whether failures relate to recent code
- Set next agent: `linter` (if passed) or `implementer` (if failed)

### Phase 6: Linter
- Run `python3 -m py_compile main.py models.py schemas.py database.py seed.py` + all routers + all services + all tests
- Verify no syntax errors
- Set next agent: `commit-msg`

### Phase 7: Commit-msg
- Read `git diff --stat` and `git diff`
- Draft a conventional commit message
- Do NOT commit automatically

---

## 10. Key Design Decisions (from the conversation)

1. **Sub-metrics are one level deep only** — a metric can have children (parent_id FK), but no grandchildren
2. **Sub-metrics are opt-in** — expanded inline via Alpine.js, not shown by default
3. **Scores are 0–100** (not 1–5) for scientific granularity
4. **Weights are 0–100 floats** — ratio-scale, industry standard for MCDA
5. **The welcome screen's free-text input is the primary entry point** — not a form
6. **Monte Carlo generates 200 candidates** — analyzes top 10% for metric importance (low variance = high importance)
7. **Seed data makes the app useful instantly** — 7 activities with sensible weights
8. **No npm/node** — Alpine.js + Chart.js loaded from CDN
9. **FastAPI serves Jinja2 templates** — no SPA framework
10. **Database: SQLite in dev** — connection string change to PostgreSQL in prod
