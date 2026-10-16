#!/usr/bin/env bash
# Runs the six project test scenarios against the deployed agent and saves
# each transcript to ../evidence/ for submission.
# Usage (from starter/, after agentcore deploy + setup_permissions.py):
#   bash run_tests.sh            # all tests
#   bash run_tests.sh 4          # a single test
set -euo pipefail

OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/evidence"
mkdir -p "$OUT_DIR"

run() {
  local file="$1" payload="$2"; shift 2
  {
    echo "\$ agentcore invoke '$payload' $*"
    echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    uv run agentcore invoke "$payload" "$@"
    echo
  } 2>&1 | tee -a "$OUT_DIR/$file"
}

t1() { run test1_order_tracking.txt '{"prompt": "Can you track order ORD-001?", "customer_id": "CUST-123", "session_id": "t1"}'; }
t2() { run test2_refund_processing.txt '{"prompt": "I want to return my Kindle Paperwhite (ORD-002). Please initiate a refund.", "customer_id": "CUST-123", "session_id": "t2"}'; }
t3() { run test3_knowledge_base.txt '{"prompt": "What are the benefits of the Platinum loyalty tier?", "customer_id": "CUST-123", "session_id": "t3"}'; }
t4() {
  # Two separate runtime sessions for the same customer: A shares facts, B recalls them.
  local run_id; run_id="$(date +%s)"
  local a="mem-session-a-${run_id}-0000000000000000" b="mem-session-b-${run_id}-0000000000000000"
  : > "$OUT_DIR/test4_memory_sessionA_shared.txt"
  : > "$OUT_DIR/test4_memory_sessionB_recalled.txt"
  echo "# Session A — information shared with the agent (customer CUST-123)" | tee -a "$OUT_DIR/test4_memory_sessionA_shared.txt"
  run test4_memory_sessionA_shared.txt '{"prompt": "Hi, my name is Jane Doe. Please keep your answers short and use bullet points. I am a Gold loyalty member and I mostly buy Kindle devices.", "customer_id": "CUST-123", "session_id": "'"$a"'"}' --session-id "$a"
  echo "Waiting 120s for long-term memory extraction..." | tee -a "$OUT_DIR/test4_memory_sessionA_shared.txt"
  sleep 120
  echo "# Session B — new session, same customer: information retrieved from memory" | tee -a "$OUT_DIR/test4_memory_sessionB_recalled.txt"
  run test4_memory_sessionB_recalled.txt '{"prompt": "Do you remember my name, how I like my answers formatted, my loyalty tier, and what I usually buy?", "customer_id": "CUST-123", "session_id": "'"$b"'"}' --session-id "$b"
}
t5() { run test5_loyalty_discount.txt '{"prompt": "I am a Gold member with 4250 points. Calculate my discount on a $150 standard order.", "customer_id": "CUST-123", "session_id": "t5"}'; }
t7() {
  # Gateway failure handling: run the agent locally against a dummy Gateway URL.
  {
    echo "\$ GATEWAY_URL=https://dummy-gateway.invalid/mcp (local invoke)"
    echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    GATEWAY_URL="https://dummy-gateway.invalid/mcp" uv run python -c '
import asyncio, json, main
payload = {"prompt": "Can you track order ORD-001?", "customer_id": "CUST-123", "session_id": "t7"}
print("Response:", asyncio.run(main.invoke(payload)))'
    echo
  } 2>&1 | grep -v "^  File \|^    " | tee "$OUT_DIR/test7_gateway_failure.txt"
}
t6() { run test6_browser.txt '{"prompt": "Go to https://www.udacity.com and tell me the page title.", "customer_id": "CUST-123", "session_id": "t6"}'; }

if [[ $# -gt 0 ]]; then
  "t$1"
else
  t1; t2; t3; t4; t5; t6; t7
fi
echo "Transcripts saved in $OUT_DIR"
