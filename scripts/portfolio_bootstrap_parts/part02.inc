            if match:
                stage = _stage_from_match(
                    match, path=path, line_number=number, heading=heading, line=line
                )
                if stage is not None:
                    candidates.append(stage)
                break
        else:
            match = UNLABELLED_OF.search(line)
            if match and heading:
                stage = _stage_from_match(
                    match, path=path, line_number=number, heading=heading, line=line
                )
                if stage is not None:
                    candidates.append(stage)

    by_label: dict[str, EvidenceStage] = {}
    exact_seen: set[tuple[str, int, int]] = set()
    for stage in candidates:
        key = (_slug(stage.label), stage.completed, stage.total)
        if key in exact_seen:
            continue
        exact_seen.add(key)
        normalized = _slug(stage.label)
        prior = by_label.get(normalized)
        if prior and (prior.completed, prior.total) != (stage.completed, stage.total):
            raise BootstrapClosed("contradictory_stage", f"{prior.evidence},{stage.evidence}")
        by_label[normalized] = stage
    stages = list(by_label.values())
    if len(stages) > MAX_STAGES:
        raise BootstrapClosed("too_many_explicit_stages", path)
    return stages


def authority_candidates(paths: Iterable[str]) -> list[str]:
    available = set(paths)
    ordered = [path for path in AUTHORITY_PATH_PRIORITY if path in available]
    excluded_roots = {
        "public",
        "private-build",
        "internal-build",
        "dist",
        "build",
        "node_modules",
        "vendor",
        ".git",
    }
    extras = sorted(
        path
        for path in available
        if path.lower().endswith((".md", ".markdown", ".txt"))
        and len(PurePosixPath(path).parts) <= 4
        and (not PurePosixPath(path).parts or PurePosixPath(path).parts[0].lower() not in excluded_roots)
        and any(term in PurePosixPath(path).name.lower() for term in AUTHORITY_NAME_TERMS)
        and path not in ordered
    )
    return ordered + extras


def classify_project(repo: dict[str, Any], paths: Iterable[str]) -> str:
    lower = {path.lower() for path in paths}
    suffixes = {PurePosixPath(path).suffix.lower() for path in lower}
    topics = repo.get("topics") if isinstance(repo.get("topics"), list) else []
    metadata = " ".join(
        [str(repo.get("description") or ""), *(str(topic) for topic in topics)]
    ).lower()

    manuscript = any(
        part in path
        for path in lower
        for part in ("manuscript/", "chapters/", "scenes/", "publication/", "proofs/")
    ) or any(
        term in metadata
        for term in ("manuscript", "novel", "novella", "fiction", "poetry", "story collection")
    )
    website = any(
        path in lower
        for path in ("astro.config.mjs", "astro.config.ts", "next.config.js", "wrangler.toml")
    ) or any(path.startswith("src/pages/") for path in lower) or any(
        term in metadata for term in ("website", "web site", "static site")
    )
    software = any(
        path in lower
        for path in (
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "cargo.toml",
            "cmakelists.txt",
            "go.mod",
        )
    )
    hardware = bool(suffixes & {".kicad_pcb", ".kicad_sch", ".sch", ".brd", ".gbr"}) or any(
        term in metadata for term in ("hardware", "pcb", "eurorack", "synthesizer module")
    )
    music = bool(suffixes & {".wav", ".flac", ".mp3", ".mid", ".midi"}) or any(
        term in metadata for term in ("music", "song archive", "audio recordings")
    )

    # Strong domain fingerprints take precedence over implementation tooling.
    # A website with package.json is still a website; a manuscript with helper
    # scripts is still a manuscript. "mixed" is reserved for genuinely distinct
    # domain fingerprints, not ordinary build infrastructure.
    strong = [
        label
        for label, present in (
            ("hardware", hardware),
            ("website", website),
            ("manuscript", manuscript),
            ("music", music),
        )
        if present
    ]
    if len(strong) == 1:
        return strong[0]
    if len(strong) > 1:
        return "mixed"
    if software:
        return "software"
    markdown_count = sum(path.endswith((".md", ".markdown")) for path in lower)
    if markdown_count:
        return "documentation"
    return "unknown"


def validate_progress(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise BootstrapClosed("progress_shape")
    allowed_top = {"schema_version", "authority", "project_type", "note", "stages", "overall"}
    if set(document) - allowed_top:
        raise BootstrapClosed("progress_unknown_field")
    if document.get("schema_version") != 1:
        raise BootstrapClosed("progress_version")
    authority = document.get("authority")
    if not isinstance(authority, str) or not authority.strip():
        raise BootstrapClosed("progress_authority")
    stages_raw = document.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise BootstrapClosed("progress_stages")
    seen: set[str] = set()
    stages: list[dict[str, Any]] = []
    for raw in stages_raw:
        if not isinstance(raw, dict):
            raise BootstrapClosed("progress_stage_shape")
        allowed_stage = {"id", "label", "completed", "total", "weight", "evidence"}
        if set(raw) - allowed_stage:
            raise BootstrapClosed("progress_stage_unknown_field")
        required = {"id", "label", "completed", "total"}
        if not required.issubset(raw):
            raise BootstrapClosed("progress_stage_fields")
        stage_id = raw["id"]
        label = raw["label"]
        completed = raw["completed"]
        total = raw["total"]
        if not isinstance(stage_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", stage_id):
            raise BootstrapClosed("progress_stage_id")
        if stage_id in seen:
            raise BootstrapClosed("progress_stage_duplicate")
        seen.add(stage_id)
        if not isinstance(label, str) or not label.strip():
            raise BootstrapClosed("progress_stage_label")
        if isinstance(completed, bool) or not isinstance(completed, int):
            raise BootstrapClosed("progress_stage_completed")
        if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
            raise BootstrapClosed("progress_stage_total")
        if completed < 0 or completed > total:
            raise BootstrapClosed("progress_stage_range")
        weight = raw.get("weight")
        if weight is not None:
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise BootstrapClosed("progress_stage_weight")
            weight = float(weight)
            if not math.isfinite(weight) or weight < 0:
                raise BootstrapClosed("progress_stage_weight")
        stages.append(
            {
                "id": stage_id,
                "label": label.strip(),
                "completed": completed,
                "total": total,
                "percentage": round(completed / total * 100, 1),
                "weight": weight,
            }
        )
    overall = document.get("overall", {"enabled": False})
    if not isinstance(overall, dict) or set(overall) - {"enabled"}:
        raise BootstrapClosed("progress_overall_shape")
    enabled = overall.get("enabled", False)
    if not isinstance(enabled, bool):
        raise BootstrapClosed("progress_overall_enabled")
    overall_percentage: float | None = None
    if enabled:
        if any(stage["weight"] is None for stage in stages):
            raise BootstrapClosed("progress_overall_missing_weight")
        weight_total = sum(float(stage["weight"]) for stage in stages)
        if abs(weight_total - 100.0) > 0.001:
            raise BootstrapClosed("progress_overall_weight_total")
        overall_percentage = round(
            sum(stage["percentage"] * float(stage["weight"]) for stage in stages) / 100,
            1,
        )
    return {
        "authority": authority.strip(),
        "stages": stages,
        "overall_percentage": overall_percentage,
    }


