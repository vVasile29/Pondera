import { useState, useEffect, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useDecision } from "@/hooks/useDecision";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, ArrowRight, Plus, X } from "lucide-react";
import type { Metric } from "@/types";

const DIMENSION_ORDER = [
  "Resource Fit",
  "Objective Fit",
  "Time Fit",
  "Assurance Fit",
  "People Fit",
  "Practical Fit",
];

export default function Review() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data, loading, error: fetchError } = useDecision(id);

  const [alternatives, setAlternatives] = useState<string[]>([]);
  const [includedMetrics, setIncludedMetrics] = useState<
    Record<number, boolean>
  >({});
  const [metricWeights, setMetricWeights] = useState<Record<number, number>>(
    {},
  );
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [koThresholds, setKoThresholds] = useState<Record<number, number | null>>({});

  // Initialize state from fetched decision data
  useEffect(() => {
    if (!data) return;

    setAlternatives(data.activities.map((a) => a.name));

    // Build weight map from rows (which hold the weight per metric name)
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

    // Initialize KO criteria from existing data
    const koInit: Record<number, number | null> = {};
    if (data.ko_criteria) {
      data.ko_criteria.forEach((kc) => {
        koInit[kc.metric_id] = kc.ko_value;
      });
    }
    data.metrics.forEach((m) => {
      if (!(m.id in koInit)) {
        koInit[m.id] = null;
      }
    });
    setKoThresholds(koInit);
  }, [data]);

  // Group metrics by dimension category, sorted in ontology order
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

  const handleAlternativeChange = (index: number, value: string) => {
    setAlternatives((prev) => {
      const next = [...prev];
      next[index] = value;
      return next;
    });
  };

  const addAlternative = () => {
    setAlternatives((prev) => [...prev, ""]);
  };

  const removeAlternative = (index: number) => {
    setAlternatives((prev) => prev.filter((_, i) => i !== index));
  };

  const toggleMetric = (metricId: number) => {
    setIncludedMetrics((prev) => {
      const next = { ...prev, [metricId]: !prev[metricId] };
      if (!next[metricId]) {
        setKoThresholds((kp) => ({ ...kp, [metricId]: null }));
      }
      return next;
    });
  };

  const toggleKo = (metricId: number) => {
    setKoThresholds((prev) => ({
      ...prev,
      [metricId]: prev[metricId] !== null ? null : 50,
    }));
  };

  const handleKoValueChange = (metricId: number, value: number) => {
    setKoThresholds((prev) => ({
      ...prev,
      [metricId]: value,
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
    const validAlternatives = alternatives
      .map((a) => a.trim())
      .filter((a) => a.length > 0);

    if (validAlternatives.length < 1) {
      errors.push("At least one alternative is required.");
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

      // Build KO criteria payload
      const koPayload = Object.entries(koThresholds)
        .filter(([, value]) => value !== null)
        .map(([metricIdStr, value]) => ({
          metric_id: parseInt(metricIdStr),
          ko_operator: ">=",
          ko_value: value!,
        }));

      await api.refineDecision(numId, {
        alternatives: validAlternatives,
        metrics: metricsPayload,
        ko_criteria: koPayload.length > 0 ? koPayload : undefined,
      });

      navigate(`/decisions/${numId}/score`);
    } catch (e: any) {
      setSubmitError(e.message || "Failed to save changes. Please try again.");
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

  // ── Fetch error state ──
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
        <h1 className="text-3xl font-bold">Decision Review</h1>
        <p className="text-muted-foreground mt-1">{data.decision.query}</p>
      </div>

      {/* ── Validation Errors ── */}
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

      {/* ── Alternatives Section ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Alternatives</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {alternatives.map((alt, index) => (
            <div key={index} className="flex items-center gap-2">
              <Input
                value={alt}
                onChange={(e) => handleAlternativeChange(index, e.target.value)}
                placeholder={`Alternative ${index + 1}`}
                className="flex-1"
              />
              {alternatives.length > 2 && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removeAlternative(index)}
                  aria-label="Remove alternative"
                >
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addAlternative}>
            <Plus className="h-4 w-4 mr-1" />
            Add alternative
          </Button>
        </CardContent>
      </Card>

      {/* ── Criteria & Weights Section ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Criteria &amp; Weights</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <p className="text-sm text-muted-foreground">
            Every slider is a 0–100 fit score. Higher always means better fit. Adjust weights to set priority. Click <span className="font-semibold">KO</span> to set a minimum fit threshold — alternatives scoring below are eliminated from results.
          </p>
          {groupedMetrics.map(({ dimension, metrics }) => (
            <div key={dimension}>
              <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider mb-3">
                {dimension}
              </h3>
              <div className="space-y-4">
                {metrics.map((metric) => (
                  <div key={metric.id} className="sm:grid sm:grid-cols-[14rem_1fr_auto] sm:gap-x-4 sm:items-center">
                    {/* Col 1: Checkbox + name + description */}
                    <div className="flex items-start gap-2 sm:w-auto mb-3 sm:mb-0">
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
                          {metric.question ?? metric.description}
                        </span>
                      </div>
                    </div>

                    {/* Col 2: Weight slider */}
                    <div className="mb-3 sm:mb-0">
                      <Slider
                        value={[metricWeights[metric.id] ?? 50]}
                        onValueChange={(v) => handleWeightChange(metric.id, v)}
                        min={0}
                        max={100}
                        step={1}
                        disabled={!includedMetrics[metric.id]}
                      />
                    </div>

                    {/* Col 3: Value + KO button (always outline, colored when active) */}
                    <div className="flex items-center gap-2 justify-self-end mb-3 sm:mb-0">
                      <span className="text-sm font-mono w-10 text-right tabular-nums shrink-0">
                        {metricWeights[metric.id] ?? 50}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        className={`shrink-0 h-7 px-2 text-xs ${koThresholds[metric.id] !== null ? "bg-red-50 border-red-300 text-red-600 dark:bg-red-950 dark:border-red-800 dark:text-red-400" : ""}`}
                        disabled={!includedMetrics[metric.id]}
                        onClick={() => toggleKo(metric.id)}
                      >
                        KO
                      </Button>
                    </div>

                    {/* KO row — same grid columns, only when enabled */}
                    {includedMetrics[metric.id] && koThresholds[metric.id] !== null && (
                      <>
                        {/* Col 1: KO label */}
                        <div className="flex items-start gap-2">
                          <div className="w-4 shrink-0" />
                          <span className="text-xs text-red-500 font-medium leading-tight mt-0.5">KO min threshold</span>
                        </div>

                        {/* Col 2: KO slider */}
                        <div>
                          <Slider
                            value={[koThresholds[metric.id]!]}
                            onValueChange={(v) => handleKoValueChange(metric.id, v[0])}
                            min={0}
                            max={100}
                            step={1}
                            className="[&_[role=slider]]:bg-red-500 [&_[role=slider]]:border-red-500 [&_.bg-primary]:bg-red-500 [&_[role=track]]:bg-red-200 dark:[&_[role=track]]:bg-red-950"
                          />
                        </div>

                        {/* Col 3: KO value + invisible button spacer */}
                        <div className="flex items-center gap-2 justify-self-end">
                          <span className="text-sm font-mono w-10 text-right tabular-nums text-red-600 dark:text-red-400">
                            {koThresholds[metric.id]}
                          </span>
                          <Button variant="outline" size="sm" className="invisible pointer-events-none shrink-0 h-7 px-2 text-xs" aria-hidden="true" tabIndex={-1}>
                            KO
                          </Button>
                        </div>
                      </>
                    )}
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
