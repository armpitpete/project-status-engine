# Real-Thing Status Contract

## Purpose

Project Status Engine has two separate authorities:

1. `.project/progress.json` records explicit bounded counts and optional weighted percentages;
2. an evidence-bound status record states what lifecycle status is actually proved.

Neither authority may silently stand in for the other.

## Progress authority

A valid progress file proves only:

- the authority path is declared;
- stage counts are integers within their declared totals;
- optional weights are finite and total 100;
- percentages are calculated deterministically.

It does **not** prove:

- implementation;
- independent review;
- merge;
- deployment;
- live behaviour;
- publication;
- human acceptance;
- product completion.

A stage whose numeric count equals its total is count-complete only.

## Status authority

Evidence-bound status claims are validated by:

```text
scripts/real_thing_status.py
```

The record declares:

- `claimed` — the status being asserted;
- `verified` — the verdict supported by the evidence;
- `authority` — the durable completion contract;
- all eight lifecycle stages;
- whether each stage is required;
- the required real environment;
- result: `PASS`, `FAIL`, `INSUFFICIENT`, or `NOT_APPLICABLE`;
- relationship: `direct`, `proxy`, `missing`, or `not-applicable`;
- observed environment;
- evidence references;
- limitations.

## Status ladder

The shared status ladder is:

```text
designed
implemented
automated-checks-passed
independently-reviewed
merged
deployed
live-behaviour-verified
human-acceptance-received
complete
```

A lower status can be verified while later stages remain open. For example, `implemented` may be verified when implementation evidence passes directly even though merge, deployment, live verification and human acceptance are still missing.

`complete` requires direct passing evidence for every required stage.

## Verdict rules

- Direct passing evidence must exercise exactly the environment required by the stage.
- Proxy evidence cannot pass a required stage.
- A proxy failure does not prove failure of an unexercised real environment; that real-world claim remains `INSUFFICIENT`.
- A direct failure of a required stage produces `failed` for claims that depend on that stage.
- Missing or inconclusive required evidence produces `insufficient`.
- A not-applicable stage requires an explicit rationale.
- A contract cannot mark every stage not applicable.

## Project-specific environments

For Project Status Engine:

| Stage | Direct environment |
|---|---|
| Designed | Accepted issue or authoritative design contract |
| Implemented | Exact repository candidate commit |
| Automated checks | Exact-head workflow run |
| Independent review | Review bound to the same exact head |
| Merged | Exact `main` commit |
| Deployed | Exact private-dashboard deployment receipt |
| Live behaviour | Actual live private dashboard or claimed runtime |
| Human acceptance | Explicit owner dashboard acceptance, where required |

Generated HTML, Markdown, JSON, fixtures, local previews and internal calculations are proxies for live dashboard behaviour unless the claim concerns those exact generated artefacts.

## Privacy

Status evidence must preserve the existing public/private boundary.

Public output must not reveal private repository status details, evidence references, limitations, authority paths or sensitive environment information. A public summary may say only that private status is redacted.

## Adoption boundary

This contract changes repository governance and supplies deterministic validation. It does not deploy the dashboard, reclassify historical project records, dispatch a portfolio scan or complete the wider Threadkeeper rollout.
