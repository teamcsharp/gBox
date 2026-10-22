"""Gate for coaching notes: every note must be guidance the autoplay's maintainers (Hermes, agents) can act on.

The operator (request #2961): "I dont want to submit nonsense." A note is rejected, with a reason shown in the box, when
it has no real words, is keyboard mash / repeated characters, or is only filler ("test", "lol", "hi"). Anything that
reads as an observation or instruction about the game is accepted; this is deliberately a floor, not a style police.
"""
from __future__ import annotations

import re

FILLER = {"test", "testing", "asdf", "qwerty", "hi", "hello", "hey", "lol", "lmao", "ok", "okay", "hmm", "hm", "yo",
          "yes", "no", "idk", "what", "huh", "wtf", "bruh", "a", "aa", "x", "xd", "k", "kk", "nice", "cool", "good", "bad"}
VOWELS = set("aeiouy")
ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")


def _row(w: str) -> bool:
    return len(w) >= 5 and any(w in r or w[::-1] in r for r in ROWS)


def _mash(word: str) -> bool:
    w = word.lower()
    if len(w) >= 4 and len(set(w)) == 1:
        return True
    if _row(w):
        return True
    if re.search(r"(.)\1{3,}", w):
        return True
    return len(w) >= 6 and w.isascii() and not (set(w) & VOWELS)   # Latin script only: CJK has no vowels to test


def check(text: str) -> str | None:
    """None when the note is usable guidance, else a short reason the operator sees."""
    words = re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", text or "", flags=re.UNICODE)
    if not words or sum(len(w) for w in words) < 3:
        return "Say what is wrong or what to change (e.g. \"stops walking into walls near the door\")."
    if all(w.lower() in FILLER or _mash(w) for w in words):
        return "That reads as filler. Say what you see wrong and what the autoplay should do instead."
    mashed = [w for w in words if _mash(w)]
    if len(words) <= 2 and mashed:
        return "That looks like random keys. Describe the problem in a few words."
    return None
