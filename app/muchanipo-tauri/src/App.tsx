import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import IdeaSubmit from "./pages/IdeaSubmit";
import RunProgress from "./pages/RunProgress";
import ReportView from "./pages/ReportView";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<IdeaSubmit />} />
        <Route path="/run/:runId" element={<RunProgress />} />
        <Route path="/report/:runId" element={<ReportView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
