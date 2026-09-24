import { post, request } from "@/lib/api";
import type { LinkStatus } from "@/lib/billing";

/**
 * The bill as the person holding a link sees it. Deliberately thin: enough
 * to know the bill is theirs and what is owed, and nothing else about them.
 */
export type PayView = {
  clinic: string;
  clinic_phone: string | null;
  patient_name: string;
  invoice_number: string | null;
  issued_on: string | null;
  amount: string;
  currency: string;
  status: LinkStatus;
  expires_at: string;
  paid_at: string | null;
  /** Both are meant to be public; the secret half never leaves the server. */
  key_id: string | null;
  order_id: string | null;
};

/** What the checkout hands back once a payment goes through. */
export type Handshake = {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
};

export const openBill = (token: string) =>
  request<PayView>(`/pay/${encodeURIComponent(token)}`);

export const confirmPayment = (token: string, handshake: Handshake) =>
  post<PayView>(`/pay/${encodeURIComponent(token)}/confirm`, handshake);

export const CHECKOUT_SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

type CheckoutOptions = {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  prefill: { name: string };
  theme: { color: string };
  handler: (handshake: Handshake) => void;
  modal: { ondismiss: () => void };
};

type Checkout = {
  open: () => void;
  on: (event: string, listener: (payload: unknown) => void) => void;
};

declare global {
  interface Window {
    Razorpay?: new (options: CheckoutOptions) => Checkout;
  }
}

/**
 * Loads the gateway's checkout once and keeps it. It is fetched from their
 * own domain rather than bundled, because they change it under us and a copy
 * pinned here would stop working the day a bank does.
 */
export function loadCheckout(): Promise<void> {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (window.Razorpay) return Promise.resolve();

  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${CHECKOUT_SCRIPT}"]`,
    );
    const script = existing ?? document.createElement("script");
    script.addEventListener("load", () => resolve());
    script.addEventListener("error", () => reject(new Error("checkout did not load")));
    if (!existing) {
      script.src = CHECKOUT_SCRIPT;
      script.async = true;
      document.body.appendChild(script);
    }
  });
}

export type { CheckoutOptions };
