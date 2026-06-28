# Pondera — Dynamic Decision Engine

## What we are building

A **universal multi-criteria decision analysis (MCDA) engine** that can answer
any structured decision question. One scoring core. Many question modes.

The engine is **not** an expert system — it does not know domain facts. Instead
it provides a structured framework for people to think through decisions
systematically, using academically validated criteria.

---

## Academic foundation

| Source | What we use |
|--------|-------------|
| **Keeney's Value-Focused Thinking** (1992) | Values-first: define what matters before evaluating alternatives |
| **Belton & Stewart's MCDA Framework** (2002) | The 6 universal value dimensions + weighted sum model |
| **Roy's Problem Typology** (1996) | The 4 canonical question types (Choice, Sorting, Ranking, Description) |
| **Tversky's Elimination by Aspects** (1972) | Threshold-based screening logic |
| **Student's t-test** | Statistical significance of score differences |

### The 6 Universal Dimensions

These are the minimum criteria set that applies to **any** decision. They never
change — they are the foundation.

| Dimension | Metrics | Direction |
|-----------|---------|-----------|
| Financial | Cost, Value | ↓ Cost, ↑ Value |
| Quality | Quality, Performance | ↑ both |
| Time | Time Required, Efficiency | ↓ Time, ↑ Efficiency |
| Risk | Risk, Safety | ↓ Risk, ↑ Safety |
| Experience | Enjoyment, Satisfaction | ↑ both |
| Convenience | Convenience, Accessibility | ↑ both |

---

## The 7 Canonical Modes

One engine, multiple modes. Each mode maps to an academically recognized
decision problem type. Each mode adds only a parser + UI — the core scoring
algorithm, 6 dimensions, and database models stay the same.

### Mode 1: CHOOSE (P.α) — ✅ Live
**Problem:** Select the best from a set.
**Input:** "X or Y?" or "Which Z should I pick?"
**Output:** Ranked alternatives with fit scores.
**Current status:** Fully implemented. Parses "or"/"vs"/"versus", extracts
alternatives, scores against universal criteria, shows ranking + radar chart
+ t-test significance.

### Mode 2: DIAGNOSE (P.δ) — 🔶 Next (~2 days)
**Problem:** Evaluate a single option against a goal.
**Input:** "How good is X for Y?" or just "Rate my X".
**Parser:** Extract single subject + optional goal context. Map to criteria.
**Output:** Single score + dimension-by-dimension breakdown + gap analysis
("you're strong in Quality but weak in Cost").
**New code:** `routers/evaluate.py`, `templates/evaluate_result.html`, parser
extension.

### Mode 3: SCREEN (P.β) — 🔲 Phase 2 (~1 week)
**Problem:** Which options meet my minimum requirements?
**Input:** Options + per-criterion thresholds ("Cost ≤ 60, Quality ≥ 70").
**Parser:** Extract alternatives + threshold constraints from structured input
or free text.
**Logic:** Elimination by Aspects — filter out any alternative that fails one
or more thresholds. Remaining alternatives enter CHOOSE scoring.
**Output:** Pass/fail per alternative + ranked survivors.
**New code:** Threshold UI on review page, elimination step in scoring pipeline.

### Mode 4: RANK (P.γ) — 🔲 Phase 2 (mostly works)
**Problem:** Order N alternatives from best to worst.
**Input:** Free-text list or manual entry of 3+ options.
**Parser:** No "or" needed — user provides alternatives directly.
**Output:** Full ranking with fit scores. Radar chart already handles N
alternatives.
**New code:** Alternative input UI (add/remove rows), parser handles list
format.

### Mode 5: PRESCRIBE (Design/Optimization) — 🔲 Phase 3 (~2 weeks)
**Problem:** What would the ideal look like?
**Input:** User sets ideal weights/priorities. No alternatives needed.
**Logic:** Generate the optimal hypothetical profile (Keeney's value-focused
thinking — values first, alternatives second). Then score real alternatives
against this ideal using a similarity/distance metric.
**Output:** Radar showing the ideal profile + how close each alternative comes.
**New code:** Ideal-profile builder, similarity scoring, comparison view.

### Mode 6: PROJECT (Dynamic/Longitudinal) — 🔲 Phase 4 (~1 month)
**Problem:** Will this still be good in 3 years?
**Input:** Same as CHOOSE or DIAGNOSE, plus a time horizon.
**Logic:** Each criterion gets a trend slider (-10 to +10 per year). Score is
computed at multiple time points. The ranking shows how it shifts over time.
**Output:** Animated radar chart at T₀, T₁, T₂ + trajectory lines.
**New code:** Time-horizon input, trend computation, animated chart render.

### Mode 7: ALLOCATE (Portfolio) — 🔲 Phase 5 (~2 months)
**Problem:** How should I distribute a limited resource?
**Input:** Alternatives + scores + resource budget (money, time, effort).
**Logic:** Knapsack optimization — find the optimal combination of alternatives
that maximizes total weighted score within budget.
**Output:** Recommended portfolio + trade-off analysis.
**New code:** Budget input, optimization solver, portfolio result view.

---

## Architecture principles

```
┌─────────────────────────────────────────────────┐
│                  Question Input                  │
│  (free text / structured / sliders / uploads)    │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│              Intent Classifier                   │
│  Maps input → one of 7 modes based on pattern   │
│  "X or Y" → CHOOSE | "Rate X" → DIAGNOSE | etc  │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│                Parser Layer                      │
│  Extracts: alternatives, criteria, thresholds,   │
│  constraints, time horizon, budget              │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│          ★ Core MCDA Engine ★                   │
│  ┌────────────┐  ┌──────────┐  ┌────────────┐  │
│  │  6 Dims    │  │ Weighted │  │ Statistical│  │
│  │ + 12 Mets  │  │  Sum     │  │ Tests      │  │
│  └────────────┘  └──────────┘  └────────────┘  │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│           Result Presentation Layer              │
│  Ranking / Diagnosis / Screen / Prescribe / etc  │
│  Radar chart + scores + narrative + t-test      │
└─────────────────────────────────────────────────┘
```

### What stays constant across all modes

- The 6 MCDA dimensions and 12 metrics (in `services/ontology.py`)
- The weighted-sum scoring algorithm (in `services/scoring.py`)
- The database models (`Decision`, `Activity`, `ActivityWeight`, `AlternativeScore`)
- The metric manager CRUD (`routers/metrics.py`)
- The t-test significance computation
- The radar chart (Chart.js)
- Alpine.js reactive UI (no npm)
- Per-(alternative, criterion) sliders at 0–100

### What changes per mode

| Layer | What differs |
|-------|-------------|
| **Parser** | How alternatives are extracted (from "or", from list, from single target, etc.) |
| **Input UI** | Additional fields per mode: thresholds, time horizon, budget, ideal profile |
| **Score computation** | Mode-specific logic: filtering, ideal-distance, time-trend, portfolio optimization |
| **Result template** | Each mode gets its own result view |
| **Router** | Each mode adds a router under `routers/` |

---

## Technology constants

| Layer | Choice |
|-------|--------|
| Backend | Python FastAPI |
| Database | SQLAlchemy + SQLite (dev) → PostgreSQL (prod) |
| Frontend | Jinja2 + Alpine.js + Chart.js (CDN, zero npm) |
| Testing | pytest + httpx |
| Scoring | Weighted sum (MCDA standard) + paired t-test |
| Significance | Student's t-distribution (hand-rolled CDF) |

---

## Roadmap

```
Phase 0 (done)      CHOOSE              Single pairwise comparison
Phase 1 (2 days)    DIAGNOSE            Single-option evaluation
Phase 2 (1 week)    SCREEN + RANK       Thresholds + multi-option ranking
Phase 3 (2 weeks)   PRESCRIBE           Ideal profile + gap analysis
Phase 4 (1 month)   PROJECT             Time-weighted projections
Phase 5 (2 months)  ALLOCATE            Portfolio / resource optimization
```

Each phase is additive. Modes never need to be rewritten — the core engine
evolves forward.

---

## Boundaries (what we do not do)

| Not in scope | Reason |
|-------------|--------|
| Domain-specific deep expertise | Our criteria are universal by design. Domain depth requires expert systems, not MCDA. |
| Probabilistic uncertainty | Decision trees, Bayesian nets, and Monte Carlo are adjacent fields — we do the scoring, not the probability modeling. |
| Group decision consensus | No voting/negotiation logic. Each decision is one person's perspective. |
| Real-time data feeds | No live API integrations for prices, ratings, etc. User provides their own scores. |
| Full text LLM reasoning | We parse structure, we do not generate free-text advice. The framework is the advice. |
