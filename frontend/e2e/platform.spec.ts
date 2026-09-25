import { readFileSync } from "node:fs";
import { expect, test } from "./fixtures";
import { PASSWORD, PLATFORM_STATE, SHARED_STATE, SPARE_CLINIC } from "./state";

const spareEmail = () => readFileSync(`${SPARE_CLINIC}.email`, "utf8").trim();

test.describe("the platform", () => {
  test.use({ storageState: PLATFORM_STATE });

  test("moves a clinic's plan, suspends it, and lets it back in", async ({ page, browser }) => {
    const owner = spareEmail();

    await page.goto("/admin/clinics");
    await page.getByRole("searchbox", { name: "Search clinics" }).fill(owner);
    await expect(page.getByRole("link", { name: new RegExp(owner) })).toHaveCount(1);
    await page.getByRole("link", { name: new RegExp(owner) }).click();
    await expect(page.getByText("What it uses")).toBeVisible();
    await expect(page.getByText(/Group trial, \d+ days left/)).toBeVisible();

    await page.getByLabel("Move to plan").selectOption({ label: "Starter" });
    await page.getByRole("button", { name: "Move to this plan" }).click();
    await page.getByRole("button", { name: "Yes, move it" }).click();
    await expect(page.getByText("Moved from Group (trial) to Starter")).toBeVisible();

    // The clinic, signed in on its own machine.
    const clinic = await browser.newContext({ storageState: SPARE_CLINIC });
    const theirs = await clinic.newPage();
    await theirs.goto("/settings");
    await expect(theirs.getByRole("heading", { name: "Plan" })).toBeVisible();
    await expect(theirs.getByText("One or two doctors getting going.")).toBeVisible();

    await page.getByRole("button", { name: "Suspend this clinic" }).click();
    await page.getByRole("button", { name: "Suspend now" }).click();
    await expect(page.getByText("Say why, in a few words.")).toBeVisible();
    await page.getByLabel("Why").fill("Unpaid since July");
    await page.getByRole("button", { name: "Suspend now" }).click();
    await expect(page.getByText("“Unpaid since July”").first()).toBeVisible();

    // Stopped on the very next thing they ask for, from whatever page.
    await theirs.goto("/patients");
    await expect(theirs.getByText("This clinic has been suspended")).toBeVisible();

    await theirs.goto("/login?ended=1");
    await theirs.getByLabel("Email").fill(owner);
    await theirs.getByRole("textbox", { name: "Password" }).fill(PASSWORD);
    await theirs.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(theirs.getByText(/This clinic has been suspended/)).toBeVisible();

    await page.getByRole("button", { name: "Reactivate" }).click();
    await page.getByRole("button", { name: "Yes, reactivate" }).click();
    await expect(page.getByRole("button", { name: "Suspend this clinic" })).toBeVisible();

    await theirs.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(theirs).toHaveURL(/\/(settings|dashboard)/);
    await theirs.goto("/audit");
    await expect(theirs.getByText(/Asha Rao \(platform\)/).first()).toBeAttached();
    await clinic.close();
  });

  test("never opens a clinic's own pages", async ({ page }) => {
    await page.goto("/patients");
    await expect(page).toHaveURL(/\/admin$/);
    const refused = await page.evaluate(async () => (await fetch("/api/v1/patients")).status);
    expect(refused).toBe(403);
  });
});

test.describe("a clinic", () => {
  test.use({ storageState: SHARED_STATE });

  test("never reaches the platform", async ({ page }) => {
    await page.goto("/admin/clinics");
    await expect(page).toHaveURL(/\/dashboard/);
    const refused = await page.evaluate(
      async () => (await fetch("/api/v1/platform/organizations")).status,
    );
    expect(refused).toBe(403);
  });

  test("picks a theme that stays after a reload", async ({ page }) => {
    await page.goto("/dashboard");
    const html = page.locator("html");

    await page
      .getByRole("button", { name: /^Theme/ })
      .first()
      .click();
    await page.getByRole("menuitemradio", { name: /Dark/ }).click();
    await expect(html).toHaveAttribute("data-theme", "dark");

    await page.reload();
    await expect(html).toHaveAttribute("data-theme", "dark");

    await page
      .getByRole("button", { name: /^Theme/ })
      .first()
      .click();
    await page.getByRole("menuitemradio", { name: /System/ }).click();
    await expect(html).not.toHaveAttribute("data-theme", /.+/);
  });
});
