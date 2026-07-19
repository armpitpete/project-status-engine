# Portfolio Completion Bootstrap

## Purpose

The portfolio bootstrap is the missing onboarding layer between owner-wide repository discovery and the daily README synchroniser.

It processes the complete active owner portfolio in one workflow run. It does not maintain a repository allowlist and does not require a person to open roughly fifty repositories individually.

## Active repository boundary

A repository enters the inventory when all of the following are true:

- it is owned by the configured owner;
- it is not archived;
- it is not a fork;
- it is not disabled;
- it has a default branch recorded by GitHub.

The inventory is resolved through the GitHub API on every run by taking the union of:

- repositories visible through the authenticated owner token, including private repositories;
- all public repositories returned for the configured owner.

Repository identities are not committed to this repository. The workflow also enforces a current minimum active-portfolio count. This is a visibility guard, not an allowlist: repositories may be added automatically, but a token that suddenly sees only a subset cannot report a successful portfolio rollout.

## Project classification

Classification is deterministic and does not affect completion. The current project types are:

- `manuscript`;
- `website`;
- `software`;
- `hardware`;
- `music`;
- `documentation`;
- `mixed`;
- `unknown`.

Classification uses repository metadata and file-tree fingerprints. It is descriptive only. It never creates, raises or lowers a percentage.

## Completion evidence boundary

A new completion contract may be proposed only when an existing repository authority or status document contains an explicit completed-and-total count.

Accepted examples include:

```text
Controlled recovery: 30 of 36 complete
Build milestones: 4/5 — 80.0%
| Publication package checks | 7/9 — 77.8% |
```

The bootstrap:

- requires both the completed count and the total count;
- calculates the display percentage only from those explicit counts;
- cross-checks any percentage already written beside the counts;
- rejects completed counts greater than totals;
- rejects contradictory counts for the same stage;
- does not accept a percentage without counts;
- does not use commits, issues, pull requests, files, activity, age, readiness or publication status as completion.

Authority files are considered in this order:

1. `docs/PROJECT_AUTHORITY.md`;
2. `PROJECT_AUTHORITY.md`;
3. completion-authority records;
4. project-status records;
5. status records;
6. `README.md`;
7. shallow text files whose names explicitly contain authority, completion, progress, status or readiness.

Generated build trees and dependency directories are excluded from authority discovery.

## Contract construction

When one authority document supplies unambiguous bounded counts, the bootstrap proposes `.project/progress.json` with:

- schema version 1;
- the classified project type;
- the existing authority path;
- one stage for each distinct explicit bounded count in that authority;
- per-stage evidence references using source path and line number;
- `overall.enabled: false`.

Overall completion is never enabled by bootstrap. Existing valid contracts with an explicitly weighted overall calculation remain valid and are preserved.

## README construction

The bootstrap adds or updates only this generated block:

```text
<!-- AUTO:PROJECT-COMPLETION:START -->
...
<!-- AUTO:PROJECT-COMPLETION:END -->
```

When markers are absent, the block is appended. Existing README bytes remain unchanged before the appended block.

When one valid marker pair exists, only its interior is replaced.

Duplicated or reversed markers are an exception. The automation does not repair them silently.

## Pull-request model

Required repository changes are written to the standard automation branch:

```text
automation/project-status-bootstrap
```

The workflow opens or updates one ready-for-review pull request titled:

```text
Bootstrap authority-backed project completion
```

The PR may change only:

- `.project/progress.json`;
- `README.md`.

An open non-bootstrap PR that already changes `.project/progress.json` is recognised as pending onboarding. The bulk controller does not open a duplicate. This absorbs earlier individual onboarding work without making that approach the rollout model.

## Exceptions

Already-correct repositories are silent.

When evidence is genuinely insufficient, contradictory, unreadable or structurally unsafe, the controller writes one machine-readable exception record to the repository branch:

```text
automation/project-status-bootstrap-exception
```

The record path is:

```text
.project/bootstrap-exception.json
```

The branch does not open a pull request and does not alter the default branch. It uses repository Contents permission only; Issues permission is not required. The record contains the fixed exception code, bounded detail, source commit and project classification. It contains no invented completion value. When the repository becomes safely bootstrappable, already onboarded or covered by a pending onboarding PR, the controller deletes the exception branch automatically.

Logs contain only opaque target digests, fixed action names, fixed exception codes and aggregate counts. Private repository identity and evidence do not enter public workflow logs.

## Run report and failure boundary

Every applied run writes one aggregate machine-readable report to the automation branch:

```text
automation/portfolio-bootstrap-report
```

The report file is `portfolio-bootstrap-report.json`. It records only:

- the triggering engine commit;
- authenticated, public and union inventory counts;
- the minimum portfolio visibility guard;
- action counts;
- exception and infrastructure error-code counts.

It contains no repository names, URLs, authority paths, evidence text or opaque target identifiers. The branch is automation state and does not open a pull request.

Evidence exceptions are a valid completed-run result when their repository exception branch was successfully created or updated. API, authentication, inventory, branch, commit, pull-request, exception-reporting or aggregate-report failures are infrastructure failures. Any infrastructure failure makes the workflow fail closed and prevents a successful `portfolio-bootstrap` commit status. An empty inventory or an inventory below the configured active-portfolio minimum also fails closed before repository planning begins.

## One approval gate

The normal `apply` mode inventories the portfolio and opens or updates every required bootstrap PR.

After review, the owner may run the same workflow once with:

```text
mode: merge-approved
```

Before merging, the controller re-derives the expected changes from the current default branch and verifies that every automation PR:

- uses the standard automation branch and title;
- is not a draft;
- changes only the two permitted paths;
- contains byte-for-byte the currently expected files.

Only that exact revalidated set is merged. Stale, edited, broadened or contradictory PRs remain unmerged and are reported as exceptions.

This is the single human authority gate. It replaces repository-by-repository merge handling.

## Continuous operation

The workflow runs:

- on implementation changes merged to `main`;
- weekly;
- manually in audit, apply or merge-approved mode.

After bootstrap PRs merge, the existing daily README synchroniser continues to update every valid contract through its marker-only, no-op-safe process.
