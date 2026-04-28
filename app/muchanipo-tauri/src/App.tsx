import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import IdeaSubmit from "./pages/IdeaSubmit";
import RunProgress from "./pages/RunProgress";
import ReportView from "./pages/ReportView";
import Settings from "./pages/Settings";
import Sidebar from "./components/Sidebar";

function BackButton() {
  const navigate = useNavigate();
  const location = useLocation();
  if (location.pathname === "/") return null;
  const goBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate("/");
  };
  return (
    <header className="sticky top-0 z-30 flex items-center border-b border-white/5 bg-[#212121] px-4 py-2.5 backdrop-blur">
      <button
        onClick={goBack}
        className="flex h-7 w-7 items-center justify-center rounded-md text-tertiary transition hover:bg-white/5 hover:text-white"
        title="뒤로"
        aria-label="뒤로"
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
      </button>
    </header>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">
          <BackButton />
          <Routes>
            <Route path="/" element={<IdeaSubmit />} />
            <Route path="/run/:runId" element={<RunProgress />} />
            <Route path="/report/:runId" element={<ReportView />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
