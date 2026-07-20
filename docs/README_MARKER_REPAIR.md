# README Marker Repair Lane

## Purpose

The README repair lane handles generated completion-block maintenance for repositories that already have a valid `.project/progress.json` contract.

It is separate from completion-contract creation and repair. It never changes stage definitions, completed counts, totals, weights, evidence references or authority paths.

## Permitted structures

The lane accepts only two README states:

1. **No marker pair** — append one generated block after all existing human-written bytes.
2. **One correctly ordered marker pair** — replace only the bytes between the existing start and end markers.

The markers are:

```text
<!-- AUTO:PROJECT-COMPLETION:START -->
<!-- AUTO:PROJECT-COMPLETION:END -->
```

The generated block is derived from the existing validated completion contract.

## Refusal boundary

The lane does not automatically repair:

- duplicate start or end markers;
- a partial marker pair;
- reversed markers;
- a non-UTF-8 README;
- any operation that would alter bytes outside the generated block.

These states remain `missing_readme_marker` exceptions for reviewed resolution.

## Pull-request boundary

Safe README-only work uses:

```text
automation/project-status-readme-repair
```

with the pull-request title:

```text
Repair generated project completion README block
```

The pull request must change exactly `README.md`. The bulk `merge-approved` mode re-derives the expected README from current `main`, verifies the branch, title, draft state, exact file set and byte-for-byte content, and merges only the exact current result.

## Completion authority

README repair is presentation maintenance. It cannot make a project more or less complete and cannot resolve missing or contradictory completion evidence.
