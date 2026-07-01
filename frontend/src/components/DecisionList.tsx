import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Trash2, ExternalLink } from "lucide-react";
import type { Decision, DecisionListResponse } from "@/types";

const MODE_COLORS: Record<string, string> = {
  choose: "bg-blue-500",
  diagnose: "bg-green-500",
  rank: "bg-amber-500",
};

export default function DecisionList() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .getDecisions()
      .then((res: DecisionListResponse) => setDecisions(res.decisions))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this decision?")) return;
    try {
      await api.deleteDecision(id);
      setDecisions((prev) => prev.filter((d) => d.id !== id));
    } catch (e: any) {
      alert(e.message);
    }
  };

  const modeUrl = (d: Decision) => `/decisions/${d.id}/result`;

  if (loading) return <div className="p-8 text-center">Loading...</div>;

  return (
    <div className="container mx-auto py-8 px-4">
      <h1 className="text-3xl font-bold mb-6">Saved Decisions</h1>
      {decisions.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            No decisions yet. Start by asking a question on the home page.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {decisions.map((d) => (
            <Card
              key={d.id}
              className="cursor-pointer hover:border-primary/50 transition-colors"
            >
              <CardContent className="p-4 flex items-center justify-between">
                <div className="flex-1" onClick={() => navigate(modeUrl(d))}>
                  <div className="flex items-center gap-2 mb-1">
                    <Badge className={MODE_COLORS[d.mode || "choose"]}>
                      {d.mode || "choose"}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {d.created_at
                        ? new Date(d.created_at).toLocaleDateString()
                        : ""}
                    </span>
                  </div>
                  <p className="font-medium">{d.query}</p>
                  {d.category && (
                    <p className="text-sm text-muted-foreground">
                      {d.category}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => navigate(modeUrl(d))}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleDelete(d.id)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
