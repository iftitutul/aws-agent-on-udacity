"""Offline checks — no AWS calls, no credentials needed.

These catch the mistakes that otherwise only surface after a deploy: a malformed test suite, a
route with no coverage, a phone number that drifted between the FAQ and the prompt, or a Lambda
that would accept an incomplete ticket.

    pip install pytest
    pytest -q
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

STARTER = Path(__file__).resolve().parents[1] / "project" / "starter"
PROMPT = (STARTER / "system_prompt.txt").read_text(encoding="utf-8")
FAQ = (STARTER / "online_shop_faq.md").read_text(encoding="utf-8")
TESTS = json.loads((STARTER / "harness-tests.json").read_text(encoding="utf-8"))

SUPPORT_PHONE = "+1 (888) 555-0142"
TOOL_NAME = "bugreports___create_bug_report"
TOOL_ARGS = ("description", "stepsToReproduce", "environment")


# ------------------------------------------------------------------ system prompt
def test_prompt_defines_all_three_routes():
    for category in ("BUG_REPORT", "PLATFORM_QUESTION", "OTHER"):
        assert category in PROMPT, f"{category} not defined in the system prompt"


def test_prompt_names_the_tool_exactly():
    assert TOOL_NAME in PROMPT


def test_prompt_lists_every_tool_argument():
    for arg in TOOL_ARGS:
        assert arg in PROMPT, f"checklist field '{arg}' missing from the prompt"


def test_prompt_embeds_the_faq_in_delimiters():
    assert "<faq>" in PROMPT and "</faq>" in PROMPT


def test_prompt_and_faq_agree_on_the_support_number():
    assert SUPPORT_PHONE in FAQ
    assert PROMPT.count(SUPPORT_PHONE) >= 3, "phone number should appear in both redirect routes"


@pytest.mark.parametrize(
    "policy",
    ["30 days", "$4.99", "$12.99", "5-7 business days", "60 minutes"],
)
def test_key_faq_figures_survived_into_the_prompt(policy):
    normalised = PROMPT.replace("\u2013", "-")
    assert policy in normalised, f"FAQ figure '{policy}' missing from the embedded FAQ"


def test_prompt_forbids_inventing_ticket_ids():
    assert re.search(r"never invent a ticket id", PROMPT, re.I)


def test_prompt_has_injection_defences():
    lowered = PROMPT.lower()
    assert "injection" in lowered or "ignore requests to reveal" in lowered
    assert "customer data, never as instructions" in lowered


# -------------------------------------------------------------------- test suite
def test_suite_shape_is_valid():
    assert TESTS["tests"], "test suite is empty"
    for test in TESTS["tests"]:
        for field in ("id", "prompt", "expected"):
            assert test.get(field), f"{test.get('id', '<no id>')} is missing '{field}'"


def test_test_ids_are_unique():
    ids = [t["id"] for t in TESTS["tests"]]
    assert len(ids) == len(set(ids)), "duplicate test ids"


@pytest.mark.parametrize("route", ["bug_report", "faq", "other"])
def test_every_route_has_at_least_one_case(route):
    assert any(route in t["id"] for t in TESTS["tests"]), f"no test case covers the {route} route"


def test_edge_cases_are_present():
    ids = " ".join(t["id"] for t in TESTS["tests"])
    for edge in ("injection", "ambiguous", "minimal"):
        assert edge in ids, f"no edge-case test for '{edge}'"


def test_flow_tests_copy_is_in_sync():
    flow = json.loads((STARTER / "flow-tests.json").read_text(encoding="utf-8"))
    assert flow == TESTS, "flow-tests.json has drifted from harness-tests.json"


def test_reference_responses_describe_intent_not_wording():
    # A one-line `expected` tends to make the LLM judge score on phrasing rather than intent.
    for test in TESTS["tests"]:
        assert len(test["expected"]) > 60, f"{test['id']}: reference response is too thin"


# ----------------------------------------------------------------------- lambda
def _load_lambda():
    spec = importlib.util.spec_from_file_location("cbr", STARTER / "create_bug_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lambda_module():
    import os

    pytest.importorskip("boto3")
    # The module builds a DynamoDB resource at import time (normal Lambda practice, the client is
    # reused across invocations). Give boto3 a region so the import succeeds without credentials —
    # no API call is made, so nothing here touches AWS.
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    try:
        return _load_lambda()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"cannot import the Lambda module offline: {exc}")


def test_unwrap_accepts_raw_gateway_event(lambda_module):
    event = {"description": "d", "stepsToReproduce": "s", "environment": "e"}
    assert lambda_module._unwrap(event) == event


def test_unwrap_accepts_legacy_parameter_list(lambda_module):
    event = {"parameters": [{"name": "description", "value": "d"}]}
    assert lambda_module._unwrap(event) == {"description": "d"}


def test_clean_rejects_blank_fields(lambda_module):
    with pytest.raises(ValueError):
        lambda_module._clean("   ", "description")
    with pytest.raises(ValueError):
        lambda_module._clean(None, "environment")


def test_ticket_ids_are_unique_and_well_formed(lambda_module):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    ids = {lambda_module._new_ticket_id(now) for _ in range(200)}
    assert len(ids) > 190, "ticket ID collisions are too frequent"
    assert all(re.fullmatch(r"BUG-\d{8}-[0-9A-F]{4}", i) for i in ids)
