import { addPatient, expect, test } from "./fixtures";
import { DOCTOR_STATE, SHARED_STATE } from "./state";
import { asTheDesk, inTheRoom } from "./visits";

/**
 * Files on a patient's record: added at the desk or in the room, opened in
 * place, and kept with the visit or the lab test they belong to.
 */

// One pixel, with the tag after the end of the image so that no two runs
// send the same file.
const PIXEL =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

function photo(name: string, tag: string) {
  return {
    name,
    mimeType: "image/png",
    buffer: Buffer.concat([Buffer.from(PIXEL, "base64"), Buffer.from(tag)]),
  };
}

function pdf(name: string, tag: string) {
  return {
    name,
    mimeType: "application/pdf",
    buffer: Buffer.from(`%PDF-1.4\n1 0 obj << >> endobj\n% ${tag}\n%%EOF\n`),
  };
}

test.describe("on the record", () => {
  test("the desk adds files, opens them, renames one and takes one off", async ({
    page,
    tag,
  }) => {
    const patient = await addPatient(page, { last_name: `Files${tag}` });
    await page.goto(`/patients/${patient.id}`);

    const panel = page.getByRole("region", { name: /^Documents/ });
    await expect(panel.getByText("Add a report, a scan or a letter")).toBeVisible();

    await panel.getByTestId("document-input").setInputFiles([
      pdf("CBC_report.pdf", tag),
      photo("Chest xray.png", tag),
      { name: "IMG_2231.HEIC", mimeType: "image/heic", buffer: Buffer.from(`heic${tag}`) },
      { name: "notes.docx", mimeType: "application/zip", buffer: Buffer.from(`PK${tag}`) },
      // Called a PDF, and only the server can tell it is not one.
      { name: "pretend.pdf", mimeType: "application/pdf", buffer: Buffer.from(`<html>${tag}`) },
    ]);
    const staged = panel.getByRole("list", { name: "Files to add" });
    await expect(staged.getByText(/iPhone photos in HEIC cannot be shown here/)).toBeVisible();
    await expect(
      staged.getByText("Only PDFs and photos (JPEG, PNG or WebP) can be added."),
    ).toBeVisible();

    await panel
      .getByRole("combobox", { name: "Kind of file for Chest xray.png" })
      .selectOption("scan");
    await panel.getByLabel("Date on CBC_report.pdf, if it has one").fill("2026-01-15");
    await panel.getByRole("button", { name: "Add 3 files" }).click();

    // The one the server refused stays, saying why, with nothing to retry.
    await expect(
      staged.getByText("Only PDFs and JPEG, PNG or WebP images can be added."),
    ).toBeVisible();
    await expect(staged.getByRole("button", { name: "Try again" })).toHaveCount(0);
    const listed = panel.getByRole("listitem");
    await expect(panel.getByRole("button", { name: /^CBC report/ })).toBeVisible();
    await expect(panel.getByRole("button", { name: /^Chest xray/ })).toBeVisible();
    await panel.getByRole("button", { name: "Cancel" }).click();
    await expect(listed).toHaveCount(2);

    // Narrowed to one kind, and back.
    await panel.getByRole("button", { name: /^Scan, X-ray or ECG/ }).click();
    await expect(listed).toHaveCount(1);
    await panel.getByRole("button", { name: /^All/ }).click();
    await expect(listed).toHaveCount(2);

    // Opened in place, one after the other.
    await panel.getByRole("button", { name: /^Chest xray/ }).click();
    const viewer = page.getByRole("dialog");
    await expect(viewer.getByRole("heading", { name: "Chest xray" })).toBeVisible();
    await expect(viewer.getByRole("img", { name: "Chest xray" })).toBeVisible();
    await viewer.getByRole("button", { name: "Next file" }).click();
    await expect(viewer.getByRole("heading", { name: "CBC report" })).toBeVisible();
    await expect(viewer.locator("iframe")).toBeAttached();
    await expect(viewer).toContainText("dated");

    await viewer.getByRole("button", { name: "Edit details" }).click();
    await viewer.getByLabel("Name").fill("");
    await viewer.getByRole("button", { name: "Save" }).click();
    await expect(viewer.getByText("Give it a name.")).toBeVisible();
    await viewer.getByLabel("Name").fill("Blood count, January");
    await viewer.getByRole("button", { name: "Save" }).click();
    await expect(viewer.getByRole("heading", { name: "Blood count, January" })).toBeVisible();

    await viewer.getByRole("button", { name: "Previous file" }).click();
    await viewer.getByRole("button", { name: "Remove" }).click();
    await viewer.getByRole("button", { name: "Yes, remove it" }).click();
    await expect(viewer).toBeHidden();
    await expect(listed).toHaveCount(1);
    await expect(panel.getByRole("button", { name: /^Blood count, January/ })).toBeVisible();

    // The same paper again is caught.
    await panel.getByTestId("document-input").setInputFiles([pdf("copy.pdf", tag)]);
    await panel.getByRole("button", { name: "Add the file" }).click();
    await expect(
      panel.getByText("That file is already on this record, as “Blood count, January”."),
    ).toBeVisible();

    // Nothing was stored twice.
    const files = await (
      await page.request.get(`/api/v1/patients/${patient.id}/documents`)
    ).json();
    expect(files.data.total).toBe(1);
  });
});

test.describe("from the room", () => {
  test.use({ storageState: DOCTOR_STATE });

  test("a file from the visit is put with the test it is the report for", async ({
    page,
    browser,
    playwright,
    baseURL,
    tag,
  }) => {
    const deskContext = await browser.newContext({ storageState: SHARED_STATE });
    const deskPage = await deskContext.newPage();
    const desk = await asTheDesk(playwright, baseURL);
    const { entry } = await inTheRoom(desk, deskPage, "Brought reports", `Room${tag}`);

    const opened = await page.request.post("/api/v1/consultations", {
      data: { queue_entry_id: entry.id },
    });
    const notes = (await opened.json()).data;
    await page.goto(`/consultations/${notes.id}`);

    const files = page.getByRole("region", { name: /^Files from this visit/ });
    await files.getByTestId("document-input").setInputFiles([pdf("Thyroid profile.pdf", tag)]);
    await files.getByRole("button", { name: "Add the file" }).click();
    await expect(files.getByRole("button", { name: /^Thyroid profile/ })).toBeVisible();

    const ordered = await page.request.post("/api/v1/lab-orders", {
      data: { consultation_id: notes.id, test_code: "thyroid" },
    });
    const order = (await ordered.json()).data;
    await page.goto(`/lab/${order.id}`);

    // Attached again from the test's page, it is the same file, so it is
    // offered to be put with the test rather than stored twice.
    const copy = page.getByRole("region", { name: /^The lab's copy/ });
    await copy.getByTestId("document-input").setInputFiles([pdf("Thyroid profile.pdf", tag)]);
    await expect(copy.getByRole("combobox", { name: /^Kind of file/ })).toBeDisabled();
    await copy.getByRole("button", { name: "Add the file" }).click();
    await copy.getByRole("button", { name: "Put “Thyroid profile” with this test" }).click();
    await expect(copy.getByRole("button", { name: /^Thyroid profile/ })).toBeVisible();

    await copy.getByRole("button", { name: /^Thyroid profile/ }).click();
    const viewer = page.getByRole("dialog");
    await expect(viewer.getByText(/The lab's report for/)).toContainText(order.order_number);

    await deskContext.close();
    await desk.dispose();
  });
});
