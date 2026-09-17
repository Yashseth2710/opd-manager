/**
 * A reception counter rather than a floating card: the clinic's side on the
 * left, the working surface on the right. On a phone the ink panel folds up
 * into a header bar so the form starts at the top of the screen.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[minmax(0,26rem)_1fr]">
      <aside className="flex flex-col justify-between border-b border-[var(--border)] bg-[var(--rail)] px-6 py-6 text-[var(--rail-text)] lg:border-r lg:border-b-0 lg:px-10 lg:py-12">
        <div className="flex w-fit items-center gap-3">
          <span className="grid size-9 place-items-center rounded-[8px] bg-[var(--accent)] text-[17px] leading-none font-bold text-[var(--color-ink-900)]">
            O
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-white">
            OPD Manager
          </span>
        </div>

        <div className="hidden lg:block">
          <p className="max-w-[24ch] text-[28px] leading-[1.25] font-semibold tracking-tight text-white">
            One patient. One timeline. One queue that everyone can see.
          </p>
          <p className="mt-4 max-w-[38ch] text-[15px] leading-relaxed">
            Registration through to payment, in the order a clinic actually works.
          </p>
        </div>

        <p className="hidden text-[13px] leading-relaxed text-[var(--color-ink-300)] lg:block">
          Every record in this build is synthetic. No patient information is used anywhere.
        </p>
      </aside>

      <main className="flex items-center justify-center px-6 py-12 lg:px-12">
        <div className="w-full max-w-[26rem]">{children}</div>
      </main>
    </div>
  );
}
