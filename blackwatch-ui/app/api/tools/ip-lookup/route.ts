// Next.js Route Handler — proxies the ip-api.com lookup so the client-side
// IpLookupModal has a same-origin JSON endpoint to fetch. Avoids exposing the
// upstream URL to the browser and lets us centralize rate-limit handling
// later if needed.

import { NextResponse } from "next/server";

const IPAPI_FIELDS = [
  "status", "message", "query",
  "country", "countryCode",
  "region", "regionName", "city", "zip",
  "lat", "lon",
  "timezone",
  "isp", "org", "as", "asname",
  "reverse",
  "mobile", "proxy", "hosting",
].join(",");

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const ip = (searchParams.get("ip") ?? "").trim();
  if (!ip) {
    return NextResponse.json(
      { status: "fail", message: "missing ip query param" },
      { status: 400 },
    );
  }
  try {
    const upstream = await fetch(
      `http://ip-api.com/json/${encodeURIComponent(ip)}?fields=${IPAPI_FIELDS}`,
      { cache: "no-store" },
    );
    if (!upstream.ok) {
      return NextResponse.json(
        { status: "fail", message: `upstream HTTP ${upstream.status}` },
        { status: 502 },
      );
    }
    const data = await upstream.json();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (exc) {
    return NextResponse.json(
      { status: "fail", message: String(exc) },
      { status: 502 },
    );
  }
}
