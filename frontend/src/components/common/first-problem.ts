/**
 * Puts the first thing that went wrong in front of the person.
 *
 * On a long form the fields that failed are usually scrolled off the top by
 * the time the submit button is reachable, so a refused save looks like
 * nothing happening at all. Moving focus there also tells a screen reader
 * what to read.
 */
export function showFirstProblem(fields: Record<string, string>) {
  const first = Object.keys(fields)[0];
  if (!first) return;
  requestAnimationFrame(() => {
    const field = document.querySelector<HTMLElement>(`[name="${first}"]`);
    const target = field ?? document.querySelector<HTMLElement>('[role="alert"]');
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
    field?.focus({ preventScroll: true });
  });
}
