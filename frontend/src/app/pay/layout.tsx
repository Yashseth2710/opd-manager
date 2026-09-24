import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Pay your bill",
  description: "Settle a clinic bill by UPI or card.",
  // A bill is nobody's business but the patient's, and the address carries
  // the token that opens it.
  robots: { index: false, follow: false },
};

/**
 * The one screen somebody sees without an account. No navigation, nothing to
 * click away to: they came here to pay a bill and leave.
 */
export default function PayLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-10">
      <main className="w-full max-w-[26rem]">{children}</main>
    </div>
  );
}
