import { parseCard } from "@/lib/poker";

type Size = "xs" | "sm" | "md" | "lg";
const SIZES: Record<Size, string> = {
  xs: "w-5 h-7 text-[10px] rounded-sm",
  sm: "w-7 h-10 text-[11px] rounded",
  md: "w-10 h-14 text-sm rounded-md",
  lg: "w-12 h-[4.25rem] text-base rounded-md sm:w-14 sm:h-20 sm:text-lg",
};

export function Card({ card, size = "md", dim = false, highlight = false }:
  { card: string; size?: Size; dim?: boolean; highlight?: boolean }) {
  const c = parseCard(card);
  return (
    <div
      aria-label={`${c.rank}${c.symbol}`}
      className={`${SIZES[size]} relative flex shrink-0 flex-col items-center justify-center bg-white font-semibold leading-none shadow ${
        c.red ? "text-red-600" : "text-neutral-900"} ${dim ? "opacity-40" : ""} ${
        highlight ? "ring-2 ring-chip" : ""}`}
    >
      <span>{c.rank}</span>
      <span className="mt-0.5">{c.symbol}</span>
    </div>
  );
}

export function CardBack({ size = "sm" }: { size?: Size }) {
  return (
    <div
      aria-label="hidden card"
      className={`${SIZES[size]} shrink-0 border border-white/30 bg-[repeating-linear-gradient(45deg,#7f1d1d_0_4px,#991b1b_4px_8px)] shadow`}
    />
  );
}

export function EmptyCard({ size = "md" }: { size?: Size }) {
  return <div className={`${SIZES[size]} shrink-0 border border-dashed border-white/15`} />;
}
