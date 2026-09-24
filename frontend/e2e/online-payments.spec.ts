import { createHmac } from "node:crypto";
import { request, type Page } from "@playwright/test";
import { addPatient, expect, test } from "./fixtures";

/**
 * Sending a bill out to be paid, and the page the patient lands on.
 *
 * Razorpay's own checkout is a window belonging to somebody else and cannot
 * be driven from here, so these run against the stand-in in
 * `scripts/dev/fake_gateway.py`. Everything above it is the real thing: the
 * order call, both signature checks, the webhook handler, and what the
 * application decides to write down.
 */

const SECRET = process.env.RAZORPAY_KEY_SECRET;
const HOOK_SECRET = process.env.RAZORPAY_WEBHOOK_SECRET;
const GATEWAY = process.env.RAZORPAY_API_URL;

function settings() {
  if (!SECRET || !HOOK_SECRET || !GATEWAY) {
    throw new Error(
      "Online payment tests need RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET and " +
        "RAZORPAY_API_URL, with the API pointed at the same stand-in gateway. " +
        "See the tests section of the README.",
    );
  }
  return { secret: SECRET, hookSecret: HOOK_SECRET, gateway: GATEWAY };
}

async function anIssuedBill(page: Page, tag: string) {
  const patient = await addPatient(page, { last_name: `Online${tag}` });
  const raised = await page.request.post("/api/v1/invoices", {
    data: {
      patient_id: patient.id,
      items: [{ item_type: "procedure", description: "Dressing", unit_price: "450.00" }],
      issue: true,
    },
  });
  expect(raised.ok(), await raised.text()).toBeTruthy();
  return { patient, bill: (await raised.json()).data };
}

/** Raises a link from the bill page and hands back its address. */
async function aLinkFrom(page: Page, billId: string) {
  await page.goto(`/billing/${billId}`);
  const panel = page.getByRole("region", { name: "Pay from a phone" });
  await panel.getByRole("button", { name: "Copy a link" }).click();
  const url = await panel.getByRole("textbox", { name: "Payment link" }).inputValue();
  return { panel, url, token: url.split("/").pop() as string };
}

/** The patient's browser: a fresh context with no session of any kind. */
async function aStranger(browser: import("@playwright/test").Browser) {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  return { context, page: await context.newPage() };
}

/** The patient paying, from the gateway's side of the glass. */
async function paidAtTheGateway(orderId: string, extra: Record<string, unknown> = {}) {
  const { gateway } = settings();
  const api = await request.newContext();
  const made = await api.post(`${gateway}/pay`, { data: { order_id: orderId, ...extra } });
  expect(made.ok(), await made.text()).toBeTruthy();
  const payment = await made.json();
  await api.dispose();
  return payment as { id: string; order_id: string; amount: number; method: string };
}

function signedHandshake(orderId: string, paymentId: string, secret = settings().secret) {
  return {
    razorpay_order_id: orderId,
    razorpay_payment_id: paymentId,
    razorpay_signature: createHmac("sha256", secret)
      .update(`${orderId}|${paymentId}`)
      .digest("hex"),
  };
}

test("the desk sends a bill out and the patient opens it", async ({ page, browser, tag }) => {
  const { patient, bill } = await anIssuedBill(page, tag);
  const { panel, url } = await aLinkFrom(page, bill.id);
  expect(url).toContain("/pay/");

  const { context, page: theirs } = await aStranger(browser);
  await theirs.goto(url);

  await expect(theirs.getByRole("heading", { level: 1 })).toContainText("Sunrise");
  await expect(theirs.getByText(patient.full_name)).toBeVisible();
  await expect(theirs.getByText("₹450.00").first()).toBeVisible();
  await expect(theirs.getByRole("button", { name: /^Pay ₹450\.00/ })).toBeEnabled();
  // Nothing about them beyond the name on the bill.
  await expect(theirs.locator("body")).not.toContainText(patient.phone);

  await page.reload();
  await expect(panel).toContainText("waiting to be paid");
  // The desk can tell it was looked at, which is what decides whether to chase.
  await expect(panel).not.toContainText("Not yet");

  await context.close();
});

test("a patient pays from their phone and the bill settles itself", async ({
  page,
  browser,
  tag,
}) => {
  const { bill } = await anIssuedBill(page, tag);
  const { url, token } = await aLinkFrom(page, bill.id);

  const { context, page: theirs } = await aStranger(browser);
  const opened = await theirs.request.get(`/api/v1/pay/${token}`);
  const order = (await opened.json()).data.order_id as string;
  const payment = await paidAtTheGateway(order);

  // The checkout, standing in for the real one, reporting what it reports.
  await theirs.addInitScript(
    (told) => {
      class FakeCheckout {
        constructor(private options: { handler: (reported: unknown) => void }) {}
        on() {}
        open() {
          this.options.handler(told);
        }
      }
      (window as unknown as { Razorpay: unknown }).Razorpay = FakeCheckout;
    },
    signedHandshake(order, payment.id),
  );

  await theirs.goto(url);
  await theirs.getByRole("button", { name: /^Pay ₹450\.00/ }).click();

  await expect(theirs.getByRole("heading", { name: "Paid" })).toBeVisible();
  await expect(theirs.getByText("Nothing more is owed on this bill")).toBeVisible();
  await expect(theirs.getByRole("button", { name: /^Pay/ })).toHaveCount(0);

  // And at the desk, without anybody there touching anything.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Paid");
  await expect(page.getByRole("article")).toContainText("Paid online, UPI");
  await expect(page.getByRole("region", { name: "Pay from a phone" })).toContainText(
    "paid online",
  );

  await context.close();
});

test("the gateway's own word settles a bill nobody came back to", async ({
  page,
  browser,
  tag,
}) => {
  const { bill } = await anIssuedBill(page, tag);
  const { token } = await aLinkFrom(page, bill.id);

  // The patient opens the link, pays, and their phone dies on the way home.
  const { context, page: theirs } = await aStranger(browser);
  const opened = await theirs.request.get(`/api/v1/pay/${token}`);
  const order = (await opened.json()).data.order_id as string;
  const payment = await paidAtTheGateway(order, { method: "card" });
  await context.close();

  const body = JSON.stringify({
    event: "payment.captured",
    payload: { payment: { entity: payment } },
  });
  const told = await page.request.post("/api/v1/pay/webhook/razorpay", {
    data: body,
    headers: {
      "Content-Type": "application/json",
      "X-Razorpay-Signature": createHmac("sha256", settings().hookSecret)
        .update(body)
        .digest("hex"),
    },
  });
  expect(told.ok(), await told.text()).toBeTruthy();

  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Paid");
  await expect(page.getByRole("article")).toContainText("Paid online, Card");
});

test("a link that is called off stops working", async ({ page, browser, tag }) => {
  const { bill } = await anIssuedBill(page, tag);
  const { panel, url } = await aLinkFrom(page, bill.id);

  await panel.getByRole("button", { name: "Call it off" }).click();
  await expect(panel).toContainText("closed");

  const { context, page: theirs } = await aStranger(browser);
  await theirs.goto(url);

  await expect(theirs.getByRole("heading", { name: "Nothing to pay here" })).toBeVisible();
  await expect(theirs.getByRole("button", { name: /^Pay/ })).toHaveCount(0);
  await context.close();
});

test("a bill paid at the desk closes the link the patient holds", async ({
  page,
  browser,
  tag,
}) => {
  const { bill } = await anIssuedBill(page, tag);
  const { url } = await aLinkFrom(page, bill.id);

  await page.getByRole("button", { name: /^Take ₹450\.00/ }).click();
  await expect(page.getByText("Paid in full")).toBeVisible();

  const { context, page: theirs } = await aStranger(browser);
  await theirs.goto(url);

  await expect(theirs.getByRole("heading", { name: "Nothing to pay here" })).toBeVisible();
  await expect(theirs.getByText(/settled at the clinic/)).toBeVisible();
  await context.close();
});

test("a link that was never real says so", async ({ browser }) => {
  const { context, page: theirs } = await aStranger(browser);

  await theirs.goto("/pay/thisisnotarealpaymentlinkatall");

  await expect(theirs.getByRole("heading", { name: "That link is not valid" })).toBeVisible();
  await expect(theirs.getByText(/Nothing has been charged/)).toBeVisible();
  await context.close();
});

test("a payment the gateway will not vouch for is not claimed as paid", async ({
  page,
  browser,
  tag,
}) => {
  const { bill } = await anIssuedBill(page, tag);
  const { url, token } = await aLinkFrom(page, bill.id);

  const { context, page: theirs } = await aStranger(browser);
  const opened = await theirs.request.get(`/api/v1/pay/${token}`);
  const order = (await opened.json()).data.order_id as string;
  const payment = await paidAtTheGateway(order);

  await theirs.addInitScript(
    (told) => {
      class FakeCheckout {
        constructor(private options: { handler: (reported: unknown) => void }) {}
        on() {}
        open() {
          this.options.handler(told);
        }
      }
      (window as unknown as { Razorpay: unknown }).Razorpay = FakeCheckout;
      // A real payment, reported with a signature nobody could have made.
    },
    signedHandshake(order, payment.id, "not-the-secret"),
  );

  await theirs.goto(url);
  await theirs.getByRole("button", { name: /^Pay ₹450\.00/ }).click();

  await expect(theirs.getByRole("status")).toContainText("not been able to confirm");
  await page.reload();
  await expect(page.getByText("Unpaid", { exact: true })).toBeVisible();
  await context.close();
});
