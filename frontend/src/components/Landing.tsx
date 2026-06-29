import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { Decision } from "@/types";
import {
  ArrowRight,
  Loader2,
  Trash2,
  Scale,
  BarChart3,
  Sparkles,
  Layers,
} from "lucide-react";

const modeBadgeClass: Record<string, string> = {
  choose:
    "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 border-blue-200 dark:border-blue-800",
  diagnose:
    "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200 border-green-200 dark:border-green-800",
  rank:
    "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 border-amber-200 dark:border-amber-800",
  screen:
    "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200 border-purple-200 dark:border-purple-800",
};

export default function Landing() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [decisionsLoading, setDecisionsLoading] = useState(true);

  useEffect(() => {
    api
      .getDecisions(10, 0)
      .then((res) => setDecisions(res.decisions))
      .catch(() => {})
      .finally(() => setDecisionsLoading(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.decide(query.trim());
      navigate(res.redirect_url);
    } catch (err: any) {
      setError(err.message || "Failed to process your question. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!window.confirm("Delete this decision and all its data?")) return;
    try {
      await api.deleteDecision(id);
      setDecisions((prev) => prev.filter((d) => d.id !== id));
    } catch {
      // silently fail
    }
  };

  const navigateToResult = (decision: Decision) => {
    if (decision.result_url) {
      navigate(decision.result_url);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "";
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="space-y-16">
      {/* ── Hero Section ── */}
      <section className="pt-8 md:pt-16 text-center space-y-6">
        <div className="space-y-2">
          <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            MCDA decision support
          </p>
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight">
            What's your decision today?
          </h1>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Turn a messy question into a weighted scoring matrix with universal criteria,
            clear tradeoffs, and a defensible winner.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="max-w-xl mx-auto space-y-3">
          <div className="flex gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='e.g. "Should I buy a house or an apartment?" or "Rank Python, Java, Go" or "How good is a Tesla for commuting?"'
              className="flex-1 h-12 text-base"
              aria-label="Decision question"
              disabled={loading}
            />
            <Button type="submit" size="lg" disabled={loading || !query.trim()}>
              {loading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <>
                  Start analysis <ArrowRight className="ml-2 h-4 w-4" />
                </>
              )}
            </Button>
          </div>
          {error && (
            <p className="text-sm text-destructive text-left">{error}</p>
          )}
          <p className="text-xs text-muted-foreground">
            No account required. Review extracted alternatives and criteria before scoring.
          </p>
        </form>
      </section>

      {/* ── Credibility Band ── */}
      <section className="flex justify-center gap-8 md:gap-16 text-center">
        <div>
          <p className="text-2xl font-bold">12</p>
          <p className="text-sm text-muted-foreground">universal metrics</p>
        </div>
        <div>
          <p className="text-2xl font-bold">6</p>
          <p className="text-sm text-muted-foreground">value dimensions</p>
        </div>
        <div>
          <p className="text-2xl font-bold">0–100</p>
          <p className="text-sm text-muted-foreground">weighted scoring</p>
        </div>
      </section>

      {/* ── How It Works ── */}
      <section className="space-y-6">
        <div className="text-center space-y-2">
          <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            How it works
          </p>
          <h2 className="text-3xl font-bold">From question to ranked result in minutes</h2>
          <p className="text-muted-foreground max-w-xl mx-auto">
            Use Pondera to structure judgment, not replace it. You stay in control of
            criteria, weights, alternatives, and scores.
          </p>
        </div>
        <div className="grid gap-6 md:grid-cols-3">
          <Card>
            <CardContent className="pt-6 space-y-2">
              <span className="text-3xl font-bold text-primary">01</span>
              <h3 className="font-semibold text-lg">Parse the prompt</h3>
              <p className="text-sm text-muted-foreground">
                Extract alternatives from &ldquo;or&rdquo;, &ldquo;vs&rdquo;, lists, or
                single-subject evaluations.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 space-y-2">
              <span className="text-3xl font-bold text-primary">02</span>
              <h3 className="font-semibold text-lg">Review criteria</h3>
              <p className="text-sm text-muted-foreground">
                Select universal MCDA metrics and tune weights before committing to a
                scoring model.
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 space-y-2">
              <span className="text-3xl font-bold text-primary">03</span>
              <h3 className="font-semibold text-lg">Score tradeoffs</h3>
              <p className="text-sm text-muted-foreground">
                Rate each option on a consistent 0–100 scale and let weighted-sum scoring
                do the math.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* ── MCDA Methodology ── */}
      <section className="grid gap-8 md:grid-cols-2 items-center">
        <div className="space-y-4">
          <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            Decision science
          </p>
          <h2 className="text-3xl font-bold">Built around Multi-Criteria Decision Analysis</h2>
          <p className="text-muted-foreground">
            Pondera is grounded in Multi-Criteria Decision Analysis principles, including
            weighted-sum scoring and Value-Focused Thinking&ndash;style attention to explicit
            values. It turns preferences into inspectable criteria, weights, and 0–100 scores
            rather than presenting a black-box answer.
          </p>
          <p className="text-muted-foreground">
            Its six global value dimensions&mdash;Financial, Quality, Time, Risk, Experience, and
            Convenience&mdash;are inspired by broad MCDA frameworks such as Keeney&rsquo;s
            Value-Focused Thinking and Belton &amp; Stewart&rsquo;s MCDA work. They provide a
            reusable starting ontology while leaving final judgment with you.
          </p>
        </div>
        <Card>
          <CardContent className="pt-6">
            <h3 className="font-semibold text-lg mb-4">Universal criteria framework</h3>
            <div className="flex flex-wrap gap-2">
              {["Financial", "Quality", "Time", "Risk", "Experience", "Convenience"].map(
                (dim) => (
                  <Badge key={dim} variant="secondary" className="text-sm px-3 py-1">
                    {dim}
                  </Badge>
                )
              )}
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── Use Cases ── */}
      <section className="text-center space-y-4">
        <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
          Use cases
        </p>
        <h2 className="text-3xl font-bold">One unified decision flow</h2>
        <p className="text-muted-foreground max-w-xl mx-auto">
          Describe your decision naturally. Pondera automatically detects comparisons,
          rankings, or single-option evaluations from your prompt &mdash; no mode selection
          needed.
        </p>
        <div className="flex justify-center gap-4 pt-2">
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <Scale className="h-4 w-4" /> Compare
          </div>
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <BarChart3 className="h-4 w-4" /> Rank
          </div>
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <Sparkles className="h-4 w-4" /> Diagnose
          </div>
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <Layers className="h-4 w-4" /> Screen
          </div>
        </div>
      </section>

      {/* ── Recent Decisions ── */}
      <section className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold">Recent Decisions</h2>
        </div>

        {decisionsLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : decisions.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center space-y-2">
              <p className="text-muted-foreground">
                No decisions yet. Enter a question above to get started.
              </p>
              <p className="text-sm text-muted-foreground">
                Try: &ldquo;Should I buy a house or an apartment?&rdquo; or
                &ldquo;Which job offer should I take?&rdquo;
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {decisions.map((decision) => (
              <Card
                key={decision.id}
                className="cursor-pointer hover:shadow-md transition-shadow"
                onClick={() => navigateToResult(decision)}
              >
                <CardContent className="pt-6">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0 space-y-2">
                      <p className="font-semibold line-clamp-2">{decision.query}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatDate(decision.created_at)}
                      </p>
                      <div className="flex flex-wrap gap-1">
                        <Badge
                          className={
                            modeBadgeClass[decision.mode] || modeBadgeClass.choose
                          }
                        >
                          {decision.mode}
                        </Badge>
                        {decision.category && (
                          <Badge variant="outline">{decision.category}</Badge>
                        )}
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="shrink-0 text-muted-foreground hover:text-destructive"
                      onClick={(e) => handleDelete(decision.id, e)}
                      title="Delete decision"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
