/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Keep standalone tracing inside this UI project. The workspace contains
  // other lockfiles above it, and allowing Next to infer the parent root can
  // make builds inspect unrelated paths.
  outputFileTracingRoot: process.cwd(),
  reactStrictMode: true,
  // Proxy /api/* to the FastAPI backend.
  //
  // IMPORTANT: rewrites() runs at BUILD time in standalone output. The
  // resolved target string is baked into the manifest — runtime env changes
  // do nothing here. So BW_API_URL must be set at `npm run build` time,
  // typically via a Docker build ARG (see Dockerfile).
  //
  // The fallback intentionally uses the docker-compose service hostname
  // `app:8000`, not localhost, because ~all deploys are docker-compose. If
  // you're running Next locally without docker, set BW_API_URL=http://localhost:8000.
  async rewrites() {
    const target = process.env.BW_API_URL || "http://app:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${target}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
