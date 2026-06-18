# Project Status Engine

Automatic project-status generation for GitHub projects.

## Core rule

This must not become a manual dashboard.

The source of truth stays where the work already happens:

- GitHub repositories
- open issues
- open pull requests
- issue and PR labels
- recent commits

Generated files are outputs. Do not maintain generated status by hand.

## What it generates

The GitHub Actions workflow runs `scripts/generate_status.py` and builds a static Pages site in `public/`.

Generated outputs:

- `index.html` — readable project status page
- `status.json` — machine-readable status data
- `project-status.md` — Markdown status report
- `home-pc-tasks.md` — tasks found through the `home-pc` label

## How it runs

The workflow runs:

- manually through Actions
- once per day by schedule
- after pushes to `main`

## Labels the engine understands

The engine will still run without these labels, but they improve sorting.

- `next`
- `home-pc`
- `blocked`
- `waiting-user`
- `review`
- `safe-to-continue`
- `move-to-new-chat`

## Current v0.1 scope

- Scans recent public repositories for `armpitpete`.
- Ignores archived repositories and forks.
- Reads open issues, open PRs, labels, and the latest commit.
- Deploys a simple generated GitHub Pages site.

## Later extensions

- Better repository filtering.
- Google Drive folder links.
- Generated handoff snippets.
- Safer stale-context warnings.
