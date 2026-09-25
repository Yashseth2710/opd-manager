"use client";

import { Check, Monitor, Moon, Sun } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { useSyncExternalStore } from "react";
import {
  applyTheme,
  CHANGED,
  chooseTheme,
  storedTheme,
  THEME_KEY,
  type Theme,
} from "@/lib/theme";

const CHOICES: { theme: Theme; label: string; hint: string; icon: typeof Sun }[] = [
  { theme: "light", label: "Light", hint: "Always light", icon: Sun },
  { theme: "dark", label: "Dark", hint: "Always dark", icon: Moon },
  { theme: "system", label: "System", hint: "Follow this device", icon: Monitor },
];

function subscribe(changed: () => void) {
  // Another tab choosing a theme changes this one too, so two windows on
  // one desk never disagree.
  const elsewhere = (event: StorageEvent) => {
    if (event.key !== THEME_KEY && event.key !== null) return;
    applyTheme(storedTheme());
    changed();
  };
  window.addEventListener(CHANGED, changed);
  window.addEventListener("storage", elsewhere);
  return () => {
    window.removeEventListener(CHANGED, changed);
    window.removeEventListener("storage", elsewhere);
  };
}

function useTheme(): Theme {
  return useSyncExternalStore(subscribe, storedTheme, () => "system");
}

/**
 * One button at the top of the rail, beside the bell, so it is in reach on
 * every page without scrolling. It shows the choice in force and opens the
 * three there are.
 */
export function ThemeMenu() {
  const current = useTheme();
  const shown = CHOICES.find((choice) => choice.theme === current) ?? CHOICES[2]!;
  const Icon = shown.icon;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label={`Theme: ${shown.hint.toLowerCase()}`}
        title="Light, dark or system theme"
        className="grid size-9 place-items-center rounded-[var(--radius-field)] text-[var(--rail-text)] transition-colors outline-none hover:bg-white/8 hover:text-white focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] data-[state=open]:bg-white/10 data-[state=open]:text-white"
      >
        <Icon className="size-[18px]" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="theme-menu z-50 min-w-[12rem] rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface-raised)] p-1 text-[var(--text)] shadow-[0_18px_40px_-12px_rgb(8_15_26/0.45)]"
        >
          <DropdownMenu.Label className="px-2.5 pt-1.5 pb-1 text-[12px] text-[var(--text-subtle)]">
            Theme
          </DropdownMenu.Label>
          <DropdownMenu.RadioGroup
            value={current}
            onValueChange={(value) => chooseTheme(value as Theme)}
          >
            {CHOICES.map(({ theme, label, hint, icon: ItemIcon }) => (
              <DropdownMenu.RadioItem
                key={theme}
                value={theme}
                className="flex cursor-default items-center gap-2.5 rounded-[var(--radius-field)] px-2.5 py-2 text-[14px] outline-none select-none data-[highlighted]:bg-[var(--surface-sunken)]"
              >
                <ItemIcon className="size-4 shrink-0 text-[var(--text-muted)]" />
                <span className="flex-1">
                  {label}
                  <span className="block text-[12px] text-[var(--text-subtle)]">{hint}</span>
                </span>
                <DropdownMenu.ItemIndicator>
                  <Check className="size-4 text-[var(--primary)] dark:text-[var(--accent)]" />
                </DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
