"""Explicit audit retention job, suitable for an operator-managed scheduler."""
import argparse
from datetime import datetime, timedelta

from ..config import settings
from ..db import SessionLocal
from .models import AgentRun


def prune_runs(db, days: int, *, apply=False):
    if days < 1:
        raise ValueError("Retention must be at least one day")
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = db.query(AgentRun).filter(AgentRun.finished_at.is_not(None), AgentRun.finished_at < cutoff)
    count = query.count()
    if apply:
        query.delete(synchronize_session=False)
        db.commit()
    return {"eligible": count, "cutoff": cutoff.isoformat(), "applied": apply}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=settings.agent_trace_retention_days)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        print(prune_runs(db, args.days, apply=args.apply))


if __name__ == "__main__":
    main()
