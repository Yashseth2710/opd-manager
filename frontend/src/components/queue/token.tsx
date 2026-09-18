import type { QueueStatus } from "@/lib/queue";

const TONES: Record<QueueStatus, string> = {
  waiting: "var(--color-state-waiting)",
  called: "var(--color-state-waiting)",
  in_consultation: "var(--color-state-consulting)",
  completed: "var(--color-state-completed)",
  skipped: "var(--color-state-cancelled)",
  no_show: "var(--color-state-noshow)",
};

/**
 * The number a patient hears called. Set in the mono face so a column of
 * them lines up, and tinted by where that patient is.
 */
export function Token({
  number,
  status,
  size = "md",
  urgent = false,
}: {
  number: number;
  status: QueueStatus;
  size?: "md" | "lg";
  urgent?: boolean;
}) {
  const tone = urgent ? "var(--color-state-urgent)" : TONES[status];
  return (
    <span
      className={`inline-grid shrink-0 place-items-center rounded-[8px] border font-mono font-semibold tabular ${
        size === "lg" ? "h-14 min-w-14 px-2 text-[28px]" : "h-9 min-w-9 px-1.5 text-[16px]"
      }`}
      style={{
        borderColor: `color-mix(in srgb, ${tone} 55%, transparent)`,
        background: `color-mix(in srgb, ${tone} 14%, transparent)`,
      }}
    >
      <span className="sr-only">Token </span>
      {number}
    </span>
  );
}
