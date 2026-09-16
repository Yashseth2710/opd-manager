import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // next dev writes agent instruction files into the repo root by default.
  agentRules: false,
  typedRoutes: true,
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
