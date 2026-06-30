import { useState, useMemo, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useDecision } from "@/hooks/useDecision";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import {
  Loader2,
  ChevronDown,
  ChevronUp,
  Trophy,
  ArrowRight,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import RadarChart from "@/components/RadarChart";
import SignificanceBadge from "@/components/SignificanceBadge";
import ThresholdPanel from "@/components/ThresholdPanel";
import ExportButton from "@/components/ExportButton";
import type { FitResult } from "@/types";
import { recomputeFitScores } from "@/lib/scoring";

const RANK_META = [
  {
    bg: "bg-yellow-100 dark:bg-yellow-900/30",
    text: "text-yellow-700 dark:text-yellow-400",
    border: "border-yellow-400",
    ring: "ring-yellow-400",
    label: "1st",
  },
  {
    bg: "bg-gray-100 dark:bg-gray-800",
    text: "text-gray-500 dark:text-gray-400",
    border: "border-gray-400",
    ring: "ring-gray-400",
    label: "2nd",
  },
  {
    bg: "bg-amber-100 dark:bg-amber-900/30",
    text: "text-amber-700 dark:text-amber-400",
    border: "border-amber-700",
    ring: "ring-amber-700",
    label: "3rd",
  },
];

function rankMeta(index: number) {
  return (
    RANK_META[index] ?? {
      bg: "bg-muted",
      text: "text-muted-foreground",
      border: "border-border",
      ring: "ring-border",
      label: `${index + 1}th`,
    }
  );
}

export default function Results() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useDecision(id);

  const [tableOpen, setTableOpen] = useState(false);
  const [sensitivityOpen, setSensitivityOpen] = useState(false);
  const [metricWeights, setMetricWeights] = useState<Record<string, number>>(
    {},
  );

  const decisionId = id ? parseInt(id) : 0;
  const mode = data?.decision?.mode ?? "choose";
  const isSingle = (data?.activities?.length ?? 0) <= 1;

  // Sensitivity weights
  const handleSensitivityChange = useCallback(
    (metricName: string, value: number[]) => {
      setMetricWeights((prev) => ({ ...prev, [metricName]: value[0] }));
    },
    [],
  );

  // Client-side recomputed results (for sensitivity analysis)
  const displayResults = useMemo<FitResult[]>(() => {
    if (!data?.results || data.results.length === 0) return [];
    if (!data.rows || Object.keys(metricWeights).length === 0)
      return data.results;
    return recomputeFitScores(
      data.activities,
      data.rows,
      metricWeights,
      data.metrics,
    );
  }, [data, metricWeights]);

  // Whether actual scores have been submitted (rows contain non-zero scores)
  const hasScores = useMemo(() => {
    if (!data?.rows) return false;
    return data.rows.some((row) => Object.values(row.scores).length > 0);
  }, [data]);

  const maxFitPct = useMemo(() => {
    if (displayResults.length === 0) return 100;
    return Math.max(...displayResults.map((r) => r.fit_pct), 1);
  }, [displayResults]);

  // ── Loading state ──
  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // ── Error state ──
  if (error) {
    return (
      <div className="container mx-auto py-8 px-4">
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!data) return null;

  // ── No results / not scored ──
  if (!hasScores) {
    return (
      <div className="container mx-auto py-8 px-4 max-w-4xl space-y-8">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">Results</h1>
            <p className="text-muted-foreground mt-1">{data.decision.query}</p>
          </div>
          <ExportButton decisionId={decisionId} mode={mode} />
        </div>
        <Card>
          <CardContent className="py-12 text-center space-y-4">
            <p className="text-muted-foreground text-lg">No scores yet.</p>
            <p className="text-sm text-muted-foreground">
              Score your alternatives to see the results.
            </p>
            <Button onClick={() => navigate(`/decisions/${decisionId}/score`)}>
              <ArrowRight className="mr-2 h-4 w-4" />
              Go to Scoring
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8 px-4 max-w-5xl space-y-8">
      {/* ── Page Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Results</h1>
          <p className="text-muted-foreground mt-1">{data.decision.query}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(`/decisions/${decisionId}/score`)}
          >
            Re-score
          </Button>
          <ExportButton decisionId={decisionId} mode={mode} />
        </div>
      </div>

      {/* ── Ranking Cards ── */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">
          {data.filter_result?.survivor_results
            ? "Survivor Ranking (filtered)"
            : "Ranking"}
        </h2>
        {displayResults.map((r, idx) => {
          const meta = rankMeta(idx);
          const barWidth = maxFitPct > 0 ? (r.fit_pct / maxFitPct) * 100 : 0;
          return (
            <Card
              key={r.activity_id}
              className={`overflow-hidden ${meta.border} ${idx < 3 ? "border-l-4" : ""}`}
              style={{ borderLeftColor: idx < 3 ? undefined : undefined }}
            >
              <CardContent className="p-4">
                <div className="flex items-center gap-4">
                  {/* Rank badge */}
                  <div
                    className={`flex items-center justify-center w-10 h-10 rounded-full shrink-0 ${meta.bg} ${meta.text} font-bold text-lg ring-2 ${meta.ring}`}
                  >
                    {idx < 3 ? (
                      <Trophy className="h-5 w-5" />
                    ) : (
                      <span>{idx + 1}</span>
                    )}
                  </div>

                  {/* Name + bar */}
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold truncate">
                        {r.activity_name}
                      </span>
                      <span className="font-mono font-bold text-xl tabular-nums ml-2">
                        {r.fit_pct}%
                      </span>
                    </div>
                    <div className="h-3 w-full bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${barWidth}%`,
                          backgroundColor:
                            idx === 0
                              ? "hsl(var(--primary))"
                              : "hsl(var(--muted-foreground))",
                        }}
                      />
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </section>

      {/* ── Threshold Panel (only for multi-alternative) ── */}
      {!isSingle && (
        <ThresholdPanel
          decisionId={decisionId}
          thresholdCriteria={data.threshold_criteria ?? []}
          filterResult={data.filter_result}
          onUpdate={refetch}
        />
      )}

      {/* ── Statistical Significance (only for multi-alternative) ── */}
      {!isSingle && <SignificanceBadge significance={data.significance} />}

      {/* ── Radar Chart ── */}
      {data.metric_names.length > 0 && data.series.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Radar Chart</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-w-lg mx-auto">
              <RadarChart
                labels={data.metric_names}
                datasets={data.series.map((s) => ({
                  label: s.name,
                  data: s.scores,
                }))}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Sensitivity Analysis (multi-alternative only, weights from rows) ── */}
      {!isSingle && data.rows.length > 0 && (
        <Card>
          <CardHeader
            className="cursor-pointer flex flex-row items-center justify-between"
            onClick={() => setSensitivityOpen(!sensitivityOpen)}
          >
            <CardTitle className="text-xl">Sensitivity Analysis</CardTitle>
            <Button variant="ghost" size="icon" aria-label="Toggle sensitivity">
              {sensitivityOpen ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </Button>
          </CardHeader>
          {sensitivityOpen && (
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Adjust weights to see how rankings change in real time.
              </p>
              {data.rows.map((row) => {
                const w = metricWeights[row.metric_name] ?? row.weight;
                return (
                  <div
                    key={row.metric_name}
                    className="flex items-center gap-3"
                  >
                    <span className="text-sm font-medium w-32 shrink-0 truncate">
                      {row.metric_name}
                    </span>
                    <Slider
                      value={[w]}
                      onValueChange={(v) =>
                        handleSensitivityChange(row.metric_name, v)
                      }
                      min={0}
                      max={100}
                      step={1}
                      className="flex-1"
                    />
                    <span className="text-sm font-mono w-10 text-right tabular-nums">
                      {w}
                    </span>
                  </div>
                );
              })}
            </CardContent>
          )}
        </Card>
      )}

      {/* ── Detailed Scores Table (collapsible) ── */}
      <Card>
        <CardHeader
          className="cursor-pointer flex flex-row items-center justify-between"
          onClick={() => setTableOpen(!tableOpen)}
        >
          <CardTitle className="text-xl">Detailed Scores</CardTitle>
          <Button variant="ghost" size="icon" aria-label="Toggle table">
            {tableOpen ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </Button>
        </CardHeader>
        {tableOpen && (
          <CardContent>
            {/* Desktop: scrollable table */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="text-left p-3 font-semibold text-muted-foreground">
                      Criterion
                    </th>
                    {data.activities.map((act) => (
                      <th
                        key={act.id}
                        className="text-center p-3 font-semibold"
                      >
                        {act.name}
                      </th>
                    ))}
                    <th className="text-center p-3 font-semibold text-muted-foreground">
                      Weight
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr
                      key={row.metric_name}
                      className="border-b last:border-b-0 hover:bg-muted/30 transition-colors"
                    >
                      <td className="p-3">
                        <div className="font-medium">{row.metric_name}</div>
                        {row.metric_desc && (
                          <div className="text-xs text-muted-foreground leading-tight mt-0.5">
                            {row.metric_desc}
                          </div>
                        )}
                      </td>
                      {data.activities.map((act) => {
                        const scoreVal = row.scores[act.id] ?? 0;
                        return (
                          <td key={act.id} className="p-3">
                            <div className="flex items-center gap-2">
                              <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden min-w-[40px]">
                                <div
                                  className="h-full rounded-full bg-primary"
                                  style={{ width: `${scoreVal}%` }}
                                />
                              </div>
                              <span className="text-xs font-mono tabular-nums w-8 text-right">
                                {scoreVal}
                              </span>
                            </div>
                          </td>
                        );
                      })}
                      <td className="p-3 text-center font-mono text-sm">
                        {row.weight}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile: stacked cards per metric */}
            <div className="md:hidden space-y-4">
              {data.rows.map((row) => (
                <Card key={row.metric_name}>
                  <CardContent className="p-3 space-y-2">
                    <div className="font-medium text-sm">{row.metric_name}</div>
                    {row.metric_desc && (
                      <div className="text-xs text-muted-foreground">
                        {row.metric_desc}
                      </div>
                    )}
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span>Weight: {row.weight}</span>
                    </div>
                    {data.activities.map((act) => {
                      const scoreVal = row.scores[act.id] ?? 0;
                      return (
                        <div key={act.id} className="flex items-center gap-2">
                          <span className="text-xs font-medium w-24 truncate shrink-0">
                            {act.name}
                          </span>
                          <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full bg-primary"
                              style={{ width: `${scoreVal}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono tabular-nums w-8 text-right">
                            {scoreVal}
                          </span>
                        </div>
                      );
                    })}
                  </CardContent>
                </Card>
              ))}
            </div>
          </CardContent>
        )}
      </Card>
    </div>
  );
}
