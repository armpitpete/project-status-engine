#!/usr/bin/env python3
"""Read-only forensic scan of all accessible repositories owned by one account.

The report never records matched secret values. It records only detector type,
location, length and a SHA-256 fingerprint of the matched bytes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator

API_ROOT = "https://api.github.com"
OVERLAP = 1024
MAX_ARCHIVE_DEPTH = 2
MAX_ARCHIVE_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class Detector:
    name: str
    pattern: re.Pattern[bytes]
    value_group: int = 0


DETECTORS = (
    Detector(
        "private_key_header",
        re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    Detector(
        "github_token",
        re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    ),
    Detector(
        "openai_key",
        re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    Detector("aws_access_key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    Detector("google_api_key", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    Detector("slack_token", re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    Detector(
        "credential_in_url",
        re.compile(rb"https?://[^\s/:@]{1,128}:[^\s/@]{3,256}@"),
    ),
    Detector(
        "credential_assignment",
        re.compile(
            rb"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|secret|token)\b"
            rb"\s*[:=]\s*[\"']?([A-Za-z0-9_./+=:-]{16,512})"
        ),
        1,
    ),
    Detector(
        "windows_absolute_path",
        re.compile(rb"\b[A-Za-z]:\\(?:[^\\\r\n\x00]{1,120}\\){1,12}[^\r\n\x00]{0,120}"),
    ),
    Detector(
        "unix_home_path",
        re.compile(rb"/(?:home|Users)/[A-Za-z0-9._-]{1,80}/[^\s\x00]{1,240}"),
    ),
    Detector(
        "ssh_target",
        re.compile(rb"(?i)\bssh\s+(?:-[A-Za-z]\s+[^\s]+\s+)*[A-Za-z0-9._-]+@[A-Za-z0-9._-]+"),
    ),
)

SENSITIVE_PATH = re.compile(
    r"(?i)(?:^|/)(?:\.env(?:\..*)?|id_(?:rsa|ed25519|ecdsa)|credentials?(?:\..*)?|secrets?(?:\..*)?|[^/]+\.(?:pem|p12|pfx|key|keystore))$"
)
SAFE_PATH_SUFFIXES = (".example", ".sample", ".template", ".dist")
PLACEHOLDER_TERMS = (
    b"example",
    b"placeholder",
    b"your-key",
    b"your_key",
    b"changeme",
    b"change-me",
    b"dummy",
    b"redacted",
    b"process.env",
    b"secrets.",
    b"${",
)


@dataclass
class Finding:
    repository: str
    surface: str
    location: str
    detector: str
    fingerprint: str
    match_length: int
    object_sha: str | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "repository": self.repository,
            "surface": self.surface,
            "location": self.location,
            "detector": self.detector,
            "fingerprint": self.fingerprint,
            "match_length": self.match_length,
        }
        if self.object_sha:
            result["object_sha"] = self.object_sha
        return result


@dataclass
class RepositoryReport:
    repository: str
    visibility: str
    archived: bool
    refs_scanned: int = 0
    git_objects_scanned: int = 0
    git_bytes_scanned: int = 0
    workflow_runs_scanned: int = 0
    workflow_logs_scanned: int = 0
    artifacts_scanned: int = 0
    releases_scanned: int = 0
    release_assets_scanned: int = 0
    findings: list[Finding] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)

    def error(self, surface: str, code: str, status: int | None = None) -> None:
        entry: dict[str, object] = {"surface": surface, "code": code}
        if status is not None:
            entry["status"] = status
        self.errors.append(entry)


class GitHubClient:
    def __init__(self, token: str):
        if not token:
            raise AuditError("FORENSIC_AUDIT_TOKEN or PROJECT_STATUS_TOKEN is required")
        self.token = token
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "project-status-engine-forensic-audit",
        }

    def request_json(self, path: str, query: dict[str, str] | None = None) -> object:
        url = API_ROOT + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ApiStatus(exc.code) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AuditError("GitHub API request failed") from exc

    def paginate(self, path: str, key: str | None = None) -> Iterator[dict[str, object]]:
        page = 1
        while True:
            payload = self.request_json(path, {"per_page": "100", "page": str(page)})
            if key is not None:
                if not isinstance(payload, dict):
                    raise AuditError("unexpected paginated payload")
                items = payload.get(key)
            else:
                items = payload
            if not isinstance(items, list):
                raise AuditError("unexpected paginated item list")
            for item in items:
                if isinstance(item, dict):
                    yield item
            if len(items) < 100:
                break
            page += 1

    def owner_repositories(self, owner: str) -> list[dict[str, object]]:
        repositories = []
        for repository in self.paginate("/user/repos"):
            full_name = repository.get("full_name")
            repository_owner = repository.get("owner")
            login = repository_owner.get("login") if isinstance(repository_owner, dict) else None
            if login == owner and isinstance(full_name, str):
                repositories.append(repository)
        return sorted(repositories, key=lambda item: str(item["full_name"]))

    def download(self, url_or_path: str, destination: Path, accept: str | None = None) -> None:
        url = url_or_path if url_or_path.startswith("https://") else API_ROOT + url_or_path
        headers = dict(self.headers)
        if accept:
            headers["Accept"] = accept
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
        except urllib.error.HTTPError as exc:
            raise ApiStatus(exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AuditError("GitHub download failed") from exc


class ApiStatus(RuntimeError):
    def __init__(self, status: int):
        super().__init__(str(status))
        self.status = status


def is_placeholder(value: bytes) -> bool:
    lowered = value.lower()
    if any(term in lowered for term in PLACEHOLDER_TERMS):
        return True
    if value.startswith(b"${{") or value.startswith(b"$"):
        return True
    if len(set(value)) <= 3:
        return True
    return False


def match_fingerprint(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def scan_bytes(
    data: bytes,
    *,
    repository: str,
    surface: str,
    location: str,
    object_sha: str | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    for detector in DETECTORS:
        for match in detector.pattern.finditer(data):
            value = match.group(detector.value_group)
            if detector.name == "credential_assignment" and is_placeholder(value):
                continue
            findings.append(
                Finding(
                    repository=repository,
                    surface=surface,
                    location=location,
                    detector=detector.name,
                    fingerprint=match_fingerprint(value),
                    match_length=len(value),
                    object_sha=object_sha,
                )
            )
    return findings


def scan_stream(
    stream: BinaryIO,
    *,
    repository: str,
    surface: str,
    location: str,
    object_sha: str | None = None,
) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    tail = b""
    total = 0
    seen: set[tuple[str, str, int]] = set()
    while True:
        block = stream.read(1024 * 1024)
        if not block:
            break
        combined = tail + block
        for finding in scan_bytes(
            combined,
            repository=repository,
            surface=surface,
            location=location,
            object_sha=object_sha,
        ):
            key = (finding.detector, finding.fingerprint, finding.match_length)
            if key not in seen:
                seen.add(key)
                findings.append(finding)
        total += len(block)
        tail = combined[-OVERLAP:]
    return findings, total


def sensitive_path_finding(repository: str, surface: str, path: str, object_sha: str | None = None) -> Finding | None:
    lowered = path.lower()
    if lowered.endswith(SAFE_PATH_SUFFIXES):
        return None
    if not SENSITIVE_PATH.search(path):
        return None
    encoded = path.encode("utf-8", errors="replace")
    return Finding(
        repository=repository,
        surface=surface,
        location=path,
        detector="sensitive_path",
        fingerprint=match_fingerprint(encoded),
        match_length=len(encoded),
        object_sha=object_sha,
    )


def safe_location(value: str) -> str:
    return value.replace("\x00", "?")[:1000]


def git_command(repository: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise AuditError("git command failed")
    return process.stdout


def clone_mirror(full_name: str, token: str, destination: Path) -> None:
    basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    header = f"AUTHORIZATION: basic {basic}"
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    clone = subprocess.run(
        [
            "git",
            "-c",
            f"http.extraHeader={header}",
            "clone",
            "--mirror",
            "--quiet",
            f"https://github.com/{full_name}.git",
            str(destination),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    if clone.returncode != 0:
        raise AuditError("mirror clone failed")
    fetch = subprocess.run(
        [
            "git",
            "-c",
            f"http.extraHeader={header}",
            "fetch",
            "--quiet",
            "origin",
            "+refs/pull/*/head:refs/pull/*/head",
        ],
        cwd=destination,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    if fetch.returncode != 0:
        # Some repositories may not expose pull refs. Existing heads and tags remain scanned.
        return


def scan_git_history(full_name: str, mirror: Path, report: RepositoryReport) -> None:
    refs = git_command(mirror, "for-each-ref", "--format=%(refname)").decode("utf-8", errors="replace").splitlines()
    report.refs_scanned = len(refs)
    raw_objects = git_command(mirror, "rev-list", "--objects", "--all")
    path_by_sha: dict[str, str] = {}
    ordered_shas: list[str] = []
    for raw_line in raw_objects.splitlines():
        sha_raw, separator, path_raw = raw_line.partition(b" ")
        sha = sha_raw.decode("ascii", errors="ignore")
        if len(sha) not in {40, 64}:
            continue
        if sha not in path_by_sha:
            ordered_shas.append(sha)
            path_by_sha[sha] = path_raw.decode("utf-8", errors="replace") if separator else ""
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=mirror,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        for sha in ordered_shas:
            process.stdin.write(sha.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().decode("ascii", errors="replace").strip().split()
            if len(header) != 3 or header[1] == "missing":
                report.error("git", "object_missing")
                continue
            object_type = header[1]
            try:
                size = int(header[2])
            except ValueError:
                report.error("git", "object_size_invalid")
                continue
            content = process.stdout.read(size)
            process.stdout.read(1)
            if object_type not in {"blob", "commit", "tag"}:
                continue
            path = path_by_sha.get(sha) or f"{object_type}:{sha}"
            report.git_objects_scanned += 1
            report.git_bytes_scanned += len(content)
            if object_type == "blob":
                path_finding = sensitive_path_finding(full_name, "git_history", path, sha)
                if path_finding:
                    report.findings.append(path_finding)
            report.findings.extend(
                scan_bytes(
                    content,
                    repository=full_name,
                    surface="git_history",
                    location=safe_location(path),
                    object_sha=sha,
                )
            )
    finally:
        process.stdin.close()
        process.stdout.close()
        process.terminate()
        process.wait(timeout=10)


def scan_archive(
    path: Path,
    *,
    repository: str,
    surface: str,
    location: str,
    depth: int = 0,
) -> tuple[list[Finding], int, list[str]]:
    findings: list[Finding] = []
    limitations: list[str] = []
    with path.open("rb") as stream:
        raw_findings, raw_size = scan_stream(
            stream,
            repository=repository,
            surface=surface,
            location=location,
        )
        findings.extend(raw_findings)
    if depth >= MAX_ARCHIVE_DEPTH:
        return findings, raw_size, limitations

    expanded = 0
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    expanded += member.file_size
                    if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                        limitations.append(f"archive_expansion_limit:{location}")
                        break
                    member_name = safe_location(member.filename)
                    path_finding = sensitive_path_finding(repository, surface, f"{location}!{member_name}")
                    if path_finding:
                        findings.append(path_finding)
                    try:
                        with archive.open(member) as member_stream:
                            member_findings, _ = scan_stream(
                                member_stream,
                                repository=repository,
                                surface=surface,
                                location=f"{location}!{member_name}",
                            )
                            findings.extend(member_findings)
                    except (RuntimeError, OSError, zipfile.BadZipFile):
                        limitations.append(f"unreadable_zip_member:{location}!{member_name}")
        except (OSError, zipfile.BadZipFile):
            limitations.append(f"unreadable_zip:{location}")
    elif tarfile.is_tarfile(path):
        try:
            with tarfile.open(path, mode="r:*") as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    expanded += member.size
                    if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                        limitations.append(f"archive_expansion_limit:{location}")
                        break
                    member_name = safe_location(member.name)
                    path_finding = sensitive_path_finding(repository, surface, f"{location}!{member_name}")
                    if path_finding:
                        findings.append(path_finding)
                    member_stream = archive.extractfile(member)
                    if member_stream is None:
                        continue
                    with member_stream:
                        member_findings, _ = scan_stream(
                            member_stream,
                            repository=repository,
                            surface=surface,
                            location=f"{location}!{member_name}",
                        )
                        findings.extend(member_findings)
        except (OSError, tarfile.TarError):
            limitations.append(f"unreadable_tar:{location}")
    return findings, raw_size, limitations


def scan_download(
    client: GitHubClient,
    *,
    repository: str,
    surface: str,
    location: str,
    url_or_path: str,
    accept: str | None = None,
) -> tuple[list[Finding], int, list[str]]:
    with tempfile.TemporaryDirectory(prefix="forensic-download-") as temporary:
        destination = Path(temporary) / "payload"
        client.download(url_or_path, destination, accept)
        return scan_archive(
            destination,
            repository=repository,
            surface=surface,
            location=location,
        )


def scan_actions(client: GitHubClient, full_name: str, report: RepositoryReport) -> None:
    try:
        runs = list(client.paginate(f"/repos/{full_name}/actions/runs", "workflow_runs"))
    except ApiStatus as exc:
        report.error("actions", "runs_unavailable", exc.status)
        return
    except AuditError:
        report.error("actions", "runs_unavailable")
        return
    report.workflow_runs_scanned = len(runs)
    for run in runs:
        run_id = run.get("id")
        if not isinstance(run_id, int):
            continue
        try:
            findings, _, limitations = scan_download(
                client,
                repository=full_name,
                surface="actions_log",
                location=f"workflow-run:{run_id}",
                url_or_path=f"/repos/{full_name}/actions/runs/{run_id}/logs",
                accept="application/vnd.github+json",
            )
            report.findings.extend(findings)
            report.limitations.extend(limitations)
            report.workflow_logs_scanned += 1
        except ApiStatus as exc:
            # 404/410 commonly means logs expired or were deleted.
            report.error("actions_log", "log_unavailable", exc.status)
        except AuditError:
            report.error("actions_log", "log_unavailable")

    try:
        artifacts = list(client.paginate(f"/repos/{full_name}/actions/artifacts", "artifacts"))
    except ApiStatus as exc:
        report.error("actions_artifacts", "artifacts_unavailable", exc.status)
        return
    except AuditError:
        report.error("actions_artifacts", "artifacts_unavailable")
        return
    for artifact in artifacts:
        artifact_id = artifact.get("id")
        expired = artifact.get("expired")
        name = safe_location(str(artifact.get("name") or "artifact"))
        if not isinstance(artifact_id, int):
            continue
        if expired is True:
            report.error("actions_artifact", "artifact_expired")
            continue
        try:
            findings, _, limitations = scan_download(
                client,
                repository=full_name,
                surface="actions_artifact",
                location=f"artifact:{artifact_id}:{name}",
                url_or_path=f"/repos/{full_name}/actions/artifacts/{artifact_id}/zip",
                accept="application/vnd.github+json",
            )
            report.findings.extend(findings)
            report.limitations.extend(limitations)
            report.artifacts_scanned += 1
        except ApiStatus as exc:
            report.error("actions_artifact", "artifact_unavailable", exc.status)
        except AuditError:
            report.error("actions_artifact", "artifact_unavailable")


def scan_releases(client: GitHubClient, full_name: str, report: RepositoryReport) -> None:
    try:
        releases = list(client.paginate(f"/repos/{full_name}/releases"))
    except ApiStatus as exc:
        report.error("releases", "releases_unavailable", exc.status)
        return
    except AuditError:
        report.error("releases", "releases_unavailable")
        return
    report.releases_scanned = len(releases)
    for release in releases:
        release_id = release.get("id")
        body = release.get("body")
        tag = safe_location(str(release.get("tag_name") or release_id or "release"))
        if isinstance(body, str):
            report.findings.extend(
                scan_bytes(
                    body.encode("utf-8"),
                    repository=full_name,
                    surface="release_metadata",
                    location=f"release:{tag}",
                )
            )
        assets = release.get("assets")
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_id = asset.get("id")
            name = safe_location(str(asset.get("name") or "asset"))
            if not isinstance(asset_id, int):
                continue
            path_finding = sensitive_path_finding(full_name, "release_asset", name)
            if path_finding:
                report.findings.append(path_finding)
            try:
                findings, _, limitations = scan_download(
                    client,
                    repository=full_name,
                    surface="release_asset",
                    location=f"release:{tag}!{name}",
                    url_or_path=f"/repos/{full_name}/releases/assets/{asset_id}",
                    accept="application/octet-stream",
                )
                report.findings.extend(findings)
                report.limitations.extend(limitations)
                report.release_assets_scanned += 1
            except ApiStatus as exc:
                report.error("release_asset", "asset_unavailable", exc.status)
            except AuditError:
                report.error("release_asset", "asset_unavailable")


def deduplicate_findings(findings: Iterable[Finding]) -> list[Finding]:
    unique: dict[tuple[str, str, str, str, str | None], Finding] = {}
    for finding in findings:
        key = (
            finding.surface,
            finding.location,
            finding.detector,
            finding.fingerprint,
            finding.object_sha,
        )
        unique[key] = finding
    return sorted(
        unique.values(),
        key=lambda item: (item.repository, item.surface, item.location, item.detector, item.fingerprint),
    )


def audit_repository(
    client: GitHubClient,
    repository: dict[str, object],
    temporary_root: Path,
) -> RepositoryReport:
    full_name = str(repository["full_name"])
    visibility = str(repository.get("visibility") or ("private" if repository.get("private") else "public"))
    report = RepositoryReport(
        repository=full_name,
        visibility=visibility,
        archived=bool(repository.get("archived")),
    )
    mirror = temporary_root / hashlib.sha256(full_name.encode("utf-8")).hexdigest()[:16]
    try:
        clone_mirror(full_name, client.token, mirror)
        scan_git_history(full_name, mirror, report)
    except AuditError:
        report.error("git_history", "mirror_scan_failed")
    scan_actions(client, full_name, report)
    scan_releases(client, full_name, report)
    report.findings = deduplicate_findings(report.findings)
    report.limitations = sorted(set(report.limitations))
    return report


def build_report(owner: str, reports: list[RepositoryReport]) -> dict[str, object]:
    findings = [finding.as_dict() for report in reports for finding in report.findings]
    errors = sum(len(report.errors) for report in reports)
    return {
        "schema_version": 1,
        "owner": owner,
        "status": "complete_with_recorded_limitations" if errors or any(r.limitations for r in reports) else "complete",
        "security_boundary": {
            "secret_values_in_report": False,
            "finding_values_replaced_by_sha256_fingerprint": True,
        },
        "coverage": {
            "repositories": len(reports),
            "refs_scanned": sum(report.refs_scanned for report in reports),
            "git_objects_scanned": sum(report.git_objects_scanned for report in reports),
            "git_bytes_scanned": sum(report.git_bytes_scanned for report in reports),
            "workflow_runs_scanned": sum(report.workflow_runs_scanned for report in reports),
            "workflow_logs_scanned": sum(report.workflow_logs_scanned for report in reports),
            "artifacts_scanned": sum(report.artifacts_scanned for report in reports),
            "releases_scanned": sum(report.releases_scanned for report in reports),
            "release_assets_scanned": sum(report.release_assets_scanned for report in reports),
        },
        "limitations": [
            "GitHub does not expose deleted unreachable branch refs or server reflogs; only currently reachable heads, tags and fetched pull-request heads can be scanned.",
            "Expired or deleted Actions logs and artifacts are recorded as unavailable and cannot be reconstructed.",
            "External Git LFS objects are not present in ordinary Git object history unless separately exposed through an artifact or release asset.",
            "Archive expansion stops after the configured anti-zip-bomb limit and records the skipped archive location.",
        ],
        "finding_count": len(findings),
        "findings": findings,
        "repositories": [
            {
                "repository": report.repository,
                "visibility": report.visibility,
                "archived": report.archived,
                "refs_scanned": report.refs_scanned,
                "git_objects_scanned": report.git_objects_scanned,
                "git_bytes_scanned": report.git_bytes_scanned,
                "workflow_runs_scanned": report.workflow_runs_scanned,
                "workflow_logs_scanned": report.workflow_logs_scanned,
                "artifacts_scanned": report.artifacts_scanned,
                "releases_scanned": report.releases_scanned,
                "release_assets_scanned": report.release_assets_scanned,
                "finding_count": len(report.findings),
                "limitations": report.limitations,
                "errors": report.errors,
            }
            for report in reports
        ],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-repositories", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    token = os.getenv("FORENSIC_AUDIT_TOKEN") or os.getenv("PROJECT_STATUS_TOKEN") or ""
    try:
        client = GitHubClient(token)
        repositories = client.owner_repositories(args.owner)
        if len(repositories) > args.max_repositories:
            raise AuditError("repository inventory exceeds configured maximum")
        with tempfile.TemporaryDirectory(prefix="portfolio-forensic-audit-") as temporary:
            root = Path(temporary)
            reports = [audit_repository(client, repository, root) for repository in repositories]
        report = build_report(args.owner, reports)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "repositories": report["coverage"]["repositories"],
                    "finding_count": report["finding_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
