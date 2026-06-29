import { useState, useEffect, useMemo, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import {
  Loader2,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  Trophy,
  CheckCircle2,
  XCircle,
  Info,
} from "lucide-react";
import RadarChart from "@/components/RadarChart";
import SignificanceBadge from "@/components/SignificanceBadge";
import ExportButton from "@/components/ExportButton";
import type { DecisionDetail, FitResult } from "@/types";
import { recomputeFitScores } from "@/lib/scoring";

const RANK_META = [
  { bg: "bg-yellow-100 dark:bg-yellow-900/30", text: "text-yellow-700 dark:text-yellow-400", border: "border-yellow-400", ring: "ring-yellow-400", label: "1st" },
  { bg: "bg-gray-100 dark:bg-gray-800", text: "text-gray-500 dark:text-gray-400", border: "border-gray-400", ring: "ring-gray-400", label: "2nd" },
  { bg: "bg-amber-100 dark:bg-amber-900/30", text: "text-amber-700 dark:text-amber-400", border: "border-amber-700", ring: "ring-amber-700", label: "3rd" },
];

function rankMeta(index: number) {
  return RANK_META[index] ?? {
    bg: "bg-muted",
    text: "text-muted-foreground",
    border: "border-border",
    ring: "ring-border",
    label: `${index + 1}th`,
  };
}

export default function ScreenResult() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [data, setData] = useState<DecisionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [tableOpen, setTableOpen] = useState(false);
  const [sensitivityOpen, setSensitivityOpen] = useState(false);
  const [metricWeights, setMetricWeights] = useState<Record<string, number>>({});

  const decisionId = id ? parseInt(id) : 0;

  const fetchScreen = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const numId = parseInt(id);
      const result = await api.getScreen(numId);
      setData(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchScreen();
  }, [fetchScreen]);

  const mode = data?.decision?.mode ?? "screen";

  // Client-side recomputed results (for sensitivity analysis)
  const displayResults = useMemo<FitResult[]>(() => {
    if (!data?.results || data.results.length === 0) return [];
    if (!data.rows || Object.keys(metricWeights).length === 0) return data.results;
    return recomputeFitScores(data.activities, data.rows, metricWeights, data.metrics);
  }, [data, metricWeights]);

  // Whether actual scores have been submitted
  const hasScores = useMemo(() => {
    if (!data?.rows) return false;
    return data.rows.some(
      (row) => Object.values(row.scores).length > 0,
    );
  }, [data]);

  const filterResult = data?.filter_result;
  const survivors = filterResult?.survivor_results ?? [];
  const passed = filterResult?.passed ?? [];
  const failed = filterResult?.failed ?? [];

  const handleSensitivityChange = useCallback(
    (metricName: string, value: number[]) => {
      setMetricWeights((prev) => ({ ...prev, [metricName]: value[0] }));
    },
    [],
  );

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
            <h1 className="text-3xl font-bold">Screen Results</h1>
            <p className="text-muted-foreground mt-1">{data.decision.query}</p>
          </div>
          <ExportButton decisionId={decisionId} mode={mode} />
        </div>
        <Card>
          <CardContent className="py-12 text-center space-y-4">
            <Info className="h-12 w-12 mx-auto text-muted-foreground" />
            <p className="text-muted-foreground text-lg">
              No scores yet.
            </p>
            <p className="text-sm text-muted-foreground">
              Score your alternatives to see pass/fail results.
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
          <h1 className="text-3xl font-bold">Screen Results</h1>
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
          <ExportButton decisionId={decisionId} mode="screen" />
        </div>
      </div>

      {/* ── Thresholds Applied Banner ── */}
      {data.threshold_criteria.length > 0 && (
        <div className="flex items-start gap-3 p-4 rounded-lg border bg-muted/30 text-sm">
          <Info className="h-5 w-5 text-primary shrink-0 mt-0.5" />
          <div>
            <span className="font-medium">Thresholds applied: </span>
            <span className="text-muted-foreground">
              {data.threshold_criteria.map((tc) => (
                <span key={tc.id} className="mr-3">
                  {tc.name} {tc.operator} {tc.value}
                </span>
              ))}
            </span>
          </div>
        </div>
      )}

      {/* ── Pass / Fail Section ── */}
      {filterResult && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl flex items-center gap-2">
              Pass / Fail
              {filterResult.all_passed && passed.length > 0 && (
                <Badge variant="secondary" className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                  All Passed
                </Badge>
              )}
              {passed.length === 0 && failed.length > 0 && (
                <Badge variant="destructive">
                  All Failed
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* All passed message */}
            {filterResult.all_passed && passed.length > 0 && (
              <div className="flex items-start gap-3 p-3 rounded-lg border border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/30 text-sm">
                <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0 mt-0.5" />
                <span className="text-green-700 dark:text-green-400 font-medium">
                  All alternatives meet your thresholds.
                </span>
              </div>
            )}

            {/* All failed message */}
            {passed.length === 0 && failed.length > 0 && (
              <div className="flex items-start gap-3 p-3 rounded-lg border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30 text-sm">
                <XCircle className="h-5 w-5 text-red-600 shrink-0 mt-0.5" />
                <span className="text-red-700 dark:text-red-400 font-medium">
                  None of your alternatives meet all thresholds.
                </span>
              </div>
            )}

            {/* Passed items */}
            {passed.map((p) => (
              <div
                key={p.activity_id}
                className="flex items-center gap-3 p-3 rounded-lg border border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/30"
              >
                <Badge className="bg-green-600 hover:bg-green-700 shrink-0">
                  PASS
                </Badge>
                <span className="font-medium">{p.activity_name}</span>
              </div>
            ))}

            {/* Failed items with reasons */}
            {failed.map((f) => (
              <div
                key={f.activity_id}
                className="flex items-start gap-3 p-3 rounded-lg border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30"
              >
                <Badge variant="destructive" className="shrink-0">
                  FAIL
                </Badge>
                <div>
                  <span className="font-medium">{f.activity_name}</span>
                  {f.reasons.length > 0 && (
                    <div className="text-xs text-muted-foreground mt-1 space-y-0.5">
                      {f.reasons.map((reason, i) => (
                        <div key={i}>• {reason}</div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* ── Survivor Ranking ── */}
      {survivors.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-xl font-semibold">Survivor Ranking</h2>
          {survivors.map((r, idx) => {
            const meta = rankMeta(idx);
            const barWidth = maxFitPct > 0 ? (r.fit_pct / maxFitPct) * 100 : 0;
            return (
              <Card
                key={r.activity_id}
                className={`overflow-hidden ${meta.border} ${idx < 3 ? "border-l-4" : ""}`}
              >
                <CardContent className="p-4">
                  <div className="flex items-center gap-4">
                    <div
                      className={`flex items-center justify-center w-10 h-10 rounded-full shrink-0 ${meta.bg} ${meta.text} font-bold text-lg ring-2 ${meta.ring}`}
                    >
                      {idx < 3 ? (
                        <Trophy className="h-5 w-5" />
                      ) : (
                        <span>{idx + 1}</span>
                      )}
                    </div>
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
      )}

      {/* ── No Survivors message ── */}
      {filterResult && passed.length > 0 && survivors.length === 0 && (
        <Card>
          <CardContent className="py-6 text-center text-muted-foreground">
            <XCircle className="h-8 w-8 mx-auto mb-2" />
            <p>No alternatives passed all thresholds, so there are no survivors to rank.</p>
          </CardContent>
        </Card>
      )}

      {/* ── Statistical Significance (survivor rankings) ── */}
      {survivors.length >= 2 && (
        <SignificanceBadge significance={data.significance} />
      )}

      {/* ── Radar Chart (all alternatives) ── */}
      {data.metric_names.length > 0 && data.series.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Radar Chart</CardTitle>
            <p className="text-sm text-muted-foreground">
              All alternatives shown for comparison (including failed).
            </p>
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

      {/* ── Sensitivity Analysis ── */}
      {data.rows.length > 0 && (
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
                Adjust weights to see how survivor rankings change in real time.
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
                        <div
                          key={act.id}
                          className="flex items-center gap-2"
                        >
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
