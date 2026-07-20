# Completion Contract Repair Lane

## Purpose

The completion-contract repair lane replaces an invalid `.project/progress.json` only when existing repository authority already records explicit completed-and-total evidence.

It does not repair authority content. It reconstructs only the machine-readable contract and the corresponding generated README block.

## Evidence selection

When the invalid contract remains parseable and contains a non-empty `authority` path, that path is the only permitted repair source.

When the contract is not valid UTF-8 JSON or contains no usable authority path, the standard authority-path priority is searched. A repair proceeds only when explicit bounded evidence is found. Multiple candidate documents are acceptable only when their normalized stage labels, completed counts and totals agree exactly.

Conflicting candidate evidence becomes `contradictory_evidence`. Missing bounded evidence remains `missing_completion_contract`.

## Generated contract

The replacement contract copies only:

- authority path;
- explicit stage labels;
- explicit completed counts;
- explicit totals;
- evidence line references generated from the selected authority.

The repair lane:

- does not copy values from the invalid contract;
- does not invent or preserve weights;
- sets `overall.enabled` to `false`;
- calculates display percentages only through ordinary contract validation after the explicit counts are copied;
- does not infer readiness, release, publication or activity state.

## Project-type and README stops

A replacement contract is not generated when repository evidence produces `mixed` or `unknown` project classification.

README changes are atomic with the contract repair. Only an absent marker pair or one correctly ordered marker pair is accepted. Duplicate, partial, reversed or non-UTF-8 README structures stop the repair as `missing_readme_marker`.

## Pull-request boundary

The controlled branch is:

```text
automation/project-status-contract-repair
```

The pull-request title is:

```text
Repair authority-backed project completion contract
```

The PR must include `.project/progress.json` and may include only `README.md` in addition. `merge-approved` re-derives the repair from current `main`, checks branch, title, draft state, exact paths and byte-for-byte content, and merges only that current expected result.
