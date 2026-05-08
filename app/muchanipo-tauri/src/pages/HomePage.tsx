import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Textarea } from "../components/ui/textarea";

export default function HomePage() {
  const [topic, setTopic] = useState("");
  const navigate = useNavigate();

  const canSubmit = topic.trim().length > 0;

  const handleSubmit = () => {
    if (!canSubmit) return;
    navigate("/interview", { state: { topic: topic.trim() } });
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col items-center justify-center p-6">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>Muchanipo</CardTitle>
          <CardDescription>
            Studio에서 Goal과 Unknown을 정리하고 Browser에서 Evidence, Run, Report를 확인합니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Textarea
            placeholder="조사하고 싶은 주제를 입력하세요. 예: '신규 진입자가 기존 시장을 재편하는 패턴과 근거'"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            className="min-h-[200px]"
          />
        </CardContent>
        <CardFooter className="justify-end">
          <Button onClick={handleSubmit} disabled={!canSubmit} size="lg">
            인터뷰 시작
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
