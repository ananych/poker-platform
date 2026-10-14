"use client";

import { useEffect } from "react";
import { UpdateBanner } from "@/components/UpdateBanner";
import { I18nProvider } from "@/lib/i18n";
import { unlockAudio } from "@/lib/sound";

export function Providers({ children }: { children: React.ReactNode }) {
  // Browsers only start audio after a user gesture: unlock on the first tap/key.
  useEffect(() => {
    const go = () => unlockAudio();
    window.addEventListener("pointerdown", go, { passive: true });
    window.addEventListener("keydown", go);
    return () => {
      window.removeEventListener("pointerdown", go);
      window.removeEventListener("keydown", go);
    };
  }, []);
  return <I18nProvider>{children}<UpdateBanner /></I18nProvider>;
}
