// Server-side IP intelligence aggregator. The ip-api.com fast path remains
// useful without credentials; optional threat providers are isolated so one
// missing key or rate limit never hides the base lookup.

import { NextResponse } from "next/server";

import { buildIpLookupResponse, fetchIpApi } from "@/lib/ip-intelligence-server";
import { isValidObservable } from "@/lib/ip-intelligence";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const observable = (searchParams.get("ip") ?? "").trim();
  if (!observable) {
    return NextResponse.json(
      { status: "fail", message: "missing ip query param" },
      { status: 400 },
    );
  }
  if (!isValidObservable(observable)) {
    return NextResponse.json(
      { status: "fail", message: "ip must be a valid IPv4, IPv6, or hostname" },
      { status: 400 },
    );
  }

  try {
    const base = await fetchIpApi(observable);
    const result = await buildIpLookupResponse(observable, base, request);
    return NextResponse.json(result, {
      headers: { "Cache-Control": "private, max-age=300" },
    });
  } catch {
    return NextResponse.json(
      {
        status: "fail",
        message: "IP intelligence lookup failed or timed out",
        providers: [],
        indicators: [],
        observedEvents: [],
        investigationStatus: "error",
      },
      { status: 502 },
    );
  }
}
