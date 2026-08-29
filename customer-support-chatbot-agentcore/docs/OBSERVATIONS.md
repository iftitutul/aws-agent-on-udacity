# Evaluation observations

> **Fill in the bracketed values from your own evaluation job before submitting.** Everything
> outside the brackets is the analysis structure the rubric asks for; the numbers must be yours.

## Job details

| Field | Value |
| --- | --- |
| Job name | `support-chatbot-eval-run-N` |
| Dataset | `s3://udacity-agentic-engineer-c1-eval-<ACCOUNT_ID>/output_eval_dataset.jsonl` |
| Metric | `Builtin.Correctness` |
| Evaluator model | `amazon.nova-pro-v1:0` |
| Chatbot model | `us.amazon.nova-pro-v1:0` (AgentCore managed harness) |
| Test cases | 14 |
| Date | `[YYYY-MM-DD]` |

## Scores

| Run | Prompt version | Overall correctness | Notes |
| --- | --- | --- | --- |
| run-1 | initial | `[0.xx]` | `[what failed]` |
| run-2 | `[what changed]` | `[0.xx]` | `[effect]` |
| run-3 | `[what changed]` | `[0.xx]` | `[effect]` |

Per-route breakdown for the final run:

| Route | Cases | Mean correctness | Comment |
| --- | --- | --- | --- |
| Bug report | t1, t2, t12 | `[0.xx]` | |
| Platform question | t3, t4, t5, t6, t13 | `[0.xx]` | |
| Other | t7, t8 | `[0.xx]` | |
| Edge cases | t9, t10, t11, t14 | `[0.xx]` | |

## What the scores showed

Answer each of these with what you actually observed:

**Are all three routes producing reasonable responses?**
`[Your observation. Name the routes that scored well and any that did not.]`

**Was anything misrouted?**
`[e.g. "t9 (six days on 'label created') was sometimes answered as an FAQ shipping question and
sometimes treated as a bug. Both are defensible, but the inconsistency showed up as a score
spread across runs."]`

**Are the FAQ answers on target?**
`[Check for invented numbers or softened policy. The judge is strict about the 30-day window,
the $4.99/$12.99 shipping prices, and the 5-7 business day refund window.]`

**Did the chatbot score badly while actually being correct?**
`[This happens when the reference response in harness-tests.json is written as a specific wording
rather than an intent. Note any cases where you loosened `expected` instead of changing the
prompt, and say why that was the right call.]`

## Changes made in response

| Observation | Change to `system_prompt.txt` | Result |
| --- | --- | --- |
| `[e.g. answered uncovered questions from general knowledge]` | `[added the verbatim refusal sentence for uncovered questions]` | `[t6 correctness went from x to y]` |
| `[e.g. filed a ticket before the checklist was complete]` | `[added "call the tool only after the checklist is complete and confirmed"]` | `[…]` |
| `[e.g. invented a ticket ID when the tool errored]` | `[added "never invent a ticket ID; it comes only from the tool response"]` | `[…]` |

## Known limitations

- Single-turn evaluation only. The bug-report route's most important behaviour — collecting the
  checklist across several turns and then calling the tool exactly once — is verified by hand in
  `chat.py` and by the DynamoDB item, not by the eval job. A multi-turn harness runner would
  close that gap.
- `Builtin.Correctness` with an LLM judge is noisy at n=14. Small score differences between runs
  are not necessarily real improvements; only changes that move a whole category are trusted here.
- The evaluator and the chatbot are the same model family, which can flatter answers that share
  its phrasing habits.
- The FAQ is embedded in the prompt, so every turn pays for its tokens and the document cannot
  grow much further. A Bedrock Knowledge Base with a vector index would be the next step.

## Conclusion

`[Two or three sentences: the final correctness score, whether all three routes route reliably,
and the one change that made the biggest difference.]`
