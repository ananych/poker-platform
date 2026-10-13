/**
 * Table geometry computed from the space actually available (ResizeObserver),
 * so seats never get clipped by the container and rarely overlap — on a 320px
 * phone, a landscape phone, a portrait tablet or a 4K monitor alike.
 *
 * Everything is in CSS pixels relative to the table container.
 */

export interface SeatSpot { x: number; y: number; angle: number }
export interface TableGeom {
  w: number;
  h: number;
  compact: boolean;
  seatW: number;
  felt: { cx: number; cy: number; rx: number; ry: number };
  seats: Record<number, SeatSpot>;
  /** where each seat's current-street bet sits: just in front of the seat */
  bets: Record<number, { x: number; y: number }>;
  boardCard: "sm" | "md" | "lg";
}

const SEATS = 9;
const PAD = 4;

/** Approximate ellipse perimeter (Ramanujan). */
function perimeter(a: number, b: number) {
  return Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)));
}

/**
 * `n` points evenly spaced by arc length (not by angle) around an ellipse,
 * starting at the bottom and going clockwise on screen. Equal-angle spacing
 * crowds the ends of a wide/tall ellipse; equal arc length does not.
 */
function evenOnEllipse(rx: number, ry: number, n: number): number[] {
  const N = 720;
  const acc = [0];
  let px = rx * Math.cos(Math.PI / 2), py = ry * Math.sin(Math.PI / 2);
  for (let i = 1; i <= N; i++) {
    const a = Math.PI / 2 + (i * 2 * Math.PI) / N;
    const x = rx * Math.cos(a), y = ry * Math.sin(a);
    acc.push(acc[i - 1] + Math.hypot(x - px, y - py));
    px = x; py = y;
  }
  const total = acc[N];
  const angles: number[] = [];
  let j = 0;
  for (let k = 0; k < n; k++) {
    const target = (k * total) / n;
    while (j < N && acc[j + 1] < target) j++;
    const f = acc[j + 1] === acc[j] ? 0 : (target - acc[j]) / (acc[j + 1] - acc[j]);
    angles.push(Math.PI / 2 + ((j + f) * 2 * Math.PI) / N);
  }
  return angles;
}

export function tableLayout(w: number, h: number, mySeat: number | null): TableGeom {
  const compact = w < 460 || h < 440;
  // seat card height (excluding hole cards) and how far cards/badges stick out
  const seatH = compact ? 62 : 84;
  const extentY = compact ? seatH / 2 + 26 : (seatH + 44) / 2 + 8;
  let seatW = compact ? 80 : w >= 900 && h >= 600 ? 128 : 108;

  let rx = 0, ry = 0;
  for (let i = 0; i < 2; i++) {
    rx = Math.max(30, w / 2 - seatW / 2 - PAD);
    ry = Math.max(30, h / 2 - extentY - PAD);
    if (!compact) break;
    // shrink compact seats when the ring is too short for nine of them
    const per = perimeter(rx, ry) / SEATS;
    seatW = Math.max(64, Math.min(80, per - 6));
  }

  const anchor = mySeat ?? 1;
  const angles = evenOnEllipse(rx, ry, SEATS);
  const seats: Record<number, SeatSpot> = {};
  const bets: Record<number, { x: number; y: number }> = {};
  for (let n = 1; n <= SEATS; n++) {
    const idx = (n - anchor + SEATS) % SEATS;
    const angle = angles[idx];
    const x = w / 2 + rx * Math.cos(angle), y = h / 2 + ry * Math.sin(angle);
    seats[n] = { x, y, angle };
    // bet chip: step from the seat toward the middle until just clear of the seat box
    const dx = w / 2 - x, dy = h / 2 - y, len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;
    const halfW = seatW / 2;
    // compact: hug the seat (the chip may overlap the tucked-in card backs a little)
    const halfH = compact ? seatH / 2 + (uy < 0 ? 6 : 12) : (seatH + 44) / 2 + (uy > 0 ? 10 : 0);
    const step = Math.min(len * 0.7, halfW * Math.abs(ux) + halfH * Math.abs(uy) + 14);
    bets[n] = { x: x + ux * step, y: y + uy * step };
  }

  // the felt sits just inside the ring of seats (seats overlap the rail a bit)
  const felt = {
    cx: w / 2,
    cy: h / 2,
    rx: Math.max(40, rx - seatW * 0.12),
    ry: Math.max(40, ry - seatH * 0.18),
  };
  const boardCard = compact ? "sm"
    : felt.rx * 2 * 0.6 >= 300 && felt.ry * 2 >= 300 ? "lg"
    : felt.rx * 2 * 0.8 >= 226 && felt.ry * 2 >= 200 ? "md" : "sm";
  return { w, h, compact, seatW, felt, seats, bets, boardCard };
}
