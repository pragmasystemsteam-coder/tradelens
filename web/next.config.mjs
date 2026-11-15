/** @type {import('next').NextConfig} */
// In production Caddy routes /api/* to the API on the same host (Detailed Design 6.7).
// For local runs and E2E, API_INTERNAL_URL makes Next proxy /api/* to the API instead.
const apiUrl = process.env.API_INTERNAL_URL;

const nextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return apiUrl ? [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }] : [];
  },
};

export default nextConfig;
