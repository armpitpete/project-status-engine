# Generated Output Schemas

Every generated JSON document carries a top-level `schema_version`, `activity_score_version`, `generated_at`, `scan_state`, `source_repository_count` and `scan_health` object.

## Common fields

- `schema_version`: integer output-contract version;
- `activity_score_version`: version of `config/activity-score.json` used for ranking;
- `generated_at`: UTC ISO-8601 generation time;
- `scan_state`: `complete` or `partial`;
- `source_repository_count`: number of discovered non-archived, non-fork repositories included before view-specific limiting or redaction;
- `scan_health`: request, failure and rate-limit metadata.

## Public `status.json`

Contains the full ranked repository pool with private records structurally redacted. It never contains private repository identity, issue/PR/commit details, completion authority or authority-exception data.

## Private `status.json`

Contains the unredacted top-five activity view, owner priority actions, completion summaries and owner-wide authority-exception summary. Detailed exception records remain available in the private detailed outputs.

## Internal `completion-status.json`

Contains every discovered repository's identity, privacy flag, URL, validated completion record and authority exception. It contains no activity items or dashboard actions and is never uploaded or deployed publicly.

## Compatibility rule

Consumers must reject an unsupported `schema_version`. Additive fields may be introduced without changing the version; removals, renames or semantic changes require a version increment and migration note.
