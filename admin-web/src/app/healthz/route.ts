// Static liveness check for the container health check (Detailed Design 4.8).
export const dynamic = "force-static";

export function GET(): Response {
  return Response.json({ status: "ok" });
}
