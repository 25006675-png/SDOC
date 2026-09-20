"""Measured operational metrics shared by the local and Supabase stores."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any


ACTION_STATES = {"DISCREPANCY", "NEEDS_REVIEW", "BLOCKED"}


def _timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def build_metrics(cases, routed, tasks, comparisons, case_email_count, now):
    """Build conservative metrics from persisted facts only."""
    states = Counter(case.get("state") for case in cases)
    states.pop(None, None)
    categories = Counter(item.get("category") for item in routed)
    categories.pop(None, None)
    classification_review = 0
    for item in routed:
        payload = _json(item.get("payload_json"), {})
        classification = payload.get("classification") if isinstance(payload, dict) else None
        if isinstance(classification, dict) and classification.get("classification_status") == "needs_review":
            classification_review += 1
    total = len(cases)
    action_count = sum(states[state] for state in ACTION_STATES)
    active_backlog = action_count + states["WAITING"]

    open_tasks = [task for task in tasks if task.get("status") == "OPEN"]
    resolved_tasks = [task for task in tasks if task.get("status") == "RESOLVED"]
    resolution_times = []
    for task in resolved_tasks:
        created, resolved = _timestamp(task.get("created_at")), _timestamp(task.get("resolved_at"))
        if created is not None and resolved is not None and resolved >= created:
            resolution_times.append(resolved - created)

    action_ages = []
    for case in cases:
        if case.get("state") in ACTION_STATES:
            updated = _timestamp(case.get("updated_at"))
            if updated is not None:
                action_ages.append(max(0, now - updated))

    defect_fields = Counter()
    verifier_checks = 0
    verifier_disagreements = 0
    verifier_failures = 0
    verifier_successes = 0
    for comparison in comparisons:
        defect_fields.update(_json(comparison.get("defect_fields"), []))
        evidence = _json(comparison.get("evidence_json", comparison.get("evidence")), {})
        verification = evidence.get("verification") if isinstance(evidence, dict) else None
        if isinstance(verification, dict) and verification.get("status"):
            verifier_checks += 1
            if verification["status"] == "DISAGREED":
                verifier_disagreements += 1
                verifier_successes += 1
            elif verification["status"] == "AGREED":
                verifier_successes += 1
            elif verification["status"] == "FAILED":
                verifier_failures += 1

    rate = lambda count, base=total: round(count / base, 4) if base else 0.0
    return {
        "cases": total,
        "states": dict(states),
        "routed_messages": len(routed),
        "classification_review_messages": classification_review,
        "categories": dict(categories),
        "processed_messages": case_email_count + len(routed),
        "comparisons": len(comparisons),
        "automated_resolution_rate": rate(states["VERIFIED"]),
        "manual_review_rate": rate(action_count),
        "active_backlog": active_backlog,
        "open_review_tasks": len(open_tasks),
        "resolved_review_tasks": len(resolved_tasks),
        "average_review_resolution_seconds": (
            round(sum(resolution_times) / len(resolution_times), 1) if resolution_times else None
        ),
        "waiting_cases": states["WAITING"],
        "overdue_cases": states["BLOCKED"],
        "oldest_action_age_seconds": round(max(action_ages), 1) if action_ages else None,
        "verifier_checks": verifier_checks,
        "verifier_disagreements": verifier_disagreements,
        "verifier_failures": verifier_failures,
        "verifier_agreement_rate": rate(verifier_successes - verifier_disagreements, verifier_successes),
        "discrepancy_fields": dict(defect_fields.most_common()),
    }
