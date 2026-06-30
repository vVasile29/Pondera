import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { DecisionDetail } from "@/types";

export function useEvaluate(id: string | undefined) {
  const [data, setData] = useState<DecisionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const numId = parseInt(id);
      const result = await api.getEvaluate(numId);
      setData(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { data, loading, error, refetch: fetch };
}
