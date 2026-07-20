# Portfolio Authority Registry

## Purpose

`config/portfolio-authority-registry.json` is the machine-readable policy registry for owner-wide completion bootstrap exceptions.

It is not a repository allowlist. Repository identity continues to come from the live authenticated/public owner inventory. The registry contains only classification policy, fixed exception codes and mappings from existing bootstrap evidence errors.

## Primary exception taxonomy

Every evidence exception receives exactly one primary code:

- `missing_completion_contract` — an existing `.project/progress.json` cannot be validated as a completion contract;
- `missing_authoritative_source` — no eligible authority or status document exists;
- `missing_readme_marker` — the README marker contract is absent in a structurally unsafe form, duplicated, reversed or unreadable;
- `ambiguous_project_type` — generic repository evidence identifies multiple project types or none, so a new contract cannot be constructed safely;
- `contradictory_evidence` — counts, percentages, stages or weighted totals conflict;
- `no_completion_evidence` — eligible authority/status documents exist but contain no explicit completed-and-total evidence;
- `inactive_repository_candidate` — a repository is outside the active inventory boundary and requires an owner decision before onboarding.

The classifier consumes only evidence already used by the bootstrap planner. It does not inspect activity, calculate a completion percentage, infer readiness, or resolve contradictions.

## Classification boundary

The priority order is committed in the registry and validated at import time. Unknown evidence codes are not placed into the nearest category. They fail closed as infrastructure/classifier failures.

A pending reviewed onboarding pull request remains pending and is not reclassified. Existing valid contracts remain valid. A repository requiring only a safe README marker-block append remains a README-only update rather than a completion exception.

## Reports

Aggregate reports use schema version 2:

```json
{
  "exceptions": {
    "missing_completion_contract": 0,
    "missing_authoritative_source": 0,
    "missing_readme_marker": 0,
    "ambiguous_project_type": 0,
    "contradictory_evidence": 0,
    "no_completion_evidence": 0,
    "inactive_repository_candidate": 0
  },
  "failures": {}
}
```

All seven exception keys are always present. Infrastructure and API failures are recorded separately under `failures`. Reports continue to exclude repository names, URLs, authority paths, evidence text and opaque target identifiers.

Repository exception branches use schema version 2 and record only one registered primary code. They still contain no inferred completion value.

## Approved bootstrap convergence proof

On 2026-07-20 the exact five-PR authority-backed bootstrap set was revalidated and merged:

- `diary-of-sound` PR #56;
- `curious-world-of-ellie-morcant` PR #135;
- `book-system-os` PR #29;
- `mutual-love` PR #5;
- `merrin-ecosystem` PR #2.

The next owner-wide apply run must classify those five repositories as `unchanged`, must not create replacement branches or pull requests, and must preserve the 50-repository inventory. This record exists only to trigger and anchor that convergence proof; it changes no completion authority rule.
