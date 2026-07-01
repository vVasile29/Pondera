import type {
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

  /** Delete a decision and all associated data. */
  deleteDecision(id: number): Promise<DeleteResponse> {
    return request(`/decisions/${id}/delete`, {
      method: "POST",
    });
  },
};
