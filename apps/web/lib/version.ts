"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "./api";

/** What this bundle was built from (inlined at build time by next.config.ts). */
export const BUILD = {
  version: process.env.NEXT_PUBLIC_APP_VERSION ?? "0.0.0",
  sha: process.env.NEXT_PUBLIC_BUILD_SHA ?? "",
  time: process.env.NEXT_PUBLIC_BUILD_TIME ?? "",
};

export interface VersionInfo { version: string; commit: string }

export function versionLabel(v: VersionInfo | null | undefined): string {
  if (!v) return "…";
  return v.commit && v.commit !== "dev" ? `v${v.version} · ${v.commit}` : `v${v.version}`;
}

export async function fetchWebVersion(): Promise<VersionInfo | null> {
  try {
    const r = await fetch("/version", { cache: "no-store" });
    return r.ok ? ((await r.json()) as VersionInfo) : null;
  } catch {
    return null;
  }
}

export async function fetchApiVersion(): Promise<VersionInfo | null> {
  try {
    const r = await fetch(`${API_BASE}/api/v1/version`, { cache: "no-store" });
    return r.ok ? ((await r.json()) as VersionInfo) : null;
  } catch {
    return null;
  }
}

/** Web (this bundle) + API versions for display. */
export function useVersions() {
  const [runtimeWeb, setRuntimeWeb] = useState<VersionInfo | null>(null);
  const [api, setApi] = useState<VersionInfo | null>(null);
  useEffect(() => {
    void fetchWebVersion().then(setRuntimeWeb);
    void fetchApiVersion().then(setApi);
  }, []);
  // prefer the id baked into the bundle; fall back to what the server reported at load
  const web: VersionInfo = BUILD.sha
    ? { version: BUILD.version, commit: BUILD.sha }
    : runtimeWeb ?? { version: BUILD.version, commit: "" };
  const mismatch = !!api && !!web.commit && api.commit !== "dev" && web.commit !== "dev"
    && api.commit !== web.commit;
  return { web, api, mismatch };
}
