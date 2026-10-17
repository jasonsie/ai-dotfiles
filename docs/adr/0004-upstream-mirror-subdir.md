# Mirrored upstream docs live in `docs/<cli>/upstream/`, separate from hand-written catalogs

> **Superseded** by [ADR-0006](0006-redesign-round-2.md) (2026-10-18): mirrors now live in
> `upstream/docs/<tool>/`, and no hand-written catalogs sit beside them.

## Context

`scripts/sync-cli-docs.sh` mirrors each CLI's upstream docs by rebuilding the whole
destination directory every run: it stages into a temp dir, then `rm -rf "$dir"; mv stage "$dir"`.
This was safe while `docs/<cli>/` held *only* machine-generated mirror pages.

That invariant broke silently. The multi-CLI parity work added **hand-written** capability
catalogs at `docs/codex/CAPABILITIES.md` and `docs/gemini/CAPABILITIES.md` — living in the
same directories the mirror rebuilds. The next `sync_codex` run would have `rm -rf docs/codex`
and **delete `docs/codex/CAPABILITIES.md`**. A real, latent data-loss bug in a weekly cron.

## Decision

Machine-owned mirror content lives in a dedicated **`docs/<cli>/upstream/`** subdirectory;
hand-written files (the `CAPABILITIES.md` catalog) stay at `docs/<cli>/` top level. The
sync's destructive `rm -rf "$dir"; mv` targets only `docs/<cli>/upstream/`, so it is
*structurally incapable* of touching hand-written files.

Applied to **both** Codex (existing mirror `git mv`'d into `upstream/`) and Gemini (new
mirror lands there directly). Claude and AGY keep mirroring to `docs/claude/` and `docs/agy/`
for now — they have no hand-written companion files, so they carry no collision risk; they
adopt `upstream/` if and when they gain one.

## Consequences

- References to mirrored Codex paths gained an `upstream/` segment (CONTEXT.md terminology
  map, `docs/codex/CAPABILITIES.md` "Upstream doc" column).
- Verified end-to-end: after a full `sync-cli-docs.sh` run, both `CAPABILITIES.md` files are
  byte-identical to before (checksum-confirmed), and the mirrors land in `upstream/`.
- The convention is asymmetric across CLIs by design (only mirror+catalog CLIs need it),
  which a future reader might find surprising — hence this ADR.
- Alternative rejected: stash-and-restore the catalog around the `rm -rf`. Fragile,
  special-cased per file, and one forgotten file means silent loss. The directory split makes
  the guarantee structural, not procedural.
