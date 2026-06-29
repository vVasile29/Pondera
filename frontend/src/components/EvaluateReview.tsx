import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useDecision } from "@/hooks/useDecision";
import { api } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Loader2,
  ArrowRight,
  ArrowUp,
  ArrowDown,
  Info,
} from "lucide-react";
import type { Metric } from "@/types";

const DIMENSION_ORDER = [
  "Financial",
  "Quality",
  "Time",
  "Risk",
  "Experience",
  "Convenience",
];

export default function EvaluateReview() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data, loading, error: fetchError } = useDecision(id);

  const [subject, setSubject] = useState("");
  const [includedMetrics, setIncludedMetrics] = useState<
    Record<number, boolean>
  >({});
  const [metricWeights, setMetricWeights] = useState<Record<number, number>>(
    {},
  );
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  // Initialize from fetched data
  useEffect(() => {
    if (!data) return;

    // Subject is the single activity name
    if (data.activities.length > 0) {
      setSubject(data.activities[0].name);
    }

    // Build weight map from rows
    const weightMap: Record<string, number> = {};
    if (data.rows) {
      data.rows.forEach((row) => {
        weightMap[row.metric_name] = row.weight;
      });
    }

    const included: Record<number, boolean> = {};
    const weights: Record<number, number> = {};
    data.metrics.forEach((m) => {
      included[m.id] = true;
      weights[m.id] = weightMap[m.name] ?? 50;
    });

    setIncludedMetrics(included);
    setMetricWeights(weights);
  }, [data]);

  // Group metrics by dimension
  const groupedMetrics = useMemo(() => {
    if (!data) return [];

    const groups: Record<string, Metric[]> = {};
    data.metrics.forEach((m) => {
      const cat = m.category || "General";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(m);
    });

    return Object.entries(groups)
      .map(([dimension, metrics]) => ({ dimension, metrics }))
      .sort(
        (a, b) =>
          DIMENSION_ORDER.indexOf(a.dimension) -
          DIMENSION_ORDER.indexOf(b.dimension),
      );
  }, [data]);

  const toggleMetric = (metricId: number) => {
    setIncludedMetrics((prev) => ({
      ...prev,
      [metricId]: !prev[metricId],
    }));
  };

  const handleWeightChange = (metricId: number, value: number[]) => {
    setMetricWeights((prev) => ({
      ...prev,
      [metricId]: value[0],
    }));
  };

  const handleSubmit = async () => {
    setSubmitError(null);
    setValidationErrors([]);

    const errors: string[] = [];
    const subjectTrimmed = subject.trim();

    if (!subjectTrimmed) {
      errors.push("Subject name is required.");
    }

    const selectedMetrics = Object.entries(includedMetrics)
      .filter(([, inc]) => inc)
      .map(([idStr]) => Number(idStr));

    if (selectedMetrics.length < 1) {
      errors.push("At least one criterion must be selected.");
    }

    if (errors.length > 0) {
      setValidationErrors(errors);
      return;
    }

    if (!id) return;

    setSubmitting(true);
    try {
      const numId = parseInt(id);
      const metricsPayload = selectedMetrics.map((metricId) => ({
        metric_id: metricId,
        weight: metricWeights[metricId] ?? 50,
      }));

      await api.refineDecision(numId, {
        alternatives: [subjectTrimmed],
        metrics: metricsPayload,
      });

      navigate(`/evaluate/${numId}/result`);
    } catch (e: any) {
      setSubmitError(
        e.message || "Failed to save changes. Please try again.",
      );
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

  // ── Fetch error ──
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

  return (
    <div className="container mx-auto py-8 px-4 max-w-4xl space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Evaluation Review</h1>
        <p className="text-muted-foreground mt-1">{data.decision.query}</p>
      </div>

      {/* ── Info callout ── */}
      {subject && (
        <div className="flex items-start gap-3 p-4 rounded-lg border bg-muted/30 text-sm">
          <Info className="h-5 w-5 text-primary shrink-0 mt-0.5" />
          <div>
            <span className="font-medium">Subject identified: </span>
            <span className="text-muted-foreground">
              We identified <strong>{subject}</strong> as the subject of
              evaluation. Adjust the name and select criteria below, then
              continue to scoring.
            </span>
          </div>
        </div>
      )}

      {/* ── Validation errors ── */}
      {validationErrors.length > 0 && (
        <Alert variant="destructive">
          <AlertDescription>
            <ul className="list-disc list-inside space-y-1">
              {validationErrors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {submitError && (
        <Alert variant="destructive">
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      )}

      {/* ── Subject ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Subject</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-w-md">
            <Input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Subject name"
            />
          </div>
        </CardContent>
      </Card>

      {/* ── Criteria & Weights ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Criteria &amp; Weights</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {groupedMetrics.map(({ dimension, metrics }) => (
            <div key={dimension}>
              <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider mb-3">
                {dimension}
              </h3>
              <div className="space-y-4">
                {metrics.map((metric) => (
                  <div
                    key={metric.id}
                    className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4"
                  >
                    {/* Checkbox + name + description */}
                    <div className="flex items-start gap-2 sm:w-56 shrink-0">
                      <Checkbox
                        id={`metric-${metric.id}`}
                        checked={includedMetrics[metric.id] ?? true}
                        onCheckedChange={() => toggleMetric(metric.id)}
                      />
                      <div className="flex flex-col min-w-0">
                        <Label
                          htmlFor={`metric-${metric.id}`}
                          className="font-medium cursor-pointer leading-tight"
                        >
                          {metric.name}
                        </Label>
                        <span className="text-xs text-muted-foreground leading-tight mt-0.5">
                          {metric.description}
                        </span>
                      </div>
                    </div>

                    {/* Weight slider */}
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <Slider
                        value={[metricWeights[metric.id] ?? 50]}
                        onValueChange={(v) =>
                          handleWeightChange(metric.id, v)
                        }
                        min={0}
                        max={100}
                        step={1}
                        disabled={!includedMetrics[metric.id]}
                        className="flex-1"
                      />
                      <span className="text-sm font-mono w-10 text-right tabular-nums shrink-0">
                        {metricWeights[metric.id] ?? 50}
                      </span>
                    </div>

                    {/* Direction indicator */}
                    <div className="flex items-center gap-1 text-xs text-muted-foreground shrink-0">
                      {metric.higher_is_better ? (
                        <ArrowUp className="h-3 w-3 text-green-500" />
                      ) : (
                        <ArrowDown className="h-3 w-3 text-red-500" />
                      )}
                      <span>
                        {metric.higher_is_better
                          ? "Higher is better"
                          : "Lower is better"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* ── Submit ── */}
      <div className="flex justify-end">
        <Button onClick={handleSubmit} disabled={submitting} size="lg">
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Saving...
            </>
          ) : (
            <>
              Confirm &amp; Continue
              <ArrowRight className="ml-2 h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
