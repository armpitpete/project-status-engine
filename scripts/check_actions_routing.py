from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
OWNED = "[self-hosted, Linux, ARM64, oracle-ci, project-status-engine]"
HOSTED_EXCEPTIONS = {
    ("status.yml", "build"): "ubuntu-latest",
    ("readme-sync.yml", "validate"): "ubuntu-latest",
    ("portfolio-bootstrap.yml", "validate"): "ubuntu-latest",
    ("actions-routing-policy.yml", "policy-pr"): "ubuntu-latest",
}

def extract_jobs(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    jobs = {}
    in_jobs = False
    current = None
    for line in lines:
        if line == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(" "):
            break
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            current = m.group(1)
            jobs[current] = []
        elif current is not None:
            jobs[current].append(line)
    return jobs

errors = []
seen_exceptions = set()
for path in sorted(WF.glob("*.y*ml")):
    for job_name, block in extract_jobs(path).items():
        run_lines = [x.strip() for x in block if x.strip().startswith("runs-on:")]
        if len(run_lines) != 1:
            errors.append(f"{path.name}:{job_name}: expected exactly one runs-on, got {len(run_lines)}")
            continue
        value = run_lines[0].split(":", 1)[1].strip()
        if "${{" in value:
            errors.append(f"{path.name}:{job_name}: dynamic runs-on forbidden")
            continue
        key = (path.name, job_name)
        if key in HOSTED_EXCEPTIONS:
            expected = HOSTED_EXCEPTIONS[key]
            seen_exceptions.add(key)
            if value != expected:
                errors.append(f"{path.name}:{job_name}: hosted exception must be {expected}, got {value}")
            if not any("if: github.event_name == 'pull_request'" in x for x in block):
                errors.append(f"{path.name}:{job_name}: hosted exception must be pull_request-only")
        elif value != OWNED:
            errors.append(f"{path.name}:{job_name}: expected owned runner {OWNED}, got {value}")

for path_name, job_name in sorted(set(HOSTED_EXCEPTIONS) - seen_exceptions):
    errors.append(f"{path_name}:{job_name}: declared hosted exception not found")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("PASS: PSE Actions routing policy")
