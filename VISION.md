# Optium - Product Vision

## What We Are Building

Optium is a universal multi-criteria decision analysis (MCDA) engine with one
simple entry point: type a decision question, review the parsed structure, score
the options, and inspect the result.

The product is not an expert system and does not claim domain facts. It gives
people a transparent framework for thinking through decisions using explicit
criteria, weights, scores, and tradeoffs.

The current product direction is **one unified prompt entry**, not a public set
of modes. Internally, Optium infers the decision shape from the prompt:

| Prompt shape | Internal flow | Example |
|--------------|---------------|---------|
| One option or subject | Diagnosis | "How good is a Tesla for commuting?" |
| Two options | Comparison | "House or apartment?" |
| Three or more options | Ranking | "Rank Python, Java, Go" |

Thresholds are not a separate public mode anymore. They are a post-hoc filter on
result pages: score first, then apply must-have cutoffs to see PASS/FAIL options
and ranked survivors.

---

## Academic Foundation

| Source | What we use |
|--------|-------------|
| Keeney's Value-Focused Thinking | Values-first framing: make what matters explicit before evaluating alternatives |
| MCDA weighted-sum models | Weighted scoring across multiple criteria |
| Roy's decision problem typology | Internal interpretation of choice, ranking, and description/diagnosis shapes |
| Elimination by Aspects | Threshold-style filtering after scores exist |

These sources guide the product, but Optium should be described as grounded in
or inspired by MCDA principles, not as academically certified advice.

### The Universal Criteria Framework

The criteria set is intentionally small and reusable. Metrics are global and
pre-seeded, not created separately for each decision.

| Dimension | Metrics | Direction |
|-----------|---------|-----------|
| Financial | Cost, Value | Lower Cost, higher Value |
| Quality | Quality, Performance | Higher is better |
| Time | Time Required, Efficiency | Lower Time Required, higher Efficiency |
| Risk | Risk, Safety | Lower Risk, higher Safety |
| Experience | Enjoyment, Satisfaction | Higher is better |
| Convenience | Convenience, Accessibility | Higher is better |

---

## Current Product Model

### Unified Entry

The landing page asks one question: "What's your decision today?" There is no
mode picker. The parser extracts alternatives or a single subject, then routes to
the appropriate internal flow.

### Review Before Scoring

The user sees what the system parsed before scoring. They can edit alternatives,
select metrics, and adjust weights. This is where Optium stays transparent: the
model is inspectable before it produces an answer.

### Score on a 0-100 Scale

Alternatives are scored against selected metrics with sliders. Weights and scores
both use a 0-100 scale.

### Results and Threshold Filters

Results show weighted fit scores, radar charts, and detailed score tables. The
result page can also apply threshold filters, such as `Cost <= 60` or
`Safety >= 80`, to separate passing and failing alternatives. Threshold filters
operate on user-entered scores; they do not fetch external facts.

---

## Architecture Principles

```
Question Input
  -> Parser
     -> alternatives / single subject / list structure
  -> Internal Routing
     -> 1 option: diagnosis
     -> 2 options: comparison
     -> 3+ options: ranking
  -> Review
     -> alternatives, metrics, weights
  -> Score
     -> 0-100 criterion scores
  -> Results
     -> fit scores, radar chart, score table
     -> optional threshold filtering
```

### What Stays Constant

- 6 value dimensions and 12 global metrics
- Weighted-sum scoring
- `Decision`, `Activity`, `ActivityWeight`, and `AlternativeScore` models
- Metric manager CRUD
- Radar chart presentation
- Jinja2 + Alpine.js + Chart.js, with no npm build step
- User-controlled criteria, weights, and scores

### What Can Vary Internally

| Layer | Variation |
|-------|-----------|
| Parser | Extracts alternatives from `or`/`vs`, lists, or single-subject prompts |
| Review UI | Shows one, two, or many alternatives as needed |
| Result UI | Emphasizes diagnosis, comparison, or ranking depending on the decision shape |
| Filters | Optional thresholds can be applied after scoring |

---

## Roadmap

The roadmap should build on the unified entry model rather than adding more
public modes.

### Current

- Unified prompt entry
- Automatic diagnosis/comparison/ranking detection
- Universal MCDA metric framework
- Weighted scoring and radar chart results
- Saved decisions
- Post-hoc threshold filtering on result pages
- Legacy screen/rank/evaluate routes for compatibility

### Near Term

- Improve parser reliability for messy natural language and list formats
- Make threshold filters easier to understand and edit on result pages
- Reduce duplication between comparison, ranking, and diagnosis result handling
- Improve empty and ambiguous prompt guidance
- Clean up dead CSS and legacy mode language in UI internals

### Later Possibilities

- Ideal-profile comparison: define what "ideal" looks like and score options against it
- Time horizon analysis: let users explore how scores might change over time
- Portfolio/resource allocation: choose combinations under a budget or constraint
- Collaboration or export features for sharing decision rationale

These should be introduced as capabilities inside the unified flow where possible,
not as a growing set of public modes.

---

## Boundaries

| Not in scope | Reason |
|--------------|--------|
| Domain-specific factual advice | Optium structures judgment; it does not know live prices, reviews, or expert facts |
| Real-time data feeds | Users provide scores based on their own information |
| Black-box recommendations | The criteria, weights, and scores should remain visible and editable |
| Full LLM reasoning | The framework is the advice; the app parses structure rather than generating persuasive prose |
| Group consensus workflows | Current decisions represent one user's perspective |
