import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { DecisionDetail } from "@/types";

export function useDecision(id: string | undefined) {
  const [data, setData] = useState<DecisionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!id) return;
      if (!options?.silent) setLoading(true);
      setError(null);
      try {
        const numId = parseInt(id);
        const result = await api.getDecision(numId);
        setData(result);
      } catch (e: any) {
        setError(e.message);
      } finally {
        if (!options?.silent) setLoading(false);
      }
    },
    [id],
  );

  const updateData = useCallback(
    (updater: (current: DecisionDetail) => DecisionDetail) => {
      setData((current) => (current ? updater(current) : current));
    },
    [],
  );

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { data, loading, error, refetch: fetch, updateData };
}
