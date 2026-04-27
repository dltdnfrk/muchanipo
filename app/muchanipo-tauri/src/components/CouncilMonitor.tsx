import { useEffect, useMemo, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import type {
  BackendEvent,
  CouncilRoundEndEvent,
  CouncilRoundStartEvent,
  CouncilTokenEvent,
  LayerName,
} from "../lib/types";
import { cn } from "../lib/utils";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";

const LAYERS: LayerName[] = [
  "intent",
  "research",
  "evidence",
  "council",
  "synthesis",
  "critique",
  "refine",
  "verify",
  "report",
  "publish",
];

type LayerState = "idle" | "active" | "done";

interface PersonaStream {
  persona: string;
  text: string;
}

interface RoundState {
  round: number;
  layer: LayerName;
  status: "active" | "done";
  personas: PersonaStream[];
  summary?: string;
}

interface CouncilMonitorProps {
  events?: BackendEvent[];
  className?: string;
}

function applyCouncilEvent(rounds: RoundState[], event: BackendEvent): RoundState[] {
  if (event.type === "council_round_start") {
    return upsertRound(rounds, event, {
      status: "active",
      personas: event.personas.map((persona) => ({ persona, text: "" })),
    });
  }

  if (event.type === "council_token") {
    return appendToken(rounds, event);
  }

  if (event.type === "council_round_end") {
    return upsertRound(rounds, event, {
      status: "done",
      summary: event.summary,
    });
  }

  return rounds;
}

function upsertRound(
  rounds: RoundState[],
  event: CouncilRoundStartEvent | CouncilRoundEndEvent,
  patch: Partial<RoundState>,
): RoundState[] {
  const existing = rounds.find(
    (round) => round.round === event.round && round.layer === event.layer,
  );

  if (!existing) {
    return [
      ...rounds,
      {
        round: event.round,
        layer: event.layer,
        status: patch.status ?? "active",
        personas: patch.personas ?? [],
        summary: patch.summary,
      },
    ];
  }

  return rounds.map((round) =>
    round === existing ? { ...round, ...patch } : round,
  );
}

function appendToken(rounds: RoundState[], event: CouncilTokenEvent): RoundState[] {
  const targetIndex = rounds.findIndex((round) => round.round === event.round);
  if (targetIndex === -1) {
    return rounds;
  }

  return rounds.map((round, index) => {
    if (index !== targetIndex) {
      return round;
    }

    const hasPersona = round.personas.some(
      (persona) => persona.persona === event.persona,
    );
    const personas = hasPersona
      ? round.personas.map((persona) =>
          persona.persona === event.persona
            ? { ...persona, text: persona.text + event.delta }
            : persona,
        )
      : [...round.personas, { persona: event.persona, text: event.delta }];

    return { ...round, personas };
  });
}

export function CouncilMonitor({ events, className }: CouncilMonitorProps) {
  const [rounds, setRounds] = useState<RoundState[]>([]);

  useEffect(() => {
    if (!events) {
      return;
    }

    setRounds(events.reduce(applyCouncilEvent, [] as RoundState[]));
  }, [events]);

  useEffect(() => {
    if (events) {
      return;
    }

    let unlisten: (() => void) | undefined;
    void listen<BackendEvent>("backend_event", (event) => {
      const payload = event.payload as BackendEvent;
      setRounds((current) => applyCouncilEvent(current, payload));
    }).then((cleanup) => {
      unlisten = cleanup;
    });

    return () => {
      unlisten?.();
    };
  }, [events]);

  const latestRound = rounds.at(-1);
  const layerStates = useMemo(() => {
    const states = new Map<LayerName, LayerState>();
    for (const layer of LAYERS) {
      states.set(layer, "idle");
    }
    for (const round of rounds) {
      states.set(round.layer, round.status === "done" ? "done" : "active");
    }
    return states;
  }, [rounds]);

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Council Monitor</CardTitle>
        <CardDescription>
          {latestRound
            ? `Round ${latestRound.round} is on ${latestRound.layer}`
            : "Waiting for council events"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {LAYERS.map((layer, index) => {
            const state = layerStates.get(layer) ?? "idle";
            return (
              <div key={layer} className="space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium capitalize">{layer}</span>
                  <span className="text-muted-foreground">{index + 1}/10</span>
                </div>
                <div className="h-2 overflow-hidden rounded-sm bg-muted">
                  <div
                    className={cn(
                      "h-full transition-all",
                      state === "done" && "w-full bg-emerald-500",
                      state === "active" && "w-2/3 bg-amber-500",
                      state === "idle" && "w-0",
                    )}
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          {rounds.length === 0 ? (
            <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">
              Council output will stream here as personas speak.
            </div>
          ) : (
            rounds.map((round) => (
              <section
                key={`${round.round}-${round.layer}`}
                className="rounded-md border bg-background p-4"
              >
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold">
                      Round {round.round}: {round.layer}
                    </h3>
                    {round.summary ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {round.summary}
                      </p>
                    ) : null}
                  </div>
                  <span
                    className={cn(
                      "rounded-sm px-2 py-1 text-xs font-medium",
                      round.status === "done"
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-amber-100 text-amber-700",
                    )}
                  >
                    {round.status}
                  </span>
                </div>
                <div className="space-y-2">
                  {round.personas.map((persona) => (
                    <div key={persona.persona} className="rounded-sm bg-muted p-3">
                      <div className="mb-1 text-xs font-semibold">
                        {persona.persona}
                      </div>
                      <p className="whitespace-pre-wrap text-sm leading-6">
                        {persona.text || "Listening..."}
                      </p>
                    </div>
                  ))}
                </div>
              </section>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}
