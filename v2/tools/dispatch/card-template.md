# Worker card template (ticket #393 — hardened contract)

Every card dispatched to the local worker MUST contain these sections. The
integrator checks the artifact against them before merging.

## TASK
One sentence: what to produce, and the exact file path(s).

## SCOPE
- **ALLOWED FILES:** the ONLY files the worker may emit content for.
- **FORBIDDEN DEPS:** dependencies the worker must not use (list any dep not in
  the crate's Cargo.toml; the worker has no network and must not invent them).
- **FORBIDDEN CHANGES:** files/behaviour that must not change.

## EXACT APIS
The real signatures/field names, copied from the source — never paraphrased.
Include struct field names verbatim (`sym`, not `symbol`).

## OUTPUT CONTRACT
Choose ONE and say so:
- `EMIT: blocks` — named blocks (=== BLOCK A ===), never whole files, when the
  worker has not seen the target file.
- `EMIT: full-file` — only when the worker has been shown the complete current
  file content in the card.

## STANDING RULES (pre-baked, no need to restate)
1. Unique temp dirs per test (never a shared static path — parallel tests clobber).
2. `#[derive(PartialEq)]` on error enums that tests compare.
3. No out-of-scope deps; check Cargo.toml in the card's EXACT APIS section.
4. Semantic ordering (versions, priorities) gets a hand-written `Ord` + a test —
   derived `String` ordering is wrong for pre-releases.
5. No panics on input paths; errors via the crate's error enum.
6. Thinking OFF below `effort: high` (mechanical cards must not burn budget reasoning).
