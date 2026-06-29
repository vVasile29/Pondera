import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { SignificanceData } from "@/types";

export default function SignificanceBadge({ significance }: { significance: SignificanceData | null }) {
  if (!significance) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          Not enough data for statistical significance analysis (need at least 2 alternatives and 2 criteria).
        </CardContent>
      </Card>
    );
  }

  const colorClass = significance.p_value < 0.05
    ? "text-green-600 dark:text-green-400"
    : significance.p_value < 0.10
    ? "text-amber-600 dark:text-amber-400"
    : "text-muted-foreground";

  return (
    <Card>
      <CardContent className="p-4 space-y-2">
        <div className="flex items-center gap-2">
          <span className="font-medium">Statistical Significance</span>
          <Badge variant={significance.significant ? "default" : "secondary"}>
            {significance.label}
          </Badge>
        </div>
        <p className={`text-sm ${colorClass}`}>
          {significance.winner_name} ({significance.winner_avg}%) vs {significance.runner_name} ({significance.runner_avg}%)
        </p>
        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
          <span>p-value: {significance.p_value}</span>
          <span>t-statistic: {significance.t_statistic}</span>
          <span>df: {significance.df}</span>
          <span>Mean diff: {significance.mean_diff}</span>
        </div>
      </CardContent>
    </Card>
  );
}
