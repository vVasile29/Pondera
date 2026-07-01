import type { FitResult, ScoreRow, Activity, Metric, FilterResult } from "@/types";

export function pythonRound(value: number, digits = 0): number {
  const factor = 10 ** digits;
  const scaled = value * factor;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;
  const epsilon = Number.EPSILON * Math.max(1, Math.abs(scaled)) * 4;

  if (diff > 0.5 + epsilon) return (floor + 1) / factor;
  if (diff < 0.5 - epsilon) return floor / factor;

  return (floor % 2 === 0 ? floor : floor + 1) / factor;
}

export function filterResultsToSurvivors(
  results: FitResult[],
  filterResult?: FilterResult | null,
): FitResult[] {
  if (!filterResult) return results;
  const survivorIds = new Set(
    filterResult.survivor_results.map((r) => r.activity_id),
  );
  return results.filter((r) => survivorIds.has(r.activity_id));
}

/**
 * Recompute fit scores client-side given adjusted weights.
 * Used for sensitivity analysis in Results.
 * Pass `metrics` to map metric names to proper metric_ids/directions when rows
 * come from older API responses.
 */
export function recomputeFitScores(
  activities: Activity[],
  rows: ScoreRow[],
  metricWeightOverrides: Record<string, number>,
  metrics?: Metric[],
): FitResult[] {
  const metricByName: Record<string, Metric> = {};
  if (metrics) {
    for (const m of metrics) {
      metricByName[m.name] = m;
    }
  }

  const results: FitResult[] = activities.map((act) => {
    let numerator = 0;
    let denominator = 0;
    const weightedScores: {
      metric_id: number;
      score: number;
      weight: number;
    }[] = [];
    for (const row of rows) {
      const metric = metricByName[row.metric_name];
      const metricId = row.metric_id ?? metric?.id ?? 0;
      const higherIsBetter = row.higher_is_better ?? metric?.higher_is_better ?? true;
      const baseWeight = row.weight;
      if (baseWeight === undefined) continue;
      const weight = metricWeightOverrides[row.metric_name] ?? baseWeight;
      const score = row.scores[act.id] ?? 0;
      const effectiveScore = higherIsBetter ? score : 100 - score;
      numerator += effectiveScore * weight;
      denominator += weight;
      weightedScores.push({ metric_id: metricId, score, weight });
    }
    const fit = denominator > 0 ? numerator / denominator / 100 : 0;
    return {
      activity_id: act.id,
      activity_name: act.name,
      fit_score: pythonRound(fit, 4),
      fit_pct: pythonRound(fit * 100, 1),
      weighted_scores: weightedScores as any,
    };
  });
  results.sort((a, b) => b.fit_score - a.fit_score);
  return results;
}
