/** Mirrors the backend data models and API response shapes. */

// ── Core Domain Models ──

export interface Decision {
  id: number;
  query: string;
  mode: string;
  category: string | null;
  created_at: string | null;
}

export interface Activity {
  id: number;
  name: string;
}

export interface Metric {
  id: number;
  name: string;
  category: string;
  description: string;
  higher_is_better: boolean;
}

// ── Scoring ──

export interface WeightedScore {
  metric_id: number;
  score: number;
  weight: number;
}

export interface FitResult {
  activity_id: number;
  activity_name: string;
  fit_score: number;
  fit_pct: number;
  weighted_scores: WeightedScore[];
}

export interface SeriesData {
  name: string;
  scores: number[];
}

export interface ScoreRow {
  metric_id?: number;
  metric_name: string;
  metric_desc: string;
  higher_is_better?: boolean;
  weight: number;
  scores: Record<number, number>;
}

export interface RobustnessData {
  method: "weighted_additive_monte_carlo";
  method_description: string;
  simulations: number;
  seed: number | null;
  weight_perturbation: {
    type: "relative_uniform";
    min_factor: number;
    max_factor: number;
  };
  score_perturbation: {
    type: "absolute_uniform";
    min_delta: number;
    max_delta: number;
    clipped_to: [number, number];
  };
  weight_renormalization: {
    applied: boolean;
    scope: string;
    target: string;
    when: string;
    zero_total_behavior: string;
  };
  winner_id: number;
  winner_name: string;
  winner_retained_count: number;
  winner_retained_total: number;
  winner_robustness_percent: number;
  winner_changed_percent: number;
  robustness_label: string;
  rank_acceptability: Array<{
    activity_id: number;
    activity_name: string;
    first_rank_count: number;
    first_rank_percent: number;
  }>;
  top_two: {
    winner_id: number;
    runner_up_id: number;
    mean_difference: number;
    mean_difference_percentage_points: number;
    interval_95: {
      lower: number;
      upper: number;
      method: "empirical_percentile";
    };
    interval_95_percentage_points: {
      lower: number;
      upper: number;
      method: "empirical_percentile";
    };
  } | null;
}

// ── Thresholds ──

export interface ThresholdEntry {
  metric_id: number;
  operator: string;
  value: number;
}

export interface ThresholdCriterion {
  id: number;
  name: string;
  operator: string;
  value: number | string;
}

export interface FilterPassedEntry {
  activity_id: number;
  activity_name: string;
}

export interface FilterFailedEntry {
  activity_id: number;
  activity_name: string;
  reasons: string[];
}

export interface FilterResult {
  passed: FilterPassedEntry[];
  failed: FilterFailedEntry[];
  all_passed: boolean;
  survivor_results: FitResult[];
}

// ── Dimensions & Gap Analysis (diagnose mode) ──

export interface DimensionMetricScore {
  metric_id: number;
  score: number;
  weight: number;
}

export interface DimensionScore {
  dimension: string;
  score: number;
  metrics: DimensionMetricScore[];
  metric_count: number;
}

export interface GapEntry {
  dimension: string;
  score: number;
  gap: number;
}

export interface GapAnalysis {
  strengths: GapEntry[];
  weaknesses: GapEntry[];
  overall_avg: number;
  balanced: boolean;
}

// ── Composite Decision Detail (full response from GET /api/decisions/{id}) ──

export interface DecisionDetail {
  decision: Decision;
  activities: Activity[];
  metrics: Metric[];
  results: FitResult[];
  series: SeriesData[];
  metric_names: string[];
  rows: ScoreRow[];
  robustness: RobustnessData | null;
  significance: null;
  dimension_scores: DimensionScore[] | null;
  gap_analysis: GapAnalysis | null;
  filter_result: FilterResult | null;
  threshold_criteria: ThresholdCriterion[];
  thresholds: ThresholdEntry[];
}

// ── Metrics endpoint ──

export interface GroupedMetric {
  id: number;
  name: string;
  category: string;
  description: string;
  higher_is_better: boolean;
}

export interface MetricsResponse {
  grouped_metrics: Record<string, GroupedMetric[]>;
}

// ── API request payload types ──

export interface DecideResponse {
  decision_id: number;
  mode: string;
  next: string;
}

export interface RefinePayload {
  alternatives: string[];
  metrics: Array<{
    metric_id: number;
    weight?: number;
  }>;
}

export interface RefineResponse {
  activities: Activity[];
  criteria: Array<{
    id: number;
    name: string;
    weight: number;
    higher_is_better: boolean;
  }>;
}

export interface ScorePayload {
  scores: Array<{
    activity_id: number;
    metric_id: number;
    score: number;
  }>;
}

export interface ScoreResponse {
  results: FitResult[];
  series: SeriesData[];
  metric_names: string[];
  robustness: RobustnessData | null;
  significance: null;
}

export interface ThresholdsPayload {
  thresholds: ThresholdEntry[];
}

export interface ThresholdsResponse {
  filter_result: FilterResult | null;
  threshold_criteria: ThresholdCriterion[];
}

export interface ClearThresholdsResponse {
  status: string;
}

export interface DeleteResponse {
  status: string;
}

export interface DecisionListResponse {
  decisions: Decision[];
}
