# Memory Constraints — pyharmonics-gpt

> What must NEVER be stored in any memory tier.

## Absolute Prohibitions

The following may NEVER be written to any tier (Scratch, Episodic, or Durable):

| Category | Examples |
|----------|----------|
| Secrets | API keys, `api_key`, `secret`, `password`, `token` |
| Raw LLM outputs | Full LLM responses, unprocessed |
| Binary data | Images, pickles, serialized models |
| Personal data | Names, emails, IPs without consent |
| Credentials | AWS keys, Supabase keys, database URLs |

## Enforcement

Checked by `loop/loop_audit.py` via regex scan.
Violations are logged and the entry is rejected.
Repeated violations should be reported to the human operator.

## Long-term

If a Durable Fact becomes invalid (e.g., a constraint changes),
it is NOT deleted — it receives a `superseded_by` field pointing to the new fact.
This maintains an audit trail of why decisions changed.
