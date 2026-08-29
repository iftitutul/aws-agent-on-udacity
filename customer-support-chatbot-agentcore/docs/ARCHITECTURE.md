# Architecture

## Why the managed harness rather than a Flow

Bedrock Agents Classic closed to new customers on 30 July 2026, so this project runs on the
AgentCore managed harness. The practical difference for the design: there is no graph of nodes to
build. The harness supplies the agent loop, the stateful session, and tool execution; the system
prompt supplies everything else — classification, the bug-report checklist, FAQ grounding, and the
redirect. One artefact holds all the behaviour, which makes it easy to version and easy to reason
about, and puts all the weight on prompt engineering.

The rubric's language ("Condition node", "Output node", "flow-tests.json") comes from the earlier
Flows version of this project. The mapping is in [`RUBRIC_MAPPING.md`](RUBRIC_MAPPING.md).

## Components

| Layer | Resource | Notes |
| --- | --- | --- |
| Orchestration | AgentCore managed harness | Model `us.amazon.nova-pro-v1:0`, instructions = `system_prompt.txt`, one gateway attached |
| Tooling | AgentCore Gateway (MCP protocol) | Target `bugreports` → the model sees `bugreports___create_bug_report` |
| Tool runtime | Lambda `bug-report-tool-stack-create-bug-report` | Python 3.12; validates the three arguments, generates the ticket ID |
| Storage | DynamoDB `bug-report-tool-stack-bug-reports` | Partition key `ticketId`, on-demand billing, SSE enabled |
| Testing | `generate-eval-dataset.py` + Bedrock Evaluations | BYOI: responses precomputed, judge only scores |

## Request path for a bug report

1. Customer message arrives via `InvokeHarness` with a `runtimeSessionId`. The same ID is reused
   for the whole conversation, so the harness remembers what has already been collected.
2. The model classifies the message, finds items missing from the checklist, and asks for them.
   This can take several turns; no tool is called during collection.
3. Once description, steps and environment are all present, the model reads them back and waits
   for confirmation.
4. On confirmation the model emits a tool call. The gateway assumes the gateway role and invokes
   the Lambda with the three arguments as the raw event body.
5. The Lambda validates, generates `BUG-YYYYMMDD-XXXX`, writes the item with `status: OPEN`, and
   returns the ticket ID.
6. The model quotes the returned ID back to the customer. It is instructed never to fabricate one.

## Design decisions

**Read-back before filing.** The model confirms the three fields with the customer before calling
the tool. It costs one extra turn and it removes the most common failure mode — a ticket filed
from a half-collected checklist, which is worse than no ticket because it looks complete to the
engineer who picks it up.

**Checklist field names match the tool arguments.** The prompt calls them `description`,
`stepsToReproduce` and `environment`, exactly as in the tool schema. When the prompt's vocabulary
and the schema's vocabulary agree, argument-mapping errors mostly disappear.

**A verbatim refusal sentence for uncovered questions.** The prompt does not say "politely explain
you don't know" — it supplies the exact sentence to use. Verbatim strings are followed far more
consistently than paraphrasable instructions, and it makes the behaviour easy to grep for in the
eval output.

**Ordered tie-break rules.** Real messages straddle categories ("the checkout crashes — will I
still be charged?"). Rather than hoping the model picks well, the prompt gives an explicit
precedence: malfunction beats question, FAQ-answerable beats other, too-vague means ask rather
than guess.

**Injection defence in the prompt, not around it.** Everything from the customer is data, never
instruction — including text that claims to be a system message, and including text inside a bug
description that will end up in the ticket. Cases `t11` and `t12` test both shapes. A Bedrock
Guardrail in front of the harness would be the natural hardening step; see
[`PROMPT_DESIGN.md`](PROMPT_DESIGN.md).

**Least privilege on the roles.** The Lambda role can only `PutItem` on the one table. The gateway
role can only invoke the one function. The harness role is scoped to the Nova Pro model ARNs and
the gateway actions.

**A tolerant API wrapper.** `agentcore_common.call_first_available` tries the known operation
aliases for the harness APIs and, if none exist, raises an error listing what the installed boto3
actually exposes. The AgentCore APIs are new enough that operation names have moved between boto3
releases; failing with a readable message beats an `AttributeError`.

## Data model

```json
{
  "ticketId":         "BUG-20260829-4F2A",
  "description":      "The app crashes when posting a review with a photo",
  "stepsToReproduce": "Open a delivered order, tap Write a review, attach a JPEG, tap Post",
  "environment":      "iPhone 14, iOS 17.4, Nimbus app 5.2.1",
  "status":           "OPEN",
  "createdAt":        "2026-08-29T11:02:44+00:00",
  "source":           "agentcore-support-chatbot"
}
```

## Possible extensions

- Replace the embedded FAQ with a Bedrock Knowledge Base over a vector index, so the document can
  grow without being paid for on every turn.
- Put a Bedrock Guardrail in front of the harness to block harmful content and injection attempts
  before the model sees them.
- Add a multi-turn test runner that scripts whole conversations, so the tool-call behaviour is
  covered by the automated evaluation rather than by hand.
- Emit a CloudWatch metric per route so misrouting is visible in production, not just in tests.
