import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useDecision } from "@/hooks/useDecision";
import { useScoring } from "@/hooks/useScoring";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Loader2, ArrowRight } from "lucide-react";

/** Map a fit score (0–100) to a Tailwind text color class. */
function scoreColor(value: number): string {
  const pct = value / 100;
  if (pct >= 0.7) return "text-green-600 dark:text-green-400";
  if (pct >= 0.4) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

/** Label tick for a given score value. */
function scoreLabel(value: number): string {
  if (value >= 95) return "Excellent";
  if (value >= 75) return "Good";
  if (value >= 50) return "Average";
  if (value >= 25) return "Below Avg";
  return "Poor";
}

export default function Scoring() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const decisionId = id ? parseInt(id) : 0;

  const { data, loading, error: fetchError } = useDecision(id);
  const {
    scores,
    updateScore,
    submit,
    submitting,
    error: submitError,
  } = useScoring(decisionId);

  const [prePopulated, setPrePopulated] = useState(false);
  const [navigating, setNavigating] = useState(false);

  // ── Pre-populate sliders from existing scores in data.rows ──
  useEffect(() => {
    if (!data || !data.rows || !data.metrics.length || prePopulated) return;

    const nameToId = new Map<string, number>(
      data.metrics.map((m) => [m.name, m.id]),
    );

    let found = false;
    data.rows.forEach((row) => {
      const metricId = nameToId.get(row.metric_name);
      if (!metricId) return;
      const entries = Object.entries(row.scores);
      if (entries.length === 0) return;
      found = true;
      entries.forEach(([actIdStr, score]) => {
        updateScore(Number(actIdStr), metricId, score);
      });
    });

    setPrePopulated(found);
  }, [data, prePopulated, updateScore]);

  // ── Handlers ──
  const handleScoreChange = (
    activityId: number,
    metricId: number,
    value: number[],
  ) => {
    updateScore(activityId, metricId, value[0]);
  };

  const handleSubmit = async () => {
    const result = await submit();
    if (result && decisionId) {
      setNavigating(true);
      navigate(`/decisions/${decisionId}/result`);
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
  if (fetchError) {
    return (
      <div className="container mx-auto py-8 px-4">
        <Alert variant="destructive">
          <AlertDescription>{fetchError}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!data) return null;

  const { activities, metrics } = data;

  return (
    <div className="container mx-auto py-8 px-4 max-w-6xl space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Score Your Alternatives</h1>
        <p className="text-muted-foreground mt-1">{data.decision.query}</p>
        <p className="text-sm text-muted-foreground mt-2">
          Every slider is a 0–100 fit score. Higher always means better fit.
        </p>
      </div>

      {/* Submit Error */}
      {submitError && (
        <Alert variant="destructive">
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      )}

      {/* ── Desktop: grid / table layout ── */}
      <div className="hidden md:block">
        <div className="rounded-lg border">
          {/* Header row */}
          <div className="grid grid-cols-[200px_repeat(auto-fit,minmax(180px,1fr))] border-b bg-muted/50">
            <div className="p-3 text-sm font-semibold text-muted-foreground">
              Criterion
            </div>
            {activities.map((act) => (
              <div
                key={act.id}
                className="p-3 text-sm font-semibold text-center"
              >
                {act.name}
              </div>
            ))}
          </div>

          {/* Data rows */}
          {metrics.map((metric) => (
            <div
              key={metric.id}
              className="grid grid-cols-[200px_repeat(auto-fit,minmax(180px,1fr))] border-b last:border-b-0 hover:bg-muted/30 transition-colors"
            >
              {/* Row header — metric info */}
              <div className="p-3 flex flex-col justify-center min-w-0">
                <span className="text-sm font-medium truncate">{metric.name}</span>
                <span className="text-xs text-muted-foreground truncate">
                  {metric.description}
                </span>
                {metric.anchors ? (
                  <span className="text-xs text-muted-foreground">
                    0: {metric.anchors.low} · 50: {metric.anchors.mid} · 100: {metric.anchors.high}
                  </span>
                ) : null}
              </div>

              {/* Per-alternative slider cells */}
              {activities.map((act) => {
                const val = scores[`${act.id}_${metric.id}`] ?? 0;
                return (
                  <div key={`${act.id}_${metric.id}`} className="p-3">
                    <div className="flex items-center gap-3">
                      <Slider
                        value={[val]}
                        onValueChange={(v) =>
                          handleScoreChange(act.id, metric.id, v)
                        }
                        min={0}
                        max={100}
                        step={1}
                        className="flex-1"
                      />
                      <div className="flex flex-col items-center shrink-0 w-14">
                        <span
                          className={`text-sm font-mono tabular-nums ${scoreColor(val)}`}
                        >
                          {val}
                        </span>
                        <span className="text-[10px] text-muted-foreground leading-tight">
                          {scoreLabel(val)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* ── Mobile: stacked by alternative ── */}
      <div className="md:hidden space-y-6">
        {activities.map((act) => (
          <Card key={act.id}>
            <CardHeader>
              <CardTitle className="text-lg">{act.name}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              {metrics.map((metric) => {
                const val = scores[`${act.id}_${metric.id}`] ?? 0;
                return (
                  <div key={`${act.id}_${metric.id}`} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium truncate">{metric.name}</span>
                      <div className="flex items-center gap-1 shrink-0">
                        <span
                          className={`text-sm font-mono tabular-nums ${scoreColor(val)}`}
                        >
                          {val}
                        </span>
                        <Badge
                          variant="outline"
                          className="text-[10px] px-1.5 py-0 h-5"
                        >
                          {scoreLabel(val)}
                        </Badge>
                      </div>
                    </div>
                    <Slider
                      value={[val]}
                      onValueChange={(v) =>
                        handleScoreChange(act.id, metric.id, v)
                      }
                      min={0}
                      max={100}
                      step={1}
                    />
                    <div className="flex justify-between text-[10px] text-muted-foreground">
                      <span>{metric.anchors?.low ?? "Poor fit"}</span>
                      <span>{metric.anchors?.mid ?? "Partial fit"}</span>
                      <span>{metric.anchors?.high ?? "Excellent fit"}</span>
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Submit ── */}
      <div className="flex justify-end">
        <Button
          onClick={handleSubmit}
          disabled={submitting || navigating}
          size="lg"
        >
          {submitting || navigating ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              {submitting ? "Submitting..." : "Navigating..."}
            </>
          ) : (
            <>
              Submit Scores
              <ArrowRight className="ml-2 h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
