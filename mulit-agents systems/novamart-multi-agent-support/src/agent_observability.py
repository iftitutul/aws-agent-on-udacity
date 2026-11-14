"""X-Ray tracing + CloudWatch logging for the NovaMart agents.  (Do not modify.)

What this gives you
-------------------
* ``tool``  - a drop-in replacement for ``strands.tool``. Every call records an
  X-Ray subsegment. ``route_to_*`` tools additionally create a *service node*
  (InventoryAgent, PolicyAgent, ...) so the X-Ray Service Map shows the real
  Orchestrator -> Worker call chain.
* ``request_trace`` - context manager that opens the root
  ``NovaMart-Orchestrator`` segment for one customer request.
* ``traced_node`` - context manager used by the KB helper to create
  ``KnowledgeBase:*`` nodes.
* ``log_event`` - structured JSON log line to ``config.AGENT_LOG_GROUP``.
* ``apply_observability_config`` - turns a ``loggingConfiguration`` dict into
  real AWS state (Transaction Search, log group, runtime env vars).

Segments are sent straight to the X-Ray API with ``PutTraceSegments`` so no
X-Ray daemon is needed - it works identically on your laptop and inside the
AgentCore Runtime. Tracing failures never break a request.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import json
import os
import random
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402
from strands import tool as strands_tool  # noqa: E402

import config  # noqa: E402

ROOT_SERVICE_NAME = "NovaMart-Orchestrator"

# route_to_* tool name -> service-map node name
ROUTE_NODE_NAMES = {
    "route_to_inventory_agent": "InventoryAgent",
    "route_to_policy_agent": "PolicyAgent",
    "route_to_refund_agent": "RefundAgent",
    "route_to_communication_agent": "CommunicationAgent",
}

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40}


def _xray_enabled() -> bool:
    return os.getenv("XRAY_ENABLED", "true").lower() == "true"


def _sampling_rate() -> float:
    try:
        return float(os.getenv("XRAY_SAMPLING_RATE", "1.0"))
    except ValueError:
        return 1.0


# =========================================================== segment model
def _new_id() -> str:
    return secrets.token_hex(8)


def _new_trace_id() -> str:
    return f"1-{int(time.time()):08x}-{secrets.token_hex(12)}"


class _Segment:
    """An X-Ray segment (service node). Subsegments are kept as plain dicts."""

    def __init__(self, name: str, trace: "_Trace", parent_id: str | None = None,
                 origin: str = "AWS::BedrockAgentCore::Runtime"):
        self.trace = trace
        self.doc: dict[str, Any] = {
            "name": name,
            "id": _new_id(),
            "trace_id": trace.trace_id,
            "start_time": time.time(),
            "in_progress": True,
            "origin": origin,
            "annotations": {"project": config.PROJECT_NAME},
            "metadata": {},
            "subsegments": [],
        }
        if parent_id:
            self.doc["parent_id"] = parent_id
        self._lock = threading.Lock()

    @property
    def id(self) -> str:
        return self.doc["id"]

    def add_subsegment(self, name: str, namespace: str | None = None) -> dict:
        sub = {"id": _new_id(), "name": name, "start_time": time.time(), "in_progress": True}
        if namespace:
            sub["namespace"] = namespace
        with self._lock:
            self.doc["subsegments"].append(sub)
        return sub

    def annotate(self, key: str, value: Any) -> None:
        if isinstance(value, (str, int, float, bool)):
            self.doc["annotations"][key.replace("-", "_")] = value

    def close(self, error: BaseException | None = None) -> None:
        self.doc["end_time"] = time.time()
        self.doc.pop("in_progress", None)
        if error is not None:
            self.doc["fault"] = True
            self.doc["cause"] = {"exceptions": [{"message": str(error)[:500], "type": type(error).__name__}]}
        self.trace.finished(self)


class _Trace:
    def __init__(self) -> None:
        self.trace_id = _new_trace_id()
        self._segments: list[_Segment] = []
        self._lock = threading.Lock()

    def finished(self, seg: _Segment) -> None:
        with self._lock:
            self._segments.append(seg)

    def flush(self) -> None:
        docs = []
        for seg in self._segments:
            for sub in seg.doc["subsegments"]:
                if sub.pop("in_progress", None):
                    sub["end_time"] = time.time()
            docs.append(json.dumps(seg.doc, default=str))
        self._segments.clear()
        if not docs:
            return
        try:
            client = boto3.client("xray", region_name=config.AWS_REGION)
            for i in range(0, len(docs), 25):
                resp = client.put_trace_segments(TraceSegmentDocuments=docs[i:i + 25])
                for bad in resp.get("UnprocessedTraceSegments", []):
                    _warn_once(f"X-Ray rejected segment: {bad}")
        except Exception as exc:  # pragma: no cover - network / IAM
            _warn_once(f"X-Ray export failed: {exc}")


_current_segment: contextvars.ContextVar[_Segment | None] = contextvars.ContextVar(
    "novamart_xray_segment", default=None)
_current_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "novamart_xray_trace_id", default="")
_warned: set[str] = set()


def _warn_once(msg: str) -> None:
    key = msg[:80]
    if key not in _warned:
        _warned.add(key)
        print(f"[observability] {msg}", file=sys.stderr)


def current_trace_id() -> str:
    """Return the X-Ray trace id of the request being processed ('' if none)."""
    return _current_trace_id.get()


@contextlib.contextmanager
def request_trace(name: str = ROOT_SERVICE_NAME, **annotations: Any) -> Iterator[str]:
    """Open the root segment for one request. Yields the X-Ray trace id."""
    if not _xray_enabled() or random.random() > _sampling_rate():
        yield ""
        return
    trace = _Trace()
    seg = _Segment(name, trace)
    for k, v in annotations.items():
        seg.annotate(k, v)
    seg_token = _current_segment.set(seg)
    id_token = _current_trace_id.set(trace.trace_id)
    error: BaseException | None = None
    try:
        yield trace.trace_id
    except BaseException as exc:
        error = exc
        raise
    finally:
        seg.close(error)
        _current_segment.reset(seg_token)
        _current_trace_id.reset(id_token)
        trace.flush()


@contextlib.contextmanager
def traced_node(node_name: str, origin: str = "AWS::BedrockAgentCore::Runtime",
                **annotations: Any) -> Iterator[None]:
    """Create a downstream service node (edge parent -> node) for the enclosed block."""
    parent = _current_segment.get()
    if parent is None:
        yield
        return
    sub = parent.add_subsegment(node_name, namespace="remote")
    child = _Segment(node_name, parent.trace, parent_id=sub["id"], origin=origin)
    for k, v in annotations.items():
        child.annotate(k, v)
    token = _current_segment.set(child)
    error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        _current_segment.reset(token)
        child.close(error)
        sub["end_time"] = time.time()
        sub.pop("in_progress", None)
        if error is not None:
            sub["fault"] = True


@contextlib.contextmanager
def traced_call(name: str) -> Iterator[None]:
    """Record a local subsegment (e.g. a DynamoDB tool) in the current node."""
    seg = _current_segment.get()
    if seg is None:
        yield
        return
    sub = seg.add_subsegment(name)
    try:
        yield
    except BaseException:
        sub["error"] = True
        raise
    finally:
        sub["end_time"] = time.time()
        sub.pop("in_progress", None)


def tool(fn: Callable | None = None, **tool_kwargs: Any):
    """Strands ``@tool`` + an X-Ray subsegment (or service node for route_to_*)."""

    def decorate(func: Callable):
        node = ROUTE_NODE_NAMES.get(func.__name__)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            started = time.time()
            cm = traced_node(node) if node else traced_call(func.__name__)
            status = "success"
            try:
                with cm:
                    return func(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                log_event("tool_call", tool=func.__name__, node=node or "",
                          status=status, latency_ms=int((time.time() - started) * 1000))

        return strands_tool(wrapper, **tool_kwargs)

    return decorate(fn) if fn is not None else decorate


# ======================================================= CloudWatch logging
class _CloudWatchLogger:
    def __init__(self) -> None:
        self._client = None
        self._stream: str | None = None
        self._lock = threading.Lock()

    def emit(self, record: dict) -> None:
        if os.getenv("AGENT_LOGGING_ENABLED", "true").lower() != "true":
            return
        level = os.getenv("AGENT_LOG_LEVEL", "INFO").upper()
        if _LEVELS.get(record.get("level", "INFO"), 20) < _LEVELS.get(level, 20):
            return
        group = os.getenv("AGENT_LOG_GROUP", config.AGENT_LOG_GROUP)
        try:
            with self._lock:
                if self._client is None:
                    self._client = boto3.client("logs", region_name=config.AWS_REGION)
                if self._stream is None:
                    self._stream = f"novamart-{time.strftime('%Y-%m-%d')}-{os.getpid()}-{secrets.token_hex(3)}"
                    try:
                        self._client.create_log_stream(logGroupName=group, logStreamName=self._stream)
                    except self._client.exceptions.ResourceAlreadyExistsException:
                        pass
                self._client.put_log_events(
                    logGroupName=group, logStreamName=self._stream,
                    logEvents=[{"timestamp": int(time.time() * 1000),
                                "message": json.dumps(record, default=str)}])
        except Exception as exc:  # pragma: no cover
            _warn_once(f"CloudWatch logging failed: {exc}")


_cw_logger = _CloudWatchLogger()


def log_event(event: str, level: str = "INFO", **fields: Any) -> None:
    """Write one structured JSON log line to the agent CloudWatch log group."""
    record = {"event": event, "level": level, "trace_id": current_trace_id(),
              "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    _cw_logger.emit(record)


# ================================================ observability config apply
_RUNTIME_UPDATE_KEYS = ("agentRuntimeArtifact", "roleArn", "networkConfiguration", "description",
                        "protocolConfiguration", "lifecycleConfiguration",
                        "requestHeaderConfiguration", "authorizerConfiguration",
                        "metadataConfiguration", "filesystemConfigurations")


def _enable_transaction_search(sampling_percentage: float) -> list[str]:
    done = []
    sts = boto3.client("sts", region_name=config.AWS_REGION)
    account = sts.get_caller_identity()["Account"]
    region = config.AWS_REGION
    logs = boto3.client("logs", region_name=region)
    xray = boto3.client("xray", region_name=region)
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "TransactionSearchXRayAccess",
            "Effect": "Allow",
            "Principal": {"Service": "xray.amazonaws.com"},
            "Action": "logs:PutLogEvents",
            "Resource": [f"arn:aws:logs:{region}:{account}:log-group:aws/spans:*",
                         f"arn:aws:logs:{region}:{account}:log-group:/aws/application-signals/data:*"],
            "Condition": {"ArnLike": {"aws:SourceArn": f"arn:aws:xray:{region}:{account}:*"},
                          "StringEquals": {"aws:SourceAccount": account}},
        }],
    }
    logs.put_resource_policy(policyName="TransactionSearchXRayAccess",
                             policyDocument=json.dumps(policy))
    done.append("logs resource policy for X-Ray")
    current = xray.get_trace_segment_destination().get("Destination")
    if current != "CloudWatchLogs":
        xray.update_trace_segment_destination(Destination="CloudWatchLogs")
    done.append("X-Ray segment destination = CloudWatchLogs (Transaction Search)")
    try:
        xray.update_indexing_rule(
            Name="Default",
            Rule={"Probabilistic": {"DesiredSamplingPercentage": float(sampling_percentage)}})
        done.append(f"Transaction Search indexing = {sampling_percentage}%")
    except Exception as exc:  # destination may still be activating
        done.append(f"indexing rule not updated yet ({exc.__class__.__name__}) - retry later")
    return done


def apply_observability_config(runtime_arn: str, logging_configuration: dict) -> dict:
    """Apply a loggingConfiguration dict to AWS.

    Expected shape::

        {"cloudWatchConfig": {"logGroupName": str, "logLevel": "INFO", "enabled": bool},
         "xRayConfig":      {"enabled": bool, "samplingRate": float (0..1)}}

    Returns a summary dict of what was configured.
    """
    cw = logging_configuration.get("cloudWatchConfig", {})
    xr = logging_configuration.get("xRayConfig", {})
    group = cw.get("logGroupName") or config.AGENT_LOG_GROUP
    rate = float(xr.get("samplingRate", 1.0))
    summary: dict[str, Any] = {"runtime_arn": runtime_arn, "steps": []}

    logs = boto3.client("logs", region_name=config.AWS_REGION)
    try:
        logs.create_log_group(logGroupName=group)
        summary["steps"].append(f"created log group {group}")
    except logs.exceptions.ResourceAlreadyExistsException:
        summary["steps"].append(f"log group {group} exists")

    if xr.get("enabled"):
        summary["steps"].extend(_enable_transaction_search(rate * 100))

    env_updates = {
        "AGENT_LOG_GROUP": group,
        "AGENT_LOG_LEVEL": str(cw.get("logLevel", "INFO")),
        "AGENT_LOGGING_ENABLED": str(bool(cw.get("enabled", True))).lower(),
        "XRAY_ENABLED": str(bool(xr.get("enabled", True))).lower(),
        "XRAY_SAMPLING_RATE": str(rate),
    }
    os.environ.update(env_updates)

    if runtime_arn:
        ctrl = boto3.client("bedrock-agentcore-control", region_name=config.AWS_REGION)
        runtime_id = runtime_arn.split("/")[-1]
        current = ctrl.get_agent_runtime(agentRuntimeId=runtime_id)
        params = {k: current[k] for k in _RUNTIME_UPDATE_KEYS if current.get(k)}
        params["environmentVariables"] = {**current.get("environmentVariables", {}), **env_updates}
        ctrl.update_agent_runtime(agentRuntimeId=runtime_id, **params)
        summary["steps"].append("runtime environment updated with logging/tracing settings")
        for _ in range(60):
            status = ctrl.get_agent_runtime(agentRuntimeId=runtime_id)["status"]
            if status in ("READY", "UPDATE_FAILED"):
                break
            time.sleep(5)
        summary["runtime_status"] = status

    for k, v in env_updates.items():
        config.update_env_file(k, v)
    summary["env"] = env_updates
    return summary
