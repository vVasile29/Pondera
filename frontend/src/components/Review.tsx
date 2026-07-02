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
import { Badge } from "@/components/ui/badge";
import {
  Loader2,
  ArrowRight,
  Plus,
  X,
  Trash2,
  Check,
  Edit3,
} from "lucide-react";
import type { AIAvailability, AIMetricSuggestion, Metric } from "@/types";

const DIMENSION_ORDER = [
  "Resource Fit",
  "Objective Fit",
  "Time Fit",
  "Assurance Fit",
  "People Fit",
  "Practical Fit",
];

const FIT_CATEGORY_OPTIONS = [
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
  const { data, loading, error: fetchError, refetch } = useDecision(id);

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
  const [koThresholds, setKoThresholds] = useState<
    Record<number, number | null>
  >({});

  // Custom metric management state
  const [showAddCustomForm, setShowAddCustomForm] = useState(false);
  const [newCustomName, setNewCustomName] = useState("");
  const [newCustomCategory, setNewCustomCategory] = useState("Resource Fit");
  const [newCustomDesc, setNewCustomDesc] = useState("");
  const [editingCustomId, setEditingCustomId] = useState<number | null>(null);
  const [editCustomName, setEditCustomName] = useState("");
  const [editCustomCategory, setEditCustomCategory] = useState("");
  const [editCustomDesc, setEditCustomDesc] = useState("");
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [customApiError, setCustomApiError] = useState<string | null>(null);
  const [aiStatus, setAiStatus] = useState<AIAvailability | null>(null);
  const [aiSuggestions, setAiSuggestions] = useState<AIMetricSuggestion[]>([]);
  const [selectedSuggestionIndexes, setSelectedSuggestionIndexes] = useState<number[]>([]);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMessage, setAiMessage] = useState<string | null>(null);

  // Split metrics into global and custom
  const globalMetrics = useMemo(() => {
    if (!data) return [];
    return data.metrics.filter(
      (m) => m.scope !== "decision",
    );
  }, [data]);

  const customMetrics = useMemo(() => {
    if (!data) return [];
    return data.metrics.filter(
      (m) => m.scope === "decision",
    );
  }, [data]);

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

  useEffect(() => {
    api.getAIStatus().then(setAiStatus).catch(() => setAiStatus(null));
  }, []);

  // Group global metrics by dimension category, sorted in ontology order
  const groupedMetrics = useMemo(() => {
    const groups: Record<string, Metric[]> = {};
    globalMetrics.forEach((m) => {
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
  }, [globalMetrics]);

  // ── Handlers ──

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
    setIncludedMetrics((prev) => ({ ...prev, [metricId]: !prev[metricId] }));
  };

  // Sync KO thresholds: when a metric is excluded, remove its KO threshold
  useEffect(() => {
    setKoThresholds((prev) => {
      const next = { ...prev };
      for (const metricId of Object.keys(next)) {
        if (!includedMetrics[Number(metricId)]) {
          delete next[Number(metricId)];
        }
      }
      return next;
    });
  }, [includedMetrics]);

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

  // ── Custom Metric CRUD ──

  const resetAddForm = () => {
    setShowAddCustomForm(false);
    setNewCustomName("");
    setNewCustomCategory("Resource Fit");
    setNewCustomDesc("");
    setCustomApiError(null);
  };

  const handleAddCustomMetric = async () => {
    if (!id) return;
    if (!newCustomName.trim()) {
      setCustomApiError("Metric name is required.");
      return;
    }
    if (!newCustomCategory.trim()) {
      setCustomApiError("Metric category is required.");
      return;
    }

    setCustomApiError(null);
    try {
      const numId = parseInt(id);
      const result = await api.createCustomMetric(numId, {
        name: newCustomName.trim(),
        category: newCustomCategory.trim(),
        description: newCustomDesc.trim() || undefined,
      });

      // Add to weights and included state
      setMetricWeights((prev) => ({ ...prev, [result.id]: 50 }));
      setIncludedMetrics((prev) => ({ ...prev, [result.id]: true }));
      setKoThresholds((prev) => ({ ...prev, [result.id]: null }));
      resetAddForm();

      // Refetch so data.metrics includes the new metric
      refetch();
    } catch (e: any) {
      setCustomApiError(e.message || "Failed to create custom metric.");
    }
  };

  const startEditCustom = (metric: Metric) => {
    setEditingCustomId(metric.id);
    setEditCustomName(metric.name);
    setEditCustomCategory(metric.category);
    setEditCustomDesc(metric.description || "");
    setCustomApiError(null);
  };

  const cancelEditCustom = () => {
    setEditingCustomId(null);
    setCustomApiError(null);
  };

  const handleSaveEditCustom = async (metricId: number) => {
    if (!id) return;
    if (!editCustomName.trim()) {
      setCustomApiError("Metric name is required.");
      return;
    }
    if (!editCustomCategory.trim()) {
      setCustomApiError("Metric category is required.");
      return;
    }

    setCustomApiError(null);
    try {
      const numId = parseInt(id);
      await api.updateCustomMetric(numId, metricId, {
        name: editCustomName.trim(),
        category: editCustomCategory.trim(),
        description: editCustomDesc.trim() || undefined,
      });
      setEditingCustomId(null);
      refetch();
    } catch (e: any) {
      setCustomApiError(e.message || "Failed to update custom metric.");
    }
  };

  const handleDeleteCustom = async (metricId: number) => {
    if (!id) return;
    setCustomApiError(null);
    try {
      const numId = parseInt(id);
      await api.deleteCustomMetric(numId, metricId);
      setDeleteConfirmId(null);

      // Clean up local state
      setMetricWeights((prev) => {
        const next = { ...prev };
        delete next[metricId];
        return next;
      });
      setIncludedMetrics((prev) => {
        const next = { ...prev };
        delete next[metricId];
        return next;
      });
      setKoThresholds((prev) => {
        const next = { ...prev };
        delete next[metricId];
        return next;
      });
    } catch (e: any) {
      setCustomApiError(e.message || "Failed to delete custom metric.");
    }
  };

  const handleSuggestMetrics = async () => {
    if (!id) return;
    setAiBusy(true);
    setAiMessage(null);
    try {
      const res = await api.suggestMetricsWithAI(parseInt(id), {});
      setAiSuggestions(res.metric_suggestions);
      setSelectedSuggestionIndexes(res.metric_suggestions.map((_, index) => index));
      setAiMessage(`AI suggested ${res.metric_suggestions.length} decision-local metric(s).`);
    } catch (e: any) {
      setAiMessage(e.message || "AI metric suggestion failed.");
    } finally {
      setAiBusy(false);
    }
  };

  const updateAiSuggestion = (index: number, patch: Partial<AIMetricSuggestion>) => {
    setAiSuggestions((prev) => prev.map((suggestion, i) => i === index ? { ...suggestion, ...patch } : suggestion));
  };

  const handleCreateSelectedSuggestions = async () => {
    if (!id) return;
    setAiBusy(true);
    try {
      const decisionId = parseInt(id);
      for (const index of selectedSuggestionIndexes) {
        const suggestion = aiSuggestions[index];
        if (!suggestion) continue;
        const created = await api.createCustomMetric(decisionId, {
          name: suggestion.name,
          category: suggestion.category,
          description: suggestion.description || suggestion.why_it_matters,
          weight: suggestion.recommended_weight ?? 50,
        });
        setMetricWeights((prev) => ({ ...prev, [created.id]: suggestion.recommended_weight ?? 50 }));
        setIncludedMetrics((prev) => ({ ...prev, [created.id]: true }));
      }
      setAiSuggestions([]);
      setSelectedSuggestionIndexes([]);
      await refetch();
    } catch (e: any) {
      setAiMessage(e.message || "Failed to add AI suggestions.");
    } finally {
      setAiBusy(false);
    }
  };

  // ── Submit ──

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
      // Include BOTH global and custom metric weights
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

  const decisionId = parseInt(id || "0");

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

      {customApiError && (
        <Alert variant="destructive">
          <AlertDescription>{customApiError}</AlertDescription>
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

      {/* ── Global Criteria & Weights Section ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">Criteria &amp; Weights</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <p className="text-sm text-muted-foreground">
            Every slider is a 0–100 fit score. Higher always means better fit.
            Adjust weights to set priority. Click{" "}
            <span className="font-semibold">KO</span> to set a minimum fit
            threshold — alternatives scoring below are eliminated from results.
          </p>
          {groupedMetrics.map(({ dimension, metrics }) => (
            <div key={dimension}>
              <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider mb-3">
                {dimension}
              </h3>
              <div className="space-y-4">
                {metrics.map((metric) => (
                  <div
                    key={metric.id}
                    className="sm:grid sm:grid-cols-[14rem_1fr_auto] sm:gap-x-4 sm:items-center"
                  >
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

                    {/* Col 3: Value + KO button */}
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
                    {includedMetrics[metric.id] &&
                      koThresholds[metric.id] !== null && (
                        <>
                          {/* Col 1: KO label */}
                          <div className="flex items-start gap-2">
                            <div className="w-4 shrink-0" />
                            <span className="text-xs text-red-500 font-medium leading-tight mt-0.5">
                              KO min threshold
                            </span>
                          </div>

                          {/* Col 2: KO slider */}
                          <div>
                            <Slider
                              value={[koThresholds[metric.id]!]}
                              onValueChange={(v) =>
                                handleKoValueChange(metric.id, v[0])
                              }
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
                            <Button
                              variant="outline"
                              size="sm"
                              className="invisible pointer-events-none shrink-0 h-7 px-2 text-xs"
                              aria-hidden="true"
                              tabIndex={-1}
                            >
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

      <Card>
        <CardHeader>
          <CardTitle className="text-xl">AI metric assistance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            AI-generated values are drafts until you approve or apply them. Metric suggestions are added as decision-local custom criteria only.
          </p>
          {!aiStatus?.enabled && (
            <Alert>
              <AlertDescription>
                AI assistance is unavailable ({aiStatus?.reason ?? "disabled"}).
              </AlertDescription>
            </Alert>
          )}
          {aiMessage && <p className="text-sm text-muted-foreground">{aiMessage}</p>}
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleSuggestMetrics} disabled={!aiStatus?.enabled || aiBusy}>
              Suggest metrics with AI
            </Button>
            {aiSuggestions.length > 0 && (
              <Button onClick={handleCreateSelectedSuggestions} disabled={aiBusy || !selectedSuggestionIndexes.length}>
                Add selected as custom metrics
              </Button>
            )}
          </div>
          {aiSuggestions.length > 0 && (
            <div className="space-y-2">
              {aiSuggestions.map((suggestion, index) => (
                <div key={`${suggestion.name}-${index}`} className="flex items-start gap-2 rounded border p-3 text-sm">
                  <Checkbox
                    checked={selectedSuggestionIndexes.includes(index)}
                    onCheckedChange={(checked) => setSelectedSuggestionIndexes((prev) => checked ? [...prev, index] : prev.filter((i) => i !== index))}
                  />
                  <div className="grid flex-1 gap-2 sm:grid-cols-[1fr_1fr_7rem]">
                    <Input
                      value={suggestion.name}
                      onChange={(e) => updateAiSuggestion(index, { name: e.target.value })}
                      aria-label="AI suggestion name"
                    />
                    <Input
                      value={suggestion.category}
                      onChange={(e) => updateAiSuggestion(index, { category: e.target.value })}
                      aria-label="AI suggestion category"
                    />
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={suggestion.recommended_weight}
                      onChange={(e) => updateAiSuggestion(index, { recommended_weight: Number(e.target.value) })}
                      aria-label="AI suggestion recommended weight"
                    />
                    <Input
                      className="sm:col-span-3"
                      value={suggestion.description || suggestion.why_it_matters}
                      onChange={(e) => updateAiSuggestion(index, { description: e.target.value })}
                      aria-label="AI suggestion description"
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Custom Criteria Section ── */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-xl">Custom Criteria</CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              resetAddForm();
              setShowAddCustomForm(true);
            }}
          >
            <Plus className="h-4 w-4 mr-1" />
            Add Custom Metric
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {customMetrics.length === 0 && !showAddCustomForm && (
            <p className="text-sm text-muted-foreground">
              No custom criteria yet. Add your own metrics tailored to this
              decision.
            </p>
          )}

          {customMetrics.map((metric) => (
            <div key={metric.id}>
              {editingCustomId === metric.id ? (
                /* ── Edit form ── */
                <div className="border rounded-lg p-4 space-y-3 bg-muted/30">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <Label
                        htmlFor={`edit-name-${metric.id}`}
                        className="text-xs font-medium"
                      >
                        Name
                      </Label>
                      <Input
                        id={`edit-name-${metric.id}`}
                        value={editCustomName}
                        onChange={(e) => setEditCustomName(e.target.value)}
                        placeholder="Metric name"
                        className="mt-1"
                      />
                    </div>
                    <div>
                      <Label
                        htmlFor={`edit-cat-${metric.id}`}
                        className="text-xs font-medium"
                      >
                        Category
                      </Label>
                      <select
                        id={`edit-cat-${metric.id}`}
                        value={editCustomCategory}
                        onChange={(e) =>
                          setEditCustomCategory(e.target.value)
                        }
                        className="mt-1 flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {FIT_CATEGORY_OPTIONS.map((opt) => (
                          <option key={opt} value={opt}>
                            {opt}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div>
                    <Label
                      htmlFor={`edit-desc-${metric.id}`}
                      className="text-xs font-medium"
                    >
                      Description
                    </Label>
                    <Input
                      id={`edit-desc-${metric.id}`}
                      value={editCustomDesc}
                      onChange={(e) => setEditCustomDesc(e.target.value)}
                      placeholder="Optional description"
                      className="mt-1"
                    />
                  </div>
                  <div className="flex gap-2 justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={cancelEditCustom}
                    >
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => handleSaveEditCustom(metric.id)}
                    >
                      <Check className="h-4 w-4 mr-1" />
                      Save
                    </Button>
                  </div>
                </div>
              ) : deleteConfirmId === metric.id ? (
                /* ── Delete confirmation ── */
                <div className="border border-red-200 rounded-lg p-4 space-y-3 bg-red-50 dark:bg-red-950/30">
                  <p className="text-sm text-red-600 dark:text-red-400">
                    Delete "{metric.name}"? This will remove all scores and
                    weights for this criterion.
                  </p>
                  <div className="flex gap-2 justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setDeleteConfirmId(null)}
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => handleDeleteCustom(metric.id)}
                    >
                      <Trash2 className="h-4 w-4 mr-1" />
                      Delete
                    </Button>
                  </div>
                </div>
              ) : (
                /* ── Normal display row ── */
                <div>
                  <div className="sm:grid sm:grid-cols-[14rem_1fr_auto] sm:gap-x-4 sm:items-center">
                    {/* Col 1: Checkbox + name + badge + description */}
                    <div className="flex items-start gap-2 sm:w-auto mb-3 sm:mb-0">
                      <Checkbox
                        id={`custom-metric-${metric.id}`}
                        checked={includedMetrics[metric.id] ?? true}
                        onCheckedChange={() => toggleMetric(metric.id)}
                      />
                      <div className="flex flex-col min-w-0">
                        <div className="flex items-center gap-2">
                          <Label
                            htmlFor={`custom-metric-${metric.id}`}
                            className="font-medium cursor-pointer leading-tight"
                          >
                            {metric.name}
                          </Label>
                          <Badge
                            variant="secondary"
                            className="text-[10px] px-1.5 py-0 h-4"
                          >
                            Custom
                          </Badge>
                        </div>
                        <span className="text-xs text-muted-foreground leading-tight mt-0.5">
                          {metric.category}
                        </span>
                      </div>
                    </div>

                    {/* Col 2: Weight slider */}
                    <div className="mb-3 sm:mb-0">
                      <Slider
                        value={[metricWeights[metric.id] ?? 50]}
                        onValueChange={(v) =>
                          handleWeightChange(metric.id, v)
                        }
                        min={0}
                        max={100}
                        step={1}
                        disabled={!includedMetrics[metric.id]}
                      />
                    </div>

                    {/* Col 3: Value + KO + action buttons */}
                    <div className="flex items-center gap-1 justify-self-end mb-3 sm:mb-0">
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
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => startEditCustom(metric)}
                        aria-label="Edit custom metric"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-red-500 hover:text-red-600"
                        onClick={() => setDeleteConfirmId(metric.id)}
                        aria-label="Delete custom metric"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>

                  {/* KO row — same grid columns, only when enabled */}
                  {includedMetrics[metric.id] &&
                    koThresholds[metric.id] !== null && (
                      <div className="sm:grid sm:grid-cols-[14rem_1fr_auto] sm:gap-x-4 sm:items-center sm:mt-2">
                        {/* Col 1: KO label */}
                        <div className="flex items-start gap-2">
                          <div className="w-4 shrink-0" />
                          <span className="text-xs text-red-500 font-medium leading-tight mt-0.5">
                            KO min threshold
                          </span>
                        </div>

                        {/* Col 2: KO slider */}
                        <div>
                          <Slider
                            value={[koThresholds[metric.id]!]}
                            onValueChange={(v) =>
                              handleKoValueChange(metric.id, v[0])
                            }
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
                          <Button
                            variant="outline"
                            size="sm"
                            className="invisible pointer-events-none shrink-0 h-7 px-2 text-xs"
                            aria-hidden="true"
                            tabIndex={-1}
                          >
                            KO
                          </Button>
                        </div>
                      </div>
                    )}
                </div>
              )}
            </div>
          ))}

          {/* ── Add custom metric form ── */}
          {showAddCustomForm && (
            <div className="border rounded-lg p-4 space-y-3 bg-muted/30">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <Label
                    htmlFor="new-custom-name"
                    className="text-xs font-medium"
                  >
                    Name *
                  </Label>
                  <Input
                    id="new-custom-name"
                    value={newCustomName}
                    onChange={(e) => setNewCustomName(e.target.value)}
                    placeholder="e.g. Work-Life Balance"
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label
                    htmlFor="new-custom-category"
                    className="text-xs font-medium"
                  >
                    Category *
                  </Label>
                  <select
                    id="new-custom-category"
                    value={newCustomCategory}
                    onChange={(e) => setNewCustomCategory(e.target.value)}
                    className="mt-1 flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {FIT_CATEGORY_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <Label
                  htmlFor="new-custom-desc"
                  className="text-xs font-medium"
                >
                  Description
                </Label>
                <Input
                  id="new-custom-desc"
                  value={newCustomDesc}
                  onChange={(e) => setNewCustomDesc(e.target.value)}
                  placeholder="Optional description or question"
                  className="mt-1"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <Button variant="outline" size="sm" onClick={resetAddForm}>
                  Cancel
                </Button>
                <Button size="sm" onClick={handleAddCustomMetric}>
                  <Plus className="h-4 w-4 mr-1" />
                  Add Metric
                </Button>
              </div>
            </div>
          )}
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
