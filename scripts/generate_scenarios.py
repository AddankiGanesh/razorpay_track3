"""
Synthetic scenario generator for RevRecover.

Creates Razorpay test orders/payment links and fires simulated webhook events
to the local RevRecover server for batch testing.

Usage:
  python scripts/generate_scenarios.py
  python scripts/generate_scenarios.py --webhook-url http://localhost:8000/webhooks/razorpay
  python scripts/generate_scenarios.py --simulate-recovery

Or use the Lab UI: http://localhost:8000/lab
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from app.lab.scenarios import fire_all_scenarios  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate RevRecover test scenarios")
    parser.add_argument("--webhook-url", default="http://localhost:8000/webhooks/razorpay")
    parser.add_argument("--simulate-recovery", action="store_true", help="Fire success webhooks after failures")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay between webhook calls")
    args = parser.parse_args()

    print(f"RevRecover scenario generator -> {args.webhook_url}\n")
    print("Tip: open http://localhost:8000/lab for interactive testing\n")

    results = fire_all_scenarios(
        webhook_url=args.webhook_url,
        simulate_recovery=args.simulate_recovery,
        recovery_count=3,
        delay=args.delay,
    )

    for r in results:
        if r.ok:
            prefix = {
                "payment_failure": "FAIL",
                "subscription": "SUB",
                "b2b": "B2B",
                "abandonment": "DROP",
                "late_auth": "LATE",
            }.get(r.group, "EVT")
            order_part = f" order={r.order_id}" if r.order_id else ""
            print(f"{prefix:5} {r.label:30}{order_part} -> {r.recommended_action}")
        else:
            print(f"ERR   {r.label:30} -> {r.error}")

    ok = sum(1 for r in results if r.ok)
    print(f"\nDone: {ok}/{len(results)} succeeded.")
    print("Metrics: http://localhost:8000/  |  Batch: http://localhost:8000/lab/batch-metrics")


if __name__ == "__main__":
    main()
