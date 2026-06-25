"""Tiny local webhook receiver for testing BlackWatch notifications.

Run it, point a `webhook` channel at http://localhost:9000/hook, and every
notification BlackWatch routes to that channel prints here.

    python scripts/webhook_listener.py          # listens on :9000
    python scripts/webhook_listener.py 9001      # custom port
"""

import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

        stamp = datetime.now().strftime("%H:%M:%S")
        try:
            payload = json.loads(body)
            summary = payload.get("summary", "(no summary)")
            print(f"\n[{stamp}] NOTIFICATION: {summary}")
            print(json.dumps(payload, indent=2)[:2000])
        except json.JSONDecodeError:
            print(f"\n[{stamp}] RAW: {body}")

    def log_message(self, *args) -> None:  # silence default access logs
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"BlackWatch webhook listener on http://127.0.0.1:{port}/hook  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
