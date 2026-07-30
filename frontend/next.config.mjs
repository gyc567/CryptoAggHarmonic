/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const apiBase = process.env.BACKEND_API_BASE || "http://127.0.0.1:5000";
    return [
      { source: "/api/health", destination: `${apiBase}/api/health` },
      { source: "/api/markets", destination: `${apiBase}/api/markets` },
      { source: "/api/analyze", destination: `${apiBase}/api/analyze` },
      { source: "/api/history", destination: `${apiBase}/api/history` },
      { source: "/api/analysis/:path*", destination: `${apiBase}/api/analysis/:path*` },
      
      { source: "/api/vibe/:path*", destination: `${apiBase}/api/vibe/:path*` },
      { source: "/api/rsi-trend/:path*", destination: `${apiBase}/api/rsi-trend/:path*` },
    ];
  },
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
