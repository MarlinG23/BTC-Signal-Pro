"""
30-day quality sweep — async start + poll (avoids Railway 502 timeout).

    python scripts/run_param_sweep.py

Uses POST /api/admin/quick-sweep?async_run=true then polls status.
"""

from __future__ import annotations

import json
import sys
import time

import httpx

DEFAULT_REMOTE = "https://btc-signal-pro-production-9401.up.railway.app"
DAYS = 30
FEE = 0.04
POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 900


def _print_summary(data: dict) -> None:
    print("\n=== SUMMARY ===", flush=True)
    print(
        f"{'scenario':<28} {'1m_sig':>7} {'1m_ret%':>10} {'gated_sig':>10} {'gated_ret%':>11}",
        flush=True,
    )
    print("-" * 70, flush=True)
    for r in data["results"]:
        print(
            f"{r['name']:<28} {r['1m_signals']:>7} {r['1m_return_pct']:>10.4f} "
            f"{r['gated_signals']:>10} {r['gated_return_pct']:>11.4f}",
            flush=True,
        )

    print("\n=== PROFITABLE WITH FEES ===", flush=True)
    if not data.get("any_profitable_with_fees"):
        print("NONE", flush=True)
    else:
        for r in data.get("profitable_1m_with_fees", []):
            print(f"  1M {r['name']}: {r['1m_return_pct']}%", flush=True)
        for r in data.get("profitable_gated_with_fees", []):
            print(f"  Gated {r['name']}: {r['gated_return_pct']}%", flush=True)

    print("\n=== JSON ===", flush=True)
    print(json.dumps(data, indent=2), flush=True)


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REMOTE
    base = base.rstrip("/")
    start_url = f"{base}/api/admin/quick-sweep?days={DAYS}&taker_fee_pct={FEE}&async_run=true"
    status_url = f"{base}/api/admin/param-sweep/status"

    print(f"POST {start_url}", flush=True)
    print("(async job — polling every 10s, ~3-5 min compute)", flush=True)

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(start_url)
        resp.raise_for_status()
        start = resp.json()
        if start.get("status") == "running":
            print("Sweep already running on server — polling...", flush=True)
        elif start.get("status") != "started":
            _print_summary(start)
            return

        deadline = time.time() + POLL_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL_S)
            st = client.get(status_url).json()
            status = st.get("status")
            if status == "running":
                print(".", end="", flush=True)
                continue
            if status == "error":
                raise RuntimeError(st.get("error", "sweep failed"))
            if status == "complete":
                print("\nDone.", flush=True)
                _print_summary(st["result"])
                return
            print(f"\nUnexpected status: {st}", flush=True)
            time.sleep(POLL_INTERVAL_S)

    raise TimeoutError(f"Sweep did not finish within {POLL_TIMEOUT_S}s")


if __name__ == "__main__":
    main()
