# Project Status Engine

Automatic activity and authority-backed completion reporting for repositories owned by `armpitpete`.

## Core rule

This is not a manual dashboard and not an inference engine.

- **Activity and attention** come from GitHub repositories, issues, pull requests, labels, commits and push recency.
- **Completion** comes only from a validated `.project/progress.json` committed inside each repository.

Generated files are outputs. Repository activity is never treated as completion.

## Completion authority

The engine looks for `.project/progress.json` in each discovered repository. A missing file means **completion not configured**, not 0%. An invalid file remains invalid. The engine does not repair authority, choose totals or estimate progress.

```json
{
  "schema_version": 1,
  "authority": "docs/PROJECT_AUTHORITY.md",
  "stages": [
    {
      "id": "drafting",
      "label": "Drafting",
      "completed": 36,
      "total": 36
    }
  ]
}
```

Stage percentages are calculated automatically. An overall percentage is absent unless it is explicitly enabled and every stage has an authorised weight totalling 100.

See `schema/progress.schema.json` and `examples/progress.example.json`.

## Three separate concepts

| Concept | Meaning | Source |
|---|---|---|
| Activity | Recent repository work and attention | GitHub metadata |
| Completion | Declared scoped work completed | `.project/progress.json` |
| Readiness | Approval to publish, release, print or deploy | Project-specific authority |

Completion does not imply readiness.

## One scan, three outputs

One paginated repository scan and one deterministic activity-ranking pass produce:

1. a public all-repository view;
2. a private top-five owner dashboard;
3. a trusted full-owner completion dataset.

Completion data never affects activity ranking.

### Public view

The public Pages output shows the full discovered pool. Public repositories retain public detail. Private repositories become anonymous placeholders with issues, PRs, commits, completion and authority data removed.

### Private owner dashboard

The authenticated owner surface contains the five busiest repositories and is divided into focused pages:

- `index.html` — compact overview with data health, **Do Next**, project shape, heat map and exception summary;
- `projects.html` — detailed top-five issue, PR and activity context;
- `completion.html` — validated completion detail;
- `exceptions.html` — complete owner-only exception queue and evidence;
- `operations.html` — freshness, scan health and generated report links.

The private build is deployed separately from Pages and anonymous access is checked after deployment.

### Trusted internal dataset

`internal-build/completion-status.json` contains every discovered repository's identity, validated completion and authority exception. It excludes activity items and dashboard actions. It remains inside the trusted workflow and is consumed by the README synchroniser.

## Generated files

Public `public/`:

- `index.html`
- `status.json`
- `project-status.md`
- `completion-status.md`
- `home-pc-tasks.md`

Private `private-build/`:

- five HTML routes;
- private JSON and Markdown reports;
- exception report and resolution templates;
- home-machine task report.

Trusted `internal-build/`:

- `completion-status.json`.

Only `public/` is uploaded to GitHub Pages.

## Versioned activity ranking

`config/activity-score.json` records the score version, caps, label weights and recency bands. Current work dominates stale backlog. Completion percentages do not affect ranking.

Fixture tests cover active implementation, stale backlog, privacy, bounded top-five selection and two-page repository discovery.

## Discovery and scan health

Discovery supports authenticated repositories across visibility levels, follows bounded pagination and applies bounded retry to transient API failures.

Generated JSON includes:

- output schema version;
- activity-score version;
- generation time;
- complete or partial scan state;
- source repository count;
- request and failure counts;
- rate-limit metadata when available.

A partial scan is reported as partial rather than presented as a complete inventory.

## Privacy and generated-output validation

`scripts/validate_generated_outputs.py` is the executable validation contract. It verifies:

- required public, private and internal files;
- output schema and health metadata;
- strict runtime completion-authority equality;
- identity-free `all-valid` README policy resolution;
- complete private and internal exception queues;
- structural private-record redaction in every public output;
- compact private navigation and detailed secondary pages.

Validation is implemented once in Python rather than duplicated inside workflow YAML.

## README synchronisation

The daily synchroniser selects every valid completion record through `config/readme-sync-policy.json`. It updates only explicit marker blocks on `automation/readme-sync` and opens or updates a reviewable pull request. It never writes directly to a default branch.

The original three contract shapes now live only at `tests/fixtures/readme-sync-contract-shapes.json`; they are regression fixtures, not production configuration.

See `docs/README_SYNCHRONISER.md`.

## Schedule

The status workflow runs:

- manually;
- hourly at minute 17;
- on pushes to `main`;
- on pull requests for validation only.

The synchroniser runs daily at 05:17 in `Europe/London` and can also be invoked manually.

## Operations

Private deployment preserves the existing authentication, dedicated-key, pinned-host and exact-target controls. Recovery and rotation procedures are recorded in:

- `docs/PRIVATE_DASHBOARD_DEPLOYMENT.md`
- `docs/OPERATIONS.md`
- `docs/OUTPUT_SCHEMAS.md`
- `docs/V1_1_CONTRACT.md`

## Configuration

- `STATUS_OWNER`
- `STATUS_MAX_REPOS`
- `STATUS_MAX_ITEMS`
- `STATUS_PROJECT_LIMIT`
- `STATUS_ACTIVITY_WINDOW_DAYS`
- `STATUS_API_RETRIES`
- `STATUS_PROGRESS_PATH`
- `STATUS_OUT_DIR`
- `PRIVATE_STATUS_OUT_DIR`
- `INTERNAL_STATUS_OUT_DIR`
- `PROJECT_STATUS_TOKEN`
- `README_SYNC_TOKEN`
- `GITHUB_TOKEN`

## Workflow labels

These labels add secondary attention signals but never affect completion:

- `next`
- `home-pc`
- `blocked`
- `waiting-user`
- `review`
- `safe-to-continue`
- `move-to-new-chat`

<!-- AUTO:PROJECT-COMPLETION:START -->
## Completion

_Generated from validated project authority by `project-status-engine`. Repository activity is not completion._

| Stage | Progress |
|---|---:|
| Activity ranking and public/private dashboard split | `1/1` — **100.0%** |
| Authority-backed completion calculation | `1/1` — **100.0%** |
| Authenticated private dashboard delivery | `1/1` — **100.0%** |
| Daily authority-backed README synchroniser | `1/1` — **100.0%** |

Authority: `README.md`

Overall completion is not enabled for this project.
<!-- AUTO:PROJECT-COMPLETION:END -->
