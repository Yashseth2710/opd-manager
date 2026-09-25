"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Loader2 } from "lucide-react";
import { useState } from "react";
import { Page } from "@/components/layout/shell";
import { NoticeRow } from "@/components/notifications/parts";
import { currentSession } from "@/lib/auth";
import {
  byDay,
  choosePreference,
  getPreferences,
  listNotices,
  markAllRead,
  refreshNotices,
  type Preference,
  type Preferences,
} from "@/lib/notifications";

type Show = "all" | "unread";

export default function NotificationsPage() {
  const [show, setShow] = useState<Show>("all");
  const queryClient = useQueryClient();

  const notices = useInfiniteQuery({
    queryKey: ["notices", "list", "page", show],
    queryFn: ({ pageParam }) => listNotices(show, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.more ? last.items.at(-1)?.id : undefined),
    refetchInterval: 30_000,
    retry: false,
  });

  const allRead = useMutation({
    mutationFn: markAllRead,
    onSettled: () => refreshNotices(queryClient),
  });

  const items = notices.data?.pages.flatMap((page) => page.items) ?? [];
  const unread = notices.data?.pages[0]?.unread ?? 0;

  return (
    <Page
      title="Notifications"
      blurb="What has happened that concerns you. Only you see these."
      action={
        unread > 0 && (
          <button
            type="button"
            onClick={() => allRead.mutate()}
            disabled={allRead.isPending}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60"
          >
            {allRead.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <CheckCheck className="size-4" />
            )}
            Mark all read
          </button>
        )
      }
    >
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_17rem] lg:items-start">
        <section aria-label="Your notifications">
          <div role="tablist" aria-label="Which notifications" className="mb-5 flex gap-1.5">
            {(["all", "unread"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={show === value}
                onClick={() => setShow(value)}
                className={`rounded-full border px-3.5 py-1.5 text-[14px] transition-colors ${
                  show === value
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]"
                    : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
                }`}
              >
                {value === "all" ? "All" : "Unread"}
                {value === "unread" && unread > 0 && (
                  <span className="ml-1.5 tabular opacity-80">{unread}</span>
                )}
              </button>
            ))}
          </div>

          {notices.isPending ? (
            <div className="flex min-h-[20vh] items-center justify-center gap-3 text-[var(--text-muted)]">
              <Loader2 className="size-5 animate-spin" />
              <span className="text-[15px]">Loading your notifications…</span>
            </div>
          ) : notices.isError ? (
            <p className="text-[15px] text-[var(--text-muted)]">
              Your notifications did not load. Try again in a moment.
            </p>
          ) : items.length === 0 ? (
            <Nothing show={show} />
          ) : (
            <div className="flex flex-col gap-7">
              {byDay(items).map(([day, group]) => (
                <section key={day} aria-label={day}>
                  <h2 className="mb-2 text-[13px] font-semibold text-[var(--text-muted)]">
                    {day}
                  </h2>
                  <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
                    {group.map((notice) => (
                      <NoticeRow key={notice.id} notice={notice} />
                    ))}
                  </ul>
                </section>
              ))}
              {notices.hasNextPage && (
                <button
                  type="button"
                  onClick={() => void notices.fetchNextPage()}
                  disabled={notices.isFetchingNextPage}
                  className="inline-flex items-center gap-2 self-start rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60"
                >
                  {notices.isFetchingNextPage && <Loader2 className="size-4 animate-spin" />}
                  Show older
                </button>
              )}
            </div>
          )}
        </section>

        <ByEmail />
      </div>
    </Page>
  );
}

function Nothing({ show }: { show: Show }) {
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-10 text-center">
      <p className="text-[15px] font-medium">
        {show === "unread" ? "You are all caught up" : "Nothing here yet"}
      </p>
      <p className="mx-auto mt-1.5 max-w-[42ch] text-[14px] leading-relaxed text-[var(--text-muted)]">
        {show === "unread"
          ? "Everything has been read. New notices land at the top of the list."
          : "When something needs you, like a booking with you or a result you are waiting on, it shows up here and on the bell."}
      </p>
    </div>
  );
}

function ByEmail() {
  const queryClient = useQueryClient();
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const preferences = useQuery({
    queryKey: ["notices", "preferences"],
    queryFn: getPreferences,
    retry: false,
  });

  const choose = useMutation({
    mutationFn: ({ kind, email }: Preference) => choosePreference(kind, email),
    onMutate: ({ kind, email }) => {
      queryClient.setQueryData<Preferences>(["notices", "preferences"], (was) =>
        was
          ? { ...was, kinds: was.kinds.map((k) => (k.kind === kind ? { ...k, email } : k)) }
          : was,
      );
    },
    onSuccess: (saved) => queryClient.setQueryData(["notices", "preferences"], saved),
    onError: () => queryClient.invalidateQueries({ queryKey: ["notices", "preferences"] }),
  });

  const available = preferences.data?.email_available ?? false;

  return (
    <section
      aria-labelledby="by-email-heading"
      className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] lg:sticky lg:top-8"
    >
      <div className="border-b border-[var(--border)] px-4 py-3">
        <h2 id="by-email-heading" className="text-[15px] font-semibold">
          Also by email
        </h2>
        <p className="mt-0.5 min-h-[2.5em] text-[13px] leading-snug text-[var(--text-muted)]">
          {!preferences.data ? null : available ? (
            <>
              Sent to{" "}
              <span className="break-all text-[var(--text)]">{session.data?.user.email}</span>.
              Everything stays here either way.
            </>
          ) : (
            "Email is not set up for this clinic yet, so these show here only."
          )}
        </p>
      </div>

      {preferences.isPending ? (
        <div className="flex items-center gap-2 px-4 py-5 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" />
          Loading…
        </div>
      ) : preferences.isError ? (
        <p className="px-4 py-5 text-[14px] text-[var(--text-muted)]">
          Your choices did not load. Try again in a moment.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {preferences.data.kinds.map((kind) => (
            <li key={kind.kind}>
              <Switch
                preference={kind}
                disabled={!available}
                onChange={(email) => choose.mutate({ ...kind, email })}
              />
            </li>
          ))}
        </ul>
      )}
      {choose.isError && (
        <p
          role="alert"
          className="border-t border-[var(--border)] px-4 py-3 text-[13px] text-[var(--color-state-noshow)]"
        >
          That choice was not saved. Try again.
        </p>
      )}
    </section>
  );
}

function Switch({
  preference,
  disabled,
  onChange,
}: {
  preference: Preference;
  disabled: boolean;
  onChange: (email: boolean) => void;
}) {
  const on = preference.email && !disabled;
  return (
    <label
      className={`flex items-start justify-between gap-3 px-4 py-3 ${
        disabled ? "cursor-not-allowed" : "cursor-pointer hover:bg-[var(--surface-sunken)]"
      }`}
    >
      <span className="min-w-0">
        <span className="block text-[14px] font-medium">{preference.label}</span>
        <span className="mt-0.5 block text-[12.5px] leading-snug text-[var(--text-muted)]">
          {preference.description}
        </span>
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={`Email me: ${preference.label}`}
        disabled={disabled}
        onClick={() => onChange(!preference.email)}
        className={`relative mt-0.5 h-[22px] w-[38px] shrink-0 rounded-full transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] disabled:opacity-45 ${
          on ? "bg-[var(--accent)]" : "bg-[var(--border-strong)]"
        }`}
      >
        <span
          aria-hidden
          className={`absolute top-[3px] left-[3px] size-4 rounded-full bg-white shadow-sm transition-transform duration-200 ease-[var(--ease-out-quint)] ${
            on ? "translate-x-4" : ""
          }`}
        />
      </button>
    </label>
  );
}
