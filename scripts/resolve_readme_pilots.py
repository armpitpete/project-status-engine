#!/usr/bin/env python3
"""Resolve contract-shaped pilot selectors to an ephemeral opaque allowlist.

Repository names are read only from the trusted internal dataset. The committed
selector file contains no repository identity, and the generated allowlist stays
inside ``internal-build/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


class ResolutionClosed(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def identifier(full_name: str) -> str:
    return hashlib.sha256(full_name.encode("utf-8")).hexdigest()


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResolutionClosed(code) from exc


def load_selectors(path: Path) -> list[dict[str, Any]]:
    document = _read_json(path, "selectors_unreadable")
    if not isinstance(document, dict) or set(document) != {"schema_version", "targets"}:
        raise ResolutionClosed("selectors_shape")
    if document.get("schema_version") != 1:
        raise ResolutionClosed("selectors_version")
    targets = document.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ResolutionClosed("selectors_empty")
    allowed = {"id", "project_type", "authority", "private", "stage_ids"}
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in targets:
        if not isinstance(raw, dict) or set(raw) != allowed:
            raise ResolutionClosed("selector_shape")
        selector_id = raw.get("id")
        project_type = raw.get("project_type")
        authority = raw.get("authority")
        private = raw.get("private")
        stage_ids = raw.get("stage_ids")
        if not isinstance(selector_id, str) or not selector_id:
            raise ResolutionClosed("selector_id")
        if selector_id in ids:
            raise ResolutionClosed("selector_duplicate")
        if not isinstance(project_type, str) or not project_type:
            raise ResolutionClosed("selector_project_type")
        if not isinstance(authority, str) or not authority:
            raise ResolutionClosed("selector_authority")
        if not isinstance(private, bool):
            raise ResolutionClosed("selector_private")
        if (
            not isinstance(stage_ids, list)
            or not stage_ids
            or any(not isinstance(value, str) or not value for value in stage_ids)
            or len(stage_ids) != len(set(stage_ids))
        ):
            raise ResolutionClosed("selector_stage_ids")
        ids.add(selector_id)
        result.append(dict(raw))
    return result


def _valid_percentage(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and 0 <= float(value) <= 100
    )


def _validated_completion(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("state") != "valid":
        return None
    authority = value.get("authority")
    project_type = value.get("project_type")
    stages = value.get("stages")
    if (
        not isinstance(authority, str)
        or not authority
        or not isinstance(project_type, str)
        or not project_type
        or not isinstance(stages, list)
        or not stages
    ):
        raise ResolutionClosed("completion_invalid")
    stage_ids: list[str] = []
    for stage in stages:
        if not isinstance(stage, dict):
            raise ResolutionClosed("completion_stage")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            raise ResolutionClosed("completion_stage_id")
        if not _valid_percentage(stage.get("percentage")):
            raise ResolutionClosed("completion_percentage")
        stage_ids.append(stage_id)
    if len(stage_ids) != len(set(stage_ids)):
        raise ResolutionClosed("completion_duplicate_stage")
    return {
        "authority": authority,
        "project_type": project_type,
        "stage_ids": stage_ids,
    }


def resolve(dataset_path: Path, selector_path: Path) -> dict[str, Any]:
    selectors = load_selectors(selector_path)
    document = _read_json(dataset_path, "dataset_unreadable")
    if not isinstance(document, dict) or document.get("view") != "internal-owner-completion":
        raise ResolutionClosed("dataset_view")
    repositories = document.get("repositories")
    if not isinstance(repositories, list):
        raise ResolutionClosed("dataset_repositories")

    candidates: list[dict[str, Any]] = []
    for record in repositories:
        if not isinstance(record, dict):
            raise ResolutionClosed("dataset_record")
        full_name = record.get("full_name")
        private = record.get("private")
        if not isinstance(full_name, str) or "/" not in full_name:
            raise ResolutionClosed("dataset_repository_name")
        if not isinstance(private, bool):
            raise ResolutionClosed("dataset_privacy")
        completion = _validated_completion(record.get("completion"))
        if completion is None:
            continue
        candidates.append(
            {
                "full_name": full_name,
                "private": private,
                **completion,
            }
        )

    hashes: list[str] = []
    used_names: set[str] = set()
    for selector in selectors:
        matches = [
            candidate
            for candidate in candidates
            if candidate["private"] is selector["private"]
            and candidate["project_type"] == selector["project_type"]
            and candidate["authority"] == selector["authority"]
            and candidate["stage_ids"] == selector["stage_ids"]
        ]
        if len(matches) != 1:
            raise ResolutionClosed("selector_match")
        full_name = matches[0]["full_name"]
        if full_name in used_names:
            raise ResolutionClosed("selector_overlap")
        used_names.add(full_name)
        hashes.append(identifier(full_name))
    return {"schema_version": 1, "target_hashes": hashes}


def write_allowlist(document: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--selectors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        document = resolve(args.dataset, args.selectors)
        write_allowlist(document, args.output)
    except ResolutionClosed as exc:
        print(json.dumps({"status": "closed", "code": exc.code}, separators=(",", ":")))
        return 1
    print(json.dumps({"status": "resolved", "targets": len(document["target_hashes"])}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
