import type { Page } from "@playwright/test";
import { addDoctor, expect, nextWeekday, test } from "./fixtures";

const MONDAY = 0;
const SUNDAY = 6;

// Every test gets its own doctor, so a rota one of them writes is never a
// rota another one is reading.
test.beforeEach(async ({ page, tag }) => {
  const doctor = await addDoctor(page, { last_name: `Rota${tag}` });
  await page.goto(`/doctors/${doctor.id}`);
});

/** Opens the rota editor and adds one block to a day. */
async function addBlock(page: Page, day: string, first = true) {
  const row = page.getByRole("listitem").filter({ hasText: day });
  await row.getByRole("button", { name: first ? "Add hours" : "Another block" }).click();
}

test("hours are set from the profile and read back the way they are written up", async ({
  page,
}) => {
  await expect(page.getByText("No hours set yet")).toBeVisible();
  await page.getByRole("button", { name: "Set hours" }).click();

  await addBlock(page, "Monday");
  await page.getByLabel("Monday start").fill("09:00");
  await page.getByLabel("Monday end").fill("11:00");
  await page.getByRole("button", { name: "Save hours" }).click();

  await expect(page.getByText("9:00 am – 11:00 am")).toBeVisible();
});

test("a morning and an evening clinic on one day are two blocks", async ({ page }) => {
  await page.getByRole("button", { name: "Set hours" }).click();

  await addBlock(page, "Tuesday");
  await page.getByLabel("Tuesday start").fill("09:00");
  await page.getByLabel("Tuesday end").fill("13:00");

  await addBlock(page, "Tuesday", false);
  await page.getByLabel("Tuesday start").nth(1).fill("17:00");
  await page.getByLabel("Tuesday end").nth(1).fill("20:00");

  await page.getByRole("button", { name: "Save hours" }).click();

  await expect(page.getByText("9:00 am – 1:00 pm")).toBeVisible();
  await expect(page.getByText("5:00 pm – 8:00 pm")).toBeVisible();
});

test("two blocks over the same hour are refused against the block that clashes", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Set hours" }).click();

  await addBlock(page, "Monday");
  await page.getByLabel("Monday start").fill("09:00");
  await page.getByLabel("Monday end").fill("13:00");

  await addBlock(page, "Monday", false);
  await page.getByLabel("Monday start").nth(1).fill("12:00");
  await page.getByLabel("Monday end").nth(1).fill("15:00");

  await page.getByRole("button", { name: "Save hours" }).click();

  await expect(page.getByText("This overlaps another Monday block.")).toBeVisible();
  // The editor stays open with everything still in it, rather than throwing
  // the week away and asking for it again.
  await expect(page.getByLabel("Monday start").first()).toHaveValue("09:00");
});

test("a break has to sit inside the hours it breaks", async ({ page }) => {
  await page.getByRole("button", { name: "Set hours" }).click();

  await addBlock(page, "Monday");
  await page.getByLabel("Monday start").fill("09:00");
  await page.getByLabel("Monday end").fill("12:00");
  await page.getByRole("button", { name: "Add a break" }).click();
  await page.getByLabel("Monday break start").fill("14:00");
  await page.getByLabel("Monday break end").fill("15:00");

  await page.getByRole("button", { name: "Save hours" }).click();
  await expect(page.getByText("The break has to sit inside these hours.")).toBeVisible();
});

test("free times follow the rota, the break and the leave", async ({ page }) => {
  const monday = nextWeekday(MONDAY);

  await page.getByRole("button", { name: "Set hours" }).click();
  await addBlock(page, "Monday");
  await page.getByLabel("Monday start").fill("09:00");
  await page.getByLabel("Monday end").fill("12:00");
  await page.getByRole("button", { name: "Save hours" }).click();
  await expect(page.getByText("9:00 am – 12:00 pm")).toBeVisible();

  // Six half-hour slots across the morning.
  await page.getByLabel("Show this day").fill(monday);
  await expect(page.getByText("6 appointments of 30 minutes")).toBeVisible();
  await expect(page.getByText("10:00 am", { exact: true })).toBeVisible();

  // Two hours off takes four of them away.
  await page.getByRole("button", { name: "Add" }).click();
  await page.getByLabel("From", { exact: true }).fill(monday);
  await page.getByLabel("From time").fill("10:00");
  await page.getByLabel("To time").fill("12:00");
  await page.getByLabel("Reason").fill("School run");
  await page.getByRole("button", { name: "Save", exact: true }).click();

  await expect(page.getByText("School run")).toBeVisible();
  await expect(page.getByText("2 appointments of 30 minutes")).toBeVisible();
  await expect(page.getByText("10:00 am", { exact: true })).toBeHidden();
});

test("a whole day off closes the day and says why", async ({ page }) => {
  const monday = nextWeekday(MONDAY);

  await page.getByRole("button", { name: "Set hours" }).click();
  await addBlock(page, "Monday");
  await page.getByRole("button", { name: "Save hours" }).click();
  await expect(page.getByText("9:00 am – 1:00 pm")).toBeVisible();

  await page.getByRole("button", { name: "Add" }).click();
  await page.getByLabel("From", { exact: true }).fill(monday);
  await page.getByLabel("Reason").fill("Conference");
  await page.getByRole("button", { name: "Save", exact: true }).click();

  await page.getByLabel("Show this day").fill(monday);
  await expect(page.getByText(/On leave.*Conference/)).toBeVisible();
});

test("a day with no clinic says which day it is", async ({ page }) => {
  await page.getByRole("button", { name: "Set hours" }).click();
  await addBlock(page, "Monday");
  await page.getByRole("button", { name: "Save hours" }).click();
  await expect(page.getByText("9:00 am – 1:00 pm")).toBeVisible();

  await page.getByLabel("Show this day").fill(nextWeekday(SUNDAY));
  await expect(page.getByText("No Sunday clinic.")).toBeVisible();
});

test("leave that was booked by mistake can be taken back off", async ({ page }) => {
  const monday = nextWeekday(MONDAY);

  await page.getByRole("button", { name: "Add" }).click();
  await page.getByLabel("From", { exact: true }).fill(monday);
  await page.getByLabel("Reason").fill("Booked in error");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Booked in error")).toBeVisible();

  await page.getByLabel(`Cancel leave on ${monday}`).click();
  await expect(page.getByText("Nothing booked off")).toBeVisible();
});

test("copying Monday across the week fills the weekdays and leaves the weekend", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Set hours" }).click();
  await addBlock(page, "Monday");
  await page.getByLabel("Monday start").fill("10:00");
  await page.getByLabel("Monday end").fill("14:00");

  await page.getByRole("button", { name: "Monday across the week" }).click();
  await page.getByRole("button", { name: "Save hours" }).click();

  for (const day of ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]) {
    await expect(page.getByRole("listitem").filter({ hasText: day })).toContainText(
      "10:00 am – 2:00 pm",
    );
  }
  await expect(page.getByText("Saturday")).toBeHidden();
});

test("clearing the week puts the profile back to having no hours", async ({ page }) => {
  await page.getByRole("button", { name: "Set hours" }).click();
  await addBlock(page, "Monday");
  await page.getByRole("button", { name: "Save hours" }).click();
  await expect(page.getByText("9:00 am – 1:00 pm")).toBeVisible();

  await page.getByRole("button", { name: "Edit hours" }).click();
  await page.getByRole("button", { name: /Remove these Monday hours/ }).click();
  await page.getByRole("button", { name: "Save hours" }).click();

  await expect(page.getByText("No hours set yet")).toBeVisible();
});

test("a doctor stood down cannot have their hours changed from the screen", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Stand down" }).click();
  await expect(page.getByText("stood down")).toBeVisible();

  await expect(page.getByRole("button", { name: "Set hours" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Add" })).toBeHidden();
});
