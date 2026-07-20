# Private Completion-Authority Exception Queue

## Purpose

The status scan now reads each repository's machine-generated exception record from:

```text
automation/project-status-bootstrap-exception
└── .project/bootstrap-exception.json
```

A missing exception branch is normal and means that repository has no current bootstrap exception. A malformed or unreadable record is a scan error; it is never converted into a guessed category.

## Trusted outputs

The complete owner-wide queue is written to both trusted output trees:

- `internal-build/completion-status.json` under `authority_exception_queue` and `authority_exception_summary`;
- `private-build/status.json`, `private-build/index.html`, and `private-build/authority-exceptions.md`.

The private dashboard remains a top-five activity dashboard, but its exception queue is portfolio-wide. A repository does not need to be in the activity top five to appear in the authority work queue.

Each queue record contains only:

- repository identity and URL;
- privacy flag;
- one registered primary exception code;
- deterministic project classification;
- bounded exception detail;
- the default-branch source commit inspected by the bootstrap.

## Public boundary

No authority-exception field, code, detail, source commit, source branch or source path is included in `public/status.json`, public Markdown or public HTML. Private repository identity remains redacted under the existing public-output rule.

The workflow validates that:

- internal and private queues contain the same owner-wide repository set;
- their totals match repository exception records;
- `private-build/authority-exceptions.md` exists;
- no equivalent public file exists;
- exception metadata is absent from every file under `public/`.

## Authority rule

The queue is a work-routing surface only. It does not calculate completion percentages, alter completion contracts, infer readiness or resolve an exception. Resolution still requires a separate bounded repair or owner decision.
