"""Bedrock Knowledge Base retrieval helper used by the PolicyAgent retrievers.  (Do not modify.)

Each call is traced as an X-Ray ``KnowledgeBase:<Domain>`` node.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boto3  # noqa: E402

import config  # noqa: E402
from agent_observability import log_event, traced_node  # noqa: E402

_client = None


def _runtime_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-agent-runtime", region_name=config.AWS_REGION)
    return _client


def retrieve_from_knowledge_base(kb_id: str, query: str, domain: str = "Policy",
                                 top_k: int = 4) -> dict:
    """Retrieve the top-k passages for ``query`` from one Bedrock Knowledge Base.

    Args:
        kb_id: Knowledge Base ID (e.g. config.RETURNS_KB_ID).
        query: Natural-language search query.
        domain: Label used in traces/results, e.g. "Returns", "Shipping", "Warranty".
        top_k: Maximum number of passages to return.

    Returns:
        {"domain": str, "kb_id": str, "query": str,
         "results": [{"text": str, "score": float, "source": str}, ...],
         "error": str | None}
    """
    out: dict = {"domain": domain, "kb_id": kb_id, "query": query, "results": [], "error": None}
    if not kb_id:
        out["error"] = f"{domain} Knowledge Base ID is not configured (.env {domain.upper()}_KB_ID)"
        return out

    started = time.time()
    with traced_node(f"KnowledgeBase:{domain}", origin="AWS::Bedrock::KnowledgeBase",
                     kb_id=kb_id):
        try:
            resp = _runtime_client().retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": top_k}},
            )
            for r in resp.get("retrievalResults", []):
                loc = r.get("location", {})
                source = (loc.get("s3Location") or {}).get("uri") or loc.get("type", "")
                out["results"].append({
                    "text": r.get("content", {}).get("text", ""),
                    "score": round(float(r.get("score", 0.0)), 4),
                    "source": source,
                })
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
    log_event("kb_retrieval", domain=domain, kb_id=kb_id, hits=len(out["results"]),
              error=out["error"] or "", latency_ms=int((time.time() - started) * 1000))
    return out


def format_results(result: dict) -> str:
    """Render a retrieval result as compact JSON for an agent tool response."""
    return json.dumps(result, ensure_ascii=False)
