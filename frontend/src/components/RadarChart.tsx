import {
  Chart as ChartJS,
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from "chart.js";
import { Radar } from "react-chartjs-2";

ChartJS.register(RadialLinearScale, PointElement, LineElement, Filler, Tooltip, Legend);

interface RadarChartProps {
  labels: string[];
  datasets: {
    label: string;
    data: number[];
    backgroundColor?: string;
    borderColor?: string;
  }[];
}

const COLORS = [
  { bg: "rgba(59, 130, 246, 0.2)", border: "rgb(59, 130, 246)" },
  { bg: "rgba(239, 68, 68, 0.2)", border: "rgb(239, 68, 68)" },
  { bg: "rgba(34, 197, 94, 0.2)", border: "rgb(34, 197, 94)" },
  { bg: "rgba(234, 179, 8, 0.2)", border: "rgb(234, 179, 8)" },
  { bg: "rgba(168, 85, 247, 0.2)", border: "rgb(168, 85, 247)" },
];

export default function RadarChart({ labels, datasets }: RadarChartProps) {
  const data = {
    labels,
    datasets: datasets.map((ds, i) => ({
      ...ds,
      backgroundColor: ds.backgroundColor || COLORS[i % COLORS.length].bg,
      borderColor: ds.borderColor || COLORS[i % COLORS.length].border,
      borderWidth: 2,
      pointRadius: 3,
    })),
  };

  const options = {
    responsive: true,
    maintainAspectRatio: true,
    scales: {
      r: {
        beginAtZero: true,
        max: 100,
        ticks: { stepSize: 20 },
        grid: { color: "hsl(var(--border))" },
        angleLines: { color: "hsl(var(--border))" },
        pointLabels: { color: "hsl(var(--foreground))" },
      },
    },
    plugins: {
      legend: {
        position: "bottom" as const,
        labels: { color: "hsl(var(--foreground))" },
      },
    },
  };

  return <Radar data={data} options={options} />;
}
