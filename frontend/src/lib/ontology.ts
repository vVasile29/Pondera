export const FIT_CATEGORY_OPTIONS = [
  "Resource Fit",
  "Objective Fit",
  "Time Fit",
  "Assurance Fit",
  "People Fit",
  "Practical Fit",
] as const;

export const METRICS_MANAGER_CATEGORY_OPTIONS = [
  ...FIT_CATEGORY_OPTIONS,
  "Other…",
] as const;
