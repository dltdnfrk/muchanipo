import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import IdeaSubmit from "./pages/IdeaSubmit";
import RunProgress from "./pages/RunProgress";
import ReportView from "./pages/ReportView";
import Settings from "./pages/Settings";

function NavHeader() {
  const location = useLocation();
  const hideOn = ["/"];
  if (hideOn.includes(location.pathname)) return null;

  return (
    <header className="fixed left-0 right-0 top-0 z-50 flex items-center justify-between border-b border-[#2A2833] bg-[#15141B]/90 px-4 py-2 backdrop-blur">
      <Link to="/" className="text-sm font-bold text-[#E8E0D0]">
        Muchanipo
      </Link>
      <Link
        to="/settings"
        className="rounded-md p-1.5 text-[#8A8599] transition hover:bg-[#2A2833] hover:text-[#FFB347]"
        title="설정"
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </Link>
    </header>
  );
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <NavHeader />
      <div className="pt-0">{children}</div>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<IdeaSubmit />} />
          <Route path="/run/:runId" element={<RunProgress />} />
          <Route path="/report/:runId" element={<ReportView />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
