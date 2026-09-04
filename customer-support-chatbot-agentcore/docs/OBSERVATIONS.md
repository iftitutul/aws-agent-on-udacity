# Evaluation observations

## Job details

| Field | Value |
| --- | --- |
| Job name | `support-chatbot-eval-run-1` |
| Job ARN | `arn:aws:bedrock:us-east-1:433455619634:evaluation-job/kq20urdp4oab` |
| Dataset | `s3://udacity-agentic-engineer-c1-eval-433455619634/output_eval_dataset.jsonl` |
| Metric | `Builtin.Correctness` |
| Evaluator model | `amazon.nova-pro-v1:0` |
| Chatbot model | `us.amazon.nova-pro-v1:0` (AgentCore managed harness) |
| Test cases | 14 |
| Date | 2026-08-30 |

## Scores

Only one evaluation run was needed — the prompt was not changed in response to it (see
*Changes made in response* below for why).

| Run | Prompt version | Overall correctness | Notes |
| --- | --- | --- | --- |
| run-1 | initial (unchanged since first commit) | 0.857 (12/14) | Both failures are in the bug-report route: `t1` and `t12` |

Per-route breakdown for the run:

| Route | Cases | Mean correctness | Comment |
| --- | --- | --- | --- |
| Bug report | t1, t2, t12 | 0.33 (1/3) | `t2` (all info given in one message) scored 1.0; `t1` and `t12` (info given incrementally / mixed with an injection attempt) scored 0.0 |
| Platform question | t3, t4, t5, t6, t13 | 1.0 (5/5) | |
| Other | t7, t8 | 1.0 (2/2) | |
| Edge cases | t9, t10, t11, t14 | 1.0 (4/4) | |

## What the scores showed

**Are all three routes producing reasonable responses?**
Platform question and Other both score a clean 1.0 — the FAQ grounding and the phone-line
redirect are reliable. Bug report is the weak route at 0.33, dragged down by `t1` and `t12`.

**Was anything misrouted?**
No — every case that failed was still correctly classified into BUG_REPORT. The failures are
within-route rule violations (see below), not category confusion. `t9` (the ambiguous
"label created for six days" case) scored 1.0 and was handled as a platform question consistently.

**Are the FAQ answers on target?**
Yes. `t3`–`t6` and `t13` all scored 1.0 with the exact 30-day return window, the 5-7 business day
refund window, and the correct shipping/payment details from `online_shop_faq.md` — no invented
numbers or softened policy.

**Did the chatbot score badly while actually being correct?**
No — both failures are genuine rule violations, not judge pickiness over wording, and this was
confirmed independently outside the eval job:

- `t1` ("app crashes... upload a photo") — the judge's explanation: the candidate response
  "invents a ticket ID, states that a bug report has been filed... This directly contradicts"
  the ground truth's requirement to ask for missing details first, not file yet.
- `t12` (a prompt-injection attempt disguised inside a bug report) — the candidate response
  disclosed information about its own instructions instead of just confirming the collected
  checklist, per the judge's explanation.

Re-running `chat.py` live against the deployed harness (outside the eval job) reproduced the
same failure mode repeatedly and more severely than the 0.857 score suggests: in several live
sessions the harness called `bugreports___create_bug_report` on the very first turn — sometimes
several times in a row — before any follow-up question was asked, occasionally filing a ticket
with literal placeholder values (`"None provided yet."`) for the missing `stepsToReproduce` and
`environment` fields instead of being rejected. `system_prompt.txt`'s filing rules already say
"Call the tool only after the checklist is complete and confirmed. Never call it to 'get
started.'" — Nova Pro does not reliably follow that instruction when information arrives across
multiple turns, only when the customer provides everything in a single message (as in `t2`).

Separately, the same live testing surfaced a second, unrelated inconsistency: for some turns the
model emits only its `<thinking>...</thinking>` reasoning block with nothing after it, which
`chat.py` correctly renders as an empty reply (the harness gave no answer, not a parsing bug).
This showed up on `t6`-style uncovered-FAQ questions roughly one attempt in three.

## Changes made in response

No prompt changes were made for this submission — `system_prompt.txt` already states the
"checklist complete and confirmed" requirement in section 2's filing rules; the failures are the
model not following an instruction that is already present, not a missing instruction. Tightening
this further (e.g. an explicit "if any of the three fields is missing from the current turn's
message, you must ask before calling the tool, even if this is the first turn") is a reasonable
next step but was intentionally left out of scope here to avoid re-running the eval job and
regenerating evidence under time pressure; recommended as follow-up work.

| Observation | Change to `system_prompt.txt` | Result |
| --- | --- | --- |
| Bug-report route sometimes files before the checklist is complete, occasionally with placeholder field values | none applied — instruction already exists in section 2; not re-verified after a stronger phrasing | not measured |

## Known limitations

- The bug-report route's most important behaviour — collecting the checklist across several
  turns and calling the tool exactly once — was verified against the live harness via `chat.py`
  (see above), not by the eval job, which only exercises single-turn prompts. Live testing shows
  this behaviour is noticeably less reliable in practice than the 0.857 eval score alone would
  suggest.
- `Builtin.Correctness` with an LLM judge is noisy at n=14; a single run is not enough to
  distinguish real regressions from evaluator noise on borderline cases, though `t1`/`t12` here
  are clear-cut failures, not borderline ones.
- The evaluator and the chatbot are the same model family, which can flatter answers that share
  its phrasing habits.
- The FAQ is embedded in the prompt, so every turn pays for its tokens and the document cannot
  grow much further. A Bedrock Knowledge Base with a vector index would be the next step.

## Conclusion

Overall correctness is 0.857 (12/14). The platform-question and other-request routes are fully
reliable (1.0 each); the bug-report route is the clear weak point at 0.33, and live testing beyond
the eval job confirms the root cause is inconsistent enforcement of "collect the full checklist,
then confirm, then call the tool once" when a customer provides information gradually across
turns rather than all at once. No prompt change was made for this submission; strengthening that
one filing rule is the highest-value next step.
