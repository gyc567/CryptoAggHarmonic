# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all
operations.

- **Remote**: `https://github.com/gyc567/pyharmonics-gpt.git`
- **Auth required**: `gh auth status` must show "Logged in to github.com". If not,
  run `gh auth login` or set `GH_TOKEN` in the environment.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc
  for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by
  `jq` and also fetching labels.
- **List issues**:
  `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`
- **Comment**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**:
  `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

## Pull requests as a triage surface

**PRs as a request surface: no.** (Flip to `yes` only if external PRs should
enter the triage queue.)

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

`gh issue view <number> --comments`.

## Wayfinding operations

For `/wayfinder`. Map = single issue labelled `wayfinder:map`; child tickets are
sub-issues or task-list items under it. Blocking uses GitHub native issue
dependencies where available, else a `Blocked by: #<n>` line in the child body.
Frontier = open children without an open blocker or assignee.