import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { api } from "@/lib/api";
import type { ThresholdCriterion, FilterResult } from "@/types";

interface ThresholdPanelProps {
  decisionId: number;
  thresholdCriteria: ThresholdCriterion[];
  filterResult: FilterResult | null;
  onUpdate: () => void;
}

export default function ThresholdPanel({
  decisionId,
  thresholdCriteria,
  filterResult,
  onUpdate,
}: ThresholdPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [operators, setOperators] = useState<Record<number, string>>(
    Object.fromEntries(
      thresholdCriteria.map((t) => [t.id, String(t.operator)]),
    ),
  );
  const [values, setValues] = useState<Record<number, string>>(
    Object.fromEntries(thresholdCriteria.map((t) => [t.id, String(t.value)])),
  );
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  if (thresholdCriteria.length === 0) return null;

  const handleApply = async () => {
    setError(null);
    setApplying(true);
    try {
      const thresholds = thresholdCriteria.map((t) => ({
        metric_id: t.id,
        operator: operators[t.id] || "<=",
        value: parseFloat(values[t.id] || "0"),
      }));
      await api.applyThresholds(decisionId, thresholds);
      onUpdate();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setApplying(false);
    }
  };

  const handleClear = async () => {
    setError(null);
    setApplying(true);
    try {
      await api.clearThresholds(decisionId);
      onUpdate();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setApplying(false);
    }
  };

  return (
    <Card>
      <CardHeader className="cursor-pointer" onClick={() => setIsOpen(!isOpen)}>
        <CardTitle className="text-lg flex items-center gap-2">
          Filter by Thresholds
          {filterResult && (
            <Badge
              variant={filterResult.all_passed ? "secondary" : "destructive"}
            >
              Filtered
            </Badge>
          )}
          <span className="ml-auto">{isOpen ? "▲" : "▼"}</span>
        </CardTitle>
      </CardHeader>
      {isOpen && (
        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {thresholdCriteria.map((tc) => (
            <div key={tc.id} className="flex items-center gap-2">
              <span className="w-32 text-sm font-medium">{tc.name}</span>
              <Select
                value={operators[tc.id] || "<="}
                onValueChange={(v) =>
                  setOperators((prev) => ({ ...prev, [tc.id]: v }))
                }
              >
                <SelectTrigger className="w-20">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="<=">≤</SelectItem>
                  <SelectItem value=">=">≥</SelectItem>
                  <SelectItem value="<">&lt;</SelectItem>
                  <SelectItem value=">">&gt;</SelectItem>
                </SelectContent>
              </Select>
              <Input
                type="number"
                min={0}
                max={100}
                className="w-24"
                value={values[tc.id] || ""}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [tc.id]: e.target.value }))
                }
              />
            </div>
          ))}

          <div className="flex gap-2">
            <Button onClick={handleApply} disabled={applying}>
              {applying ? "Applying..." : "Apply"}
            </Button>
            <Button variant="outline" onClick={handleClear} disabled={applying}>
              Clear
            </Button>
          </div>

          {filterResult && (
            <div className="space-y-2">
              {filterResult.passed.map((p) => (
                <div key={p.activity_id} className="flex items-center gap-2">
                  <Badge variant="default" className="bg-green-600">
                    PASS
                  </Badge>
                  <span>{p.activity_name}</span>
                </div>
              ))}
              {filterResult.failed.map((f) => (
                <div key={f.activity_id} className="flex items-center gap-2">
                  <Badge variant="destructive">FAIL</Badge>
                  <span className="text-sm">{f.activity_name}</span>
                  <span className="text-xs text-muted-foreground">
                    {f.reasons.join("; ")}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
