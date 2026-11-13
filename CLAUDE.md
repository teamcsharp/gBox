# Working in gBox

## Tool output size

- Use `mcp__gbox__bot_sessions` to see what is playing.
- Use `mcp__gbox__job_mercmode` with `op=status` only when you need settings or readiness.
  That operation has no filter parameters and returns every PC, title, roster and coverage row.
- When another operation supports filters, request only the rows, fields or time range needed.
