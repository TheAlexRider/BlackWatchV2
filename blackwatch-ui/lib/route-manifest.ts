export type RouteKind = "canonical" | "detail" | "compatibility";

export type RouteEntry = {
  path: string;
  kind: RouteKind;
  destination?: string;
};

/** Product-owned routes that may be referenced by internal navigation. */
export const ROUTE_MANIFEST: readonly RouteEntry[] = [
  { path: "/notifications", kind: "canonical" },
  { path: "/notifications/create", kind: "canonical" },
  { path: "/notifications/create/event", kind: "canonical" },
  { path: "/notifications/rules/new", kind: "canonical" },
  { path: "/notifications/rules/[id]/edit", kind: "canonical" },
  { path: "/notifications/channels/new", kind: "canonical" },
  { path: "/notifications/channels/[id]", kind: "detail" },
  { path: "/notifications/log", kind: "canonical" },
  { path: "/notifications/profiles", kind: "canonical" },
  { path: "/notifications/profiles/[id]", kind: "detail" },
  { path: "/investigations", kind: "canonical" },
  { path: "/investigations/[id]", kind: "detail" },
  { path: "/tools/ip-lookup", kind: "canonical" },
  { path: "/events/[id]", kind: "detail" },
  { path: "/notifications/rules/[id]", kind: "compatibility", destination: "/notifications/rules/[id]/edit" },
  { path: "/notifications/routing", kind: "compatibility", destination: "/notifications" },
  { path: "/notifications/perf-alerts/quick", kind: "compatibility", destination: "/notifications" },
];

export const CANONICAL_NOTIFICATION_ROUTE = "/notifications";

