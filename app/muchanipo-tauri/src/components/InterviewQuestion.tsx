import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type {
  BackendEvent,
  InterviewQuestionEvent,
  UserAction,
} from "../lib/types";
import { Button } from "./ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Input } from "./ui/input";

interface InterviewQuestionProps {
  question?: InterviewQuestionEvent | null;
  sendAction?: (action: UserAction) => Promise<void>;
  className?: string;
}

async function defaultSendAction(action: UserAction) {
  await invoke("send_action", { action });
}

export function InterviewQuestion({
  question: controlledQuestion,
  sendAction = defaultSendAction,
  className,
}: InterviewQuestionProps) {
  const [streamedQuestion, setStreamedQuestion] =
    useState<InterviewQuestionEvent | null>(null);
  const [selected, setSelected] = useState<UserAction["selected"]>();
  const [otherText, setOtherText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const question = controlledQuestion ?? streamedQuestion;

  useEffect(() => {
    if (controlledQuestion !== undefined) {
      return;
    }

    let unlisten: (() => void) | undefined;
    void listen<BackendEvent>("backend_event", (event) => {
      const payload = event.payload as BackendEvent;
      if (payload.type === "interview_question") {
        setStreamedQuestion(payload);
        setSelected(undefined);
        setOtherText("");
        setError(null);
      }
    }).then((cleanup) => {
      unlisten = cleanup;
    });

    return () => {
      unlisten?.();
    };
  }, [controlledQuestion]);

  async function submitAnswer(choice: UserAction["selected"]) {
    if (!question || !choice) {
      return;
    }

    setPending(true);
    setError(null);
    try {
      await sendAction({
        type: "interview_answer",
        question_id: question.question_id,
        selected: choice,
        other_text: choice === "OTHER" ? otherText.trim() : undefined,
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPending(false);
    }
  }

  if (!question) {
    return (
      <Card className={className}>
        <CardHeader>
          <CardTitle>Interview</CardTitle>
          <CardDescription>Waiting for the next question.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const canSubmitOther = question.allow_other && otherText.trim().length > 0;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Interview</CardTitle>
        <CardDescription>{question.prompt}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2 sm:grid-cols-2">
          {question.options.map((option) => (
            <Button
              key={option.key}
              type="button"
              variant={selected === option.key ? "default" : "outline"}
              className="h-auto min-h-12 justify-start whitespace-normal py-3 text-left"
              disabled={pending}
              onClick={() => {
                setSelected(option.key);
                void submitAnswer(option.key);
              }}
            >
              <span className="font-semibold">{option.key}</span>
              <span>{option.label}</span>
            </Button>
          ))}
        </div>

        {question.allow_other ? (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              value={otherText}
              disabled={pending}
              placeholder="Other answer"
              onChange={(event) => {
                setOtherText(event.target.value);
                setSelected("OTHER");
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && canSubmitOther) {
                  void submitAnswer("OTHER");
                }
              }}
            />
            <Button
              type="button"
              variant={selected === "OTHER" ? "default" : "secondary"}
              disabled={pending || !canSubmitOther}
              onClick={() => void submitAnswer("OTHER")}
            >
              Send
            </Button>
          </div>
        ) : null}
      </CardContent>
      {error ? (
        <CardFooter>
          <p className="text-sm text-destructive">{error}</p>
        </CardFooter>
      ) : null}
    </Card>
  );
}
