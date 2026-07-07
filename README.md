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

## Two views, one engine

The engine performs one automatic repository scan and one ranking pass, then derives two different views.

### Public surface

The public GitHub Pages site shows the full discovered repository pool, currently expected to be around 34 repositories.

- public repositories may show public names, links, issues and PRs;
- private repositories remain anonymous and redacted;
- all public counts, filters, heat-map rows, Markdown and JSON reflect the full public-safe candidate pool;
- the public site is a harmless portfolio/activity surface, not the owner control dashboard.

### Private owner dashboard

The private owner view contains only the five busiest repositories from the same ranking result.

- real repository names are preserved for both public and private repositories;
- issue, PR and commit context is preserved;
- `Do Next` is derived only from those same five repositories and may include private work;
- this output must be served only behind real authentication.

The private delivery target is the existing Oracle/Virtualmin command surface protected by Cloudflare Access:

- URL: `https://command.vaelinya.uk/private/project-status-engine/`
- SSH host: `server.vaelinya.uk`
- SSH user: `vaelinya`
- target path: `/home/vaelinya/public_html/private/project-status-engine/`

The deploy script is `scripts/deploy_private_dashboard.sh`. It mirrors `private-build/` to the target with `rsync --delete` and strict SSH host-key checking.

## What it generates

Public output in `public/`:

- `index.html` — public all-repository activity surface
- `status.json` — public-safe machine-readable status data
- `project-status.md` — public-safe Markdown status report
- `home-pc-tasks.md` — public tasks found through the `home-pc` label

Private build output in `private-build/`:

- `index.html` — private top-five owner dashboard
- `status.json` — unredacted top-five status data
- `project-status.md` — private top-five Markdown report
- `home-pc-tasks.md` — top-five owner tasks labelled `home-pc`

`private-build/` is not committed and must never be included in the public Pages artifact.

## Private deployment credentials

The GitHub Actions deployment wiring expects a dedicated SSH key for the `vaelinya` server account and a pinned known-hosts entry.

Required repository secrets:

- `ORACLE_SSH_PRIVATE_KEY` — dedicated private key used only for this deployment lane
- `ORACLE_SSH_KNOWN_HOSTS` — pinned `known_hosts` line for `server.vaelinya.uk`

The public half of the workflow must remain deployable without private dashboard exposure. Private deployment must be skipped on pull-request events.

## Activity ranking

Ranking deliberately gives more weight to current work than stale backlog. The score uses:

- recent commits by the configured owner
- repository push recency
- latest commit recency
- recently updated pull requests
- recently updated issues
- open PRs and workflow labels as secondary attention signals
- old open issue count only as a small signal

The default activity window is 30 days.

## Repository discovery

Without `PROJECT_STATUS_TOKEN`, the workflow safely falls back to public owner repositories.

With `PROJECT_STATUS_TOKEN`, the engine discovers repositories owned by the authenticated user across all visibility levels. The workflow repository's default `GITHUB_TOKEN` is not assumed to have access to other private repositories.

The workflow scans up to 100 owner repositories so the current complete pool can be represented without a manual allowlist.

## Public privacy rule

The public Pages deployment must not reveal:

- private repository names
- private repository URLs
- private issue titles or URLs
- private PR titles or URLs
- private commit messages or URLs

Private scan errors are also redacted.

The private owner dashboard is never placed under `public/` and is never included in the GitHub Pages artifact.

## How it runs

The workflow runs:

- manually through Actions
- every 15 minutes by schedule
- after pushes to `main`
- on pull requests for validation, without deployment

Before generation, the workflow runs deterministic standard-library tests. It then validates that public and private output trees are separate before uploading only `public/` to GitHub Pages.

The private deployment lane uses the same build output and ranking result, then sends `private-build/` directly to the Oracle target. It must not use a public intermediate artifact.

## Configuration

Environment variables:

- `STATUS_OWNER` — GitHub owner login
- `STATUS_MAX_REPOS` — candidate repositories to inspect, workflow value `100`
- `STATUS_MAX_ITEMS` — open issues and PRs read per repository, default `8`
- `STATUS_PROJECT_LIMIT` — private owner dashboard size, default `5`
- `STATUS_ACTIVITY_WINDOW_DAYS` — recent-activity window, default `30`
- `STATUS_OUT_DIR` — public generated output directory, default `public`
- `PRIVATE_STATUS_OUT_DIR` — private generated output directory, default `private-build`
- `PROJECT_STATUS_TOKEN` — optional token for authenticated cross-repository discovery
- `GITHUB_TOKEN` — API token used for public fallback and standard workflow access
- `ORACLE_SSH_HOST` — deploy host override, default `server.vaelinya.uk`
- `ORACLE_SSH_USER` — deploy user override, default `vaelinya`
- `ORACLE_PRIVATE_DASHBOARD_PATH` — deploy target override, default `/home/vaelinya/public_html/private/project-status-engine/`

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

- automatic owner-repository discovery
- one shared scan and ranking pass
- public all-repository privacy-safe surface
- private unredacted top-five owner dashboard build
- recent-activity ranking rather than stale-backlog ranking
- archived repositories and forks ignored
- GitHub Pages deployment for the public surface
- Oracle/Virtualmin target contract and rsync deployment script for the private owner dashboard
- Cloudflare Access remains the authentication boundary for the command/private surface
