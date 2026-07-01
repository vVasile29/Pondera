import { Routes, Route } from "react-router-dom";
import Layout from "@/components/Layout";
import Landing from "@/components/Landing";
import Review from "@/components/Review";
import Scoring from "@/components/Scoring";
import Results from "@/components/Results";
import DecisionList from "@/components/DecisionList";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/decisions" element={<DecisionList />} />
        <Route path="/decisions/:id/review" element={<Review />} />
        <Route path="/decisions/:id/score" element={<Scoring />} />
        <Route path="/decisions/:id/result" element={<Results />} />
      </Routes>
    </Layout>
  );
}
