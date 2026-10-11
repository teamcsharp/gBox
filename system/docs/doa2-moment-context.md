# Inspect an owned DOA2 saved moment

`doa2_assets` version 1.3 adds `op="moment_context"`. This is an offline diagnostic
operation on existing content-addressed artifacts and the owned LE Japan disc.
It does not save, load, patch or resume a state, initialize an emulator, build a
ROM, or assign the operator's marked target.

Supply `actor_index` explicitly as 0 or 1 and either a `state_artifact` SHA-256
or an exact `request_id` whose context names `state_artifact`. If both are given,
they must agree with the reported moment. An explicitly given digest may also
be linked through a report attachment when its context lacks a saved-moment
field; the tool never guesses a state from filenames or a live session. A report
without an explicit saved artifact is refused.

Existing `inspect`, `decompose`, `build`, `motions`, `native_cache` and
`environments` fields/defaults are preserved. The generic worker/MCP tool schema
advertises the new operation after the updated tool module is loaded; a source
change alone does not activate it in an existing worker.

For example, submit a normal `doa2_assets` job with:

```json
{
  "op": "moment_context",
  "game_id": "1de2e7634f3161ff",
  "actor_index": 0,
  "request_id": "6d70500464914684"
}
```

That request must already have an attached/identified checkpoint. This example
does not claim request 1135 currently supplies one or infer its selected actor.
Use the precise reported artifact and actor instead when appropriate.

The reader verifies artifact metadata size, content SHA and any declared game
provenance, retaining the original provenance in both JSON reports. The owned
executable must have the exact known SHA. Its native literals and four code
fingerprints identify one complete 16 MiB RAM image in supported 851/854
containers. Actor draw gates, cache index, selected native costume binding,
aligned bounded resource/model tables and draw pointer links must agree.

The native binding determines the source CHR filename. By default the tool
compares it with the owned disc. For a modified source, supply both
`source_chr_artifact` and `source_chr_name`, for example `KTE01.CHR`. The supplied
artifact's actual bytes and provenance are recorded; its basename must match
the selected native resource. A stock CHR that differs from the saved cache's
layout or UV/reference data is refused rather than silently substituted.

The comparison covers all model offsets/counts/terminators, mesh texture IDs
and stream lengths, inline UVs and compact references. The exact supplied file
has a SHA, but this comparison is **not** a full cached-byte match. Animated
positions/normals, shader/lighting state, texture residency, SUP/APV/ACS and GPU
submission remain unchecked. Even a valid envelope with the correct RAM does
not prove the native core can load every serializer object.

Both `doa2-details.json` and `doa2-report.json` retain `diagnostic_only=true`,
`state_loaded=false`, `operator_actor_verified=false`,
`donor_identity_verified=false`, `native_reimport_verified=false` and
`gameplay_verified=false`. The actor result additionally retains
`full_cache_bytes_verified=false`. These reports expose native RE evidence;
they do not certify a same-moment replacement. No original state, RAM, CHR,
executable or disc bytes are emitted as result artifacts.

Portable tests contain synthetic bytes only. The pinned reader's 57 regressions,
22 independent pointer/container/source checks, and tool-route ownership and
hash checks can run without a ROM or an emulator. Private historical native
fixtures can be replayed read-only separately; that is not a new gameplay run.
