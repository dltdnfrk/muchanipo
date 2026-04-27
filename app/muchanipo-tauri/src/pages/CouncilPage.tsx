import { useLocation, useNavigate } from "react-router-dom";
import { CouncilMonitor } from "../components/CouncilMonitor";
import { InterviewQuestion } from "../components/InterviewQuestion";
import { Button } from "../components/ui/button";

export default function CouncilPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const topic = (location.state as { topic?: string } | null)?.topic ?? "";

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-4xl flex-col p-6">
      <header className="mb-4 flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Council 진행 상황</h1>
          <p className="text-sm text-muted-foreground">
            토픽: <span className="font-medium text-foreground">{topic || "(없음)"}</span>
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => navigate("/")}>
            처음으로
          </Button>
          <Button onClick={() => navigate("/report", { state: { topic } })}>
            리포트 보기
          </Button>
        </div>
      </header>
      <div className="grid gap-4">
        <InterviewQuestion />
        <CouncilMonitor />
      </div>
    </div>
  );
}
