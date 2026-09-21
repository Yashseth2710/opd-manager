import { addPatient, expect, test } from "./fixtures";
import { asTheDesk, inTheRoom } from "./visits";

/**
 * Bills at the desk: a visit billed from the list of those seen, paid in
 * parts, and a bill on its own kept as a draft, issued, given back and voided.
 */

test("a visit is billed, paid in two goes, and printed", async ({
  page,
  playwright,
  baseURL,
  tag,
}) => {
  const desk = await asTheDesk(playwright, baseURL);
  const { patient, entry } = await inTheRoom(desk, page, "Fever", `Bill${tag}`);
  const done = await desk.post(`/api/v1/queue/${entry.id}/complete`);
  expect(done.ok(), await done.text()).toBeTruthy();

  await page.goto("/billing");
  const seen = page.getByRole("region", { name: /^Seen today, not billed yet/ });
  const row = seen.getByRole("listitem").filter({ hasText: patient.full_name });
  await row.getByRole("link", { name: "Bill", exact: true }).click();

  await expect(
    page.getByRole("heading", { name: `Bill for ${patient.full_name}` }),
  ).toBeVisible();
  // The doctor's fee is there to start from; a dressing is added beside it.
  await page.getByRole("combobox", { name: "Line 1, what it is for" }).fill("Consultation");
  await page.getByLabel("Line 1, rate").fill("500");
  await page.getByRole("button", { name: "Add a line" }).click();
  await page.getByRole("combobox", { name: "Line 2, what it is for" }).fill("Dressing");
  await page.getByLabel("Line 2, how many").fill("2");
  await page.getByLabel("Line 2, rate").fill("abc");
  await page.getByRole("button", { name: "Issue the bill" }).click();
  await expect(page.getByText("Type an amount, like 150 or 99.50.")).toBeVisible();
  await page.getByLabel("Line 2, rate").fill("150");
  const sums = page.getByRole("definition").last();
  await expect(sums).toContainText("800.00");
  await page.getByRole("button", { name: "Issue the bill" }).click();

  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    /INV\/\d{4}-\d{2}\/\d{4}/,
  );
  await expect(page.getByText("Unpaid", { exact: true })).toBeVisible();

  // Part now by UPI.
  await page.getByLabel("Amount", { exact: true }).fill("300");
  await expect(page.getByText(/Part of it\. ₹500\.00 will still be owed\./)).toBeVisible();
  await page.getByText("UPI", { exact: true }).click();
  await page.getByLabel("UPI reference").fill("4411 2290");
  await page.getByRole("button", { name: /^Take ₹300\.00/ }).click();
  await expect(page.getByText("Part paid", { exact: true })).toBeVisible();

  // The rest in cash, with change for a thousand.
  await expect(page.getByLabel("Amount", { exact: true })).toHaveValue("500.00");
  await page.getByLabel("Amount", { exact: true }).fill("600");
  await page.getByRole("button", { name: /^Take ₹600\.00/ }).click();
  await expect(page.getByText("₹500.00 is all that is owed on this bill.")).toBeVisible();
  await page.getByLabel("Amount", { exact: true }).fill("500");
  await page.getByLabel("Cash handed over").fill("1000");
  await expect(page.getByText("Give back")).toContainText("₹500.00");
  await page.getByRole("button", { name: /^Take ₹500\.00/ }).click();

  await expect(page.getByText("Paid in full")).toBeVisible();
  const ledger = page.getByRole("region", { name: "Money in and out" });
  await expect(ledger.getByRole("listitem")).toHaveCount(2);
  await expect(ledger).toContainText("4411 2290");

  const print = page.getByRole("link", { name: "Print" });
  const pdf = await page.request.get((await print.getAttribute("href"))!);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");

  // The visit is no longer waiting for a bill, and the list has it as paid.
  await page.goto("/billing?show=paid");
  await expect(page.getByRole("link", { name: new RegExp(patient.full_name) })).toBeVisible();
  await expect(
    page
      .getByRole("region", { name: /^Seen today, not billed yet/ })
      .getByText(patient.full_name),
  ).toHaveCount(0);

  await desk.dispose();
});

test("a draft is changed, issued, given back and voided", async ({ page, tag }) => {
  const patient = await addPatient(page, { last_name: `Draft${tag}` });
  await page.goto(`/patients/${patient.id}`);
  await page
    .getByRole("region", { name: "Bills" })
    .getByRole("link", { name: "New bill" })
    .click();

  await page.getByRole("combobox", { name: "Line 1, what it is for" }).fill("Nebulisation");
  await page.getByLabel("Line 1, rate").fill("250");
  await page.getByRole("button", { name: "Give a discount" }).click();
  await page.getByLabel("Amount off").fill("50");
  await page.getByRole("button", { name: "Keep as a draft" }).click();
  await expect(page.getByText("Say why there is a discount.")).toBeVisible();
  await page.getByLabel("Why").fill("Senior citizen");
  await page.getByRole("button", { name: "Keep as a draft" }).click();

  await expect(page.getByRole("heading", { name: "Draft bill" })).toBeVisible();
  await page.getByLabel("Line 1, how many").fill("2");
  await page.getByRole("button", { name: "Issue the bill" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("INV/");
  await expect(page.getByRole("article")).toContainText("₹450.00");

  await page.getByRole("button", { name: /^Take ₹450\.00/ }).click();
  await expect(page.getByText("Paid in full")).toBeVisible();

  // Voiding waits for the money to go back first.
  await expect(page.getByRole("button", { name: "Void this bill" })).toHaveCount(0);
  await page.getByRole("button", { name: "Give money back" }).click();
  await page.getByRole("button", { name: "Give it back" }).click();
  await expect(page.getByText("Say why, for whoever reads the bill later.")).toBeVisible();
  await page.getByLabel("Why").fill("Not needed after all");
  await page.getByRole("button", { name: "Give it back" }).click();
  await expect(page.getByText("Refunded", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Void this bill" }).click();
  await page.getByLabel("Why").fill("Raised by mistake");
  await page.getByRole("button", { name: "Void the bill" }).click();
  await expect(page.getByRole("status")).toContainText("Raised by mistake");
  await expect(page.getByText("Void", { exact: true })).toBeVisible();
});
