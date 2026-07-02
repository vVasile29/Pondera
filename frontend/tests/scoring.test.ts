import {
  filterResultsToSurvivors,
  pythonRound,
  recomputeFitScores,
} from "../src/lib/scoring.js";
import { METRICS_MANAGER_CATEGORY_OPTIONS } from "../src/lib/ontology.js";
import type { Activity, FilterResult, FitResult, ScoreRow } from "../src/types/index.js";

function assertEqual<T>(actual: T, expected: T) {
  if (actual !== expected) {
    throw new Error(`Expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function assertDeepEqual(actual: unknown, expected: unknown) {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);
  if (actualJson !== expectedJson) {
    throw new Error(`Expected ${expectedJson}, got ${actualJson}`);
  }
}

const activities: Activity[] = [
  { id: 1, name: "Alpha" },
  { id: 2, name: "Beta" },
];

function names(results: FitResult[]) {
  return results.map((r) => r.activity_name);
}

{
  const rows: ScoreRow[] = [
    {
      metric_id: 10,
      metric_name: "Affordability",
      metric_desc: "",
      weight: 100,
      scores: { 1: 80, 2: 20 },
    },
  ];

  const results = recomputeFitScores(activities, rows, {});
  assertDeepEqual(names(results), ["Alpha", "Beta"]);
  assertEqual(results[0].fit_score, 0.8);
  assertEqual(results[1].fit_score, 0.2);
}

{
  const rows: ScoreRow[] = [
    {
      metric_id: 10,
      metric_name: "Affordability",
      metric_desc: "",
      weight: 50,
      scores: { 1: 30, 2: 70 },
    },
    {
      metric_id: 11,
      metric_name: "Quality",
      metric_desc: "",
      weight: 50,
      scores: { 1: 80, 2: 60 },
    },
  ];

  const base = recomputeFitScores(activities, rows, {});
  const restored = recomputeFitScores(
    activities,
    rows,
    { Affordability: 50, Quality: 50 },
  );
  assertDeepEqual(restored, base);
}

{
  const rows: ScoreRow[] = [
    {
      metric_id: 10,
      metric_name: "Affordability",
      metric_desc: "",
      weight: 100,
      scores: { 1: 80, 2: 10 },
    },
    {
      metric_id: 11,
      metric_name: "Quality",
      metric_desc: "",
      weight: 100,
      scores: { 1: 10, 2: 90 },
    },
  ];

  const results = recomputeFitScores(
    activities,
    rows,
    { Affordability: 100, Quality: 100 },
  );
  const alpha = results.find((r) => r.activity_id === 1)!;
  const beta = results.find((r) => r.activity_id === 2)!;
  assertDeepEqual(alpha.weighted_scores.map((s) => s.metric_id), [10, 11]);
  assertDeepEqual(beta.weighted_scores.map((s) => s.metric_id), [10, 11]);
  assertEqual(alpha.fit_score, 0.45);
  assertEqual(beta.fit_score, 0.5);
}

{
  assertEqual(pythonRound(0.81245, 4), 0.8124);
  assertEqual(pythonRound(0.81255, 4), 0.8126);

  const rows: ScoreRow[] = [
    {
      metric_id: 11,
      metric_name: "Quality",
      metric_desc: "",
      weight: 100,
      scores: { 1: 81.245, 2: 81.244 },
    },
  ];
  const results = recomputeFitScores(activities, rows, {});
  assertEqual(results[0].fit_score, 0.8124);
}

{
  const allResults: FitResult[] = [
    {
      activity_id: 1,
      activity_name: "Alpha",
      fit_score: 0.8,
      fit_pct: 80,
      weighted_scores: [],
    },
    {
      activity_id: 2,
      activity_name: "Beta",
      fit_score: 0.7,
      fit_pct: 70,
      weighted_scores: [],
    },
  ];
  const filterResult: FilterResult = {
    passed: [],
    failed: [
      { activity_id: 1, activity_name: "Alpha", reasons: ["Affordability fails"] },
      { activity_id: 2, activity_name: "Beta", reasons: ["Affordability fails"] },
    ],
    all_passed: false,
    survivor_results: [],
  };

  assertDeepEqual(filterResultsToSurvivors(allResults, filterResult), []);
  assertDeepEqual(filterResultsToSurvivors(allResults, null), allResults);
}

{
  assertDeepEqual(METRICS_MANAGER_CATEGORY_OPTIONS, [
    "Resource Fit",
    "Objective Fit",
    "Time Fit",
    "Assurance Fit",
    "People Fit",
    "Practical Fit",
    "Other…",
  ]);
}

console.log("frontend scoring tests passed");
