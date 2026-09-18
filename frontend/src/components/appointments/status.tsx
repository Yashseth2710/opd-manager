import { STATUS_COLOURS, STATUS_LABELS, type Status } from "@/lib/appointments";

/**
 * One colour per state, used the same way everywhere it appears, and never
 * on its own: the dot is paired with the word, so the state reads the same
 * to somebody who cannot tell the colours apart.
 */
export function StatusBadge({ status, size = "sm" }: { status: Status; size?: "sm" | "md" }) {
  const colour = STATUS_COLOURS[status];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border font-medium whitespace-nowrap ${
        size === "md" ? "px-3 py-1 text-[13px]" : "px-2 py-0.5 text-[12px]"
      }`}
      style={{
        borderColor: `color-mix(in srgb, ${colour} 40%, transparent)`,
        background: `color-mix(in srgb, ${colour} 12%, transparent)`,
      }}
    >
      <span aria-hidden className="size-1.5 rounded-full" style={{ background: colour }} />
      {STATUS_LABELS[status]}
    </span>
  );
}
