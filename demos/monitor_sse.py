"""Monitor SSE notifications to verify worker-down detection.

Usage:
    uv run python demos/monitor_sse.py

Assumes the compose environment is running with DB already seeded
(setup complete, dummy user, monitored repo).
"""

import json
import re
import sys
import time

import httpx

BASE = "http://localhost:8080"


def login(client: httpx.Client) -> None:
    """Log in via dummy auth."""
    print("[auth] Logging in via dummy auth...")
    resp = client.get(f"{BASE}/auth/dummy/login")
    if resp.status_code != 200:
        print(f"[auth] GET /auth/dummy/login returned {resp.status_code}")
        print(f"[auth] Headers: {dict(resp.headers)}")
        sys.exit(1)

    match = re.search(r'name="_csrf" value="([^"]+)"', resp.text)
    if not match:
        print("[auth] Could not find CSRF token in login page")
        print(f"[auth] Body preview: {resp.text[:500]}")
        sys.exit(1)

    csrf = match.group(1)
    resp = client.post(
        f"{BASE}/auth/dummy-login",
        data={"email": "admin@test.local", "name": "Admin", "_csrf": csrf},
        follow_redirects=False,
    )
    if resp.status_code not in (302, 303):
        print(f"[auth] POST /auth/dummy-login returned {resp.status_code}")
        sys.exit(1)

    # Verify we're logged in
    resp = client.get(f"{BASE}/api/stats", follow_redirects=False)
    if resp.status_code == 200:
        print("[auth] Logged in successfully")
    else:
        print(f"[auth] Warning: /api/stats returned {resp.status_code}")


def stream_notifications(client: httpx.Client) -> None:
    """Connect to SSE and print every notification."""
    print()
    print("=" * 60)
    print("  SSE Notification Monitor")
    print("  Listening for worker_activity events...")
    print("  (Ctrl+C to stop)")
    print("=" * 60)
    print()

    start = time.time()
    url = f"{BASE}/notifications/stream"

    with client.stream("GET", url, timeout=None) as stream:
        for line in stream.iter_lines():
            elapsed = time.time() - start
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            timestamp = f"[+{mins:02d}:{secs:02d}]"

            if line.startswith("data:"):
                raw = line.removeprefix("data:").strip()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    print(f"{timestamp} (unparseable) {raw}")
                    continue

                ntype = data.get("type", "?")
                event = data.get("event", "")
                mode = data.get("mode", "")
                group = data.get("group", "")
                nid = data.get("id", "?")[:8]

                if ntype == "worker_activity":
                    detail = ""
                    if event == "poll_heartbeat":
                        detail = f"cycle={data.get('cycle', '?')}"
                    elif event == "worker_down":
                        detail = f"minutes_down={data.get('minutes_down', '?')}"
                    elif event == "worker_recovered":
                        detail = "back online"
                    elif event == "worker_started":
                        detail = f"webhook={data.get('webhook_url', '?')}"
                    else:
                        detail = json.dumps(
                            {k: v for k, v in data.items()
                             if k not in ("type", "id", "mode", "created_at")},
                        )

                    print(
                        f"{timestamp} ** {event:25s} "
                        f"mode={mode:10s} group={group:15s} "
                        f"id={nid}  {detail}",
                        flush=True,
                    )
                elif ntype == "dismissed":
                    print(f"{timestamp}    dismissed  id={data.get('id', '?')[:8]}", flush=True)
                else:
                    print(
                        f"{timestamp}    {ntype}: {json.dumps(data)[:120]}",
                        flush=True,
                    )

            elif line.startswith("event:"):
                etype = line.removeprefix("event:").strip()
                if etype == "sync":
                    print(f"{timestamp}    --- initial sync complete ---", flush=True)


def main():
    client = httpx.Client(follow_redirects=False, timeout=30.0)
    login(client)
    stream_notifications(client)


if __name__ == "__main__":
    main()
