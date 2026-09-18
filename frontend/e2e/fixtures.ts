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

/**
 * The next date on this weekday, never today, as the date inputs want it.
 *
 * Never today because today's earlier slots are over by the time the suite
 * runs in the afternoon, and a test counting free times would then pass or
 * fail by the hour it was run.
 */
export function nextWeekday(dayOfWeek: number): string {
  const today = new Date();
  // Date.getDay() counts from Sunday; the rota counts from Monday.
  const mondayFirst = (today.getDay() + 6) % 7;
  const day = new Date(today);
  day.setDate(today.getDate() + ((dayOfWeek - mondayFirst + 6) % 7) + 1);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(
    day.getDate(),
  ).padStart(2, "0")}`;
}

/** Nine to one, with a half-hour break, every day of the week. */
export const MORNINGS = Array.from({ length: 7 }, (_, day) => ({
  day_of_week: day,
  start_time: "09:00",
  end_time: "13:00",
  break_start: "11:00",
  break_end: "11:30",
}));

/** A doctor who can be booked, with thirty-minute appointments every morning. */
export async function bookableDoctor(page: Page, details: Record<string, unknown> = {}) {
  const doctor = await addDoctor(page, details);
  const hours = await page.request.put(`/api/v1/doctors/${doctor.id}/schedule`, {
    data: { blocks: MORNINGS },
  });
  expect(hours.ok(), await hours.text()).toBeTruthy();
  return doctor;
}

let registered = 0;

/**
 * Registers somebody without walking the form.
 *
 * The phone number is made up per call, because a number shared with an
 * earlier test's patient would be offered as a possible duplicate.
 */
export async function addPatient(page: Page, details: Record<string, unknown> = {}) {
  registered += 1;
  const digits = `${Date.now()}${registered}`.slice(-9);
  const created = await page.request.post("/api/v1/patients", {
    data: {
      first_name: "Asha",
      last_name: "Kulkarni",
      phone: `9${digits}`,
      date_of_birth: "1979-02-03",
      gender: "female",
      confirm_duplicate: true,
      ...details,
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()).data;
}

/** Books straight through the API, for tests that start after a booking. */
export async function addBooking(
  page: Page,
  booking: { patient_id: string; doctor_id: string; date: string; start_time: string } & Record<
    string,
    unknown
  >,
) {
  const made = await page.request.post("/api/v1/appointments", { data: booking });
  expect(made.ok(), await made.text()).toBeTruthy();
  return (await made.json()).data;
}
