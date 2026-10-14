"use client";

import { useEffect, useState } from "react";
import { useT } from "@/lib/i18n";
import { BUILD, fetchWebVersion, versionLabel, type VersionInfo } from "@/lib/version";

/**
 * Tabs stay open for hours at a poker table. When a newer web build is deployed,
 * offer a one-tap reload instead of letting the page drift out of date.
 */
export function UpdateBanner() {
  const { t } = useT();
  const [newer, setNewer] = useState<VersionInfo | null>(null);
  useEffect(() => {
    let base: string | null = BUILD.sha || null;
    const check = async () => {
      const v = await fetchWebVersion();
      if (!v?.commit || v.commit === "dev") return;
      if (base === null) { base = v.commit; return; }
      if (v.commit !== base) setNewer(v);
    };
    void check();
    const timer = setInterval(check, 120_000);
    const onVisible = () => { if (document.visibilityState === "visible") void check(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, []);
  if (!newer) return null;
  return (
    <button type="button" onClick={() => window.location.reload()} role="status"
            className="fixed inset-x-0 top-0 z-[60] flex min-h-9 items-center justify-center gap-2 bg-amber-500 px-3 py-1.5 text-center text-sm font-semibold text-black shadow-lg pt-[max(0.375rem,env(safe-area-inset-top))]">
      ⟳ {t("ver.update", { v: versionLabel(newer) })}
    </button>
  );
}
