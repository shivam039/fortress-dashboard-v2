import type { NextConfig } from "next";

const backendUrl =
  process.env.BACKEND_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Next.js 16 already uses Turbopack by default for `next dev`, but every
  // route still compiles on-demand the *first* time you navigate to it in a
  // given dev-server run, and that in-memory compile cache is thrown away
  // every time the dev server restarts (which happens a lot: any edited
  // file under a watched dependency, e.g. a pip-installed package touched
  // during setup, triggers a reload). That "first click on a tab after a
  // restart" recompile is the most likely cause of "switching tabs is
  // slow" — this persists Turbopack's compiled output to disk so restarts
  // don't pay the full recompile cost again. Still beta as of Next 16.3.
  experimental: {
    turbopackFileSystemCacheForDev: true,
  },
  async rewrites() {
    return backendUrl
      ? [
          {
            source: "/api/:path*",
            destination: `${backendUrl}/api/:path*`,
          },
          {
            source: "/mf/:path*",
            destination: `${backendUrl}/mf/:path*`,
          },
        ]
      : [];
  },
};

export default nextConfig;
