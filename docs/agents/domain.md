# Domain Docs

How the engineering skills consume this repo's domain documentation.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root (this repo is single-context — no
  `CONTEXT-MAP.md` exists yet, and there are no monorepo signals).
- **`docs/adr/`** — read ADRs that touch the area about to be worked in.

If neither exists yet, **proceed silently** — they are created lazily by
`/domain-modeling` (reached via `/grill-with-docs` or
`/improve-codebase-architecture`) when terms or decisions actually get resolved.

## File structure

Single-context:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-mvp-scope.md
│   └── 0002-...
└── app/
```

No `src/<context>/docs/adr/` because there is no monorepo.

## Use the glossary's vocabulary

When output names a domain concept (issue title, refactor proposal, hypothesis,
test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the
glossary explicitly avoids. If a concept isn't in the glossary, that's a signal
— either you're inventing language (reconsider) or there's a real gap (note it
for `/domain-modeling`).

## Flag ADR conflicts

If output contradicts an existing ADR, surface it explicitly rather than
silently overriding:

> _Contradicts ADR-0007 — but worth reopening because…_