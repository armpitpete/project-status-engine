# v1.1 Consolidation and Owner Usability Contract

## Goal

Reduce implementation duplication and owner-dashboard noise while preserving completion authority, public/private separation, deployment security and review-only README writes.

## Allowed changes

- extract generated-output validation from workflow YAML into tested Python;
- remove completed transition exceptions and obsolete standalone generation entry points;
- move legacy pilot selectors from production configuration to test fixtures;
- make the private landing page concise and move detailed reports to secondary pages;
- add scan freshness, health, API-rate-limit and schema-version metadata;
- reduce the activity schedule to hourly;
- update GitHub Actions to Node 24-compatible supported majors;
- add operational recovery guidance and output-schema documentation.

## Forbidden changes

- no inferred completion percentages;
- no completion influence on activity ranking;
- no direct synchroniser writes to default branches;
- no weakening of SSH host-key pinning, deployment credentials or Cloudflare Access;
- no public exposure of private identities, authority or exception details;
- no manual repository allowlist or overall portfolio percentage.

## Completion gate

- deterministic tests pass;
- generated-output validation passes locally and in CI;
- public leakage checks remain fail-closed;
- pull-request runs skip private deployment;
- exact-head main run deploys the private output and verifies anonymous blocking;
- authenticated owner review confirms the compact landing page and detailed secondary reports.
