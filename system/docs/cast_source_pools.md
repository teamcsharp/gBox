# Alternating requested donor pools

`characters op=cast_swap source="sonic,mario" mapping=alternate` alternates the
requested source components in their given order. A component can be a named
group, game ID, extractor, or title selection. An extractor/title selection that
matches several source games remains one pool. This changes planning only.

Pools whose resolved donor members are identical are aliases and coalesce.
Otherwise a donor matching several components belongs to the first component.
A distinct component left with no eligible donors (because of overlap or the
existing quality gate) fails clearly instead of silently disappearing. Normal
random/by-role union behavior remains unchanged.

The automatic assignments keep pool slot counts within one. Each pool pass
contains every distinct character name once. When one name has several donor
variants, those variants rotate without replacement before being reshuffled.
The seed makes the plan reproducible. Unequal pool sizes and variant counts can
repeat a donor before all donors globally have appeared; there is no global
donor-exhaustion guarantee for alternate mapping. Explicit operator assignment
edits retain their existing override behavior.

Mario's existing best-per-character and donor quality checks still apply.
Source metadata is not modified. No model, archive, save, or ROM is written by
this planning change. Supported target builders retain their existing native
acceptance requirements. DOA3 remains unsupported: this change does not route
the unfinished DOA3 scaffold, produce a mod, or close whole-cast request #1977.

The original mapping publication `421c7a94b96899dfad16f0ebbb50b54aa40824c0`
from PR #465 is retained through a normal merge. Later DOA3 additions from that
PR are outside this split and remain unmerged pending separate review.
