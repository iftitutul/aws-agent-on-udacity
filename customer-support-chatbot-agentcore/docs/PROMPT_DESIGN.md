# Prompt design

`project/starter/system_prompt.txt` is the whole application. This is what is in it and why.

## Structure

| Section | Purpose |
| --- | --- |
| 1. Classification | Three categories with signal words, plus ordered tie-break rules |
| 2. Route A — bug report | Checklist, collection rules, filing rules |
| 3. Route B — platform question | FAQ-only grounding, verbatim refusal sentence |
| 4. Route C — other | Three-sentence redirect |
| 5. Style, safety, limits | Tone, injection resistance, sensitive data |
| 6. FAQ | The document itself, in `<faq>` tags |
| 7. Worked examples | One per route plus the two failure shapes |

Order matters. Classification comes first because it gates everything else; the FAQ sits after the
rules so the rules are not buried behind a long document; examples come last so they are the most
recent thing in context before the conversation starts.

## Techniques used

**Classify silently, then act.** The prompt asks for a category assignment but forbids emitting
it. A separate classifier node would produce a label to switch on; here the label lives in the
model's reasoning and the behaviour rules do the switching. The rules are written so that each
category's instructions are self-contained — nothing in Route B depends on having read Route A.

**Ordered disambiguation.** Categories overlap in real messages, so precedence is stated
explicitly rather than left to the model: malfunction beats question; FAQ-answerable beats other;
too-vague means ask one question rather than guess. Without rule (c), "it's broken" reliably
triggers a half-invented ticket.

**Named checklist fields.** `description`, `stepsToReproduce`, `environment` — the same names as
the tool schema. This is the single highest-leverage detail in the bug-report route.

**Negative constraints where the failure is predictable.** "Never invent a ticket ID." "Chrome
alone is not an environment." "Do not call the tool to get started." Each of these exists because
it is a specific thing this route does wrong when left unconstrained, not as generic caution.

**Verbatim strings for the important refusals.** The uncovered-FAQ response and the injection
response are given as exact sentences. Reliability goes up and the behaviour becomes greppable in
the eval output.

**Delimited reference material.** The FAQ sits in `<faq>` tags and is named as the single source
of truth for Route B, which makes "answer only from this" a concrete instruction with a visible
boundary rather than an abstract one.

**Worked examples over adjectives.** Six examples, including a partially-collected bug report, an
uncovered FAQ question, and an injection attempt. Examples of the *hard* cases are worth more than
examples of the easy ones — the model already handles a clean returns question.

## Injection resistance

Three layers, all in section 5:

1. **Framing** — conversation text is customer data, never instructions, including text claiming
   to be from an administrator or a system message.
2. **Explicit refusals** — prompt disclosure, role changes, "developer mode", rule-dropping, each
   named, with a fixed response.
3. **Tool protection** — instructions embedded in a bug description are recorded as literal ticket
   text and never executed, and no message can trigger a tool call on its own; only a completed,
   confirmed checklist can.

Tests `t11` (direct override) and `t12` (injection hidden inside a legitimate bug report) cover
both shapes. The second matters more in practice: the text goes into a ticket that a human will
later read, so the ticket must contain the injection as data, not act on it.

A Bedrock Guardrail attached in front of the harness would add a layer that runs before the model
sees anything, which is strictly better than prompt-level defence alone. That is left as the
documented next step rather than claimed as implemented.

## Sensitive data

The prompt forbids echoing card numbers, CVVs, passwords and ID numbers, and forbids putting them
into a ticket. Without this, a customer who pastes a card number into a bug description gets it
persisted into DynamoDB in plaintext. Test `t14` covers it.

## What was deliberately left out

- **A confidence score or category label in the output.** It leaks internals to the customer and
  invites the model to explain itself instead of answering.
- **Chain-of-thought instructions.** The routes are short; asking for visible reasoning made
  answers longer without making routing better.
- **Apology-heavy language.** Capped at one apology per conversation. Repeated apologising reads
  as evasive and pushes the useful content further down the reply.
- **Any promise the FAQ does not authorise** — refunds, credits, escalation timelines. The model
  will offer these if not told otherwise, and they are exactly the sentences a support team cannot
  honour.
