def build_contract(project_type: str, authority: str, stages: list[EvidenceStage]) -> dict[str, Any]:
    used: set[str] = set()
    payload_stages: list[dict[str, Any]] = []
    for index, stage in enumerate(stages, 1):
        base = _slug(stage.label)
        stage_id = base
        suffix = 2
        while stage_id in used:
            stage_id = f"{base}_{suffix}"
            suffix += 1
        used.add(stage_id)
        payload_stages.append(
            {
                "id": stage_id,
                "label": stage.label,
                "completed": stage.completed,
                "total": stage.total,
                "evidence": stage.evidence,
            }
        )
    return {
        "schema_version": 1,
        "authority": authority,
        "project_type": project_type,
        "note": "This contract reports only the bounded completion stages explicitly recorded in the cited repository authority. Overall completion, readiness and release status are not inferred.",
        "stages": payload_stages,
        "overall": {"enabled": False},
    }


def progress_view(contract: dict[str, Any]) -> dict[str, Any]:
    return validate_progress(contract)


def render_generated_section(progress: dict[str, Any], newline: bytes = b"\n") -> bytes:
    lines = [
        "## Completion",
        "",
        "_Generated from validated project authority by `project-status-engine`. Repository activity is not completion._",
        "",
        "| Stage | Progress |",
        "|---|---:|",
    ]
    for stage in progress["stages"]:
        label = stage["label"].replace("|", "\\|").replace("\r", " ").replace("\n", " ")
        lines.append(
            f"| {label} | `{stage['completed']}/{stage['total']}` — **{stage['percentage']:.1f}%** |"
        )
    authority = progress["authority"].replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    lines += ["", f"Authority: `{authority}`", ""]
    overall = progress.get("overall_percentage")
    if overall is None:
        lines.append("Overall completion is not enabled for this project.")
    else:
        lines.append(f"Overall completion: **{float(overall):.1f}%**")
    return newline.join(line.encode("utf-8") for line in lines)


def desired_readme(readme: bytes | None, progress: dict[str, Any]) -> bytes:
    readme = readme or b""
    try:
        readme.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BootstrapClosed("readme_not_utf8") from exc
    start_count = readme.count(START_MARKER)
    end_count = readme.count(END_MARKER)
    newline = b"\r\n" if b"\r\n" in readme else b"\n"
    generated = render_generated_section(progress, newline)
    if start_count == 0 and end_count == 0:
        prefix = readme
        separator = b"" if not prefix else (b"" if prefix.endswith((b"\n", b"\r")) else newline)
        if prefix and not prefix.endswith(newline * 2):
            separator += newline
        return prefix + separator + START_MARKER + newline + generated + newline + END_MARKER + newline
    if start_count != 1 or end_count != 1:
        raise BootstrapClosed("readme_markers")
    start = readme.index(START_MARKER)
    end = readme.index(END_MARKER)
    if start >= end:
        raise BootstrapClosed("readme_marker_order")
    inner_start = start + len(START_MARKER)
    prefix = readme[:inner_start]
    suffix = readme[end:]
    desired = prefix + newline + generated + newline + suffix
    if desired[:inner_start] != prefix or desired[-len(suffix) :] != suffix:
        raise BootstrapClosed("human_readme_bytes_changed")
    return desired


class GitHubClient:
    def __init__(self, token: str, api_root: str = API_ROOT):
        if not token:
            raise BootstrapClosed("token_missing")
        self.token = token
        self.api_root = api_root.rstrip("/")

    def request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        url = self.api_root + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "project-status-engine-bootstrap",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            raise ApiFailure(operation, exc.code) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ApiFailure(operation) from None

    def repositories(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self.request(
                "repositories",
                "GET",
                "/user/repos",
                query={
                    "visibility": "all",
                    "affiliation": "owner",
                    "sort": "full_name",
                    "direction": "asc",
                    "per_page": 100,
                    "page": page,
                },
            )
            if not isinstance(batch, list):
                raise BootstrapClosed("repository_inventory_shape")
            result.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return result

    def repository(self, full_name: str) -> dict[str, Any]:
        value = self.request("repository", "GET", f"/repos/{full_name}")
        if not isinstance(value, dict):
            raise BootstrapClosed("repository_shape")
        return value

    def ref(self, full_name: str, branch: str) -> dict[str, Any] | None:
        encoded = urllib.parse.quote(f"heads/{branch}", safe="/")
        return self.request("ref", "GET", f"/repos/{full_name}/git/ref/{encoded}", allow_404=True)

    def tree(self, full_name: str, sha: str) -> list[dict[str, Any]]:
        value = self.request(
            "tree", "GET", f"/repos/{full_name}/git/trees/{sha}", query={"recursive": "1"}
        )
        if not isinstance(value, dict) or not isinstance(value.get("tree"), list):
            raise BootstrapClosed("tree_shape")
        if value.get("truncated"):
            raise BootstrapClosed("tree_truncated")
        return value["tree"]

    def file(self, full_name: str, path: str, ref: str) -> tuple[bytes, str] | None:
        value = self.request(
            "file",
            "GET",
            f"/repos/{full_name}/contents/{urllib.parse.quote(path, safe='/')}",
            query={"ref": ref},
            allow_404=True,
        )
        if value is None:
            return None
        if not isinstance(value, dict) or value.get("type") != "file" or value.get("encoding") != "base64":
            raise BootstrapClosed("file_shape", path)
        content = value.get("content")
        sha = value.get("sha")
        if not isinstance(content, str) or not isinstance(sha, str):
            raise BootstrapClosed("file_payload", path)
        try:
            raw = base64.b64decode(content.replace("\n", ""), validate=True)
        except ValueError as exc:
            raise BootstrapClosed("file_base64", path) from exc
        return raw, sha

