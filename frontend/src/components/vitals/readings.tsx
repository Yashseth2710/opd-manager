"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { useSyncExternalStore } from "react";
import {
  saveUnit,
  savedUnit,
  shownReadings,
  type Level,
  type TemperatureUnit,
  type Vitals,
} from "@/lib/vitals";

const UNIT_CHANGED = "opd:temperature-unit";

function subscribe(onChange: () => void) {
  window.addEventListener(UNIT_CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(UNIT_CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The unit this browser reads temperatures in, shared by every reading on screen. */
export function useTemperatureUnit(): [TemperatureUnit, (unit: TemperatureUnit) => void] {
  const unit = useSyncExternalStore(subscribe, savedUnit, () => "F" as const);
  return [
    unit,
    (next) => {
      saveUnit(next);
      window.dispatchEvent(new Event(UNIT_CHANGED));
    },
  ];
}

export function Flag({ level, spoken = false }: { level: Level; spoken?: boolean }) {
  const Arrow = level === "high" ? ArrowUp : ArrowDown;
  return (
    <span className="inline-flex items-center gap-0.5 text-[var(--color-state-noshow)]">
      <Arrow aria-hidden className="size-3 shrink-0" strokeWidth={2.5} />
      <span className={spoken ? "text-[12px] font-medium" : "sr-only"}>
        {level === "high" ? "High" : "Low"}
      </span>
    </span>
  );
}

/**
 * The readings on one line, for a row in the queue. Anything out of range is
 * marked with an arrow, which a screen reader hears as high or low.
 */
export function ReadingsLine({
  vitals,
  spoken = false,
  className = "",
}: {
  vitals: Partial<Vitals> & Pick<Vitals, "flags">;
  /** Says high or low in words beside the arrow, where there is room. */
  spoken?: boolean;
  className?: string;
}) {
  const [unit] = useTemperatureUnit();
  const shown = shownReadings(vitals, unit).filter((item) => item.key !== "height");
  if (shown.length === 0) return null;
  return (
    <p
      className={`flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[13px] tabular ${className}`}
    >
      {shown.map((item) => (
        <span key={item.key} className="inline-flex items-baseline gap-1 whitespace-nowrap">
          <span className="text-[var(--text-subtle)]">{item.label}</span>
          <span
            className={
              item.flag
                ? "font-semibold text-[var(--color-state-noshow)]"
                : "text-[var(--text)]"
            }
          >
            {item.value}
          </span>
          {item.flag && <Flag level={item.flag} spoken={spoken} />}
        </span>
      ))}
    </p>
  );
}
