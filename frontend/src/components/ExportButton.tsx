import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";

interface ExportButtonProps {
  decisionId: number;
}

export default function ExportButton({ decisionId }: ExportButtonProps) {
  const exportPath = `/api/decisions/${decisionId}/export-markdown`;

  return (
    <Button variant="outline" size="sm" asChild>
      <a href={exportPath} target="_blank" rel="noopener noreferrer">
        <Download className="mr-2 h-4 w-4" />
        Export Markdown
      </a>
    </Button>
  );
}
