import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Input } from "../components/ui/input";

type Choice = "A" | "B" | "C" | "D" | "OTHER";

const PLACEHOLDER_OPTIONS: { key: Exclude<Choice, "OTHER">; label: string }[] = [
  { key: "A", label: "기술 동향과 시장 흐름 위주의 broad survey" },
  { key: "B", label: "특정 제품/회사 사례를 깊게 파고드는 case study" },
  { key: "C", label: "내가 직접 적용할 수 있는 actionable playbook" },
  { key: "D", label: "역사적 맥락과 이론적 framework 정리" },
];

export default function InterviewPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const topic = (location.state as { topic?: string } | null)?.topic ?? "";

  const [selected, setSelected] = useState<Choice | null>(null);
  const [otherText, setOtherText] = useState("");

  const canContinue =
    selected !== null && (selected !== "OTHER" || otherText.trim().length > 0);

  const handleContinue = () => {
    if (!canContinue) return;
    navigate("/council", {
      state: {
        topic,
        answer: {
          selected,
          other_text: selected === "OTHER" ? otherText.trim() : undefined,
        },
      },
    });
  };

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col items-center justify-center p-6">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>인터뷰</CardTitle>
          <CardDescription>
            토픽: <span className="font-medium text-foreground">{topic || "(없음)"}</span>
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            어떤 형태의 결과물이 가장 도움이 될까요?
          </p>
          <div className="grid gap-2">
            {PLACEHOLDER_OPTIONS.map((opt) => (
              <Button
                key={opt.key}
                variant={selected === opt.key ? "default" : "outline"}
                className="justify-start text-left"
                onClick={() => setSelected(opt.key)}
              >
                <span className="font-mono text-xs">{opt.key}</span>
                <span className="flex-1">{opt.label}</span>
              </Button>
            ))}
            <Button
              variant={selected === "OTHER" ? "default" : "outline"}
              className="justify-start text-left"
              onClick={() => setSelected("OTHER")}
            >
              <span className="font-mono text-xs">Other</span>
              <span className="flex-1">직접 입력</span>
            </Button>
          </div>
          {selected === "OTHER" && (
            <Input
              autoFocus
              placeholder="원하는 형태를 직접 적어주세요"
              value={otherText}
              onChange={(e) => setOtherText(e.target.value)}
            />
          )}
        </CardContent>
        <CardFooter className="justify-between">
          <Button variant="ghost" onClick={() => navigate(-1)}>
            뒤로
          </Button>
          <Button onClick={handleContinue} disabled={!canContinue} size="lg">
            계속
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
