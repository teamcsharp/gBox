# NUP test fixture

`sample_game.nup` is the reference sample container from
[SPIN0ZAi/nup-extractor](https://github.com/SPIN0ZAi/nup-extractor) (MIT License), downloaded 2026-11-11.

It is a 3,570-byte NUP v1 with two packages (`base` + `update`), nine directories, five files (raw and Zstandard
extents) and per-package metadata (title, publisher, display version, build id, icon). It is used only by
`tests/test_nup.py`; no game content is included.

The format is documented in `docs/nup.md` (a copy of the project's `docs/SPEC.md`), and gBox's reader is
`gbox/nup.py`.
