import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus, Pencil, Trash2, Loader2, RefreshCw } from "lucide-react";
import type {
  GroupedMetric,
  MetricsResponse,
  MetricCreatePayload,
  MetricUpdatePayload,
} from "@/types";

const CATEGORIES = [
  "Financial",
  "Quality",
  "Time",
  "Risk",
  "Experience",
  "Convenience",
];

type FormState = {
  name: string;
  category: string;
  description: string;
  higher_is_better: boolean;
};

const emptyForm = (): FormState => ({
  name: "",
  category: "Financial",
  description: "",
  higher_is_better: true,
});

export default function MetricsManager() {
  const [metrics, setMetrics] = useState<Record<string, GroupedMetric[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createForm, setCreateForm] = useState<FormState>(emptyForm());
  const [createError, setCreateError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<FormState>(emptyForm());

  const fetchMetrics = async () => {
    setLoading(true);
    setError(null);
    try {
      const res: MetricsResponse = await api.getMetrics();
      setMetrics(res.grouped_metrics);
    } catch (e: any) {
      setError(e.message || "Failed to load metrics");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
  }, []);

  const totalCount = Object.values(metrics).reduce(
    (sum, arr) => sum + arr.length,
    0,
  );

  const sortedDimensions = Object.entries(metrics).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  const resetCreateForm = () => {
    setCreateForm(emptyForm());
    setCreateError(null);
    setShowCreateForm(false);
  };

  const handleCreate = async () => {
    if (!createForm.name.trim()) {
      setCreateError("Name is required");
      return;
    }
    setCreateError(null);
    try {
      const payload: MetricCreatePayload = {
        name: createForm.name.trim(),
        category: createForm.category,
        description: createForm.description.trim() || undefined,
        higher_is_better: createForm.higher_is_better,
      };
      await api.createMetric(payload);
      resetCreateForm();
      await fetchMetrics();
    } catch (e: any) {
      setCreateError(e.message || "Failed to create metric");
    }
  };

  const startEditing = (m: GroupedMetric) => {
    setEditingId(m.id);
    setEditForm({
      name: m.name,
      category: m.category,
      description: m.description || "",
      higher_is_better: m.higher_is_better,
    });
  };

  const cancelEditing = () => {
    setEditingId(null);
  };

  const handleUpdate = async (metricId: number) => {
    if (!editForm.name.trim()) return;
    try {
      const payload: MetricUpdatePayload = {
        name: editForm.name.trim(),
        category: editForm.category,
        description: editForm.description.trim() || undefined,
        higher_is_better: editForm.higher_is_better,
      };
      await api.updateMetric(metricId, payload);
      setEditingId(null);
      await fetchMetrics();
    } catch (e: any) {
      alert(e.message || "Failed to update metric");
    }
  };

  const handleDelete = async (m: GroupedMetric) => {
    if (
      !window.confirm(
        `Delete "${m.name}"? This will remove all associated scores and weights.`,
      )
    )
      return;
    try {
      await api.deleteMetric(m.id);
      await fetchMetrics();
    } catch (e: any) {
      alert(e.message || "Failed to delete metric");
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto py-8 px-4">
        <div className="flex items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          Loading metrics...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto py-8 px-4">
        <Alert variant="destructive">
          <AlertTitle>Error</AlertTitle>
          <AlertDescription className="flex items-center gap-2">
            {error}
            <Button variant="outline" size="sm" onClick={fetchMetrics}>
              <RefreshCw className="h-4 w-4 mr-1" /> Retry
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold">Manage Metrics</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {totalCount} metric{totalCount !== 1 ? "s" : ""} across{" "}
            {sortedDimensions.length} dimension
            {sortedDimensions.length !== 1 ? "s" : ""}
          </p>
        </div>
        <Button
          onClick={() => setShowCreateForm(true)}
          disabled={showCreateForm}
        >
          <Plus className="h-4 w-4 mr-2" /> Add Metric
        </Button>
      </div>

      {showCreateForm && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-lg">New Metric</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {createError && (
              <Alert variant="destructive">
                <AlertDescription>{createError}</AlertDescription>
              </Alert>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="create-name">Name</Label>
                <Input
                  id="create-name"
                  placeholder="e.g. Cost"
                  value={createForm.name}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, name: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="create-category">Category</Label>
                <Select
                  value={createForm.category}
                  onValueChange={(val) =>
                    setCreateForm({ ...createForm, category: val })
                  }
                >
                  <SelectTrigger id="create-category">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((cat) => (
                      <SelectItem key={cat} value={cat}>
                        {cat}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="create-desc">Description (optional)</Label>
                <Input
                  id="create-desc"
                  placeholder="Brief description of the metric"
                  value={createForm.description}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      description: e.target.value,
                    })
                  }
                />
              </div>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="create-higher"
                  checked={createForm.higher_is_better}
                  onCheckedChange={(checked) =>
                    setCreateForm({
                      ...createForm,
                      higher_is_better: checked === true,
                    })
                  }
                />
                <Label htmlFor="create-higher">Higher is Better</Label>
              </div>
            </div>
            <div className="flex gap-2 pt-2">
              <Button onClick={handleCreate}>Save</Button>
              <Button variant="outline" onClick={resetCreateForm}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {totalCount === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            No metrics defined yet. Add one above.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {sortedDimensions.map(([dimension, dimMetrics]) => (
            <Card key={dimension}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-xl">{dimension}</CardTitle>
                  <Badge variant="secondary">{dimMetrics.length}</Badge>
                </div>
              </CardHeader>
              <CardContent className="divide-y">
                {dimMetrics.map((m) => (
                  <div key={m.id} className="py-3 first:pt-0 last:pb-0">
                    {editingId === m.id ? (
                      <div className="space-y-3">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <Label>Name</Label>
                            <Input
                              value={editForm.name}
                              onChange={(e) =>
                                setEditForm({
                                  ...editForm,
                                  name: e.target.value,
                                })
                              }
                            />
                          </div>
                          <div className="space-y-1">
                            <Label>Category</Label>
                            <Select
                              value={editForm.category}
                              onValueChange={(val) =>
                                setEditForm({ ...editForm, category: val })
                              }
                            >
                              <SelectTrigger>
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {CATEGORIES.map((cat) => (
                                  <SelectItem key={cat} value={cat}>
                                    {cat}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="space-y-1 md:col-span-2">
                            <Label>Description</Label>
                            <Input
                              value={editForm.description}
                              onChange={(e) =>
                                setEditForm({
                                  ...editForm,
                                  description: e.target.value,
                                })
                              }
                            />
                          </div>
                          <div className="flex items-center gap-2">
                            <Checkbox
                              id={`edit-higher-${m.id}`}
                              checked={editForm.higher_is_better}
                              onCheckedChange={(checked) =>
                                setEditForm({
                                  ...editForm,
                                  higher_is_better: checked === true,
                                })
                              }
                            />
                            <Label htmlFor={`edit-higher-${m.id}`}>
                              Higher is Better
                            </Label>
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <Button size="sm" onClick={() => handleUpdate(m.id)}>
                            Save
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={cancelEditing}
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-medium">{m.name}</span>
                            <Badge
                              variant={
                                m.higher_is_better ? "default" : "secondary"
                              }
                              className={
                                m.higher_is_better
                                  ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100"
                                  : "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100"
                              }
                            >
                              {m.higher_is_better
                                ? "\u2191 Higher better"
                                : "\u2193 Lower better"}
                            </Badge>
                          </div>
                          {m.description && (
                            <p className="text-sm text-muted-foreground mt-1">
                              {m.description}
                            </p>
                          )}
                          {m.children && m.children.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              {m.children.map((child) => (
                                <Badge
                                  key={child.id}
                                  variant="outline"
                                  className="text-xs"
                                >
                                  {child.name}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => startEditing(m)}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDelete(m)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
