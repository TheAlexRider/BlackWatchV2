"""Discover everything BlackWatch's ECS probe needs to monitor your services.

For each cluster you pass, this script:
  1. Reads the existing services' networkConfiguration -> subnets + SGs
     (so the probe agent runs on the same network plumbing as your services)
  2. Reads each service's task definition -> port mappings + service registries
  3. Categorizes each service by tier based on its exposed ports:
        - http_alive  -> HTTP-looking port (80/8080/8000/3000/etc.)
        - tcp         -> database / queue port (5432/3306/27017/9200/etc.)
        - ecs_running -> no exposed port (background workers)
  4. Tries to derive an internal URL/hostname from Cloud Map service discovery.
     If none configured, falls back to the service name and FLAGS for review.
  5. Prints:
        a. PowerShell `$env:*` block for setup.ps1 (one per cluster)
        b. A summary so you can sanity-check before doing anything

  --emit-ssm: in addition, writes each VPC's target list straight into the
  corresponding SSM parameter (`/blackwatch/ecs-probe/<vpc>/targets`). The
  in-VPC probe agent reads that parameter every TARGETS_REFRESH_SEC seconds,
  so updating the parameter is the entire "refresh targets" workflow -- no
  task-def re-register, no service redeploy.

Usage:
    python -m scripts.ecs_discover --cluster development-cluster:dev --cluster production-cluster:prod --region us-west-1 --emit-ssm
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import uuid
from collections import defaultdict
from typing import Any

# Force UTF-8 stdout — Windows console (cp1252) chokes on common chars like →.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # py 3.7+
except (AttributeError, OSError):
    pass

# --- Port -> tier heuristics --------------------------------------------------
_HTTP_PORTS = {80, 443, 3000, 4000, 4200, 5000, 5173, 8000, 8001,
               8080, 8081, 8088, 8090, 8443, 8888, 9000, 9090}
_TCP_PORTS = {
    1433,                 # MSSQL
    1521,                 # Oracle
    2049,                 # NFS
    3306,                 # MySQL
    5432,                 # Postgres
    5672, 15672,          # RabbitMQ (AMQP + mgmt)
    5701,                 # Hazelcast
    6379,                 # Redis
    7000, 7001, 9042,     # Cassandra
    9092, 2181,           # Kafka / Zookeeper
    9200, 9300,           # Elasticsearch
    11211,                # memcached
    27017, 27018,         # MongoDB
}

# Severity defaults — operator can override per-row before importing.
_DEFAULT_SEVERITY = {
    "prod_api":      "critical",
    "prod_db":       "critical",
    "prod_worker":   "high",
    "prod_other":    "high",
    "dev_api":       "high",
    "dev_db":        "high",
    "dev_worker":    "medium",
    "dev_other":     "medium",
    "other":         "medium",
}


def _tier_for_port(port: int) -> str:
    if port in _HTTP_PORTS:
        return "http_alive"
    if port in _TCP_PORTS:
        return "tcp"
    # Default unknown numeric ports to TCP — at least we know it accepts
    # connections. Better than ecs_running for services that DO expose a port.
    return "tcp"


def _is_worker(name: str) -> bool:
    return bool(re.search(r"(worker|processor|handler|consumer|ingest)", name, re.I))


def _is_api(name: str) -> bool:
    return bool(re.search(r"(api|backend|frontend|portal|web|gateway)", name, re.I))


def _is_db(name: str) -> bool:
    return bool(re.search(r"(database|^db|postgres|mysql|mongo|redis|search|chromadb|keycloak|sso)", name, re.I))


def _role_tag(name: str) -> str:
    if _is_db(name):      return "db"
    if _is_worker(name):  return "worker"
    if _is_api(name):     return "api"
    return "other"


def _severity(env: str, role: str) -> str:
    key = f"{env}_{role}"
    return _DEFAULT_SEVERITY.get(key, _DEFAULT_SEVERITY["other"])


def _yaml_escape(v: str) -> str:
    return v if re.match(r"^[A-Za-z0-9_./-]+$", v) else f'"{v}"'


def _resolve_cloudmap_dns(registry_arn: str, sd, ns_cache: dict[str, str]) -> str | None:
    """Turn a service-registry ARN into the actual DNS hostname the probe should
    use. Cloud Map private namespaces register `<service>.<namespace>` in the
    VPC's resolver, but the ECS API only exposes the registry ARN, so we have
    to follow it through servicediscovery to get the namespace name.

    Returns None if the ARN can't be resolved (rare -- usually means the
    service uses an A-record namespace we don't support yet)."""
    # registryArn: arn:aws:servicediscovery:region:acct:service/srv-xxxxx
    try:
        srv_id = registry_arn.rsplit("/", 1)[1]
    except IndexError:
        return None
    try:
        srv = sd.get_service(Id=srv_id).get("Service") or {}
    except Exception:
        return None
    ns_id = srv.get("NamespaceId")
    srv_name = srv.get("Name")
    if not ns_id or not srv_name:
        return None
    ns_name = ns_cache.get(ns_id)
    if ns_name is None:
        try:
            ns = sd.get_namespace(Id=ns_id).get("Namespace") or {}
            ns_name = ns.get("Name") or ""
            ns_cache[ns_id] = ns_name
        except Exception:
            ns_cache[ns_id] = ""
            return None
    if not ns_name:
        return None
    return f"{srv_name}.{ns_name}"


def discover(cluster: str, vpc: str, region: str) -> dict[str, Any]:
    """Returns a dict with: subnets, security_groups, targets (list of dicts)."""
    import boto3
    ecs = boto3.client("ecs", region_name=region)
    sd = boto3.client("servicediscovery", region_name=region)
    ns_cache: dict[str, str] = {}  # namespace id -> name, shared across the run

    arns = []
    paginator = ecs.get_paginator("list_services")
    for page in paginator.paginate(cluster=cluster):
        arns.extend(page.get("serviceArns", []))

    targets: list[dict[str, Any]] = []
    # Track subnets by VPC — some clusters span multiple VPCs (legacy services
    # in a separate VPC) and ECS rejects services with subnets from > 1 VPC.
    # We pick the VPC with the most subnets as the canonical one for the probe.
    subnets_by_vpc: defaultdict[str, set[str]] = defaultdict(set)
    # Count SG usage frequency — AWS limits a single service to 5 SGs, so we
    # pick the most-shared 5 (those are typically the cluster-wide "all tasks
    # talk to all tasks" SGs that the probe needs to reach every service).
    sg_freq: defaultdict[str, int] = defaultdict(int)
    # SG -> VPC index, so we can filter SGs to the chosen VPC after picking.
    sg_to_vpc: dict[str, str] = {}

    # Batch describe (max 10 per call).
    for i in range(0, len(arns), 10):
        chunk = arns[i:i + 10]
        services = ecs.describe_services(cluster=cluster, services=chunk).get("services", [])
        # Collect task def ARNs to batch-describe.
        td_arns = [s.get("taskDefinition") for s in services if s.get("taskDefinition")]
        td_map: dict[str, dict[str, Any]] = {}
        for td_arn in set(td_arns):
            td = ecs.describe_task_definition(taskDefinition=td_arn).get("taskDefinition", {})
            td_map[td_arn] = td

        for svc in services:
            name = svc["serviceName"]
            td = td_map.get(svc.get("taskDefinition"), {})

            # Network — capture subnets and SGs we'll reuse for the probe agent.
            netcfg = ((svc.get("networkConfiguration") or {})
                      .get("awsvpcConfiguration") or {})
            # Track raw subnets — VPC resolution happens in one batch call below.
            for s in netcfg.get("subnets", []):
                subnets_by_vpc["__unresolved__"].add(s)
            for s in netcfg.get("securityGroups", []):
                sg_freq[s] += 1

            # Ports — flatten across all container definitions.
            ports: list[int] = []
            for c in td.get("containerDefinitions", []) or []:
                for pm in c.get("portMappings", []) or []:
                    p = pm.get("containerPort")
                    if isinstance(p, int):
                        ports.append(p)
            ports = sorted(set(ports))

            # Cloud Map service discovery — resolves to the real DNS name the
            # probe should hit (e.g. `web-backend.dev.local`). Bare service
            # names don't resolve, so falling back to them would produce
            # uniformly DOWN targets.
            cloudmap_name: str | None = None
            for reg in svc.get("serviceRegistries") or []:
                arn = reg.get("registryArn")
                if not arn:
                    continue
                resolved = _resolve_cloudmap_dns(arn, sd, ns_cache)
                if resolved:
                    cloudmap_name = resolved
                    break

            tier = "ecs_running" if not ports else _tier_for_port(ports[0])
            role = _role_tag(name)
            sev = _severity(vpc, role)

            # Build a per-service target row.
            row: dict[str, Any] = {
                "name": name,
                "vpc": vpc,
                "tier": tier,
                "severity_when_down": sev,
                "tags": {"env": vpc, "role": role},
            }
            if tier == "http_alive":
                # Prefer Cloud Map name; fall back to bare service name (operator can fix).
                host = cloudmap_name or name
                port = ports[0]
                scheme = "https" if port in (443, 8443) else "http"
                row["config"] = {
                    "url": f"{scheme}://{host}:{port}/",
                    "timeout_seconds": 5,
                }
            elif tier == "tcp":
                host = cloudmap_name or name
                port = ports[0]
                row["config"] = {"host": host, "port": port, "timeout_seconds": 3}
            else:  # ecs_running — uses AWS API count check
                row["config"] = {"cluster": cluster, "service": name}

            targets.append(row)

    # Resolve subnet -> VPC in one batch call. ECS clusters sometimes span
    # multiple VPCs (legacy services left in the default VPC, etc.), and ECS
    # rejects a service with subnets from more than one VPC. We pick the VPC
    # with the MOST subnets as canonical.
    unresolved = subnets_by_vpc.pop("__unresolved__", set())
    if unresolved:
        ec2c = boto3.client("ec2", region_name=region)
        for batch_start in range(0, len(unresolved), 100):
            batch = list(unresolved)[batch_start:batch_start + 100]
            resp = ec2c.describe_subnets(SubnetIds=batch)
            for sn in resp.get("Subnets", []):
                subnets_by_vpc[sn["VpcId"]].add(sn["SubnetId"])
    # Pick the VPC with the most subnets as canonical.
    if subnets_by_vpc:
        canonical_vpc = max(subnets_by_vpc.items(), key=lambda kv: len(kv[1]))[0]
        canonical_subnets = sorted(subnets_by_vpc[canonical_vpc])
        dropped_vpcs = {v: sorted(s) for v, s in subnets_by_vpc.items() if v != canonical_vpc}
    else:
        canonical_vpc = ""
        canonical_subnets = []
        dropped_vpcs = {}

    # Resolve SGs to their VPC and keep only those in the canonical VPC.
    sg_in_canonical = sg_freq.copy()
    if sg_freq and canonical_vpc:
        ec2c = boto3.client("ec2", region_name=region)
        sg_ids = list(sg_freq.keys())
        for batch_start in range(0, len(sg_ids), 100):
            batch = sg_ids[batch_start:batch_start + 100]
            resp = ec2c.describe_security_groups(GroupIds=batch)
            for sg in resp.get("SecurityGroups", []):
                if sg["VpcId"] != canonical_vpc:
                    sg_in_canonical.pop(sg["GroupId"], None)

    # Top 5 most-shared SGs IN the canonical VPC (AWS limit per service = 5).
    top_sgs = [sg for sg, _n in sorted(sg_in_canonical.items(),
                                       key=lambda kv: (-kv[1], kv[0]))][:5]
    return {
        "vpc_id": canonical_vpc,
        "subnets": canonical_subnets,
        "security_groups": top_sgs,
        "sg_frequency": dict(sg_freq),
        "dropped_subnets_by_vpc": dropped_vpcs,  # info for the operator
        "targets": targets,
    }


def _emit_env_block(vpc: str, cluster: str, region: str, info: dict[str, Any]) -> str:
    subnets = ",".join(info["subnets"]) or "<SET MANUALLY>"
    sgs = ",".join(info["security_groups"]) or "<SET MANUALLY>"
    return textwrap.dedent(f"""
        # --- {vpc.upper()} ({cluster}) -----------------------------------------
        $env:VPC = "{vpc}"
        $env:VPC_REGION = "{region}"
        $env:CLUSTER = "{cluster}"
        $env:SUBNET_IDS = "{subnets}"
        $env:SECURITY_GROUP_IDS = "{sgs}"
        .\\deploy\\ecs\\setup.ps1
    """).strip()


def _ssm_payload(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape the targets list the way the in-VPC probe expects.

    The probe only reads id/name/tier/config to actually run checks. We also
    include vpc/tags/severity_when_down so the BW-side connector can mirror
    these into the probe_targets table (the UI and the notification routing
    both rely on those fields existing per-target). The probe itself ignores
    the extra keys -- they ride along but don't change probe behavior.

    Deterministic UUID per (vpc, name) keeps re-discovery from resetting IDs.
    """
    out: list[dict[str, Any]] = []
    for t in targets:
        if t["tier"] not in ("http_alive", "tcp"):
            continue  # ecs_running tier is handled by BW-side reader, not probe
        tid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bw-ecs-probe::{t['vpc']}::{t['name']}"))
        out.append({
            "id": tid,
            "name": t["name"],
            "vpc": t["vpc"],
            "tier": t["tier"],
            "config": t["config"],
            "tags": t.get("tags") or {},
            "severity_when_down": t.get("severity_when_down") or "medium",
        })
    return out


def _put_ssm_param(vpc: str, region: str, targets: list[dict[str, Any]]) -> None:
    """Write the targets JSON into /blackwatch/ecs-probe/<vpc>/targets."""
    import boto3
    ssm = boto3.client("ssm", region_name=region)
    name = f"/blackwatch/ecs-probe/{vpc}/targets"
    body = json.dumps(targets)
    if len(body) > 8 * 1024:
        # 4KB is Standard limit; Advanced extends to 8KB. Above that, the operator
        # needs to split or switch to S3-backed targets. Flag loudly.
        print(f"WARNING: targets payload for {vpc} is {len(body)} bytes -- exceeds 8KB SSM Advanced limit",
              file=sys.stderr)
    ssm.put_parameter(Name=name, Value=body, Type="String", Tier="Advanced", Overwrite=True)
    print(f"# Wrote {len(targets)} targets to {name} ({len(body)} bytes)", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cluster", action="append", required=True,
                   help="cluster:vpc_label  e.g.  development-cluster:dev")
    p.add_argument("--region", default="us-west-1")
    p.add_argument("--emit-ssm", action="store_true",
                   help="Also write each VPC's target list into its SSM parameter "
                        "(/blackwatch/ecs-probe/<vpc>/targets). Without this flag, "
                        "the script only prints what it would do.")
    args = p.parse_args()

    env_blocks: list[str] = []
    summaries: list[str] = []
    by_vpc_targets: dict[str, list[dict[str, Any]]] = {}

    for spec in args.cluster:
        if ":" not in spec:
            print(f"--cluster must be CLUSTER:VPC, got {spec}", file=sys.stderr)
            return 2
        cluster, vpc = spec.split(":", 1)
        print(f"# Discovering {cluster} (vpc={vpc})...", file=sys.stderr)
        info = discover(cluster, vpc, args.region)
        env_blocks.append(_emit_env_block(vpc, cluster, args.region, info))
        by_vpc_targets[vpc] = info["targets"]

        tier_counts: dict[str, int] = defaultdict(int)
        for t in info["targets"]:
            tier_counts[t["tier"]] += 1
        line = (
            f"  {vpc} ({cluster}): {len(info['targets'])} services "
            f"[{', '.join(f'{k}={v}' for k, v in sorted(tier_counts.items()))}] "
            f"vpc={info.get('vpc_id', '?')} "
            f"subnets={len(info['subnets'])} sgs={len(info['security_groups'])}"
        )
        if info.get("dropped_subnets_by_vpc"):
            line += f" (dropped subnets from other VPCs: {info['dropped_subnets_by_vpc']})"
        summaries.append(line)

    # --- Output ----------------------------------------------------------
    print("=" * 78)
    print("DISCOVERY SUMMARY")
    print("=" * 78)
    for s in summaries:
        print(s)

    print()
    print("=" * 78)
    print("STEP 1 -- Run setup.ps1 once per VPC (Windows, from repo root)")
    print("=" * 78)
    for block in env_blocks:
        print(block)
        print()

    if args.emit_ssm:
        print("=" * 78)
        print("STEP 2 -- Writing targets to SSM (probe will pick them up within TARGETS_REFRESH_SEC)")
        print("=" * 78)
        for vpc, raw_targets in by_vpc_targets.items():
            payload = _ssm_payload(raw_targets)
            _put_ssm_param(vpc, args.region, payload)
            print(f"  {vpc}: {len(payload)} targets written")
    else:
        print("=" * 78)
        print("STEP 2 -- (skipped) Pass --emit-ssm to write targets into SSM Parameter Store.")
        print("=" * 78)
        for vpc, raw_targets in by_vpc_targets.items():
            payload = _ssm_payload(raw_targets)
            print(f"  Would write {len(payload)} targets to /blackwatch/ecs-probe/{vpc}/targets")

    print()
    print("# " + "=" * 76)
    print("# REVIEW BEFORE COMMITTING")
    print("# Targets defaulted to: HTTP probe for web-looking ports, TCP probe")
    print("# for database-looking ports. Hostnames default to bare service name --")
    print("# adjust if your internal DNS uses a namespace (e.g. svc.internal).")
    print("# ecs_running tier is excluded from SSM -- it's covered by BW's AWS reader.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
