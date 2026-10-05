#!/usr/bin/env bash
# Runs the six project test scenarios against the deployed agent and saves
# each transcript to ../evidence/ for submission.
# Usage (from starter/, after agentcore deploy + setup_permissions.py):
#   bash run_tests.sh            # all tests
#   bash run_tests.sh 4          # a single test
set -uo pipefail

OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/evidence"
mkdir -p "$OUT_DIR"

run() {
  local file="$1" payload="$2"
  {
    echo "\$ agentcore invoke '$payload'"
    echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    uv run agentcore invoke "$payload"
    echo
  } 2>&1 | tee -a "$OUT_DIR/$file"
}

t1() { run test1_order_tracking.txt '{"prompt": "Can you track order ORD-001?", "customer_id": "CUST-123", "session_id": "t1"}'; }
t2() { run test2_refund_processing.txt '{"prompt": "I want to return my Kindle Paperwhite (ORD-002). Please initiate a refund.", "customer_id": "CUST-123", "session_id": "t2"}'; }
t3() { run test3_knowledge_base.txt '{"prompt": "What are the benefits of the Platinum loyalty tier?", "customer_id": "CUST-123", "session_id": "t3"}'; }
t4() {
  run test4_memory.txt '{"prompt": "Hi, I am Jane. I prefer concise responses.", "customer_id": "CUST-123", "session_id": "s-A"}'
  echo "Waiting 60s for long-term memory extraction..." | tee -a "$OUT_DIR/test4_memory.txt"
  sleep 60
  run test4_memory.txt '{"prompt": "Do you remember my name and communication preference?", "customer_id": "CUST-123", "session_id": "s-B"}'
}
t5() { run test5_loyalty_discount.txt '{"prompt": "I am a Gold member with 4250 points. Calculate my discount on a $150 standard order.", "customer_id": "CUST-123", "session_id": "t5"}'; }
t6() { run test6_browser.txt '{"prompt": "Go to https://www.udacity.com and tell me the page title.", "customer_id": "CUST-123", "session_id": "t6"}'; }

if [[ $# -gt 0 ]]; then
  "t$1"
else
  t1; t2; t3; t4; t5; t6
fi
echo "Transcripts saved in $OUT_DIR"
