"""Pure diff of two host snapshots -> list of (action, extra) tuples the
projection wraps into derived host.* events. No DB, no Event objects — pure
data, easy to test."""

from __future__ import annotations

from typing import Any


def diff_snapshots(prev: dict[str, Any], current: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    # Only diff categories present in BOTH snapshots. This avoids two flood modes:
    #   (a) a new snapshot category (added by a later agent version) showing
    #       "all items appeared at once" on its first ship,
    #   (b) a transient collector failure on the current side flooding with
    #       false "everything removed" events.
    common = set(prev) & set(current)
    prev = {k: prev[k] for k in common}
    current = {k: current[k] for k in common}
    out: list[tuple[str, dict[str, Any]]] = []

    # --- listening ports (identity: proto + address + port) -----------------
    def _pkey(p):
        return (p.get("proto"), p.get("address"), p.get("port"))

    prev_ports = {_pkey(p): p for p in prev.get("ports") or []}
    cur_ports = {_pkey(p): p for p in current.get("ports") or []}
    for k in cur_ports.keys() - prev_ports.keys():
        p = cur_ports[k]
        out.append(("host.port.opened", {
            "proto": p.get("proto"), "address": p.get("address"),
            "port": p.get("port"), "process": p.get("process"),
        }))
    for k in prev_ports.keys() - cur_ports.keys():
        out.append(("host.port.closed", {"proto": k[0], "address": k[1], "port": k[2]}))

    # --- OS users (identity: name) ------------------------------------------
    prev_users = {u.get("name") for u in prev.get("users") or [] if u.get("name")}
    cur_users = {u.get("name") for u in current.get("users") or [] if u.get("name")}
    cur_user_map = {u.get("name"): u for u in current.get("users") or [] if u.get("name")}
    for name in cur_users - prev_users:
        u = cur_user_map.get(name, {})
        out.append(("host.user.added", {"user": name, "uid": u.get("uid"), "shell": u.get("shell")}))
    for name in prev_users - cur_users:
        out.append(("host.user.removed", {"user": name}))

    # --- authorized_keys (identity: user + fingerprint) ----------------------
    def _kkey(k):
        return (k.get("user"), k.get("fingerprint"))

    prev_keys = {_kkey(k): k for k in prev.get("authorized_keys") or []}
    cur_keys = {_kkey(k): k for k in current.get("authorized_keys") or []}
    for k in cur_keys.keys() - prev_keys.keys():
        kk = cur_keys[k]
        out.append(("host.authorized_key.added", {
            "user": kk.get("user"), "fingerprint": kk.get("fingerprint"),
            "preview": (kk.get("preview") or "")[:80],
        }))
    for k in prev_keys.keys() - cur_keys.keys():
        out.append(("host.authorized_key.removed", {"user": k[0], "fingerprint": k[1]}))

    # --- sudoers (dict {path: sha256}) --------------------------------------
    prev_sudo = dict(prev.get("sudoers") or {})
    cur_sudo = dict(current.get("sudoers") or {})
    changes: dict[str, str] = {}
    for path in set(prev_sudo) | set(cur_sudo):
        a, b = prev_sudo.get(path), cur_sudo.get(path)
        if a == b:
            continue
        if a is None:
            changes[path] = "added"
        elif b is None:
            changes[path] = "removed"
        else:
            changes[path] = "changed"
    if changes:
        out.append(("host.sudoers.changed", {"changes": changes}))

    # --- critical files / cron files (both dict {path: sha256}) -------------
    for key, action_name in (("critical_files", "host.file.changed"),
                              ("cron", "host.cron.changed")):
        prev_map = dict(prev.get(key) or {})
        cur_map = dict(current.get(key) or {})
        for path in set(prev_map) | set(cur_map):
            a, b = prev_map.get(path), cur_map.get(path)
            if a == b:
                continue
            kind = "added" if a is None else "removed" if b is None else "changed"
            out.append((action_name, {"path": path, "change": kind}))

    # --- systemd unit-files (list of names) ---------------------------------
    prev_units = set(prev.get("systemd_units") or [])
    cur_units = set(current.get("systemd_units") or [])
    for u in cur_units - prev_units:
        out.append(("host.service.added", {"unit": u}))
    for u in prev_units - cur_units:
        out.append(("host.service.removed", {"unit": u}))

    # --- SUID binaries (list of paths) --------------------------------------
    prev_suid = set(prev.get("suid") or [])
    cur_suid = set(current.get("suid") or [])
    for path in cur_suid - prev_suid:
        out.append(("host.suid.added", {"path": path}))
    for path in prev_suid - cur_suid:
        out.append(("host.suid.removed", {"path": path}))

    # --- packages (list of names; one summary event per change-set, capped) -
    prev_pkgs = set(prev.get("packages") or [])
    cur_pkgs = set(current.get("packages") or [])
    added = sorted(cur_pkgs - prev_pkgs)
    removed = sorted(prev_pkgs - cur_pkgs)
    if added or removed:
        out.append(("host.packages.changed", {
            "added": added[:50],
            "removed": removed[:50],
            "added_count": len(added),
            "removed_count": len(removed),
        }))

    # --- kernel modules (list of names) — rootkit primitive ------------------
    prev_mods = set(prev.get("kernel_modules") or [])
    cur_mods = set(current.get("kernel_modules") or [])
    for m in sorted(cur_mods - prev_mods):
        out.append(("host.kernel.module.added", {"module": m}))
    for m in sorted(prev_mods - cur_mods):
        out.append(("host.kernel.module.removed", {"module": m}))

    # --- disk fill thresholds (transitions only, hysteresis on recover) -----
    # WARN >=90, CRITICAL >=95, RECOVER <85. Edges fire one event per mount.
    prev_disk = {d.get("mount"): d for d in prev.get("disk") or [] if d.get("mount")}
    cur_disk = {d.get("mount"): d for d in current.get("disk") or [] if d.get("mount")}

    def _disk_state(pct: int) -> str:
        if pct >= 95:
            return "critical"
        if pct >= 90:
            return "warn"
        if pct < 85:
            return "normal"
        return "warn_recovering"   # 85..90 — no transition, hysteresis band

    for mount in set(prev_disk) & set(cur_disk):
        p_pct = int(prev_disk[mount].get("used_pct") or 0)
        c_pct = int(cur_disk[mount].get("used_pct") or 0)
        p_state = _disk_state(p_pct)
        c_state = _disk_state(c_pct)
        # Treat the hysteresis band as "no change unless prev_state was normal".
        # That stops a hover near 90% from flapping warn/recovered.
        if c_state == "warn_recovering":
            continue
        if p_state == c_state:
            continue
        info = {
            "mount": mount,
            "used_pct": c_pct,
            "total": cur_disk[mount].get("total"),
            "fs_type": cur_disk[mount].get("fs_type"),
        }
        if c_state == "critical":
            out.append(("host.disk.critical", info))
        elif c_state == "warn":
            out.append(("host.disk.warn", info))
        else:  # normal — fell back below 85
            out.append(("host.disk.recovered", info))

    return out
