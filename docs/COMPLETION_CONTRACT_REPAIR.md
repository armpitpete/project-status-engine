# Completion Contract Repair Lane

## Purpose

The completion-contract repair lane replaces an invalid `.project/progress.json` only when existing repository authority already records explicit completed-and-total evidence.

Despite its historical name, this is a **progress-count repair lane**. It does not prove product completion or any lifecycle status.

It does not repair authority content. It reconstructs only the machine-readable count contract and the corresponding generated README block.

## Governing evidence boundary

This repository adopts Threadkeeper’s Real-Thing Proof and Completion Status Protocol v0.1 from exact release:

```text
a5bc55336c86097301b378d8654ac92a26ef81e5
```

A repaired progress file proves only that explicit bounded counts can be represented and calculated deterministically.

It does not prove:

- design acceptance;
- implementation;
- automated checks;
- independent review;
- merge;
- deployment;
- live behaviour;
- publication;
- human acceptance;
- project or product completion.

A count that reaches its total is count-complete only. Evidence-bound lifecycle claims are governed separately by `docs/REAL_THING_STATUS_CONTRACT.md` and validated by `scripts/real_thing_status.py`.

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
- does not infer readiness, release, publication, activity state or lifecycle status;
- does not create or modify an evidence-bound status record.

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

That merge establishes only a valid progress-count contract. It must not be reported as project completion.
