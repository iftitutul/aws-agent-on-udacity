"""Run one end-to-end refund request locally with the live trace.  (Do not modify.)

    python src/demo.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("NOVAMART_FORCE_TRACE", "1")

from agent_orchestrator import handle_request  # noqa: E402

if __name__ == "__main__":
    result = handle_request("I want to return my order ORD-27176", customer_id="CUST-001")
    print("\nRouting:", " -> ".join(result["routing"]))
    print("X-Ray trace:", result["trace_id"] or "(not sampled)")
