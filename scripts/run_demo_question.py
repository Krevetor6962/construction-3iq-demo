from __future__ import annotations

import argparse
import json
import logging

from construction_iq.orchestrator import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an evidence-grounded construction supplier question.")
    parser.add_argument("question")
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--mode", choices=("live", "offline"), default="live")
    args = parser.parse_args()
    result = run({"question": args.question, "recordId": args.record_id, "mode": args.mode})
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(main())
