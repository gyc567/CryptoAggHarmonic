# Triage Labels

The `triage` skill speaks in terms of five canonical roles. This file maps them
to the actual label strings used in this repo's GitHub issue tracker.

| Skill role        | Label in our tracker | Meaning                                    |
| ----------------- | -------------------- | ------------------------------------------ |
| `needs-triage`    | `needs-triage`       | Maintainer needs to evaluate this issue    |
| `needs-info`      | `needs-info`         | Waiting on reporter for more information   |
| `ready-for-agent` | `ready-for-agent`    | Fully specified, ready for an AFK agent    |
| `ready-for-human` | `ready-for-human`    | Requires human implementation              |
| `wontfix`         | `wontfix`            | Will not be actioned                       |

When `triage` (or any downstream skill) mentions a role by name, use the
corresponding label string above.

## Pre-creation check

Before `gh issue create --add-label "..."`, the labels must already exist in the
repo. If not, create them once via:

```
gh label create needs-triage    --color "FBCA04" --description "Maintainer needs to evaluate"
gh label create needs-info      --color "D93F0B" --description "Waiting on reporter"
gh label create ready-for-agent --color "0E8A16" --description "Fully specified, AFK-agent ready"
gh label create ready-for-human --color "1D76DB" --description "Requires human implementation"
gh label create wontfix         --color "FFFFFF" --description "Will not be actioned"
```

Run these once per repo. Re-running is a no-op if labels already exist.