import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type {
  BackendEvent,
  InterviewQuestionEvent,
  UserAction,
} from "../lib/types";
import { backendEventName } from "../lib/types";
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringField(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function booleanField(value: unknown, fallback = false): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["1", "true", "yes"].includes(normalized)) return true;
    if (["0", "false", "no"].includes(normalized)) return false;
  }
  return fallback;
}

function normalizeOption(
  option: unknown,
  index: number,
): InterviewQuestionEvent["options"][number] | null {
  if (typeof option === "string") {
    const match = option.match(/^\s*([A-Za-z])[\).\s-]*(.*)$/);
    return {
      key: (match?.[1] || String.fromCharCode(65 + index)).toUpperCase(),
      label: (match?.[2] || option).trim(),
    };
  }
  if (!isRecord(option)) return null;
  const key = stringField(option.key, option.value, option.id) || String.fromCharCode(65 + index);
  const label = stringField(option.label, option.text, option.description, option.value, option.key);
  if (!label) return null;
  return { key, label };
}

function normalizeInterviewQuestionEvent(payload: BackendEvent): InterviewQuestionEvent {
  const data = isRecord(payload.data) ? payload.data : {};
  const rawOptions = Array.isArray(payload.options)
    ? payload.options
    : Array.isArray(data.options)
      ? data.options
      : [];
  return {
    ...payload,
    type: "interview_question",
    event: "interview_question",
    question_id: stringField(payload.question_id, payload.q_id, data.question_id, data.q_id),
    prompt: stringField(payload.prompt, payload.text, data.prompt, data.text),
    options: rawOptions.map(normalizeOption).filter((option): option is NonNullable<typeof option> => Boolean(option)),
    allow_other: booleanField(payload.allow_other ?? payload.allowOther ?? data.allow_other ?? data.allowOther, true),
  };
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
      if (backendEventName(payload) === "interview_question") {
        setStreamedQuestion(normalizeInterviewQuestionEvent(payload));
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
