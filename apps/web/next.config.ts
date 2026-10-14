import type { NextConfig } from "next";
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

// Release info baked into the bundle (shown in the UI; see lib/version.ts).
// Railway passes RAILWAY_GIT_COMMIT_SHA as a build arg on GitHub deploys; locally we ask git.
const pkg = JSON.parse(readFileSync(path.join(process.cwd(), "package.json"), "utf8")) as { version: string };
function buildSha(): string {
  const env = process.env.RAILWAY_GIT_COMMIT_SHA || process.env.GIT_COMMIT_SHA;
  if (env) return env.slice(0, 7);
  try {
    return execSync("git rev-parse --short=7 HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return "";
  }
}

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "";
const apiWs = apiBase.replace(/^http/, "ws");
const isProd = process.env.NODE_ENV === "production";

// SDD §12: secure headers. Same-origin deployment (reverse proxy) needs only 'self'.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProd ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  ["connect-src 'self'", apiBase, apiWs, apiBase ? "" : "ws: wss:"].filter(Boolean).join(" "),
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  env: {
    NEXT_PUBLIC_APP_VERSION: pkg.version,
    NEXT_PUBLIC_BUILD_SHA: buildSha(),
    NEXT_PUBLIC_BUILD_TIME: new Date().toISOString(),
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "Content-Security-Policy", value: csp },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "same-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
};

export default nextConfig;
