"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell as BellIcon, Loader2 } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { NoticeRow } from "@/components/notifications/parts";
import { countUnread, listNotices, markAllRead, refreshNotices } from "@/lib/notifications";

const SHOWN = 6;

/**
 * The count in the rail, and the latest few notices under it.
 *
 * It asks for one number every half minute and nothing more; the list itself
 * is fetched only when somebody opens it.
 */
export function Bell() {
  const [open, setOpen] = useState(false);
  const [ringing, setRinging] = useState(false);
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const heard = useRef<number | null>(null);
  const queryClient = useQueryClient();

  const unread = useQuery({
    queryKey: ["notices", "unread"],
    queryFn: countUnread,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const count = unread.data?.unread ?? 0;

  const recent = useQuery({
    queryKey: ["notices", "list", "all"],
    queryFn: () => listNotices("all"),
    enabled: open,
    retry: false,
  });

  const allRead = useMutation({
    mutationFn: markAllRead,
    onSettled: () => refreshNotices(queryClient),
  });

  // One swing when something new arrives, never on the first count.
  useEffect(() => {
    if (unread.data === undefined) return;
    if (heard.current !== null && count > heard.current) {
      setRinging(true);
      const timer = setTimeout(() => setRinging(false), 900);
      heard.current = count;
      return () => clearTimeout(timer);
    }
    heard.current = count;
  }, [count, unread.data]);

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !button.current?.contains(target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  useEffect(() => {
    if (open) panel.current?.focus();
  }, [open]);

  const items = recent.data?.items.slice(0, SHOWN) ?? [];

  return (
    <div className="relative">
      <button
        ref={button}
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={count ? `Notifications, ${count} unread` : "Notifications"}
        className="relative grid size-9 place-items-center rounded-[var(--radius-field)] text-[var(--rail-text)] transition-colors hover:bg-white/8 hover:text-white aria-expanded:bg-white/10 aria-expanded:text-white"
      >
        <BellIcon className={`size-[18px] ${ringing ? "bell-ringing" : ""}`} />
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-[var(--accent)] px-1 text-[11px] leading-none font-bold text-[var(--color-ink-900)] tabular ring-2 ring-[var(--rail)]">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panel}
          id={panelId}
          role="dialog"
          aria-label="Notifications"
          tabIndex={-1}
          className="notice-panel fixed inset-x-3 top-[4.5rem] z-50 overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--text)] shadow-[0_18px_40px_-12px_rgb(8_15_26/0.45)] outline-none lg:absolute lg:inset-x-auto lg:top-full lg:left-0 lg:mt-2 lg:w-[23rem]"
        >
          <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
            <p className="text-[15px] font-semibold">
              Notifications
              {count > 0 && (
                <span className="ml-2 text-[13px] font-normal text-[var(--text-muted)] tabular">
                  {count} unread
                </span>
              )}
            </p>
            {count > 0 && (
              <button
                type="button"
                onClick={() => allRead.mutate()}
                disabled={allRead.isPending}
                className="rounded-[var(--radius-field)] px-2 py-1 text-[13px] font-medium text-[var(--primary)] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60 dark:text-[var(--accent)]"
              >
                Mark all read
              </button>
            )}
          </div>

          {recent.isPending ? (
            <div className="flex items-center justify-center gap-2 px-4 py-8 text-[14px] text-[var(--text-muted)]">
              <Loader2 className="size-4 animate-spin" />
              Loading…
            </div>
          ) : recent.isError ? (
            <p className="px-4 py-6 text-[14px] text-[var(--text-muted)]">
              Your notifications did not load. Try again in a moment.
            </p>
          ) : items.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <p className="text-[14px] font-medium">Nothing new</p>
              <p className="mt-1 text-[13px] leading-relaxed text-[var(--text-muted)]">
                Bookings with you, results you are waiting on and money that comes in online
                show up here.
              </p>
            </div>
          ) : (
            <ul className="max-h-[min(26rem,60vh)] divide-y divide-[var(--border)] overflow-y-auto overscroll-contain">
              {items.map((notice) => (
                <NoticeRow
                  key={notice.id}
                  notice={notice}
                  dense
                  onOpened={() => setOpen(false)}
                />
              ))}
            </ul>
          )}

          <Link
            href={"/notifications" as Route}
            onClick={() => setOpen(false)}
            className="block border-t border-[var(--border)] px-4 py-2.5 text-center text-[13px] font-medium text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
          >
            See all, and choose what comes by email
          </Link>
        </div>
      )}
    </div>
  );
}
