# Project Status Engine

Automatic activity and completion reporting for repositories owned by `armpitpete`.

## Core rule

This must not become a manual dashboard or an inference engine.

It has two separate evidence channels:

1. **Activity and attention** come from GitHub repositories, issues, pull requests, labels, commits and push recency.
2. **Completion percentages** come only from a validated `.project/progress.json` file committed inside each repository.

Generated files are outputs. Do not maintain generated status by hand.

Repository activity is never treated as completion. A busy repository may be 10% complete; a quiet repository may be finished.

## Completion authority

The engine looks for this path in every discovered repository:

```text
.project/progress.json
```

A missing file means **completion not configured**. It does not mean 0%.

An invalid file is reported as invalid. The engine does not repair it, choose new totals, adjust weights or guess project state.

### Required fields

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

Rules:

- `authority` identifies the human-approved repository record supporting the figures;
- stage IDs must be unique lowercase identifiers;
- `completed` and `total` must be integers;
- `total` must be greater than zero;
- `completed` cannot exceed `total`;
- stage percentages are calculated automatically;
- an overall percentage is absent by default;
- an overall percentage is calculated only when `overall.enabled` is `true`, every stage has a weight, and weights total exactly 100.

See:

- `schema/progress.schema.json`
- `examples/progress.example.json`

## Three states kept separate

The engine must keep these concepts distinct:

| Concept | Meaning | Source |
|---|---|---|
| Activity | How much recent repository work is happening | GitHub events and metadata |
| Completion | How much declared scoped work is complete | `.project/progress.json` |
| Readiness or authority | Whether a manuscript, build, release or print package is approved | Project-specific authority records |

A high completion percentage does not automatically mean ready, authoritative, releasable, print-ready or published.

## Three outputs, one engine

The engine performs one automatic repository scan and one activity-ranking pass, then derives two dashboard views and one trusted internal dataset. Completion data does not affect activity ranking.

### Public surface

The public GitHub Pages site shows the full discovered repository pool. The number of repositories is discovered at runtime and must not be maintained as a hard-coded portfolio count.

- public repositories may show public names, links, issues, PRs and validated completion data;
- private repositories remain anonymous and completion data is redacted;
- public counts, filters, heat-map rows, Markdown and JSON reflect the full public-safe candidate pool;
- the public site is a portfolio/activity surface, not the owner control dashboard.

### Private owner dashboard

The private owner view contains only the five busiest repositories from the same ranking result.

- real repository names are preserved for public and private repositories;
- issue, PR, commit and completion context is preserved;
- `Do Next` is derived only from those same five repositories and may include private work;
- this output must be served only behind real authentication.

The workflow currently generates the private view into `private-build/` on the ephemeral runner but does not upload it into the public Pages artifact. An authenticated deployment target remains a separate delivery task.

### Internal full-owner completion dataset

The trusted internal dataset contains every discovered repository, including private repository identity and validated completion data. It is deliberately minimal:

- repository name and full name;
- privacy flag;
- repository URL;
- validated completion authority and calculated stages.

It excludes issues, pull requests, commits, activity details and dashboard actions. The daily README synchroniser consumes this dataset inside the trusted workflow before runner cleanup.

The dataset is written to `internal-build/completion-status.json`. It is not a dashboard, is never placed under `public/`, and is never included in the GitHub Pages artifact.

## What it generates

Public output in `public/`:

- `index.html` — public all-repository activity and completion surface;
- `status.json` — public-safe machine-readable activity and completion data;
- `project-status.md` — public-safe activity report;
- `completion-status.md` — public-safe completion report;
- `home-pc-tasks.md` — public tasks found through the `home-pc` label.

Private build output in `private-build/`:

- `index.html` — private top-five owner dashboard;
- `status.json` — unredacted top-five activity and completion data;
- `project-status.md` — private top-five activity report;
- `completion-status.md` — private top-five completion report;
- `home-pc-tasks.md` — top-five owner tasks labelled `home-pc`.

Trusted internal output in `internal-build/`:

- `completion-status.json` — unredacted completion data for every discovered repository, intended for internal machine consumers.

`private-build/` and `internal-build/` are not committed and are not included in the public Pages artifact.

## Activity ranking

Ranking deliberately gives more weight to current work than stale backlog. The score uses:

- recent commits by the configured owner;
- repository push recency;
- latest commit recency;
- recently updated pull requests;
- recently updated issues;
- open PRs and workflow labels as secondary attention signals;
- old open issue count only as a small signal.

The default activity window is 30 days. Completion percentages do not affect ranking.

## Repository discovery

Without `PROJECT_STATUS_TOKEN`, the workflow safely falls back to public owner repositories.

With `PROJECT_STATUS_TOKEN`, the engine discovers repositories owned by the authenticated user across all visibility levels. The workflow repository's default `GITHUB_TOKEN` is not assumed to have access to other private repositories.

The workflow scans up to 100 owner repositories so the current complete pool can be represented without a manual allowlist.

## Public privacy rule

The public Pages deployment must not reveal:

- private repository names or URLs;
- private issue or PR titles and URLs;
- private commit messages or URLs;
- private progress stages, percentages, authority paths or validation errors.

Private scan errors are also redacted.

The workflow tests public output for private-data leakage. Only `public/` is passed to `actions/upload-pages-artifact`; neither `private-build/` nor `internal-build/` is uploaded.

## How it runs

The status workflow runs:

- manually through Actions;
- every 15 minutes for the existing activity surface;
- after pushes to `main`;
- on pull requests for validation, without deployment.

Before generation, the status workflow runs deterministic standard-library tests. It then generates all three outputs, validates their separation, verifies the three pilot completion contracts, scans public files for private pilot identity and completion details, and uploads only `public/` to GitHub Pages.

The separate README synchroniser workflow runs daily at 05:17 in `Europe/London` and can also be invoked manually. It consumes `internal-build/completion-status.json`, resolves exactly three contract-selected pilots, updates only explicit marker blocks on `automation/readme-sync`, and opens or updates ready-for-review pull requests. Pull-request and ordinary push events run validation only and perform no cross-repository write.

The complete synchroniser contract is recorded in `docs/README_SYNCHRONISER.md`.

## Configuration

Environment variables:

- `STATUS_OWNER` — GitHub owner login;
- `STATUS_MAX_REPOS` — candidate repositories to inspect, workflow value `100`;
- `STATUS_MAX_ITEMS` — open issues and PRs read per repository, default `8`;
- `STATUS_PROJECT_LIMIT` — private owner dashboard size, default `5`;
- `STATUS_ACTIVITY_WINDOW_DAYS` — recent-activity window, default `30`;
- `STATUS_PROGRESS_PATH` — repository-relative completion authority path, default `.project/progress.json`;
- `STATUS_OUT_DIR` — public generated output directory, default `public`;
- `PRIVATE_STATUS_OUT_DIR` — private generated output directory, default `private-build`;
- `INTERNAL_STATUS_OUT_DIR` — trusted full-owner completion output directory, default `internal-build`;
- `PROJECT_STATUS_TOKEN` — optional token for authenticated cross-repository discovery;
- `README_SYNC_TOKEN` — preferred dedicated token for pilot README branch and pull-request writes;
- `GITHUB_TOKEN` — API token used for public fallback and standard workflow access.

## Labels the activity engine understands

The engine still runs without these labels, but they add secondary attention signals:

- `next`
- `home-pc`
- `blocked`
- `waiting-user`
- `review`
- `safe-to-continue`
- `move-to-new-chat`

Labels do not affect completion percentages.

## Current scope

- automatic owner-repository discovery;
- one shared scan and activity-ranking pass;
- validated stage completion from `.project/progress.json`;
- optional explicit weighted overall completion;
- public all-repository privacy-safe surface;
- private unredacted top-five owner dashboard build;
- trusted unredacted full-owner completion dataset;
- explicit public-leakage validation;
- daily authority-backed README synchronisation for three contract-selected pilots;
- recent-activity ranking rather than stale-backlog ranking;
- archived repositories and forks ignored;
- GitHub Pages deployment for the public surface only;
- private authenticated hosting still to be attached.

<!-- AUTO:PROJECT-COMPLETION:START -->
## Completion

_Generated from validated project authority by `project-status-engine`. Repository activity is not completion._

| Stage | Progress |
|---|---:|
| Activity ranking and public/private dashboard split | `1/1` — **100.0%** |
| Authority-backed completion calculation | `1/1` — **100.0%** |
| Authenticated private dashboard delivery | `0/1` — **0.0%** |
| Daily authority-backed README synchroniser | `1/1` — **100.0%** |

Authority: `README.md`

Overall completion is not enabled for this project.
<!-- AUTO:PROJECT-COMPLETION:END -->
