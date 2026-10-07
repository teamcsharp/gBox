# Security

- **Auth:** every API route except `/` and `/api/health` requires `Authorization: Bearer <token>`. Tokens are compared in constant time. The token lives in `data_dir/api_token` (created with a random value) or the `GBOX_TOKEN` env var, never in the TOML or source control.
- **Binding:** defaults to `127.0.0.1`. Bind `0.0.0.0` only on a trusted LAN. There is no TLS yet, so put a reverse proxy (Caddy/nginx) or a VPN (Tailscale/WireGuard) in front for anything beyond the LAN. Never expose it to the internet.
- **Permissions:** tools declare `read`, `execute`, `stage`, `network`, `memory_write`, `file_mutation` or `binary_patch`. Mutating permissions are not granted by default (`granted_permissions` in gbox.toml), and jobs that need them are rejected and audited.
- **Originals:** the scanner opens library files read-only (tested via mtimes). Launches can stage copies into the bounded cache. `write_memory` saves the prior bytes as a rollback artifact.
- **Audit:** append-only (SQLite triggers) with a hash chain that `/api/audit/verify` recomputes.
- **Untrusted files:** header sniffing reads fixed offsets only. Heavy third-party parsers (Ghidra, Blender, future extractors) run as separate processes. ponytail: there's no OS-level sandbox yet; run workers as an unprivileged user and add containers/AppContainer when real extractors land.
- **Scope:** gBox contains no DRM or access-control circumvention. Use it only on games and assets you are authorized to use.
- **Known gap:** there's a single shared token, so actors are self-declared (`x-gbox-actor`). Per-principal tokens are needed before the proposer/evaluator separation can be enforced cryptographically.
