import { HashRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import IdeaSubmit from "./pages/IdeaSubmit";
import StudioSession from "./pages/StudioSession";
import BrowserHome from "./pages/BrowserHome";
import RunProgress from "./pages/RunProgress";
import ReportView from "./pages/ReportView";
import Settings from "./pages/Settings";
import Sidebar from "./components/Sidebar";
import { listRuns } from "./lib/runsIndex";

function HomeRedirect() {
  // Dev autostart is used for desktop E2E verification when macOS UI automation
  // cannot click through the Tauri window. It must take precedence over the
  // existing run index; otherwise returning users land on BrowserHome and the
  // IdeaSubmit autostart hook never gets a chance to seed /browser/:runId.
  const autostartTopic = import.meta.env.DEV
    ? (import.meta.env.VITE_MUCHANIPO_AUTOSTART_TOPIC || "").trim()
    : "";
  const hasRun = listRuns().length > 0;
  return <Navigate to={autostartTopic ? "/studio" : hasRun ? "/browser" : "/studio"} replace />;
}

function BackButton() {
  const navigate = useNavigate();
  const location = useLocation();
  if (location.pathname === "/") return null;
  const goBack = () => {
    if (window.history.length > 1) navigate(-1);
    else navigate("/");
  };
  return (
    <header
      data-tauri-drag-region
      className="sticky top-0 z-30 flex items-center border-b border-white/5 bg-transparent pl-[88px] pr-4 py-2.5 backdrop-blur-xl supports-[backdrop-filter]:bg-black/20"
    >
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
    <HashRouter>
      <div className="flex h-screen">
        <Sidebar />
        <main className="app-workspace flex-1 overflow-y-auto">
          <BackButton />
          <Routes>
            <Route path="/" element={<HomeRedirect />} />
            <Route path="/studio" element={<IdeaSubmit />} />
            <Route path="/studio/:studioId" element={<StudioSession />} />
            <Route path="/browser" element={<BrowserHome />} />
            <Route path="/browser/:runId" element={<RunProgress />} />
            <Route path="/browser/:runId/report" element={<ReportView />} />
            <Route path="/run/:runId" element={<RunProgress />} />
            <Route path="/report/:runId" element={<ReportView />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}
