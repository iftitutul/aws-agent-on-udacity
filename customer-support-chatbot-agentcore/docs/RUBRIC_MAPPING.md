# Rubric mapping

The rubric text was written for the earlier Bedrock Flows version of this project, while the
current instructions use the AgentCore managed harness. This table maps each criterion to the
artefact that satisfies it in a harness build.

## Terminology

| Rubric term (Flows) | AgentCore equivalent here |
| --- | --- |
| Flow | The managed harness, defined by `system_prompt.txt` |
| Classifier prompt node | Section 1 of `system_prompt.txt` |
| Condition node expressions | The tie-break rules in section 1 |
| Distinct paths / Output nodes | Routes A, B and C — sections 2, 3 and 4 |
| FAQ Prompt node template | Section 6 of `system_prompt.txt` (`<faq>` block) |
| `flow-tests.json` | `harness-tests.json`, copied verbatim as `flow-tests.json` |

## 1. Implement classification and routing

| Requirement | Where |
| --- | --- |
| Messages classified into distinct categories | `system_prompt.txt` §1 — BUG_REPORT / PLATFORM_QUESTION / OTHER, with signal words |
| Consistent, unambiguous classifier output | §1 tie-break rules (a)–(d), applied in order; re-classification stated per turn |
| Routed to distinct paths | §2, §3, §4 — each route self-contained with its own required behaviour |
| Each path terminates separately | Route A ends in a tool call + ticket ID, Route B in an FAQ answer, Route C in the phone redirect |

**Evidence to attach:** `system_prompt.txt`; `docs/evidence/05-routing-tests.png` (chat responses
for one message of each category).

## 2. Bug report path

| Requirement | Where |
| --- | --- |
| Defined in the system prompt, no separate agent resource | `system_prompt.txt` §2 |
| Harness invokes the Lambda through the gateway | `setup_gateway.py` (target `bugreports`), `create_harness.py` (gateway attached), `agentcore_config.json` |
| Collects description, steps, environment before calling the tool | §2 checklist and collection rules; read-back-and-confirm step |
| A record appears in `bug-report-tool-stack-bug-reports` | Created live in `chat.py` |

**Evidence to attach:** `system_prompt.txt`; `project/starter/examples/chat_transcript_bug_report.md`
showing the follow-up questions and the `[tool call] bugreports___create_bug_report` line;
`docs/evidence/02-dynamodb-item.png`.

## 3. Platform question and other request paths

| Requirement | Where |
| --- | --- |
| Relevant answer when the FAQ covers the question | `system_prompt.txt` §3 + §6; tests `t3`, `t4`, `t5` |
| Directs to the support phone number when not covered | §3 verbatim refusal sentence; test `t6` |
| Separate path for other requests, redirecting to the phone number | §4; tests `t7`, `t8` |

**Evidence to attach:** `docs/evidence/06-faq-node.png` (the `<faq>` block in `system_prompt.txt`);
`docs/evidence/07-covered-question.png`, `08-uncovered-question.png`, `09-other-request.png`.

## 4. Testing and evaluation

| Requirement | Where |
| --- | --- |
| At least one test per path | `harness-tests.json` — bug report `t1`, `t2`; platform question `t3`–`t6`; other `t7`, `t8`; plus six edge cases |
| `generate-eval-dataset.py` run, JSONL produced | `project/starter/output_eval_dataset.jsonl` |
| JSONL uploaded to S3, evaluation job created | `docs/TESTING.md` §4 |
| Correctness score close to 1 | `docs/OBSERVATIONS.md` |
| Written observation | `docs/OBSERVATIONS.md` |

**Evidence to attach:** `harness-tests.json` (and `flow-tests.json`); `output_eval_dataset.jsonl`;
`docs/evidence/04-eval-results.png`; `docs/OBSERVATIONS.md`.

## Stand-out items

| Suggestion | Status |
| --- | --- |
| Guardrail against harmful content and prompt injection | Prompt-level defence implemented (`system_prompt.txt` §5, tests `t11`, `t12`, `t14`); a Bedrock Guardrail resource is documented as the next step in `PROMPT_DESIGN.md`, not claimed as built |
| Edge-case test prompts | Implemented — ambiguous `t9`, minimal-context `t10`, injection `t11`/`t12`, account-specific `t13`, sensitive data `t14` |
| Knowledge Base instead of an embedded FAQ | Not implemented; rationale and migration path in `ARCHITECTURE.md` |
| Structured output for the classifier | Not applicable in the same form — there is no classifier node. The equivalent constraint is the fixed category set plus ordered tie-break rules in §1, with the classification kept internal |

## Before submitting

See [`SUBMISSION_CHECKLIST.md`](SUBMISSION_CHECKLIST.md).
