import type { FitResult, ScoreRow, Activity, Metric } from "@/types";

/**
 * Recompute fit scores client-side given adjusted weights.
 * Used for sensitivity analysis in Results and ScreenResult.
 * Pass `metrics` to map metric names to proper metric_ids.
 */
export function recomputeFitScores(
  activities: Activity[],
  rows: ScoreRow[],
  metricWeightOverrides: Record<string, number>,
  metrics?: Metric[],
): FitResult[] {
  const nameToId: Record<string, number> = {};
  if (metrics) {
    for (const m of metrics) {
      nameToId[m.name] = m.id;
    }
  }

  const results: FitResult[] = activities.map((act) => {
    let numerator = 0;
    let denominator = 0;
    const weightedScores: { metric_id: number; score: number; weight: number }[] = [];
    for (const row of rows) {
      const weight = metricWeightOverrides[row.metric_name] ?? row.weight;
      const score = row.scores[act.id] ?? 0;
      numerator += score * weight;
      denominator += weight;
      const metricId = nameToId[row.metric_name] ?? 0;
      weightedScores.push({ metric_id: metricId, score, weight });
    }
    const fit = denominator > 0 ? numerator / denominator / 100 : 0;
    return {
      activity_id: act.id,
      activity_name: act.name,
      fit_score: Math.round(fit * 10000) / 10000,
      fit_pct: Math.round(fit * 100 * 10) / 10,
      weighted_scores: weightedScores as any,
    };
  });
  results.sort((a, b) => b.fit_score - a.fit_score);
  return results;
}
