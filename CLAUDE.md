# Working in gBox

## Game asset storage

- Keep extracted models, textures, ROMs, game executables, and game decompilation output in Spark's local library or analysis directories. Never commit those payloads to this repository.
- Commit gBox source, tests, configuration, and documentation. Refer to library assets by identifiers or paths instead of copying them into Git, and keep the game-data and binary push checks enabled.

## Tool output size

- Use `mcp__gbox__bot_sessions` to see what is playing.
- Use `mcp__gbox__job_mercmode` with `op=status` only when you need settings or readiness.
  That operation has no filter parameters and returns every PC, title, roster and coverage row.
- When another operation supports filters, request only the rows, fields or time range needed.
