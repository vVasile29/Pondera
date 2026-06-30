import { useState, useEffect } from "react";
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

ChartJS.register(
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
);

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

/** Reactive hook: returns true when the .dark class is present on <html>.
 *  Watches for class changes via MutationObserver so the chart updates
 *  immediately when the user toggles the theme. */
function useIsDark(): boolean {
  const [isDark, setIsDark] = useState(() => {
    if (typeof document === "undefined") return false;
    return document.documentElement.classList.contains("dark");
  });

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains("dark"));
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    return () => observer.disconnect();
  }, []);

  return isDark;
}

/** Return high-contrast theme colours based on the resolved dark-mode flag.
 *  Using explicit hsl() strings so canvas rendering is reliable. */
function themeColors(dark: boolean) {
  return {
    fg: dark ? "hsl(210, 40%, 98%)" : "hsl(222.2, 84%, 4.9%)",
    popover: dark ? "hsl(222.2, 84%, 4.9%)" : "hsl(0, 0%, 100%)",
    popoverFg: dark ? "hsl(210, 40%, 98%)" : "hsl(222.2, 84%, 4.9%)",
    border: dark ? "hsl(217.2, 32.6%, 17.5%)" : "hsl(214.3, 31.8%, 91.4%)",
    bg: dark ? "hsl(222.2, 84%, 4.9%)" : "hsl(0, 0%, 100%)",
  };
}

export default function RadarChart({ labels, datasets }: RadarChartProps) {
  const isDark = useIsDark();
  const theme = themeColors(isDark);

  const data = {
    labels,
    datasets: datasets.map((ds, i) => ({
      ...ds,
      backgroundColor: ds.backgroundColor || COLORS[i % COLORS.length].bg,
      borderColor: ds.borderColor || COLORS[i % COLORS.length].border,
      borderWidth: 2,
      pointRadius: 3,
      pointHoverRadius: 5,
    })),
  };

  const options = {
    responsive: true,
    maintainAspectRatio: true,
    scales: {
      r: {
        beginAtZero: true,
        max: 100,
        ticks: {
          stepSize: 20,
          color: theme.fg,
          backdropColor: theme.bg,
          font: { size: 11, weight: 600 as const },
          z: 100,
        },
        grid: { color: theme.border },
        angleLines: { color: theme.border },
        pointLabels: {
          color: theme.fg,
          font: { size: 13, weight: 600 as const },
        },
      },
    },
    plugins: {
      legend: {
        position: "bottom" as const,
        labels: {
          color: theme.fg,
          font: { size: 12, weight: 500 as const },
          usePointStyle: true,
          padding: 16,
        },
      },
      tooltip: {
        enabled: true,
        backgroundColor: theme.popover,
        titleColor: theme.popoverFg,
        bodyColor: theme.popoverFg,
        borderColor: theme.border,
        borderWidth: 1,
        padding: 10,
        cornerRadius: 8,
        boxPadding: 6,
        usePointStyle: true,
        callbacks: {
          labelColor: function (tooltipItem: any) {
            const dataset = tooltipItem.dataset;
            const color = dataset.borderColor || "rgba(0,0,0,0)";
            return {
              backgroundColor: color,
              borderColor: color,
            };
          },
        },
      },
    },
  };

  // key = isDark forces a full canvas remount when theme changes,
  // because Chart.js doesn't reliably re-apply scale/plugin colours in-place
  return <Radar key={String(isDark)} data={data} options={options} />;
}
