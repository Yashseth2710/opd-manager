"use client";

import { useQuery } from "@tanstack/react-query";
import { Expand, WifiOff } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Permitted } from "@/components/layout/permitted";
import { currentSession } from "@/lib/auth";
import { getQueue, POLL_MS, type Lane } from "@/lib/queue";

/**
 * The screen on the waiting-room wall.
 *
 * Read from four metres away by people who are anxious about missing their
 * turn, so it carries numbers and rooms and nothing else. No names: the
 * room is full of neighbours.
 */
export default function BoardPage() {
  return (
    <Permitted permission="appointment:read">
      <Suspense>
        <Board />
      </Suspense>
    </Permitted>
  );
}

function Board() {
  const params = useSearchParams();
  const only = params.get("doctor") ?? "";
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const queue = useQuery({
    queryKey: ["queue"],
    queryFn: () => getQueue(),
    refetchInterval: POLL_MS,
    // The wall screen is the one place nobody is watching the tab itself,
    // and a browser in a kiosk can report it as hidden.
    refetchIntervalInBackground: true,
    retry: 2,
  });

  const lanes = (queue.data?.lanes ?? []).filter(
    (lane) =>
      (!only || lane.doctor.id === only) &&
      (!lane.closed || lane.now_seeing || lane.called || lane.waiting.length > 0),
  );

  return (
    <div className="flex min-h-screen flex-col bg-[#0b1a2b] px-[clamp(16px,3vw,56px)] py-[clamp(16px,3vh,40px)] text-white">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <span className="grid size-[clamp(40px,4vw,64px)] shrink-0 place-items-center rounded-[10px] bg-[var(--color-marigold-400)] text-[clamp(20px,2vw,32px)] font-bold text-[var(--color-ink-900)]">
            {session.data?.organization?.name.trim().charAt(0).toUpperCase() ?? "O"}
          </span>
          <p className="min-w-0 truncate text-[clamp(20px,2.2vw,36px)] font-semibold tracking-tight">
            {session.data?.organization?.name ?? ""}
          </p>
        </div>
        <div className="flex items-center gap-5">
          {queue.isError && (
            <span className="inline-flex items-center gap-2 text-[clamp(14px,1.2vw,20px)] text-[var(--color-marigold-300)]">
              <WifiOff className="size-[1.1em]" />
              Reconnecting
            </span>
          )}
          <Clock />
          <FullScreen />
        </div>
      </header>

      <Announcer lanes={lanes} />

      {queue.isPending ? (
        <p className="m-auto text-[clamp(20px,2vw,32px)] text-[var(--color-ink-300)]">
          Loading the queue…
        </p>
      ) : queue.data?.unlinked || lanes.length === 0 ? (
        <p className="m-auto max-w-[30ch] text-center text-[clamp(24px,2.6vw,44px)] leading-tight text-[var(--color-ink-200)]">
          {queue.isError && !queue.data
            ? "The queue cannot be reached right now."
            : "Nobody is waiting. Please check in at the desk."}
        </p>
      ) : (
        <main
          className="mt-[clamp(20px,4vh,48px)] grid flex-1 content-start gap-[clamp(16px,2vw,32px)]"
          style={{
            gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, ${
              lanes.length > 2 ? "22rem" : "28rem"
            }), 1fr))`,
          }}
        >
          {lanes.map((lane) => (
            <Column key={lane.doctor.id} lane={lane} />
          ))}
        </main>
      )}

      <footer className="mt-[clamp(20px,4vh,48px)] text-[clamp(15px,1.3vw,22px)] text-[var(--color-ink-300)]">
        Please wait for your token number. Urgent cases may be seen first.
      </footer>
    </div>
  );
}

function Column({ lane }: { lane: Lane }) {
  const upcoming = lane.waiting.slice(0, 6);
  const more = lane.waiting.length - upcoming.length;

  return (
    <section
      aria-label={lane.doctor.display_name}
      className="flex flex-col gap-[clamp(14px,2vh,24px)] rounded-[16px] bg-white/[0.05] p-[clamp(16px,2vw,32px)] ring-1 ring-white/10"
    >
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="min-w-0 truncate text-[clamp(20px,2vw,34px)] font-semibold tracking-tight">
          {lane.doctor.display_name}
        </h2>
        {lane.doctor.room && (
          <p className="shrink-0 text-[clamp(18px,1.8vw,30px)] font-semibold text-[var(--color-marigold-300)]">
            Room {lane.doctor.room}
          </p>
        )}
      </div>

      {lane.called ? (
        <div
          key={lane.called.id}
          className="token-called flex items-center justify-between gap-4 rounded-[12px] bg-[var(--color-marigold-400)] px-[clamp(16px,2vw,28px)] py-[clamp(10px,1.5vh,18px)] text-[var(--color-ink-900)]"
        >
          <p className="text-[clamp(18px,1.8vw,30px)] leading-tight font-semibold">
            Please come in
          </p>
          <p className="font-mono text-[clamp(56px,7vw,120px)] leading-none font-semibold tabular">
            {lane.called.token}
          </p>
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-4">
        <p className="text-[clamp(16px,1.5vw,26px)] text-[var(--color-ink-200)]">
          {lane.now_seeing ? "With the doctor" : lane.closed ? lane.closed : "Nobody in yet"}
        </p>
        <p
          className={`font-mono leading-none font-semibold tabular ${
            lane.now_seeing
              ? "text-[clamp(48px,5.5vw,96px)] text-[#7fd0dc]"
              : "text-[clamp(32px,3vw,56px)] text-white/25"
          }`}
        >
          {lane.now_seeing ? lane.now_seeing.token : "–"}
        </p>
      </div>

      <div className="border-t border-white/10 pt-[clamp(12px,2vh,20px)]">
        <p className="mb-3 text-[clamp(15px,1.3vw,22px)] text-[var(--color-ink-300)]">
          {lane.waiting.length === 0
            ? "Nobody waiting"
            : lane.waiting.length === 1
              ? "Next"
              : `Next, ${lane.waiting.length} waiting`}
        </p>
        <ol className="flex flex-wrap gap-[clamp(8px,1vw,14px)]">
          {upcoming.map((entry) => (
            <li
              key={entry.id}
              className={`min-w-[2.2em] rounded-[10px] px-[0.35em] py-[0.1em] text-center font-mono text-[clamp(28px,3vw,52px)] font-semibold tabular ring-1 ${
                entry.priority === "urgent"
                  ? "bg-[#c04a42]/25 ring-[#e07a72]/60"
                  : "bg-white/[0.06] ring-white/15"
              }`}
            >
              <span className="sr-only">Token </span>
              {entry.token}
            </li>
          ))}
          {more > 0 && (
            <li className="self-center text-[clamp(18px,1.6vw,28px)] text-[var(--color-ink-300)]">
              and {more} more
            </li>
          )}
        </ol>
      </div>
    </section>
  );
}

/** Says each new call out loud to a screen reader, once. */
function Announcer({ lanes }: { lanes: Lane[] }) {
  const calls = lanes
    .filter((lane) => lane.called)
    .map(
      (lane) =>
        `Token ${lane.called!.token}, please go to ${
          lane.doctor.room ? `room ${lane.doctor.room}` : lane.doctor.display_name
        }.`,
    )
    .join(" ");
  return (
    <p aria-live="assertive" className="sr-only">
      {calls}
    </p>
  );
}

function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  // Started after the first paint, so the server's idea of the time never
  // has to agree with the wall's.
  useEffect(() => {
    const tick = () => setNow(new Date());
    const first = setTimeout(tick, 0);
    const timer = setInterval(tick, 15_000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, []);
  if (!now) return null;
  return (
    <p className="text-right leading-tight">
      <span className="block font-mono text-[clamp(22px,2.4vw,40px)] font-semibold tabular">
        {now.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}
      </span>
      <span className="block text-[clamp(13px,1.1vw,18px)] text-[var(--color-ink-300)]">
        {now.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
      </span>
    </p>
  );
}

function FullScreen() {
  const [full, setFull] = useState(false);
  useEffect(() => {
    const changed = () => setFull(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);
  if (full) return null;
  return (
    <button
      type="button"
      onClick={() => void document.documentElement.requestFullscreen?.().catch(() => undefined)}
      aria-label="Fill the screen"
      title="Fill the screen"
      className="rounded-[8px] p-2 text-[var(--color-ink-300)] ring-1 ring-white/15 transition-colors hover:bg-white/10 hover:text-white"
    >
      <Expand className="size-5" />
    </button>
  );
}
