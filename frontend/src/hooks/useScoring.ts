import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import { ScoreResponse } from "@/types";

export function useScoring(decisionId: number) {
  const [scores, setScores] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const [results, setResults] = useState<ScoreResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const updateScore = useCallback(
    (activityId: number, metricId: number, value: number) => {
      setScores((prev) => ({
        ...prev,
        [`${activityId}_${metricId}`]: value,
      }));
    },
    [],
  );

  const submit = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    try {
      const payload = Object.entries(scores).map(([key, value]) => {
        const [activityId, metricId] = key.split("_").map(Number);
        return { activity_id: activityId, metric_id: metricId, score: value };
      });
      const result = await api.submitScores(decisionId, payload);
      setResults(result);
      return result;
    } catch (e: any) {
      setError(e.message);
      return null;
    } finally {
      setSubmitting(false);
    }
  }, [decisionId, scores]);

  return { scores, updateScore, submit, submitting, results, error };
}
