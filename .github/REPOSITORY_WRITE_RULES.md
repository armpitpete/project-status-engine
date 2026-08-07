# Repository Write Rules — Project Status Engine adoption v0.1

## Canonical authority

This repository adopts Threadkeeper’s **Real-Thing Proof and Completion Status Protocol v0.1** from exact canonical release:

```text
repository: armpitpete/threadkeeper
commit: a5bc55336c86097301b378d8654ac92a26ef81e5
protocol: docs/REAL_THING_PROOF_AND_COMPLETION_STATUS_V0_1.md
canonical rules: .github/REPOSITORY_WRITE_RULES.md
```

Local rules may strengthen that protocol. They must not weaken it.

## Governing rule

> Never test a proxy when the claim concerns the real thing. Never allow `complete` to absorb implementation, deployment, live verification and human acceptance into one vague word.

## Project Status Engine boundary

Project Status Engine collects, validates, calculates, redacts and renders status evidence. Its generated output is evidence about submitted records. It is not direct proof of the external condition described by those records.

Therefore:

- a valid `.project/progress.json` proves only that explicit bounded counts satisfy the progress schema;
- a calculated percentage does not prove implementation, readiness, deployment, live behaviour, publication or acceptance;
- generated HTML, Markdown or JSON does not prove the live private dashboard;
- repository code or CI does not prove the deployed dashboard release;
- a successful workflow does not prove human acceptance;
- repository activity must never be treated as completion;
- missing, proxy-only or inconclusive required evidence is `INSUFFICIENT`.

## Required status vocabulary

Consequential status claims preserve these distinct states:

1. `designed`;
2. `implemented`;
3. `automated-checks-passed`;
4. `independently-reviewed`;
5. `merged`;
6. `deployed`;
7. `live-behaviour-verified`;
8. `human-acceptance-received`;
9. `complete`.

`Complete` is permitted only when every stage required by the declared completion contract has direct passing evidence in its declared environment.

A stage may be not applicable only with an explicit rationale. At least one stage must be required.

## Direct proof for this repository

- **Designed** — the exact authoritative contract or accepted issue.
- **Implemented** — the exact repository commit containing the bounded implementation.
- **Automated checks passed** — the exact-head workflow result.
- **Independently reviewed** — review bound to the exact candidate head.
- **Merged** — the exact default-branch commit.
- **Deployed** — an exact deployment receipt binding the deployed release to a commit.
- **Live behaviour verified** — observation from the actual claimed live private dashboard or runtime.
- **Human acceptance received** — explicit owner acceptance where required by the contract.

Fixtures, generated files, local previews, internal functions and historical workflow records may support diagnosis. They cannot substitute for the required real environment.

## Progress-versus-status rule

`.project/progress.json` remains a count-and-percentage authority only. A stage reaching its numeric total is **count complete**, not proof that the project or product is complete.

Evidence-bound status claims use the validator in:

```text
scripts/real_thing_status.py
```

The status authority must identify the claimed and verified status, all eight stages, required environments, observed environments, evidence relationship and limitations.

## Protected boundaries

This adoption does not authorise:

- private-dashboard deployment or mutation;
- portfolio-wide workflow dispatch;
- secret or private evidence disclosure;
- automatic acceptance;
- rewriting historical records;
- mass repository adoption;
- merge without exact-head checks, independent review and separate authority.

## Adoption record

- local issue: `armpitpete/project-status-engine#68`;
- rollout issue: `armpitpete/threadkeeper#123`;
- canonical release: `a5bc55336c86097301b378d8654ac92a26ef81e5`;
- adoption class after merge: `canonical-adopted`;
- introduced: 7 August 2026.
