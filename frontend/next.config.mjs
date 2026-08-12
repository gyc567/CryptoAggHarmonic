/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const apiBase = process.env.BACKEND_API_BASE || "http://127.0.0.1:5000";
    return [
      { source: "/api/health", destination: `${apiBase}/api/health` },
      { source: "/api/markets", destination: `${apiBase}/api/markets` },
      { source: "/api/markets/futures/symbols", destination: `${apiBase}/api/markets/futures/symbols` },
      { source: "/api/markets/futures/quote", destination: `${apiBase}/api/markets/futures/quote` },
      { source: "/api/analyze", destination: `${apiBase}/api/analyze` },
      { source: "/api/history", destination: `${apiBase}/api/history` },
      { source: "/api/analysis/:path*", destination: `${apiBase}/api/analysis/:path*` },
      { source: "/api/watchlist", destination: `${apiBase}/api/watchlist` },
      { source: "/api/watchlist/:path*", destination: `${apiBase}/api/watchlist/:path*` },
      { source: "/api/admin/markets/futures/refresh", destination: `${apiBase}/api/admin/markets/futures/refresh` },

      { source: "/api/vibe/:path*", destination: `${apiBase}/api/vibe/:path*` },
      { source: "/api/rsi-trend/:path*", destination: `${apiBase}/api/rsi-trend/:path*` },

      // Loop #13 — FT Strategy UI (Phase 4)
      { source: "/api/ft-strategies", destination: `${apiBase}/api/ft-strategies` },
      { source: "/api/ft-strategies/:path*", destination: `${apiBase}/api/ft-strategies/:path*` },
    ];
  },
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
