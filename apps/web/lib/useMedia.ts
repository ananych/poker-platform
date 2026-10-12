"use client";

import { useEffect, useState } from "react";

export function useMedia(query: string, initial = false) {
  const [match, setMatch] = useState(initial);
  useEffect(() => {
    const m = window.matchMedia(query);
    const f = () => setMatch(m.matches);
    f();
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, [query]);
  return match;
}
