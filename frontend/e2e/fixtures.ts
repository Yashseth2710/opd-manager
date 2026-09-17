import { expect, test as base, type Page } from "@playwright/test";

let tagged = 0;

export const test = base.extend<{ tag: string }>({
  /**
   * A string no other test in this run uses.
   *
   * Everything shares one clinic, so a test that wants a doctor it can
   * search for has to name them in a way nothing else will match.
   */
  tag: async ({}, use) => {
    tagged += 1;
    await use(`${Date.now().toString(36)}${tagged}`);
  },
});

export { expect };

/** Adds a doctor without walking the form, for tests that start after one. */
export async function addDoctor(page: Page, details: Record<string, unknown> = {}) {
  const created = await page.request.post("/api/v1/doctors", {
    data: {
      first_name: "Ananya",
      speciality: "Paediatrics",
      qualifications: "MBBS, MD",
      slot_duration_minutes: 30,
      ...details,
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).data;
}

/** The next date on this weekday, today included, as the date inputs want it. */
export function nextWeekday(dayOfWeek: number): string {
  const today = new Date();
  // Date.getDay() counts from Sunday; the rota counts from Monday.
  const mondayFirst = (today.getDay() + 6) % 7;
  const day = new Date(today);
  day.setDate(today.getDate() + ((dayOfWeek - mondayFirst + 7) % 7));
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(
    day.getDate(),
  ).padStart(2, "0")}`;
}
