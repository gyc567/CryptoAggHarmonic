# Memory Budget — pyharmonics-gpt

> Token and entry limits per memory tier.

## Tier Limits

| Tier | Max Entries | Max Tokens (approx) | Notes |
|------|-------------|---------------------|-------|
| Scratch | 50 | 10,000 | ~200 tokens/entry avg |
| Episodic | 100 | 50,000 | ~500 tokens/entry avg |
| Durable Facts | 200 | 100,000 | ~500 tokens/entry avg |

## Enforcement

Checked by `loop/loop_audit.py` on every audit run.
Breaching a tier limit triggers a WARNING but does not block the loop.
Humans review and prune at the weekly hygiene loop.

## Token Counting

Uses `tiktoken` (same library as GPT tokenization) for accurate counting.
Count is approximate — designed to catch bloat, not be exact.

## Soft Limits

When a tier exceeds 80% of its limit, the loop-context skill:
1. Logs a warning
2. Prioritizes promoting old Scratch entries to Episodic
3. Suppresses new Scratch writes until under 80%
