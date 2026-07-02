import type {
  CreateCustomMetricPayload,
  CustomMetricResponse,
  DecideResponse,
  DecisionDetail,
  DecisionListResponse,
  DeleteResponse,
  MetricsResponse,
  RefinePayload,
  RefineResponse,
  ScorePayload,
  ScoreResponse,
  ThresholdsPayload,
  ThresholdsResponse,
  ClearThresholdsResponse,
  CreateMetricPayload,
  UpdateMetricPayload,
  MetricCRUDResponse,
  AIAvailability,
  EvidenceItem,
  ScoreDraft,
  AIMetricSuggestion,
  AIEvidenceResponse,
  AIScoreDraftResponse,
} from "@/types";

const API_BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  /** Parse a free-text question and create a decision. */
  decide(q: string): Promise<DecideResponse> {
    return request("/decide", {
      method: "POST",
      body: JSON.stringify({ q }),
    });
  },

  /** Get full decision detail including results, series, etc. */
  getDecision(id: number): Promise<DecisionDetail> {
    return request(`/decisions/${id}`);
  },

  /** List decisions with pagination. */
  getDecisions(limit = 20, offset = 0): Promise<DecisionListResponse> {
    return request(`/decisions?limit=${limit}&offset=${offset}`);
  },

  /** Update alternatives and metric weights for a decision. */
  refineDecision(id: number, data: RefinePayload): Promise<RefineResponse> {
    return request(`/decisions/${id}/refine`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  /** Submit scores and get computed results. */
  submitScores(
    id: number,
    scores: ScorePayload["scores"],
  ): Promise<ScoreResponse> {
    return request(`/decisions/${id}/score`, {
      method: "POST",
      body: JSON.stringify({ scores }),
    });
  },

  /** Apply threshold filters on a result page. */
  applyThresholds(
    id: number,
    thresholds: ThresholdsPayload["thresholds"],
  ): Promise<ThresholdsResponse> {
    return request(`/decisions/${id}/thresholds`, {
      method: "POST",
      body: JSON.stringify({ thresholds }),
    });
  },

  /** Clear all threshold filters. */
  clearThresholds(id: number): Promise<ClearThresholdsResponse> {
    return request(`/decisions/${id}/thresholds/clear`, {
      method: "POST",
    });
  },

  /** List all metrics grouped by dimension. */
  getMetrics(): Promise<MetricsResponse> {
    return request("/metrics");
  },

  createMetric(data: CreateMetricPayload): Promise<MetricCRUDResponse> {
    return request("/metrics", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  updateMetric(id: number, data: UpdateMetricPayload): Promise<MetricCRUDResponse> {
    return request(`/metrics/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  deleteMetric(id: number): Promise<{ status: string }> {
    return request(`/metrics/${id}`, {
      method: "DELETE",
    });
  },

  /** Delete a decision and all associated data. */
  deleteDecision(id: number): Promise<DeleteResponse> {
    return request(`/decisions/${id}/delete`, {
      method: "POST",
    });
  },

  /** Create a decision-scoped custom metric. */
  createCustomMetric(
    decisionId: number,
    data: CreateCustomMetricPayload,
  ): Promise<CustomMetricResponse> {
    return request(`/decisions/${decisionId}/custom-metrics`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  /** Update a decision-scoped custom metric. */
  updateCustomMetric(
    decisionId: number,
    metricId: number,
    data: Partial<CreateCustomMetricPayload>,
  ): Promise<CustomMetricResponse> {
    return request(`/decisions/${decisionId}/custom-metrics/${metricId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  /** Delete a decision-scoped custom metric. */
  deleteCustomMetric(
    decisionId: number,
    metricId: number,
  ): Promise<{ status: string }> {
    return request(`/decisions/${decisionId}/custom-metrics/${metricId}`, {
      method: "DELETE",
    });
  },

  getAIStatus(): Promise<AIAvailability> {
    return request("/ai/status");
  },

  suggestMetricsWithAI(decisionId: number, data: { user_context?: string; max_suggestions?: number }): Promise<{ metric_suggestions: AIMetricSuggestion[]; questions_for_user: string[] }> {
    return request(`/decisions/${decisionId}/ai/suggest-metrics`, { method: "POST", body: JSON.stringify(data) });
  },

  draftEvidenceWithAI(decisionId: number, data: { user_context?: string; activity_ids?: number[]; metric_ids?: number[]; include_general_evidence?: boolean; max_items?: number }): Promise<AIEvidenceResponse> {
    return request(`/decisions/${decisionId}/ai/draft-evidence`, { method: "POST", body: JSON.stringify(data) });
  },

  suggestScoresWithAI(decisionId: number, data: { user_context?: string; activity_ids?: number[]; metric_ids?: number[]; evidence_review_policy?: "approved_only" | "approved_and_pending"; max_drafts?: number }): Promise<AIScoreDraftResponse> {
    return request(`/decisions/${decisionId}/ai/suggest-scores`, { method: "POST", body: JSON.stringify(data) });
  },

  getEvidence(decisionId: number): Promise<{ evidence: EvidenceItem[] }> {
    return request(`/decisions/${decisionId}/evidence`);
  },

  createEvidence(decisionId: number, data: Partial<EvidenceItem> & { claim: string }): Promise<EvidenceItem> {
    return request(`/decisions/${decisionId}/evidence`, { method: "POST", body: JSON.stringify(data) });
  },

  approveEvidence(decisionId: number, evidenceId: number): Promise<EvidenceItem> {
    return request(`/decisions/${decisionId}/evidence/${evidenceId}/approve`, { method: "POST" });
  },

  rejectEvidence(decisionId: number, evidenceId: number): Promise<EvidenceItem> {
    return request(`/decisions/${decisionId}/evidence/${evidenceId}/reject`, { method: "POST" });
  },

  deleteEvidence(decisionId: number, evidenceId: number): Promise<{ status: string }> {
    return request(`/decisions/${decisionId}/evidence/${evidenceId}`, { method: "DELETE" });
  },

  getScoreDrafts(decisionId: number): Promise<{ drafts: ScoreDraft[] }> {
    return request(`/decisions/${decisionId}/score-drafts`);
  },

  updateScoreDraft(decisionId: number, draftId: number, data: Partial<ScoreDraft>): Promise<ScoreDraft> {
    return request(`/decisions/${decisionId}/score-drafts/${draftId}`, { method: "PATCH", body: JSON.stringify(data) });
  },

  approveScoreDraft(decisionId: number, draftId: number): Promise<ScoreDraft> {
    return request(`/decisions/${decisionId}/score-drafts/${draftId}/approve`, { method: "POST" });
  },

  rejectScoreDraft(decisionId: number, draftId: number): Promise<ScoreDraft> {
    return request(`/decisions/${decisionId}/score-drafts/${draftId}/reject`, { method: "POST" });
  },

  applyScoreDraft(decisionId: number, draftId: number): Promise<{ draft: ScoreDraft; score: { id: number; activity_id: number; metric_id: number; score: number } }> {
    return request(`/decisions/${decisionId}/score-drafts/${draftId}/apply`, { method: "POST" });
  },

  applyScoreDrafts(decisionId: number, draftIds: number[]): Promise<{ status: string; applied_draft_ids: number[]; scores: Array<{ id: number; activity_id: number; metric_id: number; score: number }> }> {
    return request(`/decisions/${decisionId}/score-drafts/apply`, { method: "POST", body: JSON.stringify({ draft_ids: draftIds }) });
  },
};
