import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";

interface ExportButtonProps {
  decisionId: number;
  mode: string;
}

export default function ExportButton({ decisionId, mode }: ExportButtonProps) {
  const exportPath =
    {
      diagnose: `/evaluate/${decisionId}/export-markdown`,
      screen: `/screen/${decisionId}/export-markdown`,
      rank: `/rank/${decisionId}/export-markdown`,
    }[mode] || `/decisions/${decisionId}/export-markdown`;

  return (
    <Button variant="outline" size="sm" asChild>
      <a href={exportPath} target="_blank" rel="noopener noreferrer">
        <Download className="mr-2 h-4 w-4" />
        Export Markdown
      </a>
    </Button>
  );
}
