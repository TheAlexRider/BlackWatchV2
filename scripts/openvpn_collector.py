#!/usr/bin/env python3
"""BlackWatch OpenVPN collector — runs ON the OpenVPN EC2 instance.

It is a dumb edge agent (stdlib only, no dependencies): every INTERVAL seconds
it checks the systemd service state and reads the OpenVPN status file, then
POSTs the raw data to BlackWatch /ingest. All parsing/detection happens in
BlackWatch (the vpn.openvpn module). The core never reaches out to this box;
this box only pushes outbound HTTPS and holds a single ingest token.

Configure via environment variables:

    BLACKWATCH_URL        e.g. https://blackwatch.internal:8000   (default http://localhost:8000)
    BLACKWATCH_TOKEN      ingest token mapped to module vpn.openvpn (default "vpntoken")
    VPN_SERVER_NAME       logical name for this server            (default "openvpn-prod-1")
    OPENVPN_STATUS_FILE   path to the status file                 (default /var/log/openvpn/status.log)
    OPENVPN_UNIT          systemd unit                            (default "openvpn@server")
    INTERVAL              seconds between polls                    (default 60)

Run once (for testing):   python3 openvpn_collector.py --once
Run as a loop:            python3 openvpn_collector.py

Notes for the current server config:
  * status file is /var/log/openvpn/status.log (status-version 1). It refreshes
    every 60s by default; add an interval to refresh faster, e.g.
        status /var/log/openvpn/status.log 30
    and optionally `status-version 3` for tab-separated machine output.
  * the status file is typically root-owned; run this collector as root or grant
    read access to that file.
  * find your unit name with: systemctl list-units 'openvpn*'
    (often openvpn@server or openvpn-server@server)

Example systemd unit (/etc/systemd/system/blackwatch-collector.service):
    [Unit]
    Description=BlackWatch OpenVPN collector
    After=network-online.target
    [Service]
    Environment=BLACKWATCH_URL=https://blackwatch.internal:8000
    Environment=BLACKWATCH_TOKEN=vpntoken
    Environment=VPN_SERVER_NAME=openvpn-prod-1
    Environment=OPENVPN_UNIT=openvpn@server
    ExecStart=/usr/bin/python3 /opt/blackwatch/openvpn_collector.py
    Restart=always
    [Install]
    WantedBy=multi-user.target
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

URL = os.environ.get("BLACKWATCH_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("BLACKWATCH_TOKEN", "vpntoken")
SERVER = os.environ.get("VPN_SERVER_NAME", "openvpn-prod-1")
STATUS_FILE = os.environ.get("OPENVPN_STATUS_FILE", "/var/log/openvpn/status.log")
UNIT = os.environ.get("OPENVPN_UNIT", "openvpn@server")
INTERVAL = int(os.environ.get("INTERVAL", "60"))


def service_state() -> str:
    """Return systemd's view: active / inactive / failed / unknown."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", UNIT],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def read_status_file() -> str | None:
    try:
        with open(STATUS_FILE, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except Exception as exc:
        print(f"warning: could not read {STATUS_FILE}: {exc}", file=sys.stderr)
        return None


def post(payload: dict) -> int:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{URL}/ingest",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-BlackWatch-Token": TOKEN,
            "X-BlackWatch-Transport": "poll",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        return resp.status


def cycle() -> None:
    state = service_state()
    payload = {
        "kind": "poll",
        "server": SERVER,
        "state": state,
        "active": state == "active",
        "status_raw": read_status_file(),
    }
    try:
        code = post(payload)
        print(f"posted server={SERVER} state={state} -> HTTP {code}")
    except Exception as exc:
        print(f"post failed: {exc}", file=sys.stderr)


def main() -> None:
    once = "--once" in sys.argv
    print(f"BlackWatch OpenVPN collector -> {URL} (server={SERVER}, unit={UNIT}, every {INTERVAL}s)")
    while True:
        cycle()
        if once:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
