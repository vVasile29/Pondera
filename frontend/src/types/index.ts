/** Mirrors the backend data models and API response shapes. */

// ── Core Domain Models ──

export interface Decision {
  id: number;
  query: string;
  mode: string;
  category: string | null;
  created_at: string | null;
  /** Only present in list endpoint */
  result_url?: string;
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

export interface ActivityWeight {
  id: number;
  activity_id: number;
  metric_id: number;
  weight: number;
}

export interface AlternativeScore {
  id: number;
  activity_id: number;
  metric_id: number;
  score: number;
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
  metric_name: string;
  metric_desc: string;
  weight: number;
  scores: Record<number, number>;
}

export interface SignificanceData {
  t_statistic: number;
  df: number;
  p_value: number;
  label: string;
  winner_avg: number;
  runner_avg: number;
  winner_name: string;
  runner_name: string;
  mean_diff: number;
  std_diff: number;
  num_criteria: number;
  significant: boolean;
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
  significance: SignificanceData | null;
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
  unit: string;
  higher_is_better: boolean;
  children?: GroupedMetric[];
}

export interface MetricsResponse {
  grouped_metrics: Record<string, GroupedMetric[]>;
}

// ── Metric CRUD payloads ──

export interface MetricCreatePayload {
  name: string;
  category: string;
  description?: string;
  unit?: string;
  higher_is_better: boolean;
}

export interface MetricUpdatePayload {
  name?: string;
  category?: string;
  description?: string;
  unit?: string;
  higher_is_better?: boolean;
}

export interface MetricCRUDResponse {
  id: number;
  name: string;
  category?: string;
}

// ── API request payload types ──

export interface DecideResponse {
  decision_id: number;
  mode: string;
  redirect_url: string;
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
  significance: SignificanceData | null;
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
