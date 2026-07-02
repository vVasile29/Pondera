import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { FIT_CATEGORY_OPTIONS } from "@/lib/ontology";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus, Pencil, Trash2, Loader2, RefreshCw } from "lucide-react";
import type { GroupedMetric, CreateMetricPayload, UpdateMetricPayload } from "@/types";

const CATEGORIES: string[] = [...FIT_CATEGORY_OPTIONS];

type FormState = {
  name: string;
  category: string;
  description: string;
  categoryOther: boolean;
};

const emptyForm = (): FormState => ({
  name: "",
  category: "Resource Fit",
  description: "",
  categoryOther: false,
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
  const [editError, setEditError] = useState<string | null>(null);

  const fetchMetrics = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getMetrics();
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
      const payload: CreateMetricPayload = {
        name: createForm.name.trim(),
        category: createForm.categoryOther
          ? createForm.category
          : createForm.category,
        description: createForm.description.trim() || undefined,
      };
      await api.createMetric(payload);
      resetCreateForm();
      await fetchMetrics();
    } catch (e: any) {
      setCreateError(e.message || "Failed to create metric");
    }
  };

  const startEditing = (m: GroupedMetric) => {
    const isOther = !CATEGORIES.includes(m.category);
    setEditingId(m.id);
    setEditForm({
      name: m.name,
      category: isOther ? m.category : m.category,
      description: m.description || "",
      categoryOther: isOther,
    });
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditError(null);
  };

  const handleUpdate = async (metricId: number) => {
    if (!editForm.name.trim()) return;
    setEditError(null);
    try {
      const payload: UpdateMetricPayload = {
        name: editForm.name.trim(),
        category: editForm.categoryOther
          ? editForm.category
          : editForm.category,
        description: editForm.description.trim() || undefined,
      };
      await api.updateMetric(metricId, payload);
      setEditingId(null);
      await fetchMetrics();
    } catch (e: any) {
      setEditError(e.message || "Failed to update metric");
    }
  };

  const handleDelete = async (m: GroupedMetric) => {
    if (
      !window.confirm(
        `Delete "${m.name}"?\n\nThis will permanently delete this metric and all associated scores and weights across ALL decisions. This cannot be undone.`,
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
                  placeholder="e.g. Custom Metric"
                  value={createForm.name}
                  onChange={(e) =>
                    setCreateForm({ ...createForm, name: e.target.value })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="create-category">Category</Label>
                {createForm.categoryOther ? (
                  <div className="flex gap-2">
                    <Input
                      placeholder="Custom category"
                      value={createForm.category}
                      onChange={(e) =>
                        setCreateForm({
                          ...createForm,
                          category: e.target.value,
                        })
                      }
                    />
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        setCreateForm({
                          ...createForm,
                          category: "Resource Fit",
                          categoryOther: false,
                        })
                      }
                    >
                      Back
                    </Button>
                  </div>
                ) : (
                  <Select
                    value={createForm.category}
                    onValueChange={(val) => {
                      if (val === "__other__") {
                        setCreateForm({
                          ...createForm,
                          category: "",
                          categoryOther: true,
                        });
                      } else {
                        setCreateForm({ ...createForm, category: val });
                      }
                    }}
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
                      <SelectItem value="__other__">Other…</SelectItem>
                    </SelectContent>
                  </Select>
                )}
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
                        {editError && (
                          <Alert variant="destructive">
                            <AlertDescription>{editError}</AlertDescription>
                          </Alert>
                        )}
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
                            {editForm.categoryOther ? (
                              <div className="flex gap-2">
                                <Input
                                  value={editForm.category}
                                  onChange={(e) =>
                                    setEditForm({
                                      ...editForm,
                                      category: e.target.value,
                                    })
                                  }
                                />
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() =>
                                    setEditForm({
                                      ...editForm,
                                      category: "Resource Fit",
                                      categoryOther: false,
                                    })
                                  }
                                >
                                  Back
                                </Button>
                              </div>
                            ) : (
                              <Select
                                value={editForm.category}
                                onValueChange={(val) => {
                                  if (val === "__other__") {
                                    setEditForm({
                                      ...editForm,
                                      category: "",
                                      categoryOther: true,
                                    });
                                  } else {
                                    setEditForm({
                                      ...editForm,
                                      category: val,
                                    });
                                  }
                                }}
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
                                  <SelectItem value="__other__">
                                    Other…
                                  </SelectItem>
                                </SelectContent>
                              </Select>
                            )}
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
                          </div>
                          {m.description && (
                            <p className="text-sm text-muted-foreground mt-1">
                              {m.description}
                            </p>
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
