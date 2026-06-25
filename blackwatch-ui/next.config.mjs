/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Proxy /api/* to the FastAPI backend.
  // In docker-compose, BW_API_URL=http://app:8000. Local dev defaults to localhost.
  async rewrites() {
    const target = process.env.BW_API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${target}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
