import { Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import Landing from "@/components/Landing";
import Review from "@/components/Review";
import Scoring from "@/components/Scoring";
import Results from "@/components/Results";
import EvaluateReview from "@/components/EvaluateReview";
import EvaluateResult from "@/components/EvaluateResult";
import RankReview from "@/components/RankReview";
import ScreenResult from "@/components/ScreenResult";
import DecisionList from "@/components/DecisionList";
import MetricsManager from "@/components/MetricsManager";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/decisions" element={<DecisionList />} />
        <Route path="/decisions/:id/review" element={<Review />} />
        <Route path="/decisions/:id/score" element={<Scoring />} />
        <Route path="/decisions/:id/result" element={<Results />} />
        <Route path="/evaluate/:id/review" element={<EvaluateReview />} />
        <Route path="/evaluate/:id/result" element={<EvaluateResult />} />
        <Route path="/rank/:id/review" element={<RankReview />} />
        <Route path="/rank/:id/result" element={<Results />} />
        <Route path="/screen/:id/result" element={<ScreenResult />} />
        <Route path="/metrics" element={<MetricsManager />} />
      </Routes>
    </Layout>
  );
}
