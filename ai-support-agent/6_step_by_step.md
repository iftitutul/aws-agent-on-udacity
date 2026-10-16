# Step-by-Step Guide: Customer Support Agent on AgentCore

This guide combines `1_project_overview.md` through `5_project_submission.md` into one ordered checklist.

`main.py` is already complete: all eight TODOs are implemented. Your remaining work is the AWS setup, adding your resource IDs, deploying, running the tests, collecting evidence, and cleaning up.

All resources go in **us-east-1**. Run commands from `ai-support-agent/starter/` unless a step says otherwise.

---

## Phase 0 — Local machine prep (once per terminal)

### 0.1 Install tools
- [ ] Python 3.13+, [uv](https://docs.astral.sh/uv/), AWS CLI v2, Node.js 18+ (for MCP Inspector)
- [ ] Do **not** install `@aws/agentcore` (npm). The project uses the Python starter toolkit, and both provide an `agentcore` command.

### 0.2 Load AWS credentials
1. In Udacity, open **Cloud Resources** and copy the access key, secret key, and session token.
2. Put them in `~/.aws/credentials` under `[default]`, including `aws_session_token`.
3. Make sure `~/.aws/config` has `region = us-east-1`.

> These credentials are temporary. If a command later says your credentials are invalid or expired, copy fresh keys from Cloud Resources.

### 0.3 Get past the Netskope SSL proxy (required on this laptop)
Without this step, `agentcore configure` fails with *"requires valid aws credentials"*.

```bash
export AWS_CA_BUNDLE=~/.aws/ca-bundle-netskope.pem
export SSL_CERT_FILE=~/.aws/ca-bundle-netskope.pem
export REQUESTS_CA_BUNDLE=~/.aws/ca-bundle-netskope.pem
export AGENTCORE_SUPPRESS_RECOMMENDATION=1
```

To make the AWS part permanent, add `ca_bundle = ~/.aws/ca-bundle-netskope.pem` under `[default]` in `~/.aws/config`.

### 0.4 Verify credentials and install dependencies
```bash
aws sts get-caller-identity        # should show the voclabs role
cd ai-support-agent/starter
uv sync --python 3.13
```

---

## Phase 1 — Lambda functions

1. Open **Lambda → Create function** and create:
   - `order-tracker` (Python 3.12): paste in `starter/lambda/order_tracker.py`.
   - `refund-processor` (Python 3.12): paste in `starter/lambda/refund_processor.py`.
2. Keep the default execution role, which includes CloudWatch Logs permissions.
3. Click **Deploy** for each function.
4. Write down both function ARNs.

---

## Phase 2 — API Gateway REST API (for order-tracker)

1. Open **API Gateway → Create API → REST API → Build** and name it something like `order-tracker-api`.
2. Create these resources, each with a **GET** method:

   | Resource path | Operation name |
   |---|---|
   | `/orders/{order_id}` | `get_order` |
   | `/customers/{customer_id}/orders` | `get_customer_orders` |
   | `/customers/{customer_id}` | `get_customer` |

3. For each GET method:
   - Set the integration type to **Lambda function**.
   - Turn on **Lambda proxy integration**.
   - Select `order-tracker`.
4. Set each method's **Operation name** to the name in the table. You'll find it under **Method request settings**.
5. Click **Deploy API**, create a new stage named `prod`, and deploy.
6. Write down the **REST API ID** and the stage name (`prod`).

---

## Phase 3 — AgentCore Gateway

1. Open **Amazon Bedrock → AgentCore → Gateways → Create gateway**.
2. Name it `CustomerSupportGateway` and choose the **NONE** inbound authorizer.
3. Add target #1:

   | Setting | Value |
   |---|---|
   | Target name | `order-tracker` |
   | Target type | API Gateway REST API stage |
   | REST API / Stage | the API from Phase 2, stage `prod` |
   | Operations | all three GET operations |

4. Add target #2:

   | Setting | Value |
   |---|---|
   | Target name | `refund-processor` |
   | Target type | Lambda function |
   | Lambda | `refund-processor` |
   | Tool schema | paste the contents of `starter/lambda/lambda_schema` |

5. Copy the **Gateway URL**. It ends in `/mcp`.
6. Check the Gateway with MCP Inspector:
   ```bash
   npx @modelcontextprotocol/inspector
   ```
   - Set the transport to **Streamable HTTP** and enter the Gateway URL.
   - Click **Connect**, then **List Tools**.
   - You should see tools whose names start with `order-tracker___` and `refund-processor___`, for example `order-tracker___get_order` and `refund-processor___initiate_refund`.

---

## Phase 4 — Knowledge Base

1. Open **S3 → Create bucket** (any unique name, in us-east-1). Upload `starter/product_catalog.txt`.
2. Open **Bedrock AgentCore → Built-in tools → Knowledge Base → Create Managed Knowledge Base** and use these settings:

   | Setting | Value |
   |---|---|
   | Name | `CustomerSupportKB` |
   | Embedding model type | Managed |
   | Service role | create new |
   | Data source | your bucket / `product_catalog.txt` |
   | Encryption | default |

3. Click **Sync** and wait until the sync status shows *Completed*.
4. Open the **Test** tab and ask: *"What is the return policy for electronics?"* The answer should mention a **15-day** window.
5. Copy the **Knowledge Base ID**, a 10-character value.

---

## Phase 5 — AgentCore Memory

1. Open **Bedrock → AgentCore → Memory → Create memory** and name it `CustomerSupportMemory`.
2. Add two strategies:

   | Strategy | Name | Namespace |
   |---|---|---|
   | Semantic | `customer_facts` | `cs_agent/{actorId}/facts` |
   | User preference | `customer_preferences` | `cs_agent/{actorId}/preferences` |

3. Wait for the status to change to **ACTIVE**.
4. Copy the **Memory ID**. It looks like `CustomerSupportMemory-abc123XYZ0`.

---

## Phase 6 — Put your IDs in main.py

Edit lines 68–71 of `starter/main.py`. Use plain string values only, because `setup_permissions.py` reads these literals directly from the file.

```python
GATEWAY_URL = "https://<alias>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "<10-char KB ID>"
REGION      = "us-east-1"
MEMORY_ID   = "<CustomerSupportMemory-xxxxxxxxxx>"
```

---

## Phase 7 — Deploy the agent

Run these from `starter/`, with the Phase 0.3 exports set in the same terminal.

```bash
# 1. Configure. The agent name may contain letters, numbers, and underscores only — no hyphens.
uv run agentcore configure --entrypoint main.py --name ai_support_agent \
  --deployment-type direct_code_deploy --runtime PYTHON_3_13 --disable-memory
#    When asked about the execution role, let it auto-create one.

# 2. Deploy
uv run agentcore deploy

# 3. Grant the agent's role access to the KB, Memory, and Browser
uv run setup_permissions.py
#    Optional preview first: uv run setup_permissions.py --dry-run
```

Wait about 30–60 seconds for the IAM permissions to take effect.

> If you change `main.py` later, run `uv run agentcore deploy` again. If you change the resource IDs, run `setup_permissions.py` again too.

Quick smoke test:
```bash
uv run agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "smoke"}'
```

---

## Phase 8 — Run the six tests and capture evidence

The easiest way is to run all six tests with the script. It saves each transcript to `ai-support-agent/evidence/` and stops if an invocation fails.

```bash
bash run_tests.sh        # all six (Test 4 waits 120s between sessions)
bash run_tests.sh 3      # rerun just one test
```

You can also run each `uv run agentcore invoke '...'` command yourself. **Take a screenshot of each result** as well.

| # | Test | Prompt | What to check in the output |
|---|---|---|---|
| 1 | Order tracking (API target) | Can you track order ORD-001? | SHIPPED, **TRK987654321**, **UPS**, estimated delivery date |
| 2 | Refund (Lambda target) | I want to return my Kindle Paperwhite (ORD-002)… | refund ID, **APPROVED**, "3-5 business days" |
| 3 | RAG | Benefits of the Platinum tier? | free same-day shipping, **15%** discount, priority support |
| 4 | Memory | Session `s-A`: "Hi, I am Jane. I prefer concise responses." → wait 120s → session `s-B`: "Do you remember my name…" | recalls **Jane** and **concise** |
| 5 | Code Interpreter | Gold, 4250 pts, $150 standard order | points redeemed **4000**, tier discount **10%**, final total **$99.00**, remaining points **250** |
| 6 | Browser | Go to https://www.udacity.com … page title | the live page title |

The rubric requires successful calls to **two different Gateway tools**: one from the API target and one from the Lambda target. Tests 1 and 2 cover this.

For Test 4, capture **two separate screenshots** in addition to the transcript:

- `evidence/test4_session_a.png`: the first invocation showing the name and preference shared with the agent.
- `evidence/test4_session_b.png`: the later invocation in session `s-B` showing it recalls both facts.

The existing `evidence/test4.png` only shows Session A, and the existing Test 4 transcript records a failed recall in Session B. Neither is sufficient evidence of cross-session recall. Redeploy after code changes, rerun Test 4, and only submit a new Session B screenshot if the response actually recalls both facts. If it still fails after the extraction wait, inspect the AgentCore Memory strategy status and runtime logs rather than treating the test as passed.

---

## Phase 9 — Reflection

`REFLECTION.md` already contains a 367-word draft. It covers a design decision, a challenge, and a production consideration. Edit it to match what actually happened during your deployment; real problems you hit, like the SSL proxy and the agent-name rule, make good examples. Keep it between **200 and 400 words**.

---

## Phase 10 — Submit

Use this checklist from `5_project_submission.md`:

- [ ] `starter/main.py`: all TODOs implemented and real IDs filled in
- [ ] Screenshots or terminal output for Tests 1–6, with both sessions for Test 4 (`evidence/`)
- [ ] `REFLECTION.md` (200–400 words)
- [ ] Any other files: `run_tests.sh`, `pyproject.toml`, `lambda/`, and so on

Zip the `ai-support-agent/` folder and upload it. Leave out `.venv/`.

```bash
cd ..
zip -r ai-support-agent.zip ai-support-agent -x "*/.venv/*" "*/__pycache__/*" "*.DS_Store"
```

---

## Phase 11 — Clean up (do this right after submitting)

Delete these resources in order. OpenSearch Serverless keeps charging until you delete it.

1. Run `uv run agentcore destroy` from `starter/`.
2. In **Bedrock → AgentCore**, delete the Gateway and the Memory.
3. In **Bedrock → Knowledge Bases**, delete `CustomerSupportKB`.
4. In **OpenSearch → Serverless → Collections**, delete the collection that was auto-created for the Knowledge Base.
5. In **S3**, empty the bucket, then delete it.
6. In **API Gateway**, delete the REST API.
7. In **Lambda**, delete `order-tracker` and `refund-processor`.
8. *(Optional)* In **IAM**, delete the auto-created roles.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `agentcore configure requires valid aws credentials` | Set the Phase 0.3 CA exports, or refresh your expired Udacity keys |
| `Invalid agent name` | Use underscores, not hyphens (`ai_support_agent`) |
| `setup_permissions.py`: "Set KB_ID … literal string" | Replace the `<...>` placeholders in `main.py` with real values |
| `setup_permissions.py`: "Run agentcore deploy first" | Deploy before running it; it reads `.bedrock_agentcore.yaml` |
| Agent says "Knowledge base not configured" | `KB_ID` is still a placeholder. Fix it and redeploy |
| AccessDenied on Retrieve, Memory, or Browser | Run `setup_permissions.py` again and wait about 60 seconds |
| No order or refund tools are used | Check `GATEWAY_URL` (it must end in `/mcp`) and the targets in MCP Inspector |
| Gateway connection fails | Check the endpoint and the runtime role's Gateway permissions. The agent returns a safe retry message and logs the failure without returning exception details to the user |
| Test 4 doesn't recall Jane | Allow up to 120 seconds for extraction, then run `bash run_tests.sh 4` to create a fresh Session A/B transcript and check whether Session B recalls both facts |
| Starter Toolkit "no longer supported" warning | Safe to ignore for this project |
