import { useLocation, useNavigate } from "react-router-dom";
import { ReportViewer } from "../components/ReportViewer";
import { Button } from "../components/ui/button";

export default function ReportPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const topic = (location.state as { topic?: string } | null)?.topic ?? "";

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-4xl flex-col p-6">
      <header className="mb-4 flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold">REPORT.md</h1>
          <p className="text-sm text-muted-foreground">
            토픽: <span className="font-medium text-foreground">{topic || "(없음)"}</span>
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate("/")}>
          새 토픽 시작
        </Button>
      </header>
      <ReportViewer />
    </div>
  );
}
