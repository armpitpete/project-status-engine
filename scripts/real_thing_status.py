"""Validate evidence-bound project status claims.

This module implements the project-local adoption of Threadkeeper's
Real-Thing Proof and Completion Status Protocol v0.1. Progress percentages
remain separate: counted work does not prove deployment, live behaviour,
human acceptance, or completion.
"""
from __future__ import annotations

from typing import Any

STAGES = (
    "designed",
    "implemented",
    "automated-checks",
    "independent-review",
    "merged",
    "deployed",
    "live-behaviour",
    "human-acceptance",
)

STATUS_TO_STAGE = {
    "designed": "designed",
    "implemented": "implemented",
    "automated-checks-passed": "automated-checks",
    "independently-reviewed": "independent-review",
    "merged": "merged",
    "deployed": "deployed",
    "live-behaviour-verified": "live-behaviour",
    "human-acceptance-received": "human-acceptance",
}

CLAIMED_STATUSES = set(STATUS_TO_STAGE) | {"complete"}
VERIFIED_STATUSES = CLAIMED_STATUSES | {"insufficient", "failed"}
RESULTS = {"PASS", "FAIL", "INSUFFICIENT", "NOT_APPLICABLE"}
RELATIONSHIPS = {"direct", "proxy", "missing", "not-applicable"}
STATUS_FIELDS = {"claimed", "verified", "authority", "stages", "limitations"}
STAGE_FIELDS = {
    "stage",
    "required",
    "required_environment",
    "rationale",
    "result",
    "relationship",
    "observed_environment",
    "evidence",
    "limitations",
}


class StatusValidationError(ValueError):
    """Raised when a status claim overstates its evidence."""


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise StatusValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise StatusValidationError(f"{field} must be an array")
    result = []
    for index, item in enumerate(value):
        result.append(str(_text(item, f"{field}[{index}]")))
    if len(result) != len(set(result)):
        raise StatusValidationError(f"{field} must not contain duplicates")
    return result


def _expected_verified(claimed: str, stages: dict[str, dict[str, Any]]) -> str:
    required = [stage for stage in STAGES if stages[stage]["required"]]
    if not required:
        return "insufficient"

    if claimed == "complete":
        relevant = required
    else:
        target = STATUS_TO_STAGE[claimed]
        if not stages[target]["required"]:
            return "insufficient"
        target_index = STAGES.index(target)
        relevant = [stage for stage in required if STAGES.index(stage) <= target_index]

    if any(stages[stage]["result"] == "FAIL" for stage in relevant):
        return "failed"

    if all(
        stages[stage]["result"] == "PASS"
        and stages[stage]["relationship"] == "direct"
        and stages[stage]["observed_environment"]
        == stages[stage]["required_environment"]
        for stage in relevant
    ):
        return "complete" if claimed == "complete" else claimed
    return "insufficient"


def validate_status(raw: Any) -> dict[str, Any]:
    """Validate one explicit status claim and return its normalized form."""
    if not isinstance(raw, dict):
        raise StatusValidationError("status must be an object")
    unknown = sorted(set(raw) - STATUS_FIELDS)
    if unknown:
        raise StatusValidationError(
            "status contains unknown fields: " + ", ".join(unknown)
        )

    claimed = _text(raw.get("claimed"), "status.claimed")
    verified = _text(raw.get("verified"), "status.verified")
    if claimed not in CLAIMED_STATUSES:
        raise StatusValidationError("status.claimed is not a supported status")
    if verified not in VERIFIED_STATUSES:
        raise StatusValidationError("status.verified is not a supported status")
    authority = _text(raw.get("authority"), "status.authority")
    limitations = _text_list(raw.get("limitations", []), "status.limitations")

    stages_raw = raw.get("stages")
    if not isinstance(stages_raw, list) or len(stages_raw) != len(STAGES):
        raise StatusValidationError("status.stages must contain all eight stages")

    stages: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(stages_raw):
        prefix = f"status.stages[{index}]"
        if not isinstance(item, dict):
            raise StatusValidationError(f"{prefix} must be an object")
        unknown = sorted(set(item) - STAGE_FIELDS)
        if unknown:
            raise StatusValidationError(
                f"{prefix} contains unknown fields: " + ", ".join(unknown)
            )
        stage = _text(item.get("stage"), f"{prefix}.stage")
        if stage not in STAGES:
            raise StatusValidationError(f"{prefix}.stage is not supported")
        if stage in stages:
            raise StatusValidationError(f"duplicate status stage: {stage}")
        required = item.get("required")
        if not isinstance(required, bool):
            raise StatusValidationError(f"{prefix}.required must be true or false")
        required_environment = _text(
            item.get("required_environment"),
            f"{prefix}.required_environment",
            optional=True,
        )
        rationale = _text(
            item.get("rationale"), f"{prefix}.rationale", optional=True
        )
        result = _text(item.get("result"), f"{prefix}.result")
        relationship = _text(item.get("relationship"), f"{prefix}.relationship")
        observed_environment = _text(
            item.get("observed_environment"),
            f"{prefix}.observed_environment",
            optional=True,
        )
        evidence = _text_list(item.get("evidence", []), f"{prefix}.evidence")
        stage_limitations = _text_list(
            item.get("limitations", []), f"{prefix}.limitations"
        )

        if result not in RESULTS:
            raise StatusValidationError(f"{prefix}.result is not supported")
        if relationship not in RELATIONSHIPS:
            raise StatusValidationError(f"{prefix}.relationship is not supported")

        if required:
            if required_environment is None:
                raise StatusValidationError(
                    f"{prefix} requires a required_environment"
                )
            if rationale is not None:
                raise StatusValidationError(
                    f"{prefix} cannot have a not-applicable rationale"
                )
            if result == "NOT_APPLICABLE" or relationship == "not-applicable":
                raise StatusValidationError(
                    f"{prefix} is required and cannot be not applicable"
                )
        else:
            if required_environment is not None:
                raise StatusValidationError(
                    f"{prefix} is not applicable and cannot require an environment"
                )
            if rationale is None:
                raise StatusValidationError(
                    f"{prefix} is not applicable and requires a rationale"
                )
            if result != "NOT_APPLICABLE" or relationship != "not-applicable":
                raise StatusValidationError(
                    f"{prefix} must use NOT_APPLICABLE and not-applicable"
                )
            if observed_environment is not None or evidence:
                raise StatusValidationError(
                    f"{prefix} is not applicable and cannot contain evidence"
                )

        if required and result == "PASS":
            if relationship != "direct":
                raise StatusValidationError(
                    f"{prefix} PASS requires direct evidence; proxy evidence cannot pass"
                )
            if observed_environment != required_environment:
                raise StatusValidationError(
                    f"{prefix} PASS must exercise the required environment"
                )
            if not evidence:
                raise StatusValidationError(f"{prefix} PASS requires evidence")
        elif required and result == "FAIL":
            if relationship != "direct":
                raise StatusValidationError(
                    f"{prefix} FAIL requires direct evidence; proxy failure is INSUFFICIENT"
                )
            if observed_environment != required_environment:
                raise StatusValidationError(
                    f"{prefix} FAIL must exercise the required environment"
                )
            if not evidence:
                raise StatusValidationError(f"{prefix} FAIL requires evidence")
        elif required and result == "INSUFFICIENT":
            if relationship == "missing":
                if observed_environment is not None or evidence:
                    raise StatusValidationError(
                        f"{prefix} missing evidence cannot contain observations"
                    )
            elif relationship == "proxy":
                if observed_environment is None or not evidence:
                    raise StatusValidationError(
                        f"{prefix} proxy evidence needs an environment and evidence"
                    )
            elif relationship == "direct":
                if observed_environment is None:
                    raise StatusValidationError(
                        f"{prefix} direct INSUFFICIENT needs an observed environment"
                    )
            else:
                raise StatusValidationError(
                    f"{prefix} INSUFFICIENT must be direct, proxy, or missing"
                )

        stages[stage] = {
            "stage": stage,
            "required": required,
            "required_environment": required_environment,
            "rationale": rationale,
            "result": result,
            "relationship": relationship,
            "observed_environment": observed_environment,
            "evidence": evidence,
            "limitations": stage_limitations,
        }

    missing = [stage for stage in STAGES if stage not in stages]
    if missing:
        raise StatusValidationError("status is missing stages: " + ", ".join(missing))
    if not any(item["required"] for item in stages.values()):
        raise StatusValidationError("status must require at least one stage")

    expected = _expected_verified(str(claimed), stages)
    if verified != expected:
        raise StatusValidationError(
            f"status.verified must be {expected!r} for the declared evidence"
        )

    return {
        "claimed": claimed,
        "verified": verified,
        "authority": authority,
        "stages": [stages[stage] for stage in STAGES],
        "limitations": limitations,
    }
