# Weapon-specific aim evidence, 2026-11-13

The verified aim book persists under
`gbox-data/mercs/learned/<title-id>/aim_book_verified.json`. It remains separate
from the older `aim_book.json`, whose observations did not require native
discharge confirmation. The new optional `weapons` map partitions measurements
by exact title-local weapon item, weapon family, enemy class, observed pose and
distance band. The key is a canonical JSON array; item numbers are never assumed
to identify the same weapon in different titles. Existing family cells and the
cross-title family prior retain their format.

A weapon correction blends its own observations with a family prior worth at most four
observations. Its own evidence becomes dominant as it grows; another weapon or
pose cannot overwrite its cell. At most 2,048 weapon cells are kept per title,
evicting the oldest update first. Loaded cells must contain finite, valid numeric
measurements and bounded histories. Malformed partitions are discarded. RE5 and
RE6 reject cached plans after weapon, pose, family or target allocation changes.

Weapon cells update only after matched native discharge confirmation and eligible
attribution, including the existing settled-aim, measured residual and confounder
checks. HP loss alone and trigger requests cannot train a weapon cell. Shot logs
retain the weapon, pose and discharge provenance. A new optional Plan suffix
preserves the old positional constructor and `_replace` API.

RE4's new reader can supply native post-emission step-edge evidence for verified
shotgun and magnum handlers; sampling that misses an edge remains unconfirmed.
RE5's current feed still lacks a verified native discharge witness and therefore
does not yet train verified weapon cells. RE6 retains its existing native
confirmation path. These changes establish evidence separation and persistence;
synthetic regression tests do not establish improved live accuracy or ranking.
