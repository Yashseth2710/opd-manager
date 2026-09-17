import { addDoctor, expect, test } from "./fixtures";
import { EMPTY_STATE } from "./state";

test("adding a doctor opens their profile with everything that was typed", async ({
  page,
  tag,
}) => {
  await page.goto("/doctors/new");

  await page.getByLabel("First name").fill("Ananya");
  await page.getByLabel("Last name").fill(`Typed${tag}`);
  await page.getByLabel("Speciality").fill("Paediatrics");
  await page.getByLabel("Qualifications").fill("MBBS, MD");
  await page.getByLabel("Consulting room").fill("3");
  await page.getByLabel("Languages").fill("Hindi, Marathi, English");
  await page.getByRole("button", { name: "Add doctor" }).click();

  await expect(page).toHaveURL(/\/doctors\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: `Dr Ananya Typed${tag}` })).toBeVisible();
  await expect(page.getByText("Paediatrics · MBBS, MD · Room 3")).toBeVisible();
  for (const language of ["Hindi", "Marathi", "English"]) {
    await expect(page.getByText(language, { exact: true })).toBeVisible();
  }
});

test("a fee left blank says it is following the clinic", async ({ page, tag }) => {
  await page.goto("/doctors/new");

  await page.getByLabel("First name").fill(`Blank${tag}`);
  await page.getByRole("button", { name: "Add doctor" }).click();
  await expect(page).toHaveURL(/\/doctors\/[0-9a-f-]{36}$/);

  await expect(page.getByText("following the clinic").first()).toBeVisible();
});

test("a name is the only thing the form insists on", async ({ page, tag }) => {
  await page.goto("/doctors/new");

  const submit = page.getByRole("button", { name: "Add doctor" });
  await expect(submit).toBeDisabled();

  await page.getByLabel("First name").fill(`Sadhana${tag}`);
  await expect(submit).toBeEnabled();
  await submit.click();

  await expect(page.getByRole("heading", { name: `Dr Sadhana${tag}` })).toBeVisible();
});

test("a registration number already in use is refused where it can be seen", async ({
  page,
  tag,
}) => {
  const number = `MH-2019-${tag}`;
  await addDoctor(page, { last_name: `Held${tag}`, registration_number: number });
  await page.goto("/doctors/new");

  await page.getByLabel("First name").fill("Rohit");
  await page.getByLabel("Registration number").fill(number);
  await page.getByRole("button", { name: "Add doctor" }).click();

  await expect(page.getByText(/already has that registration number/i)).toBeVisible();
  // Still on the form, with what was typed intact.
  await expect(page).toHaveURL(/\/doctors\/new$/);
  await expect(page.getByLabel("First name")).toHaveValue("Rohit");
});

test("clicking add twice in the same moment makes one doctor", async ({ page, tag }) => {
  const surname = `Clicked${tag}`;
  await page.goto("/doctors/new");
  await page.getByLabel("First name").fill("Twice");
  await page.getByLabel("Last name").fill(surname);

  // All three in one tick, which is the case a disabled button cannot catch:
  // awaiting them in turn would just wait for a button that had gone.
  await page.getByRole("button", { name: "Add doctor" }).evaluate((button) => {
    button.click();
    button.click();
    button.click();
  });

  await expect(page).toHaveURL(/\/doctors\/[0-9a-f-]{36}$/);

  const listed = await page.request.get(`/api/v1/doctors?status=all&q=${surname}`);
  expect((await listed.json()).data.total).toBe(1);
});

test("search finds a doctor by a misspelt surname and by speciality", async ({ page, tag }) => {
  await addDoctor(page, { first_name: "Ananya", last_name: `Deshmukh${tag}` });
  await addDoctor(page, {
    first_name: "Rohit",
    last_name: `Menon${tag}`,
    speciality: `Cardiology${tag}`,
  });
  await page.goto("/doctors");

  const box = page.getByLabel("Search doctors");
  await box.fill(`Deshmuk${tag}`);
  await expect(page.getByRole("link", { name: new RegExp(`Deshmukh${tag}`) })).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(`Menon${tag}`) })).toBeHidden();

  await box.fill(`Cardiology${tag}`);
  await expect(page.getByRole("link", { name: new RegExp(`Menon${tag}`) })).toBeVisible();

  await box.fill(`zzzznobody${tag}`);
  await expect(page.getByText(/Nobody matches/)).toBeVisible();
});

test("the search stays in the address bar, so the back button comes home", async ({
  page,
  tag,
}) => {
  const surname = `Backwards${tag}`;
  await addDoctor(page, { last_name: surname });
  await page.goto("/doctors");

  await page.getByLabel("Search doctors").fill(surname);
  await expect(page).toHaveURL(new RegExp(`q=${surname}`));

  await page.getByRole("link", { name: new RegExp(surname) }).click();
  await expect(page).toHaveURL(/\/doctors\/[0-9a-f-]{36}$/);

  await page.goBack();
  await expect(page.getByLabel("Search doctors")).toHaveValue(surname);
});

test("the speciality filter is built from what this clinic offers", async ({ page, tag }) => {
  const speciality = `Cardiology${tag}`;
  await addDoctor(page, { last_name: `Heart${tag}`, speciality });
  await addDoctor(page, { last_name: `Child${tag}`, speciality: `Paediatrics${tag}` });
  await page.goto("/doctors");

  await page.getByRole("button", { name: speciality, exact: true }).click();
  await expect(page.getByRole("link", { name: new RegExp(`Heart${tag}`) })).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(`Child${tag}`) })).toBeHidden();

  await page.getByRole("button", { name: "All specialities" }).click();
  await expect(page.getByRole("link", { name: new RegExp(`Child${tag}`) })).toBeVisible();
});

test("a doctor with no hours is flagged, because nobody can be booked with them", async ({
  page,
  tag,
}) => {
  await addDoctor(page, { last_name: `Hourless${tag}` });
  await page.goto(`/doctors?q=Hourless${tag}`);

  await expect(page.getByText("no hours")).toBeVisible();
});

test("standing a doctor down takes them off the list and keeps their record", async ({
  page,
  tag,
}) => {
  const surname = `Retiring${tag}`;
  const doctor = await addDoctor(page, { last_name: surname });
  await page.goto(`/doctors/${doctor.id}`);

  await page.getByRole("button", { name: "Stand down" }).click();
  await expect(page.getByText("stood down")).toBeVisible();
  // Editing a closed record is a decision, not something to stumble into.
  await expect(page.getByRole("button", { name: "Edit" })).toBeHidden();

  await page.goto(`/doctors?q=${surname}`);
  await expect(page.getByText(/Nobody matches/)).toBeVisible();

  await page.getByRole("button", { name: "Stood down" }).click();
  await page.getByRole("link", { name: new RegExp(surname) }).click();
  await page.getByRole("button", { name: "Bring back" }).click();
  await expect(page.getByRole("button", { name: "Edit" })).toBeVisible();
});

test("an id that belongs to nobody shows a page rather than a spinner", async ({ page }) => {
  await page.goto("/doctors/00000000-0000-7000-8000-000000000000");

  await expect(page.getByRole("heading", { name: "No such doctor" })).toBeVisible();
  await page.getByRole("link", { name: "Back to doctors" }).click();
  await expect(page).toHaveURL(/\/doctors$/);
});

test("a name that is trying to be code is shown as text", async ({ page, tag }) => {
  const doctor = await addDoctor(page, {
    first_name: '<img src=x onerror="window.__owned=1">Rita',
    last_name: `Script${tag}`,
  });
  await page.goto(`/doctors/${doctor.id}`);

  await expect(page.getByRole("heading", { name: /<img/ })).toBeVisible();
  expect(await page.evaluate(() => "__owned" in window)).toBe(false);
});

test("editing keeps a blank fee blank rather than writing the clinic's in", async ({
  page,
  tag,
}) => {
  const doctor = await addDoctor(page, { last_name: `Edited${tag}` });
  await page.goto(`/doctors/${doctor.id}`);

  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByLabel("Consultation fee")).toHaveValue("");

  await page.getByLabel("Consulting room").fill("7");
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByText(/Room 7/)).toBeVisible();
  await expect(page.getByText("following the clinic").first()).toBeVisible();
});

test.describe("a clinic that has not added anyone yet", () => {
  // Its own clinic, because an empty register is the one thing the shared
  // one stops being the moment any other test runs.
  test.use({ storageState: EMPTY_STATE });

  test("says so, and offers the way in", async ({ page }) => {
    await page.goto("/doctors");
    await expect(page.getByRole("heading", { name: "No doctors yet" })).toBeVisible();
    await page.getByRole("link", { name: "Add the first doctor" }).click();
    await expect(page).toHaveURL(/\/doctors\/new$/);
  });
});

test.describe("nobody signed in", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("is sent to sign in, and told where they were headed", async ({ page }) => {
    await page.goto("/doctors/new");

    await expect(page).toHaveURL(/\/login\?next=%2Fdoctors%2Fnew$/);
    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  });
});
