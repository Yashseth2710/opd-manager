/**
 * The product mark: a stethoscope bent into a loop with a cross inside it,
 * and the chest piece hanging off the bottom.
 *
 * Drawn rather than placed as an image, so it stays sharp at every size,
 * costs nothing to load, and takes its two colours from the same tokens as
 * everything else. It stands for the product, not for a clinic — the rail
 * shows whichever clinic you are signed in to, and that stays as it is.
 */
export function Mark({ className = "size-9" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden className={className}>
      <rect width="64" height="64" rx="15" fill="var(--color-marigold-400)" />
      {/* The tubing, and the lead running out to the chest piece. */}
      <path
        d="M30 13a12 12 0 0 1 12 12v11a12 12 0 0 1-12 12 12 12 0 0 1-12-12V25a12 12 0 0 1 12-12z"
        fill="none"
        stroke="var(--color-ink-900)"
        strokeWidth="7.5"
      />
      <path
        d="M40 45c2 3 4 3.5 5.5 4.5"
        fill="none"
        stroke="var(--color-ink-900)"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <circle cx="49" cy="52" r="4.5" fill="var(--color-ink-900)" />
      <g stroke="var(--color-ink-900)" strokeWidth="4" strokeLinecap="round">
        <path d="M30 26v9" />
        <path d="M25.5 30.5h9" />
      </g>
    </svg>
  );
}

/**
 * The mark with the name beside it, for the front door and anywhere else the
 * product introduces itself.
 */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={`flex w-fit items-center gap-3 ${className ?? ""}`}>
      <Mark />
      <span className="text-[15px] font-semibold tracking-tight text-white">OPD Manager</span>
    </span>
  );
}
