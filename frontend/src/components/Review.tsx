import { useState, useEffect, useMemo, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useDecision } from "@/hooks/useDecision";
import { useScoring } from "@/hooks/useScoring";
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
  ArrowLeft,
  Plus,
  X,
  Trash2,
  Check,
  Edit3,
  CheckCheck,
  Sparkles,
} from "lucide-react";
import type { AIAvailability, AIMetricSuggestion, AIMetricRecommendation, Metric, ScoreDraft, EvidenceItem } from "@/types";

const DIMENSION_ORDER = [
  "Resource Fit",
  "Objective Fit",
  "Time Fit",
  "Assurance Fit",
  "People Fit",
  "Practical Fit",
];

const DIMENSION_QUESTIONS: Record<string, string> = {
  "Resource Fit": "Is the required burden acceptable and worth it?",
  "Objective Fit": "Does this achieve the purpose of the decision?",
  "Time Fit": "Does the timing work?",
  "Assurance Fit": "Can we trust this option to work without unacceptable downside?",
  "People Fit": "Does this option fit the people affected?",
  "Practical Fit": "Can this option realistically be done, used, accessed, operated, and adapted?",
};

const FIT_CATEGORY_OPTIONS = [
  "Resource Fit",
  "Objective Fit",
  "Time Fit",
  "Assurance Fit",
  "People Fit",
  "Practical Fit",
];

function AIContextField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor="user-context" className="text-sm font-medium">
        Context for AI (optional)
      </Label>
      <textarea
        id="user-context"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="e.g. I'm a first-time home buyer in Seattle with a family of four looking for good schools..."
        className="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
      <p className="text-xs text-muted-foreground">
        This context is sent with every AI request across all steps.
      </p>
    </div>
  );
}

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

  const [customApiError, setCustomApiError] = useState<string | null>(null);
  const [step, setStep] = useState(1);
  const [aiStatus, setAiStatus] = useState<AIAvailability | null>(null);
  const [aiSuggestions, setAiSuggestions] = useState<AIMetricSuggestion[]>([]);
  const [aiRecommendations, setAiRecommendations] = useState<Record<string, AIMetricRecommendation>>({});
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMessage, setAiMessage] = useState<string | null>(null);
  const [userContext, setUserContext] = useState("");

  const {
    scores: scoreValues,
    updateScore,
    submitting: scoresSubmitting,
    error: scoresError,
  } = useScoring(parseInt(id || "0"));

  // ── Helpers for score color/label ──
  function scoreColor(value: number): string {
    const pct = value / 100;
    if (pct >= 0.7) return "text-green-600 dark:text-green-400";
    if (pct >= 0.4) return "text-amber-600 dark:text-amber-400";
    return "text-red-600 dark:text-red-400";
  }
  function scoreLabel(value: number): string {
    if (value >= 95) return "Excellent";
    if (value >= 75) return "Good";
    if (value >= 50) return "Average";
    if (value >= 25) return "Below Avg";
    return "Poor";
  }

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

  // Pre-populate scores when entering Step 3
  const [scoresPrePopulated, setScoresPrePopulated] = useState(false);
  useEffect(() => {
    if (step !== 3 || scoresPrePopulated || !data || !data.rows) return;
    const nameToId = new Map(data.metrics.map((m) => [m.name, m.id]));
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
    setScoresPrePopulated(found);
  }, [step, scoresPrePopulated, data, updateScore]);

  // ── Evidence + AI Score Drafts (Step 3) ──
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [scoreDrafts, setScoreDrafts] = useState<ScoreDraft[]>([]);
  const [manualEvidenceClaims, setManualEvidenceClaims] = useState<Record<string, string>>({});
  const [draftEditScores, setDraftEditScores] = useState<Record<number, number>>({});

  const refreshEvidenceDrafts = useCallback(async () => {
    if (!id) return;
    const decisionId = parseInt(id);
    const [evidenceRes, draftsRes] = await Promise.all([
      api.getEvidence(decisionId),
      api.getScoreDrafts(decisionId),
    ]);
    setEvidence(evidenceRes.evidence);
    setScoreDrafts(draftsRes.drafts);
  }, [id]);

  useEffect(() => {
    if (step !== 3) return;
    refreshEvidenceDrafts().catch(() => undefined);
  }, [step, refreshEvidenceDrafts]);

  const handleDraftEvidence = async () => {
    if (!id || !data) return;
    const selectedMetricIds = data.metrics.filter((m) => includedMetrics[m.id]).map((m) => m.id);
    setAiBusy(true);
    setAiMessage(null);
    try {
      const res = await api.draftEvidenceWithAI(parseInt(id), {
        user_context: userContext || undefined,
        activity_ids: data.activities.map((a) => a.id),
        metric_ids: selectedMetricIds,
        include_general_evidence: false,
        max_items: Math.max(1, data.activities.length * selectedMetricIds.length),
      });
      await refreshEvidenceDrafts();
      setAiMessage(`AI drafted ${res.evidence_items.length} pending evidence item(s).`);
    } catch (e: any) {
      setAiMessage(e.message || "AI evidence drafting failed.");
    } finally {
      setAiBusy(false);
    }
  };

  const handleSuggestScores = async () => {
    if (!id || !data) return;
    const selectedMetricIds = data.metrics.filter((m) => includedMetrics[m.id]).map((m) => m.id);
    setAiBusy(true);
    setAiMessage(null);
    try {
      const res = await api.suggestScoresWithAI(parseInt(id), {
        user_context: userContext || undefined,
        activity_ids: data.activities.map((a) => a.id),
        metric_ids: selectedMetricIds,
        evidence_review_policy: "approved_and_pending",
        max_drafts: Math.max(1, data.activities.length * selectedMetricIds.length),
      });
      await refreshEvidenceDrafts();
      setAiMessage(`AI created ${res.score_drafts.length} pending score draft(s).`);
    } catch (e: any) {
      setAiMessage(e.message || "AI score suggestion failed.");
    } finally {
      setAiBusy(false);
    }
  };

  const handleApplyScoreDraft = async (draft: ScoreDraft) => {
    if (!id) return;
    const decisionId = parseInt(id);
    const editedScore = draftEditScores[draft.id];
    if (editedScore !== undefined && editedScore !== draft.effective_score) {
      await api.updateScoreDraft(decisionId, draft.id, { human_adjusted_score: editedScore });
    }
    const res = await api.applyScoreDraft(decisionId, draft.id);
    updateScore(res.score.activity_id, res.score.metric_id, res.score.score);
    setDraftEditScores((prev) => {
      const next = { ...prev };
      delete next[draft.id];
      return next;
    });
    await refreshEvidenceDrafts();
  };

  const handleRejectScoreDraft = async (draft: ScoreDraft) => {
    if (!id) return;
    await api.rejectScoreDraft(parseInt(id), draft.id);
    setDraftEditScores((prev) => {
      const next = { ...prev };
      delete next[draft.id];
      return next;
    });
    await refreshEvidenceDrafts();
  };

  const handleAddEvidence = async (activityId: number, metricId: number) => {
    if (!id) return;
    const key = `${activityId}_${metricId}`;
    const claim = (manualEvidenceClaims[key] || "").trim();
    if (!claim) return;
    await api.createEvidence(parseInt(id), { activity_id: activityId, metric_id: metricId, claim });
    setManualEvidenceClaims((prev) => ({ ...prev, [key]: "" }));
    await refreshEvidenceDrafts();
  };

  const handleReviewEvidence = async (item: EvidenceItem, action: "approve" | "reject") => {
    if (!id) return;
    if (action === "approve") {
      await api.approveEvidence(parseInt(id), item.id);
    } else {
      await api.rejectEvidence(parseInt(id), item.id);
    }
    await refreshEvidenceDrafts();
  };

  // Group all metrics by dimension category, sorted in ontology order
  const groupedMetrics = useMemo(() => {
    const groups: Record<string, Metric[]> = {};
    data?.metrics.forEach((m) => {
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
  // Group AI suggestions by category
  const groupedAiSuggestions = useMemo(() => {
    const groups: Record<string, { index: number; suggestion: AIMetricSuggestion }[]> = {};
    aiSuggestions.forEach((s, index) => {
      const cat = s.category || "General";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push({ index, suggestion: s });
    });
    return Object.entries(groups)
      .map(([dimension, items]) => ({ dimension, items }))
      .sort(
        (a, b) =>
          DIMENSION_ORDER.indexOf(a.dimension) -
          DIMENSION_ORDER.indexOf(b.dimension),
      );
  }, [aiSuggestions]);

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
      refetch();
    } catch (e: any) {
      setCustomApiError(e.message || "Failed to delete custom metric.");
    }
  };

  const handleSuggestMetrics = async () => {
    if (!id) return;
    setAiBusy(true);
    setAiMessage(null);
    setAiSuggestions([]);
    try {
      const res = await api.suggestMetricsWithAI(parseInt(id), { user_context: userContext || undefined });
      setAiSuggestions(res.metric_suggestions);
      setAiMessage(`AI suggested ${res.metric_suggestions.length} criteria. Review each row and accept or reject it.`);
    } catch (e: any) {
      setAiMessage(e.message || "AI metric suggestion failed.");
    } finally {
      setAiBusy(false);
    }
  };

  const updateAiSuggestion = (index: number, patch: Partial<AIMetricSuggestion>) => {
    setAiSuggestions((prev) => prev.map((suggestion, i) => i === index ? { ...suggestion, ...patch } : suggestion));
  };

  const handleAcceptSuggestion = async (index: number) => {
    if (!id) return;
    const suggestion = aiSuggestions[index];
    if (!suggestion) return;
    setAiBusy(true);
    try {
      const decisionId = parseInt(id);
      const existingNames = new Set((data?.metrics ?? []).map((m) => m.name.toLowerCase()));
      if (existingNames.has(suggestion.name.trim().toLowerCase())) {
        setAiSuggestions((prev) => prev.filter((_, i) => i !== index));
        setAiMessage(`Skipped "${suggestion.name}" because it already exists.`);
        return;
      }
      const created = await api.createCustomMetric(decisionId, {
        name: suggestion.name.trim(),
        category: suggestion.category.trim(),
        description: suggestion.description || suggestion.why_it_matters,
        weight: suggestion.recommended_weight ?? 50,
      });
      setMetricWeights((prev) => ({ ...prev, [created.id]: suggestion.recommended_weight ?? 50 }));
      setIncludedMetrics((prev) => ({ ...prev, [created.id]: true }));
      setKoThresholds((prev) => ({ ...prev, [created.id]: null }));
      setAiSuggestions((prev) => prev.filter((_, i) => i !== index));
      await refetch();
      setAiMessage(`Added "${created.name}".`);
    } catch (e: any) {
      setAiMessage(e.message || "Failed to add AI suggestion.");
    } finally {
      setAiBusy(false);
    }
  };

  const handleRejectSuggestion = (index: number) => {
    const rejected = aiSuggestions[index]?.name;
    setAiSuggestions((prev) => prev.filter((_, i) => i !== index));
    if (rejected) setAiMessage(`Rejected "${rejected}".`);
  };

  const handleOptimizeWeights = async () => {
    if (!id) return;
    setAiBusy(true);
    setAiMessage(null);
    setAiRecommendations({});
    try {
      const res = await api.optimizeWeightsWithAI(parseInt(id), { user_context: userContext || undefined });
      const recs: Record<string, AIMetricRecommendation> = {};
      for (const r of res.metric_recommendations) {
        recs[r.metric_name] = r;
      }
      setAiRecommendations(recs);
      const count = res.metric_recommendations.length;
      setAiMessage(`AI recommended weight adjustments for ${count} metric(s). Click "Apply" to accept.`);
    } catch (e: any) {
      setAiMessage(e.message || "AI recommendation failed.");
    } finally {
      setAiBusy(false);
    }
  };

  const applyAiRecommendation = (metricName: string, weight: number) => {
    const metric = data?.metrics.find((m) => m.name === metricName);
    if (!metric) {
      setAiMessage(`Could not find metric "${metricName}".`);
      return;
    }
    setMetricWeights((prev) => ({ ...prev, [metric.id]: weight }));
    rejectAiRecommendation(metricName);
    setAiMessage(`Applied weight ${weight} for "${metricName}".`);
  };

  const rejectAiRecommendation = (metricName: string) => {
    setAiRecommendations((prev) => {
      const next = { ...prev };
      delete next[metricName];
      return next;
    });
  };

  const clearAiRecommendations = () => {
    setAiRecommendations({});
    setAiMessage(null);
  };

  // ── Validation helper ──

  const validateForm = (): { valid: boolean; validAlternatives: string[]; selectedMetrics: number[] } => {
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

    setValidationErrors(errors);
    return { valid: errors.length === 0, validAlternatives, selectedMetrics };
  };

  // ── Step 2 → Step 3 (validate + refineDecision so DecisionWeight records exist for AI) ──

  const handleAdvanceToScoring = async () => {
    setSubmitError(null);
    setValidationErrors([]);

    const { valid, validAlternatives, selectedMetrics } = validateForm();
    if (!valid || !id) return;

    setSubmitting(true);
    try {
      const numId = parseInt(id);
      const metricsPayload = selectedMetrics.map((metricId) => ({
        metric_id: metricId,
        weight: metricWeights[metricId] ?? 50,
      }));
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

      setScoresPrePopulated(false);
      await refetch();
      setStep(3);
    } catch (e: any) {
      setSubmitError(e.message || "Failed to save. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  // ── Final submit (score only — refineDecision already saved on Step 2 → 3) ──

  const handleFinalSubmit = async () => {
    setSubmitError(null);

    if (!id || !data) return;
    const selectedMetrics = data.metrics.filter((m) => includedMetrics[m.id]);
    const scores = data.activities.flatMap((activity) =>
      selectedMetrics.map((metric) => ({
        activity_id: activity.id,
        metric_id: metric.id,
        score: scoreValues[`${activity.id}_${metric.id}`] ?? 0,
      })),
    );

    setSubmitting(true);
    try {
      await api.submitScores(parseInt(id), scores);
      navigate(`/decisions/${parseInt(id)}/result`);
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

  const renderCellReview = (activityId: number, metricId: number) => {
    const key = `${activityId}_${metricId}`;
    const cellEvidence = evidence.filter(
      (item) =>
        (!item.activity_id || item.activity_id === activityId) &&
        (!item.metric_id || item.metric_id === metricId),
    );
    const cellDrafts = scoreDrafts.filter(
      (draft) =>
        draft.activity_id === activityId &&
        draft.metric_id === metricId &&
        draft.status !== "applied" &&
        draft.status !== "rejected",
    );

    return (
      <div className="mt-2 space-y-2 text-xs">
        <div className="flex gap-1">
          <Input
            value={manualEvidenceClaims[key] ?? ""}
            onChange={(e) =>
              setManualEvidenceClaims((prev) => ({ ...prev, [key]: e.target.value }))
            }
            placeholder="Add evidence"
            className="h-7 text-xs"
          />
          <Button size="sm" variant="outline" onClick={() => handleAddEvidence(activityId, metricId)}>
            Add
          </Button>
        </div>

        {cellEvidence.map((item) => (
          <div key={item.id} className="rounded border bg-muted/30 p-1.5 space-y-1">
            <div className="flex flex-wrap items-start gap-1">
              <Badge variant="outline" className="mr-1 text-[10px]">
                {item.review_status}
              </Badge>
              <span>{item.claim}</span>
            </div>
            {item.rationale && (
              <p className="text-[10px] text-muted-foreground">{item.rationale}</p>
            )}
            {item.review_status === "pending" && (
              <div className="flex gap-1">
                <Button size="sm" variant="outline" className="h-6 text-[10px] px-1.5" onClick={() => handleReviewEvidence(item, "approve")}>
                  Approve evidence
                </Button>
                <Button size="sm" variant="ghost" className="h-6 text-[10px] px-1.5" onClick={() => handleReviewEvidence(item, "reject")}>
                  Reject
                </Button>
              </div>
            )}
          </div>
        ))}

        {cellDrafts.map((draft) => (
          <div key={draft.id} className="rounded border border-dashed border-blue-300 bg-blue-50/40 dark:bg-blue-950/20 dark:border-blue-800 p-1.5 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-blue-700 dark:text-blue-300">AI score draft</span>
              <Input
                type="number"
                min={0}
                max={100}
                value={draftEditScores[draft.id] ?? draft.effective_score}
                onChange={(e) =>
                  setDraftEditScores((prev) => ({
                    ...prev,
                    [draft.id]: Number(e.target.value),
                  }))
                }
                className="h-7 w-20 text-xs border-blue-200 dark:border-blue-800"
                aria-label="Draft score"
              />
              <Button size="sm" variant="outline" className="h-6 text-[10px] px-1.5 ml-auto" onClick={() => handleApplyScoreDraft(draft)}>
                Apply
              </Button>
              <Button size="sm" variant="ghost" className="h-6 text-[10px] px-1.5" onClick={() => handleRejectScoreDraft(draft)}>
                Reject
              </Button>
            </div>
            {draft.rationale && (
              <p className="text-[10px] text-blue-700 dark:text-blue-300">{draft.rationale}</p>
            )}
          </div>
        ))}
      </div>
    );
  };

  const stepLabels = ["Set Criteria", "Set Weights", "Score"];

  return (
    <div className="container mx-auto py-8 px-4 max-w-4xl space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Decision Review</h1>
        <p className="text-muted-foreground mt-1">{data.decision.query}</p>
      </div>

      {/* ── Step Indicator ── */}
      <div className="flex items-center gap-0">
        {stepLabels.map((label, i) => {
          const stepNum = i + 1;
          const isActive = step === stepNum;
          const isComplete = step > stepNum;
          return (
            <div key={label} className="flex items-center">
              <div className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium ${isActive ? "bg-primary text-primary-foreground" : isComplete ? "bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400" : "bg-muted text-muted-foreground"}`}>
                <span className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${isActive ? "bg-primary-foreground/20" : isComplete ? "bg-green-200 dark:bg-green-800" : "bg-muted-foreground/20"}`}>
                  {isComplete ? <Check className="h-3.5 w-3.5" /> : stepNum}
                </span>
                {label}
              </div>
              {i < stepLabels.length - 1 && (
                <div className={`h-0.5 w-8 ${step > stepNum ? "bg-green-400" : "bg-muted-foreground/20"}`} />
              )}
            </div>
          );
        })}
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

      {/* ════════════════════════════════════════
          STEP 1: Set Criteria
          ════════════════════════════════════════ */}
      {step === 1 && (
        <>
          {/* ── User context (shared for all AI calls) ── */}
          <Card>
            <CardContent className="pt-6">
              <AIContextField value={userContext} onChange={setUserContext} />
            </CardContent>
          </Card>

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
                    <Button variant="ghost" size="icon" onClick={() => removeAlternative(index)} aria-label="Remove alternative">
                      <X className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={addAlternative}>
                <Plus className="h-4 w-4 mr-1" /> Add alternative
              </Button>
            </CardContent>
          </Card>

          {/* ── Criteria Selection ── */}
          <Card>
            <CardHeader>
              <CardTitle className="text-xl">Criteria</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <p className="text-sm text-muted-foreground">
                Select the criteria that matter for your decision. Check/uncheck to include or exclude.
              </p>
              {groupedMetrics.map(({ dimension, metrics }) => (
                <div key={dimension}>
                  <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider mb-1">{dimension}</h3>
                  {DIMENSION_QUESTIONS[dimension] && (
                    <p className="text-xs text-muted-foreground mb-3 italic">{DIMENSION_QUESTIONS[dimension]}</p>
                  )}
                  <div className="space-y-2">
                    {metrics.map((metric) => {
                      const isCustom = metric.scope === "decision";
                      return (
                        <div key={metric.id}>
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 min-w-0">
                              <Checkbox
                                id={`metric-${metric.id}`}
                                checked={includedMetrics[metric.id] ?? true}
                                onCheckedChange={() => toggleMetric(metric.id)}
                              />
                              <div className="min-w-0">
                                <Label htmlFor={`metric-${metric.id}`} className="font-medium cursor-pointer leading-tight">
                                  {metric.name}
                                </Label>
                                {(metric.description || metric.question) && (
                                  <p className="text-xs text-muted-foreground truncate max-w-md">{metric.question || metric.description}</p>
                                )}
                              </div>
                              {isCustom && <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 shrink-0">Custom</Badge>}
                            </div>
                            {isCustom && (
                              <div className="flex items-center gap-1 shrink-0">
                                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => startEditCustom(metric)} aria-label="Edit">
                                  <Edit3 className="h-3.5 w-3.5" />
                                </Button>
                                <Button variant="ghost" size="icon" className="h-7 w-7 text-red-500 hover:text-red-600" onClick={() => handleDeleteCustom(metric.id)} aria-label="Delete">
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}

                    {/* ── AI suggestion preview rows ── */}
                    {groupedAiSuggestions
                      .filter((g) => g.dimension === dimension)
                      .map(({ items }) =>
                        items.map(({ index, suggestion }) => (
                          <div key={`ai-preview-${index}`} className="rounded border border-dashed border-blue-300 bg-blue-50/40 dark:bg-blue-950/20 dark:border-blue-800 p-2.5 space-y-2">
                            <div className="grid gap-1.5 sm:grid-cols-[1fr_1fr_5rem]">
                              <Input value={suggestion.name} onChange={(e) => updateAiSuggestion(index, { name: e.target.value })} aria-label="Name" className="h-8 text-xs border-blue-200 dark:border-blue-800" />
                              <Input value={suggestion.category} onChange={(e) => updateAiSuggestion(index, { category: e.target.value })} aria-label="Category" className="h-8 text-xs border-blue-200 dark:border-blue-800" />
                              <Input type="number" min={0} max={100} value={suggestion.recommended_weight} onChange={(e) => updateAiSuggestion(index, { recommended_weight: Number(e.target.value) })} aria-label="Weight" className="h-8 text-xs border-blue-200 dark:border-blue-800" />
                            </div>
                            {(suggestion.description || suggestion.why_it_matters) && (
                              <p className="text-xs text-blue-700 dark:text-blue-300">
                                {suggestion.description || suggestion.why_it_matters}
                              </p>
                            )}
                            <div className="flex justify-end gap-1.5">
                              <Button size="sm" variant="outline" className="h-7 text-xs px-2" disabled={aiBusy} onClick={() => handleAcceptSuggestion(index)}>Accept</Button>
                              <Button size="sm" variant="ghost" className="h-7 text-xs px-2" disabled={aiBusy} onClick={() => handleRejectSuggestion(index)}>Reject</Button>
                            </div>
                          </div>
                        )),
                      )}
                  </div>
                </div>
              ))}

              {/* ── AI / Custom section in Step 1 ── */}
              <div className="border-t pt-4 space-y-3">
                {!aiStatus?.enabled && (
                  <Alert><AlertDescription>AI assistance is unavailable ({aiStatus?.reason ?? "disabled"}).</AlertDescription></Alert>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" onClick={handleSuggestMetrics} disabled={!aiStatus?.enabled || aiBusy}>
                    {aiBusy ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" /> Suggesting...</> : <><Sparkles className="h-4 w-4 mr-1" /> Suggest metrics with AI</>}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => { resetAddForm(); setShowAddCustomForm(true); }}>
                    <Plus className="h-4 w-4 mr-1" /> Add Custom Metric
                  </Button>
                </div>
                {aiMessage && <p className="text-sm text-muted-foreground">{aiMessage}</p>}

                {showAddCustomForm && (
                  <div className="border rounded-lg p-3 space-y-2 bg-muted/30">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <div>
                        <Label htmlFor="new-custom-name" className="text-xs font-medium">Name *</Label>
                        <Input id="new-custom-name" value={newCustomName} onChange={(e) => setNewCustomName(e.target.value)} placeholder="e.g. Work-Life Balance" className="mt-1 h-8 text-xs" />
                      </div>
                      <div>
                        <Label htmlFor="new-custom-category" className="text-xs font-medium">Category *</Label>
                        <select id="new-custom-category" value={newCustomCategory} onChange={(e) => setNewCustomCategory(e.target.value)}
                          className="mt-1 flex h-8 w-full rounded-md border border-input bg-transparent px-2 py-1 text-xs shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
                          {FIT_CATEGORY_OPTIONS.map((opt) => (<option key={opt} value={opt}>{opt}</option>))}
                        </select>
                      </div>
                    </div>
                    <Input id="new-custom-desc" value={newCustomDesc} onChange={(e) => setNewCustomDesc(e.target.value)} placeholder="Optional description" className="h-8 text-xs" />
                    <div className="flex gap-2 justify-end">
                      <Button variant="outline" size="sm" onClick={resetAddForm}>Cancel</Button>
                      <Button size="sm" onClick={handleAddCustomMetric}><Plus className="h-4 w-4 mr-1" />Add Metric</Button>
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* ── Edit forms rendered inline within metrics ── */}
          {data.metrics.filter((m) => m.scope === "decision").map((metric) => (
            <div key={`inline-${metric.id}`}>
              {editingCustomId === metric.id && (
                <Card><CardContent className="pt-4">
                  <div className="border rounded-lg p-3 space-y-2 bg-muted/30">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <div>
                        <Label htmlFor={`edit-name-${metric.id}`} className="text-xs font-medium">Name</Label>
                        <Input id={`edit-name-${metric.id}`} value={editCustomName} onChange={(e) => setEditCustomName(e.target.value)} placeholder="Metric name" className="mt-1 h-8 text-xs" />
                      </div>
                      <div>
                        <Label htmlFor={`edit-cat-${metric.id}`} className="text-xs font-medium">Category</Label>
                        <select id={`edit-cat-${metric.id}`} value={editCustomCategory} onChange={(e) => setEditCustomCategory(e.target.value)}
                          className="mt-1 flex h-8 w-full rounded-md border border-input bg-transparent px-2 py-1 text-xs shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
                          {FIT_CATEGORY_OPTIONS.map((opt) => (<option key={opt} value={opt}>{opt}</option>))}
                        </select>
                      </div>
                    </div>
                    <Input id={`edit-desc-${metric.id}`} value={editCustomDesc} onChange={(e) => setEditCustomDesc(e.target.value)} placeholder="Optional description" className="h-8 text-xs" />
                    <div className="flex gap-2 justify-end">
                      <Button variant="outline" size="sm" onClick={cancelEditCustom}>Cancel</Button>
                      <Button size="sm" onClick={() => handleSaveEditCustom(metric.id)}><Check className="h-4 w-4 mr-1" />Save</Button>
                    </div>
                  </div>
                </CardContent></Card>
              )}
            </div>
          ))}

          {/* ── Step 1: Next button ── */}
          <div className="flex justify-end">
            <Button onClick={() => setStep(2)} size="lg">
              Next: Set Weights <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </div>
        </>
      )}

      {/* ════════════════════════════════════════
          STEP 2: Set Weights
          ════════════════════════════════════════ */}
      {step === 2 && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-xl">Weights</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* ── User context (shared for all AI calls) ── */}
              <AIContextField value={userContext} onChange={setUserContext} />

              <p className="text-sm text-muted-foreground">
                Every slider is a 0–100 fit score. Higher always means better fit.
                Adjust weights to set priority. Click{" "}
                <span className="font-semibold">KO</span> to set a minimum fit
                threshold — alternatives scoring below are eliminated from results.
              </p>

              {/* ── AI Optimize button ── */}
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" onClick={handleOptimizeWeights} disabled={!aiStatus?.enabled || aiBusy} size="sm">
                  {aiBusy ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" /> Optimizing...</> : <><Sparkles className="h-4 w-4 mr-1" /> Optimize weights with AI</>}
                </Button>
                {Object.keys(aiRecommendations).length > 0 && (
                  <Button variant="ghost" size="sm" onClick={clearAiRecommendations}>Clear all</Button>
                )}
                {!aiStatus?.enabled && (
                  <span className="text-xs text-muted-foreground">AI assistance is unavailable ({aiStatus?.reason ?? "disabled"}).</span>
                )}
              </div>
              {aiMessage && <p className="text-sm text-muted-foreground -mt-2">{aiMessage}</p>}

              {groupedMetrics.map(({ dimension, metrics }) => (
                <div key={dimension}>
                  <h3 className="font-semibold text-sm text-muted-foreground uppercase tracking-wider mb-3">{dimension}</h3>
                  <div className="space-y-4">
                    {metrics.map((metric) => {
                      const isCustom = metric.scope === "decision";
                      return (
                        <div key={metric.id}>
                          <div className="sm:grid sm:grid-cols-[14rem_1fr_auto] sm:gap-x-4 sm:items-center">
                            <div className="flex items-start gap-2 sm:w-auto mb-3 sm:mb-0">
                              <div className="flex flex-col min-w-0">
                                <div className="flex items-center gap-2">
                                  <Label className="font-medium leading-tight">{metric.name}</Label>
                                  {isCustom && <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">Custom</Badge>}
                                </div>
                                <span className="text-xs text-muted-foreground leading-tight mt-0.5">{metric.question ?? metric.description}</span>
                              </div>
                            </div>
                            <div className="mb-3 sm:mb-0">
                              <Slider value={[metricWeights[metric.id] ?? 50]} onValueChange={(v) => handleWeightChange(metric.id, v)} min={0} max={100} step={1} disabled={!includedMetrics[metric.id]} />
                            </div>
                            <div className="flex items-center gap-2 justify-self-end mb-3 sm:mb-0">
                              <span className="text-sm font-mono w-10 text-right tabular-nums shrink-0">{metricWeights[metric.id] ?? 50}</span>
                              <Button variant="outline" size="sm"
                                className={`shrink-0 h-7 px-2 text-xs ${koThresholds[metric.id] !== null ? "bg-red-50 border-red-300 text-red-600 dark:bg-red-950 dark:border-red-800 dark:text-red-400" : ""}`}
                                disabled={!includedMetrics[metric.id]} onClick={() => toggleKo(metric.id)}>KO</Button>
                            </div>
                          </div>
                          {includedMetrics[metric.id] && koThresholds[metric.id] !== null && (
                            <div className="sm:grid sm:grid-cols-[14rem_1fr_auto] sm:gap-x-4 sm:items-center sm:mt-2">
                              <div className="flex items-start gap-2"><div className="w-4 shrink-0" /><span className="text-xs text-red-500 font-medium leading-tight mt-0.5">KO min threshold</span></div>
                              <div><Slider value={[koThresholds[metric.id]!]} onValueChange={(v) => handleKoValueChange(metric.id, v[0])} min={0} max={100} step={1}
                                className="[&_[role=slider]]:bg-red-500 [&_[role=slider]]:border-red-500 [&_.bg-primary]:bg-red-500 [&_[role=track]]:bg-red-200 dark:[&_[role=track]]:bg-red-950" /></div>
                              <div className="flex items-center gap-2 justify-self-end"><span className="text-sm font-mono w-10 text-right tabular-nums text-red-600 dark:text-red-400">{koThresholds[metric.id]}</span></div>
                            </div>
                          )}
                          {/* ── AI recommendation inline per row ── */}
                          {aiRecommendations[metric.name] && (
                            <div className="mt-2 rounded border border-dashed border-blue-300 bg-blue-50/40 dark:bg-blue-950/20 dark:border-blue-800 p-2 flex flex-wrap items-center gap-2">
                              <span className="text-xs text-blue-700 dark:text-blue-300">
                                AI suggests weight <strong>{aiRecommendations[metric.name].recommended_weight}</strong>
                                {aiRecommendations[metric.name].rationale && <> — {aiRecommendations[metric.name].rationale}</>}
                              </span>
                              <div className="flex items-center gap-1 ml-auto">
                                <Button size="sm" variant="outline" className="h-6 text-xs px-2" onClick={() => applyAiRecommendation(metric.name, aiRecommendations[metric.name].recommended_weight)}>Apply</Button>
                                <Button size="sm" variant="ghost" className="h-6 text-xs px-2" onClick={() => rejectAiRecommendation(metric.name)}>Reject</Button>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* ── Step 2: Navigation ── */}
          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setStep(1)} size="lg">
              <ArrowLeft className="mr-2 h-4 w-4" /> Back: Set Criteria
            </Button>
            <Button onClick={handleAdvanceToScoring} size="lg">
              Next: Score <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </div>
        </>
      )}

      {/* ════════════════════════════════════════
          STEP 3: Score
          ════════════════════════════════════════ */}
      {step === 3 && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-xl">Score Your Alternatives</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* ── User context (shared for all AI calls) ── */}
              <AIContextField value={userContext} onChange={setUserContext} />

              <p className="text-sm text-muted-foreground">
                Every slider is a 0–100 fit score. Higher always means better fit.
              </p>

              {/* ── AI Evidence + Score Suggestions ── */}
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" onClick={handleDraftEvidence} disabled={!aiStatus?.enabled || aiBusy} size="sm">
                  {aiBusy ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" /> Working...</> : <><Sparkles className="h-4 w-4 mr-1" /> Draft evidence with AI</>}
                </Button>
                <Button variant="outline" onClick={handleSuggestScores} disabled={!aiStatus?.enabled || aiBusy} size="sm">
                  {aiBusy ? <><Loader2 className="h-4 w-4 mr-1 animate-spin" /> Working...</> : <><Sparkles className="h-4 w-4 mr-1" /> Suggest scores with AI</>}
                </Button>
                {!aiStatus?.enabled && (
                  <span className="text-xs text-muted-foreground">AI assistance is unavailable ({aiStatus?.reason ?? "disabled"}).</span>
                )}
              </div>
              {aiMessage && <p className="text-sm text-muted-foreground">{aiMessage}</p>}
              {scoresError && (
                <Alert variant="destructive">
                  <AlertDescription>{scoresError}</AlertDescription>
                </Alert>
              )}

              {/* ── Desktop: grid layout ── */}
              <div className="hidden md:block">
                <div className="rounded-lg border">
                  <div className="grid border-b bg-muted/50" style={{ gridTemplateColumns: `200px repeat(${data.activities.length}, minmax(180px, 1fr))` }}>
                    <div className="p-3 text-sm font-semibold text-muted-foreground">Criterion</div>
                    {data.activities.map((act) => (
                      <div key={act.id} className="p-3 text-sm font-semibold text-center">{act.name}</div>
                    ))}
                  </div>
                  {data.metrics.filter((m) => includedMetrics[m.id]).map((metric) => (
                    <div key={metric.id} className="grid border-b last:border-b-0 hover:bg-muted/30 transition-colors" style={{ gridTemplateColumns: `200px repeat(${data.activities.length}, minmax(180px, 1fr))` }}>
                      <div className="p-3 flex flex-col justify-center min-w-0">
                        <span className="text-sm font-medium truncate">{metric.name}</span>
                        {metric.description && <span className="text-xs text-muted-foreground truncate">{metric.description}</span>}
                      </div>
                      {data.activities.map((act) => {
                        const val = scoreValues[`${act.id}_${metric.id}`] ?? 0;
                        return (
                          <div key={`${act.id}_${metric.id}`} className="p-3">
                            <div className="flex items-center gap-3">
                              <Slider value={[val]} onValueChange={(v) => updateScore(act.id, metric.id, v[0])} min={0} max={100} step={1} className="flex-1" />
                              <div className="flex flex-col items-center shrink-0 w-14">
                                <span className={`text-sm font-mono tabular-nums ${scoreColor(val)}`}>{val}</span>
                                <span className="text-[10px] text-muted-foreground leading-tight">{scoreLabel(val)}</span>
                              </div>
                            </div>
                            {renderCellReview(act.id, metric.id)}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>

              {/* ── Mobile: stacked by alternative ── */}
              <div className="md:hidden space-y-6">
                {data.activities.map((act) => (
                  <Card key={act.id}>
                    <CardHeader><CardTitle className="text-lg">{act.name}</CardTitle></CardHeader>
                    <CardContent className="space-y-5">
                      {data.metrics.filter((m) => includedMetrics[m.id]).map((metric) => {
                        const val = scoreValues[`${act.id}_${metric.id}`] ?? 0;
                        return (
                          <div key={`${act.id}_${metric.id}`} className="space-y-2">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-medium truncate">{metric.name}</span>
                              <div className="flex items-center gap-1 shrink-0">
                                <span className={`text-sm font-mono tabular-nums ${scoreColor(val)}`}>{val}</span>
                                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-5">{scoreLabel(val)}</Badge>
                              </div>
                            </div>
                            <Slider value={[val]} onValueChange={(v) => updateScore(act.id, metric.id, v[0])} min={0} max={100} step={1} />
                            {renderCellReview(act.id, metric.id)}
                          </div>
                        );
                      })}
                    </CardContent>
                  </Card>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* ── Step 3: Navigation + Submit ── */}
          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setStep(2)} size="lg">
              <ArrowLeft className="mr-2 h-4 w-4" /> Back: Set Weights
            </Button>
            <Button onClick={handleFinalSubmit} disabled={submitting || scoresSubmitting} size="lg">
              {submitting || scoresSubmitting ? (
                <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Saving...</>
              ) : (
                <><CheckCheck className="mr-2 h-4 w-4" /> Submit Scores</>
              )}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
