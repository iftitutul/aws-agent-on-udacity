"""create_bug_report — AWS Lambda implementation of the chatbot's bug-report tool.

The AgentCore Gateway invokes this function with the tool arguments as the raw event body:

    {
      "description": "...",
      "stepsToReproduce": "...",
      "environment": "..."
    }

There is no messageVersion/parameters envelope (that was Bedrock Agents Classic). A small
unwrapping step is kept below so the same code can be exercised from the Lambda console, from a
Gateway invoke, and from unit tests without change.

The function writes one item per report to DynamoDB and returns the generated ticket ID so the
model can quote it back to the customer.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "bug-report-tool-stack-bug-reports")
MAX_FIELD_CHARS = 4000

_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table(TABLE_NAME)

REQUIRED_FIELDS = ("description", "stepsToReproduce", "environment")


def _unwrap(event):
    """Return the tool arguments regardless of how the event was delivered."""
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")

    # Gateway: arguments are the event itself.
    if any(field in event for field in REQUIRED_FIELDS):
        return event

    # Lambda proxy / API Gateway style body.
    body = event.get("body")
    if isinstance(body, str):
        return json.loads(body)
    if isinstance(body, dict):
        return body

    # Agents Classic style parameter list, kept for backwards compatibility.
    if "parameters" in event and isinstance(event["parameters"], list):
        return {p.get("name"): p.get("value") for p in event["parameters"]}

    return event


def _clean(value, field):
    if value is None:
        raise ValueError(f"missing required field: {field}")
    text = str(value).strip()
    if not text:
        raise ValueError(f"missing required field: {field}")
    return text[:MAX_FIELD_CHARS]


def _new_ticket_id(now):
    return f"BUG-{now:%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"


def lambda_handler(event, context):
    logger.info("received event: %s", json.dumps(event, default=str)[:2000])

    try:
        args = _unwrap(event)
        item = {field: _clean(args.get(field), field) for field in REQUIRED_FIELDS}
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("rejected tool call: %s", exc)
        return {"status": "REJECTED", "error": str(exc)}

    now = datetime.now(timezone.utc)
    item.update(
        {
            "ticketId": _new_ticket_id(now),
            "status": "OPEN",
            "createdAt": now.isoformat(timespec="seconds"),
            "source": "agentcore-support-chatbot",
        }
    )

    try:
        _table.put_item(Item=item)
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as a tool error
        logger.exception("failed to write ticket to DynamoDB")
        return {"status": "ERROR", "error": f"could not store bug report: {exc}"}

    logger.info("created ticket %s", item["ticketId"])
    return {
        "ticketId": item["ticketId"],
        "status": item["status"],
        "createdAt": item["createdAt"],
        "message": f"Bug report {item['ticketId']} created.",
    }
