# Authority and Owner-Decision Lanes

## Purpose

The private completion-authority queue routes every primary exception into one controlled resolution lane. Routing is policy only: it does not edit project repositories, fill placeholders, calculate completion or resolve owner decisions.

The identity-free policy is committed at:

```text
config/authority-resolution-lanes.json
```

Every primary exception must have exactly one resolution lane, one required action, one template kind and an explicit `owner_decision_required` value.

## Lanes

| Primary exception | Resolution lane | Owner decision |
|---|---|---:|
| `missing_completion_contract` | `completion_contract_repair` | no, unless controlled repair remains unresolved |
| `missing_authoritative_source` | `authority_record_creation` | yes |
| `missing_readme_marker` | `readme_marker_review` | yes |
| `ambiguous_project_type` | `project_type_decision` | yes |
| `contradictory_evidence` | `evidence_reconciliation` | yes |
| `no_completion_evidence` | `bounded_evidence_authoring` | yes |
| `inactive_repository_candidate` | `repository_lifecycle_decision` | yes |

## Owner-only outputs

Each queue item contains:

- repository identity;
- primary exception;
- resolution lane;
- whether an owner decision is required;
- bounded required action;
- template kind.

The queue and lane summaries appear in the trusted internal dataset and private dashboard outputs.

The private build also generates:

```text
private-build/authority-resolution-templates.md
```

Templates use explicit placeholders such as `[completed]` and `[total]`. They never populate counts from repository activity, file totals, commit history or percentage-only text.

## Authority authoring

`missing_authoritative_source` receives a new authority-record skeleton. `no_completion_evidence` receives a bounded-evidence addition skeleton for an existing authority record.

Both require a person to approve:

- the bounded scope;
- stage labels;
- completed counts;
- totals;
- which repository record is authoritative.

## Owner decisions

The project-type, contradiction, unsafe README marker and repository-lifecycle lanes generate decision prompts rather than changes. Automation cannot select a project type, choose between conflicting sources, remove ambiguous README content or decide whether a repository should be active or archived.

## Public boundary

No resolution lane, required action, template, repository identity or private exception detail is written under `public/`. The templates and full queue remain owner-only until authenticated private deployment is attached.
