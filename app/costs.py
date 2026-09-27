"""Per-call cost tracking + budget guard. Every vision/embedding/text call writes one CostLog row."""
import logging
from sqlalchemy import func, select
from .config import settings
from .db import CostLog
from .providers.base import Usage

log = logging.getLogger("costs")


def estimate(kind: str, u: Usage) -> float:
    if kind == "embedding":
        return u.input_tokens / 1e6 * settings.embed_input_usd_per_m
    return u.input_tokens / 1e6 * settings.vision_input_usd_per_m + u.output_tokens / 1e6 * settings.vision_output_usd_per_m


def record(db, *, job_id, kind, target, usage: Usage | None, ok=True, attempt=1, model=None):
    u = usage or Usage(model or "unknown")
    row = CostLog(job_id=job_id, kind=kind, model=u.model, target=target, input_tokens=u.input_tokens,
                  output_tokens=u.output_tokens, est_cost_usd=round(estimate(kind, u), 8), ok=ok, attempt=attempt)
    db.add(row)
    db.flush()
    return row


def total_spent(db) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(CostLog.est_cost_usd), 0.0))) or 0.0)


def over_budget(db) -> bool:
    return total_spent(db) >= settings.budget_usd
