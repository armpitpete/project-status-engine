# Project Status Engine

Automatic project-status generation for GitHub projects.

## Core rule

This must not become a manual dashboard.

The source of truth stays where the work already happens:

- GitHub repositories
- open issues
- open pull requests
- issue and PR labels
- recent commits and pushes

Generated files are outputs. Do not maintain generated status by hand.

## What it generates

The GitHub Actions workflow runs `scripts/generate_status.py` and builds a static Pages site in `public/`.

Generated outputs:

- `index.html` — readable top-five status page
- `status.json` — machine-readable status data
- `project-status.md` — Markdown status report
- `home-pc-tasks.md` — public tasks found through the `home-pc` label

## Live top-five behaviour

The engine scans a recent candidate pool, scores current activity, and publishes no more than five projects.

Ranking deliberately gives more weight to current work than stale backlog. The score uses:

- recent commits by the configured owner
- repository push recency
- latest commit recency
- recently updated pull requests
- recently updated issues
- open PRs and workflow labels as secondary attention signals
- old open issue count only as a small signal

The default activity window is 30 days. `status.json` includes score components for public projects and an aggregate private-safe score for redacted private projects.

## Repository discovery

Without `PROJECT_STATUS_TOKEN`, the workflow safely falls back to public owner repositories.

With `PROJECT_STATUS_TOKEN`, the engine can discover repositories owned by the authenticated user across all visibility levels. The workflow repository's default `GITHUB_TOKEN` is not assumed to have access to other private repositories.

For private activity to influence ranking, create a GitHub Actions repository secret named `PROJECT_STATUS_TOKEN`. The token must have read access to the private repositories that should contribute to ranking.

## Public Pages privacy rule

The Pages deployment is public.

Private repositories may influence ranking, but generated public outputs redact private details. They do not publish:

- private repository names
- private repository URLs
- private issue titles or URLs
- private PR titles or URLs
- private commit messages or URLs

A selected private repository appears only as a generic label such as `Private project #2`, together with rank, aggregate score, and a broad activity reason.

Private scan errors are also redacted.

## How it runs

The workflow runs:

- manually through Actions
- every 15 minutes by schedule
- after pushes to `main`

Before generation, the workflow runs deterministic standard-library tests.

## Configuration

Environment variables:

- `STATUS_OWNER` — GitHub owner login
- `STATUS_MAX_REPOS` — candidate repositories to inspect, default `30`
- `STATUS_MAX_ITEMS` — open issues and PRs read per repository, default `8`
- `STATUS_PROJECT_LIMIT` — published project count, default `5`
- `STATUS_ACTIVITY_WINDOW_DAYS` — recent-activity window, default `30`
- `STATUS_OUT_DIR` — generated output directory, default `public`
- `PROJECT_STATUS_TOKEN` — optional token for authenticated cross-repository discovery
- `GITHUB_TOKEN` — API token used for the public fallback and standard workflow access

## Labels the engine understands

The engine still runs without these labels, but they add secondary attention signals:

- `next`
- `home-pc`
- `blocked`
- `waiting-user`
- `review`
- `safe-to-continue`
- `move-to-new-chat`

## Current scope

- scans a recent automatic repository candidate pool
- ignores archived repositories and forks
- ranks recent activity rather than stale backlog
- publishes only the five busiest projects
- supports authenticated private-repository discovery
- redacts private repository details from every public output
- deploys a generated GitHub Pages status board

<!-- temporary verification probe: PROJECT_STATUS_TOKEN -->
