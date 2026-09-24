import { addPatient, expect, test } from "./fixtures";
import { SHARED_STATE } from "./state";

test.use({ storageState: SHARED_STATE });

test("finds a patient from anywhere with the keyboard, and keeps them close", async ({
  page,
  tag,
}) => {
  const patient = await addPatient(page, { first_name: "Zarin", last_name: `Find${tag}` });

  await page.goto("/dashboard");
  await expect(page.getByRole("button", { name: /^Search/ })).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");

  const box = page.getByRole("combobox", { name: "Search the clinic" });
  await expect(box).toBeFocused();
  await box.fill(`find${tag}`);

  const found = page.getByRole("group", { name: "Patients" }).getByRole("option");
  await expect(found).toHaveCount(1);
  await expect(found).toContainText(`Zarin Find${tag}`);
  await expect(found).toContainText(patient.patient_number);
  await expect(found).toHaveAttribute("aria-selected", "true");

  await box.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/patients/${patient.id}$`));
  await expect(box).toBeHidden();

  // Opened once, it waits at the top the next time the box is empty.
  await page.keyboard.press("/");
  const lately = page.getByRole("group", { name: "Opened lately" }).getByRole("option");
  await expect(lately.first()).toContainText(`Zarin Find${tag}`);
  await page.keyboard.press("Escape");
  await expect(box).toBeHidden();
});

test("says where it looked when nothing matches", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByRole("button", { name: /^Search/ }).click();
  await page.getByRole("combobox", { name: "Search the clinic" }).fill("qqqq-no-such-person");

  await expect(page.getByText("Nothing matches “qqqq-no-such-person”")).toBeVisible();
  await expect(
    page.getByText(/Looked through patients, bookings coming up, bills/),
  ).toBeVisible();
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 780 } });

  test("opens from the icon and closes with Cancel", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const box = page.getByRole("combobox", { name: "Search the clinic" });
    await expect(box).toBeVisible();

    await page.getByRole("button", { name: "Close search" }).click();
    await expect(box).toBeHidden();
  });
});
