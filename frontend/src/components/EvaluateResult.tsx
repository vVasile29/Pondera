import { useState, useMemo, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useEvaluate } from "@/hooks/useEvaluate";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Loader2,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import RadarChart from "@/components/RadarChart";
import ExportButton from "@/components/ExportButton";
import type { DimensionScore, GapAnalysis } from "@/types";

interface DimensionBreakdownItem extends DimensionScore {
  gap: number;
  overall_avg: number;
}

/** Map score to a color class for the progress bar. */
function scoreBarColor(score: number): string {
  if (score >= 75) return "bg-green-500";
  if (score >= 50) return "bg-amber-500";
  return "bg-red-500";
}

export default function EvaluateResult() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data, loading, error, refetch } = useEvaluate(id);

  const decisionId = id ? parseInt(id) : 0;

  // Inline scoring state (used when no scores exist yet)
  const [inlineScores, setInlineScores] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Detailed scores table expand
  const [tableOpen, setTableOpen] = useState(false);

  // Check whether actual scores have been submitted
  const hasScores = useMemo(() => {
    if (!data?.rows) return false;
    return data.rows.some((row) => Object.values(row.scores).length > 0);
  }, [data]);

  // Merge dimension scores with gap info
  const dimensionBreakdown = useMemo<DimensionBreakdownItem[]>(() => {
    if (!data?.dimension_scores || !data?.gap_analysis) return [];
    const { strengths, weaknesses, overall_avg } = data.gap_analysis;
    return data.dimension_scores.map((ds) => {
      const gapInfo =
        strengths.find((s) => s.dimension === ds.dimension) ??
        weaknesses.find((w) => w.dimension === ds.dimension);
      return {
        ...ds,
        gap: gapInfo?.gap ?? 0,
        overall_avg,
      };
    });
  }, [data]);

  const gapAnalysis: GapAnalysis | null = data?.gap_analysis ?? null;

  // Overall result (first and only result in diagnose mode)
  const overallResult = data?.results?.[0] ?? null;

  // ── Inline scoring handlers ──
  const actId = data?.activities?.[0]?.id ?? 0;

  const handleScoreChange = useCallback(
    (metricId: number, value: number[]) => {
      setInlineScores((prev) => ({
        ...prev,
        [`${actId}_${metricId}`]: value[0],
      }));
    },
    [actId],
  );

  const handleSubmitScores = async () => {
    if (!decisionId || !data) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const scoresPayload = data.metrics.map((m) => ({
        activity_id: actId,
        metric_id: m.id,
        score: inlineScores[`${actId}_${m.id}`] ?? 0,
      }));
      await api.submitScores(decisionId, scoresPayload);
      await refetch();
    } catch (e: any) {
      setSubmitError(e.message || "Failed to submit scores.");
    } finally {
      setSubmitting(false);
    }
  };

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

  // ── No scores yet — show inline scoring ──
  if (!hasScores && data.metrics.length > 0 && actId) {
    return (
      <div className="container mx-auto py-8 px-4 max-w-4xl space-y-8">
        <div>
          <h1 className="text-3xl font-bold">Evaluation Result</h1>
          <p className="text-muted-foreground mt-1">{data.decision.query}</p>
        </div>

        {submitError && (
          <Alert variant="destructive">
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-xl">
              Score: {data.activities[0]?.name ?? "Subject"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            {data.metrics.map((metric) => {
              const val = inlineScores[`${actId}_${metric.id}`] ?? 0;
              return (
                <div key={metric.id} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1 min-w-0">
                      <span className="text-sm font-medium truncate">
                        {metric.name}
                      </span>
                      {metric.higher_is_better ? (
                        <ArrowUp className="h-3 w-3 shrink-0 text-muted-foreground" />
                      ) : (
                        <ArrowDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                      )}
                    </div>
                    <span className="text-sm font-mono tabular-nums ml-2">
                      {val}
                    </span>
                  </div>
                  <Slider
                    value={[val]}
                    onValueChange={(v) => handleScoreChange(metric.id, v)}
                    min={0}
                    max={100}
                    step={1}
                  />
                  <div className="flex justify-between text-[10px] text-muted-foreground">
                    {metric.higher_is_better ? (
                      <>
                        <span>Poor</span>
                        <span>Below Avg</span>
                        <span>Average</span>
                        <span>Good</span>
                        <span>Excellent</span>
                      </>
                    ) : (
                      <>
                        <span>Excellent</span>
                        <span>Good</span>
                        <span>Average</span>
                        <span>Below Avg</span>
                        <span>Poor</span>
                      </>
                    )}
                  </div>
                </div>
              );
            })}

            <div className="flex justify-end pt-4">
              <Button
                onClick={handleSubmitScores}
                disabled={submitting}
                size="lg"
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Submitting...
                  </>
                ) : (
                  <>
                    Submit Scores
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── No results available (fallback) ──
  if (!overallResult) {
    return (
      <div className="container mx-auto py-8 px-4 max-w-4xl space-y-8">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">Evaluation Result</h1>
            <p className="text-muted-foreground mt-1">{data.decision.query}</p>
          </div>
          <ExportButton decisionId={decisionId} />
        </div>
        <Card>
          <CardContent className="py-12 text-center space-y-4">
            <p className="text-muted-foreground text-lg">No results yet.</p>
            <p className="text-sm text-muted-foreground">
              Score the subject to see evaluation results.
            </p>
            <Button onClick={() => navigate(`/evaluate/${decisionId}/result`)}>
              <ArrowRight className="mr-2 h-4 w-4" />
              Score Now
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ── Results available ──
  return (
    <div className="container mx-auto py-8 px-4 max-w-5xl space-y-8">
      {/* ── Page Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Evaluation Result</h1>
          <p className="text-muted-foreground mt-1">{data.decision.query}</p>
        </div>
        <ExportButton decisionId={decisionId} />
      </div>

      {/* ── Overall Score ── */}
      <Card>
        <CardContent className="py-8 text-center">
          <div className="text-6xl font-extrabold text-primary">
            {overallResult.fit_pct}%
          </div>
          <p className="text-lg text-muted-foreground mt-2">
            {overallResult.activity_name} scores {overallResult.fit_pct}%
            overall
          </p>
          <div className="max-w-md mx-auto mt-4">
            <div className="h-4 w-full bg-muted rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all duration-500"
                style={{ width: `${overallResult.fit_pct}%` }}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Dimension Breakdown ── */}
      {dimensionBreakdown.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Dimension Breakdown</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {dimensionBreakdown.map((d) => (
              <div
                key={d.dimension}
                className="flex items-center gap-4 flex-wrap"
              >
                <span className="font-medium w-28 shrink-0">{d.dimension}</span>
                <div className="flex-1 min-w-[120px]">
                  <div className="h-3 w-full bg-muted rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${scoreBarColor(d.score)}`}
                      style={{ width: `${d.score}%` }}
                    />
                  </div>
                </div>
                <span className="font-mono text-sm tabular-nums w-12 text-right">
                  {d.score}%
                </span>
                <span
                  className={`text-sm w-24 text-right ${
                    d.gap > 0
                      ? "text-green-600 dark:text-green-400"
                      : d.gap < 0
                        ? "text-red-600 dark:text-red-400"
                        : "text-muted-foreground"
                  }`}
                >
                  {d.gap > 0 ? (
                    <>▲ +{d.gap}</>
                  ) : d.gap < 0 ? (
                    <>▼ {d.gap}</>
                  ) : (
                    <>— 0</>
                  )}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* ── Gap Analysis ── */}
      {gapAnalysis && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Gap Analysis</CardTitle>
          </CardHeader>
          <CardContent>
            {gapAnalysis.balanced ? (
              <div className="p-4 rounded-lg border bg-muted/30 text-sm">
                All dimensions are evenly balanced (within 5 points of the{" "}
                {gapAnalysis.overall_avg}% average).
              </div>
            ) : (
              <div className="space-y-3 text-sm">
                <div className="p-3 rounded-lg border border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/30">
                  <span className="font-medium text-green-700 dark:text-green-400">
                    Strengths:
                  </span>{" "}
                  {gapAnalysis.strengths.length > 0 ? (
                    <span className="text-green-600 dark:text-green-300">
                      {gapAnalysis.strengths
                        .map(
                          (s) =>
                            `${s.dimension} (${s.score}% vs avg ${gapAnalysis.overall_avg}%)`,
                        )
                        .join("; ")}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">(none)</span>
                  )}
                </div>
                <div className="p-3 rounded-lg border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30">
                  <span className="font-medium text-red-700 dark:text-red-400">
                    Weaknesses:
                  </span>{" "}
                  {gapAnalysis.weaknesses.length > 0 ? (
                    <span className="text-red-600 dark:text-red-300">
                      {gapAnalysis.weaknesses
                        .map(
                          (w) =>
                            `${w.dimension} (${w.score}% vs avg ${gapAnalysis.overall_avg}%)`,
                        )
                        .join("; ")}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">(none)</span>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

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
            {/* Desktop table */}
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

            {/* Mobile stacked cards */}
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
