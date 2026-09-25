"use client";

import { type InfiniteData, useMutation, useQueryClient } from "@tanstack/react-query";
import { Mail } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import {
  markRead,
  refreshNotices,
  sinceThen,
  TONE,
  type Notice,
  type NoticeList,
  type Tone,
} from "@/lib/notifications";

const TONE_COLOUR: Record<Tone, string> = {
  diary: "var(--color-state-confirmed)",
  clinical: "var(--color-state-consulting)",
  money: "var(--color-marigold-500)",
  people: "var(--color-ink-400)",
};

const TONE_WORDS: Record<Tone, string> = {
  diary: "Appointments",
  clinical: "Lab",
  money: "Money",
  people: "Your clinic",
};

/**
 * Marks a notice read everywhere it is shown at once, rather than waiting for
 * the lists to be asked for again.
 */
export function useMarkRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: markRead,
    onMutate: (id: string) => {
      const now = new Date().toISOString();
      const marked = (list: NoticeList, wasUnread: boolean): NoticeList => ({
        ...list,
        unread: wasUnread ? Math.max(list.unread - 1, 0) : list.unread,
        items: list.items.map((n) => (n.id === id ? { ...n, read_at: n.read_at ?? now } : n)),
      });
      const unreadIn = (lists: NoticeList[]) =>
        lists.some((list) => list.items.some((n) => n.id === id && !n.read_at));
      // The bell holds one list; the full page holds them a page at a time.
      queryClient.setQueriesData<NoticeList | InfiniteData<NoticeList>>(
        { queryKey: ["notices", "list"] },
        (held) => {
          if (!held) return held;
          if ("pages" in held) {
            const was = unreadIn(held.pages);
            return { ...held, pages: held.pages.map((page) => marked(page, was)) };
          }
          return marked(held, unreadIn([held]));
        },
      );
    },
    onSettled: () => refreshNotices(queryClient),
  });
}

export function NoticeRow({
  notice,
  dense = false,
  onOpened,
}: {
  notice: Notice;
  dense?: boolean;
  onOpened?: () => void;
}) {
  const router = useRouter();
  const read = useMarkRead();
  const tone = TONE[notice.kind];
  const unread = !notice.read_at;

  const open = () => {
    if (unread) read.mutate(notice.id);
    onOpened?.();
    if (notice.link) router.push(notice.link as Route);
  };

  return (
    <li>
      <button
        type="button"
        onClick={open}
        className={`group relative flex w-full items-start gap-3 text-left transition-colors hover:bg-[var(--surface-sunken)] focus-visible:bg-[var(--surface-sunken)] focus-visible:outline-none ${
          dense ? "px-4 py-3" : "px-5 py-4"
        }`}
      >
        {unread && (
          <span
            aria-hidden
            className="absolute top-0 bottom-0 left-0 w-[3px] bg-[var(--accent)]"
          />
        )}
        <span
          aria-hidden
          className="mt-[7px] size-2 shrink-0 rounded-full"
          style={{ background: TONE_COLOUR[tone] }}
        />
        <span className="min-w-0 flex-1">
          <span className="sr-only">
            {unread ? "Unread. " : ""}
            {TONE_WORDS[tone]}.{" "}
          </span>
          <span
            className={`block text-[14px] leading-snug text-balance ${
              unread ? "font-semibold text-[var(--text)]" : "text-[var(--text-muted)]"
            }`}
          >
            {notice.title}
          </span>
          {notice.body && (
            <span
              className={`mt-0.5 block text-[13px] leading-snug text-[var(--text-muted)] ${
                dense ? "line-clamp-2" : ""
              }`}
            >
              {notice.body}
            </span>
          )}
          <span className="mt-1 flex items-center gap-2 text-[12px] text-[var(--text-subtle)]">
            <time dateTime={notice.created_at} className="tabular">
              {sinceThen(notice.created_at)}
            </time>
            {notice.channel === "email" && (
              <span className="inline-flex items-center gap-1" title="Also sent by email">
                <Mail aria-hidden className="size-3" />
                <span className={dense ? "sr-only" : ""}>
                  {notice.sent_at ? "Emailed" : "Email not sent"}
                </span>
              </span>
            )}
          </span>
        </span>
      </button>
    </li>
  );
}
