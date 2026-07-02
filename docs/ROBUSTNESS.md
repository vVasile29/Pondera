# Decision Robustness

Optium uses Monte Carlo sensitivity analysis on a weighted additive value model
(WAVM) to assess ranking stability. This is **not hypothesis testing** — it is a
deterministic perturbation analysis that measures how often a winner would change
if weights and scores varied within a plausible range.

## Algorithm

Each simulation iteration:

1. **Perturb the shared decision-level weight vector** — each weight is
   multiplied by a uniform random factor in [0.9, 1.1] (independent per metric).
2. **Clip weights** to [0, 100].
3. **Renormalize** sampled weights back to the decision's base total weight
   (capped per-metric at 100).
4. **Perturb scores** — each score is shifted by a uniform random delta in
   [-5, +5] points (independent per score).
5. **Clip scores** to [0, 100].
6. **Recompute fit scores and rankings** using the standard fit-score
   MCDA formula (higher score is always better; no score inversion).
7. **Track**:
   - How often the base-case winner remains first (`winner_retained_count`).
   - How often the winner changes (`winner_changed_count`).
   - First-rank frequency across all alternatives (`rank_acceptability`).

## Report Format

| Field | Description |
|---|---|
| `simulations` | Number of Monte Carlo iterations (default 1000, range 100–5000) |
| `winner_robustness_percent` | Percentage of simulations where the base winner stayed first |
| `robustness_label` | `Very High` (≥95%), `High` (≥85%), `Moderate` (≥70%), or `Low` |
| `rank_acceptability` | Per-alternative percentage of first-rank finishes |
| `top_two.mean_difference_percentage_points` | Mean weighted-score gap between winner and runner-up |
| `top_two.interval_95_percentage_points` | 95% empirical percentile interval of the winner-runner-up gap |

## Scope

- Weight perturbation: `relative_uniform`, factor range [0.9, 1.1].
- Score perturbation: `absolute_uniform`, delta range [-5, +5], clipped to
  [0, 100].
- Renormalization scope: `"decision"` — the perturbed weight vector is scaled
  to match the base decision's total weight, so relative importance is preserved.
- Renormalization only applies when both base and sampled totals are positive.
- If base or sampled total is zero, the sampled weights are used as-is.
