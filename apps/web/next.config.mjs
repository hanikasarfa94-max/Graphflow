/** @type {import('next').NextConfig} */
// Proxy /api/* and /ws/* to the FastAPI backend so the browser talks to one
// origin. Same-origin keeps session cookies simple and sidesteps CORS for
// SSE/WebSocket. API_BASE defaults to the dev backend on :8000.
const API_BASE = process.env.WORKGRAPH_API_BASE ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  // Standalone output ships a minimal node_modules graph with .next/standalone,
  // which is what the Dockerfile copies. Without this, `next start` needs the
  // full repo.
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_BASE}/api/:path*` },
      { source: "/ws/:path*", destination: `${API_BASE}/ws/:path*` },
    ];
  },
};

export default nextConfig;
