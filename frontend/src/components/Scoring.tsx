import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useDecision } from "@/hooks/useDecision";
import { useScoring } from "@/hooks/useScoring";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Loader2, ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import type { AIAvailability, EvidenceItem, ScoreDraft } from "@/types";

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
  const [aiStatus, setAiStatus] = useState<AIAvailability | null>(null);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [drafts, setDrafts] = useState<ScoreDraft[]>([]);
  const [selectedDraftIds, setSelectedDraftIds] = useState<number[]>([]);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMessage, setAiMessage] = useState<string | null>(null);
  const [manualEvidenceClaims, setManualEvidenceClaims] = useState<Record<string, string>>({});
  const [draftEditScores, setDraftEditScores] = useState<Record<number, number>>({});

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

  const refreshEvidenceDrafts = async () => {
    if (!decisionId) return;
    const [evidenceRes, draftsRes] = await Promise.all([
      api.getEvidence(decisionId),
      api.getScoreDrafts(decisionId),
    ]);
    setEvidence(evidenceRes.evidence);
    setDrafts(draftsRes.drafts);
  };

  useEffect(() => {
    if (!decisionId) return;
    api.getAIStatus().then(setAiStatus).catch(() => setAiStatus(null));
    refreshEvidenceDrafts().catch(() => undefined);
  }, [decisionId]);

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

  const handleDraftEvidence = async () => {
    setAiBusy(true);
    setAiMessage(null);
    try {
      const res = await api.draftEvidenceWithAI(decisionId, {});
      await refreshEvidenceDrafts();
      setAiMessage(`Drafted ${res.evidence_items.length} pending evidence item(s).`);
    } catch (err) {
      setAiMessage(err instanceof Error ? err.message : "AI evidence drafting failed");
    } finally {
      setAiBusy(false);
    }
  };

  const handleSuggestScores = async () => {
    setAiBusy(true);
    setAiMessage(null);
    try {
      const res = await api.suggestScoresWithAI(decisionId, { evidence_review_policy: "approved_and_pending" });
      await refreshEvidenceDrafts();
      setAiMessage(`Created ${res.score_drafts.length} pending score draft(s).`);
    } catch (err) {
      setAiMessage(err instanceof Error ? err.message : "AI score drafting failed");
    } finally {
      setAiBusy(false);
    }
  };

  const handleApplySelected = async () => {
    if (!selectedDraftIds.length) return;
    const res = await api.applyScoreDrafts(decisionId, selectedDraftIds);
    res.scores.forEach((score) => updateScore(score.activity_id, score.metric_id, score.score));
    setSelectedDraftIds([]);
    await refreshEvidenceDrafts();
  };

  const handleApplyDraft = async (draft: ScoreDraft) => {
    const res = await api.applyScoreDraft(decisionId, draft.id);
    updateScore(res.score.activity_id, res.score.metric_id, res.score.score);
    await refreshEvidenceDrafts();
  };

  const handleRejectDraft = async (draft: ScoreDraft) => {
    await api.rejectScoreDraft(decisionId, draft.id);
    setSelectedDraftIds((ids) => ids.filter((id) => id !== draft.id));
    await refreshEvidenceDrafts();
  };

  const handleApproveDraft = async (draft: ScoreDraft) => {
    await api.approveScoreDraft(decisionId, draft.id);
    await refreshEvidenceDrafts();
  };

  const handleEditDraft = async (draft: ScoreDraft) => {
    const score = draftEditScores[draft.id] ?? draft.effective_score;
    await api.updateScoreDraft(decisionId, draft.id, { human_adjusted_score: score });
    await refreshEvidenceDrafts();
  };

  const handleAddEvidence = async (activityId: number, metricId: number) => {
    const key = `${activityId}_${metricId}`;
    const claim = (manualEvidenceClaims[key] || "").trim();
    if (!claim) return;
    await api.createEvidence(decisionId, { activity_id: activityId, metric_id: metricId, claim });
    setManualEvidenceClaims((prev) => ({ ...prev, [key]: "" }));
    await refreshEvidenceDrafts();
  };

  const handleReviewEvidence = async (item: EvidenceItem, action: "approve" | "reject") => {
    if (action === "approve") await api.approveEvidence(decisionId, item.id);
    else await api.rejectEvidence(decisionId, item.id);
    await refreshEvidenceDrafts();
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
  const renderCellReview = (actId: number, metricId: number) => {
    const key = `${actId}_${metricId}`;
    const cellEvidence = evidence.filter((item) => (!item.activity_id || item.activity_id === actId) && (!item.metric_id || item.metric_id === metricId));
    const cellDrafts = drafts.filter((draft) => draft.activity_id === actId && draft.metric_id === metricId && draft.status !== "applied" && draft.status !== "rejected");

    return (
      <div className="mt-2 space-y-2 text-xs">
        <div className="flex gap-1">
          <Input
            value={manualEvidenceClaims[key] ?? ""}
            onChange={(e) => setManualEvidenceClaims((prev) => ({ ...prev, [key]: e.target.value }))}
            placeholder="Add evidence"
            className="h-7 text-xs"
          />
          <Button size="sm" variant="outline" onClick={() => handleAddEvidence(actId, metricId)}>Add</Button>
        </div>
        {cellEvidence.map((item) => (
          <div key={item.id} className="rounded border bg-muted/30 p-1 space-y-1">
            <div><Badge variant="outline" className="mr-1 text-[10px]">{item.review_status}</Badge>{item.claim}</div>
            {item.review_status === "pending" && (
              <div className="flex gap-1">
                <Button size="sm" variant="outline" onClick={() => handleReviewEvidence(item, "approve")}>Approve evidence</Button>
                <Button size="sm" variant="ghost" onClick={() => handleReviewEvidence(item, "reject")}>Reject</Button>
              </div>
            )}
          </div>
        ))}
        {cellDrafts.map((draft) => (
          <div key={draft.id} className="rounded border p-1 space-y-1">
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={selectedDraftIds.includes(draft.id)}
                onChange={(e) => setSelectedDraftIds((ids) => e.target.checked ? [...ids, draft.id] : ids.filter((id) => id !== draft.id))}
              />
              <span>Draft {Math.round(draft.effective_score)} ({draft.status})</span>
            </label>
            <div className="flex flex-wrap gap-1">
              <Input
                type="number"
                min={0}
                max={100}
                value={draftEditScores[draft.id] ?? draft.effective_score}
                onChange={(e) => setDraftEditScores((prev) => ({ ...prev, [draft.id]: Number(e.target.value) }))}
                className="h-7 w-20 text-xs"
                aria-label="Draft score"
              />
              <Button size="sm" variant="outline" onClick={() => handleEditDraft(draft)}>Edit</Button>
              <Button size="sm" variant="outline" onClick={() => handleApproveDraft(draft)}>Approve</Button>
              <Button size="sm" variant="outline" onClick={() => handleApplyDraft(draft)}>Apply</Button>
              <Button size="sm" variant="ghost" onClick={() => handleRejectDraft(draft)}>Reject</Button>
            </div>
          </div>
        ))}
      </div>
    );
  };

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

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">AI draft assistance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            AI-generated values are drafts until you approve or apply them.
          </p>
          {!aiStatus?.enabled && (
            <Alert>
              <AlertDescription>
                AI assistance is unavailable ({aiStatus?.reason ?? "disabled"}). Final scoring still works normally.
              </AlertDescription>
            </Alert>
          )}
          {aiMessage && <p className="text-sm text-muted-foreground">{aiMessage}</p>}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={handleDraftEvidence} disabled={!aiStatus?.enabled || aiBusy}>
              Draft evidence with AI
            </Button>
            <Button variant="outline" onClick={handleSuggestScores} disabled={!aiStatus?.enabled || aiBusy}>
              Suggest draft scores
            </Button>
            <Button onClick={handleApplySelected} disabled={!selectedDraftIds.length}>
              Apply selected drafts
            </Button>
          </div>
        </CardContent>
      </Card>

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
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium truncate">{metric.name}</span>
                  {metric.scope === "decision" && (
                    <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded shrink-0">
                      Custom
                    </span>
                  )}
                </div>
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
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-sm font-medium truncate">{metric.name}</span>
                        {metric.scope === "decision" && (
                          <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded shrink-0">
                            Custom
                          </span>
                        )}
                      </div>
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
                    {renderCellReview(act.id, metric.id)}
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
