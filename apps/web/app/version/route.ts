// GET /version — which web build this server runs. Read at request time, so an open
// tab can notice a newer deploy (see components/UpdateBanner.tsx).
export const dynamic = "force-dynamic";

export function GET() {
  const runtime = (process.env.RAILWAY_GIT_COMMIT_SHA ?? "").slice(0, 7);
  return Response.json(
    {
      version: process.env.NEXT_PUBLIC_APP_VERSION ?? "0.0.0",
      commit: runtime || process.env.NEXT_PUBLIC_BUILD_SHA || "dev",
      built_at: process.env.NEXT_PUBLIC_BUILD_TIME ?? null,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
