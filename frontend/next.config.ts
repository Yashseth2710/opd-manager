import type { NextConfig } from "next";

const developing = process.env.NODE_ENV === "development";

// Razorpay's checkout is the one thing a page loads from anywhere else: its
// script, the window it opens, and the calls that window makes.
const RAZORPAY = "https://*.razorpay.com";

/**
 * What a page may load. Scripts are the application's own, inline ones
 * included since Next hydrates through them, plus the checkout. The
 * development server alone may evaluate code, which it needs to reload
 * a page as it is edited, and talk over a socket to do so.
 */
const POLICY = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' ${RAZORPAY}${developing ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  `connect-src 'self' ${RAZORPAY}${developing ? " ws: wss:" : ""}`,
  // A PDF on the record is shown from a blob the page fetched for itself.
  `frame-src 'self' blob: ${RAZORPAY}`,
  "object-src 'none'",
  "base-uri 'self'",
  `form-action 'self' ${RAZORPAY}`,
  "frame-ancestors 'none'",
].join("; ");

const HEADERS = [
  { key: "Content-Security-Policy", value: POLICY },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value:
      'camera=(), microphone=(), geolocation=(), payment=(self "https://api.razorpay.com")',
  },
  ...(developing
    ? []
    : [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }]),
];

const config: NextConfig = {
  reactStrictMode: true,
  // next dev writes agent instruction files into the repo root by default.
  agentRules: false,
  typedRoutes: true,
  poweredByHeader: false,
  async headers() {
    // The API sets its own, and in development it is reached through here.
    return [{ source: "/((?!api/).*)", headers: HEADERS }];
  },
  async rewrites() {
    // In development the Python API runs as a separate process. On Vercel the
    // routing in vercel.json sends these straight to the serverless function.
    if (process.env.NODE_ENV !== "development") return [];
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.API_ORIGIN ?? "http://127.0.0.1:8000"}/api/v1/:path*`,
      },
    ];
  },
};

export default config;
