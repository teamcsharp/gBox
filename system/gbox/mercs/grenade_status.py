"""What the grenade ring can honestly do on each Mercenaries title, per grenade kind.

The ring is a native spectacle: ten grenades spawned in a ring around the player, blooming outward and
detonating (``grenade_ring`` in ``gbox.mercs.interventions``). It is built on some titles and kinds and not on
others, and a title can be temporarily unusable (between rounds, a dead player, a changed build, a session whose
adapter has no native controller). This module is the single place that decides which of the three kinds a session
offers and, when it does not, why - so the PiP's menu and the MCP tool say exactly what works instead of greying
everything out with one generic reason.

Three levels of truth, in the order the rows are resolved:

1. the title: is a ring built for it at all, and which kinds are verified there (``TITLES``);
2. the live native controller: it may know more than the table (RE4 GameCube's hand grenades are only enabled while
   its verified unlimited life is on) and it overrides the table for the kinds it reports. A kind the table calls
   verified is still unavailable when no controller exists for this session - never advertised without a worker
   that could fire it;
3. this moment: with no living player in an active round the kinds that would otherwise work carry that reason
   (the queue refuses the click anyway, because the capability is absent).

No row is ever invented: a kind the title cannot do says so, and a kind the controller reports unavailable keeps
the controller's own reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("flash", "hand", "incendiary", "launcher", "shell1302", "shell1303", "shell1304", "mine")
LABELS = {"flash": "Flash", "hand": "Hand", "incendiary": "Incendiary", "launcher": "Launcher",
          "shell1302": "Explosive shell", "shell1303": "Acid shell", "shell1304": "Nitrogen shell (freeze)",
          "mine": "Mine thrower"}

# Reason texts are shown in the PiP's chooser and returned by the API/tool. Keep them one sentence and specific.
TITLE_NOT_BUILT = "the grenade ring is not built for {title} yet"
KIND_NOT_OFFERED = "this title does not offer {kind} grenades"
CONTROLLER_ABSENT = "{title}'s native grenade controller is not available for this session"
CONTROLLER_STATUS_UNREAD = "this title's native grenade status could not be read; no kind is advertised without it"
NO_PLAYER = "no living player in an active Mercenaries round"
#: The transient reason a native controller gives before its harness is attached (re4_switch_native.grenade_kinds).
#: A controller with `ensure_attached` attaches on the click itself, so this reason is not "unbuilt".
ATTACH_ON_DEMAND = "the harness is not attached to the player"


@dataclass(frozen=True)
class Kind:
    available: bool
    reason: str = ""
    source: str = "title"


@dataclass(frozen=True)
class Title:
    """One Mercenaries title's ring support: the kinds it is built and verified for, or why it has none."""
    name: str
    kinds: dict = field(default_factory=dict)      # kind -> Kind (missing kinds are not offered at all)
    reason: str = ""                               # the title-level reason when no ring is built
    controller: str = ""                           # the module whose native controller owns this title's ring
    ids: frozenset = frozenset()                   # game ids / map ids / title ids this entry answers to

    @property
    def ring(self) -> bool:
        return bool(self.kinds)


def _title(name, ids, kinds=None, reason="", controller=""):
    return Title(name=name, kinds=kinds or {}, reason=reason, controller=controller,
                 ids=frozenset(i.upper() for i in ids))


# The table. A verified kind is True; an unverified one carries the reason it is refused; a kind that is not
# listed at all is not offered by that title (the row still appears, saying so).
TITLES = {
    "re4_gc": _title(
        "RE4 GameCube", ("78ab9efa2e310db4", "G4BE08", "G4BE07", "G4BE"),
        {"flash": Kind(True), "hand": Kind(True), "launcher": Kind(True)},
        controller="re4_gc_native",
    ),
    "re4_switch": _title(
        "RE4 Switch", ("270a15eb98dab4d7", "010099A00BC1E000"),
        # Checkpoint F/G: the flash and the hand-grenade ring are built on the native harness (the game's own blasts
        # through the cloned vtable's one 8-byte store) but have no live receipt yet; the incendiary blast is not
        # identified on this build (G3). The mine thrower's placed round is the class table's fourth spawn (G5's
        # candidate, 0x2E5050): a probe, refused until a live receipt.
        {"flash": Kind(False, "a flash is built on the RE4 Switch native harness (main+0x2E4E50 via one vtable "
                              "store) but has no live receipt yet"),
         "hand": Kind(False, "a hand-grenade ring is built on the RE4 Switch native harness (main+0x2E48B0, 7000 mm "
                             "floor) but has no live receipt yet"),
         "launcher": Kind(False, "RE4 has no grenade launcher: its launcher-style ring is the mine thrower, offered "
                                 "as the Mine kind"),
         "mine": Kind(False, "the mine thrower's placed round is the class table's fourth spawn (0x2E5050) - a "
                             "probe: no live mine-ring receipt yet")},
        controller="re4_switch_native",
    ),
    "re5_switch": _title(
        "RE5 Switch", ("52d15709be0fda1a", "010018100CD46000"),
        {"flash": Kind(True),
         "hand": Kind(False, "a hand-grenade ring is not yet verified on this build (its projectile class and "
                             "explosion are unconfirmed)"),
         "incendiary": Kind(False, "an incendiary-grenade ring is not yet verified on this build (its projectile "
                                   "class and explosion are unconfirmed)"),
         "launcher": Kind(True)},
        controller="re5_switch_native",
    ),
    "re5_ps3": _title(
        "RE5 PS3", ("e7ca89bbeb67360d", "BLUS30491", "BLUS30492", "NPEB01096"),
        reason=TITLE_NOT_BUILT.format(title="RE5 PS3"),
    ),
    "re6_switch": _title(
        "RE6 Switch", ("115f9cdbba115432", "01002A000CD48000"),
        {"flash": Kind(True),
         "hand": Kind(False, "a hand-grenade ring is not yet verified on this build (its item class/DTI is "
                             "unconfirmed)"),
         "incendiary": Kind(False, "an incendiary-grenade ring is not yet verified on this build (its item "
                                   "class/DTI is unconfirmed)"),
         "launcher": Kind(False, "the 360 launcher ring spawns the launcher's shell rounds (uWp1302/1303/1304) "
                                 "through the parameterised class image; awaiting the first live ring receipt"),
         "shell1302": Kind(False, "the launcher's Explosive round (uWp1302) is a probe through the parameterised "
                                  "class spawn; awaiting the first live shell-ring receipt"),
         "shell1303": Kind(False, "the launcher's Acid round (uWp1303) is a probe through the parameterised class "
                                  "spawn; awaiting the first live shell-ring receipt"),
         "shell1304": Kind(False, "the launcher's Nitrogen round (uWp1304, the freeze) is a probe through the "
                                  "parameterised class spawn; awaiting the first live shell-ring receipt")},
        controller="re6_switch_native",
    ),
    "re6_ps3": _title(
        "RE6 PS3", ("0871eee3b68cdea3", "BLUS30855", "BLES01424"),
        reason=TITLE_NOT_BUILT.format(title="RE6 PS3"),
    ),
    "re4_wii": _title(
        "RE4 Wii", ("re4wii", "R4WE", "R4WP"),
        reason=TITLE_NOT_BUILT.format(title="RE4 Wii"),
    ),
    "merc3d": _title(
        "The Mercenaries 3D", ("0ed22ae742e1b56b", "0004000000038B00"),
        reason=TITLE_NOT_BUILT.format(title="The Mercenaries 3D"),
    ),
    "re3_psx": _title(
        "RE3 Nemesis", ("361337431d93bd1b", "SLUS-00923", "SLES-02529"),
        reason=TITLE_NOT_BUILT.format(title="RE3 Nemesis"),
    ),
}

# The table key each native module owns, for a controller built without its session record.
_CONTROLLERS = {"re4_gc_native": "re4_gc", "re4_switch_native": "re4_switch",
                "re5_switch_native": "re5_switch", "re6_switch_native": "re6_switch"}


def identify(game=None, controller=None) -> str | None:
    """The table key for a session: its game/map/title ids first, then the native controller's own module.

    Returns None for a session that is not a known Mercenaries title (no rows are published for it).
    """
    ids = set()
    if isinstance(game, dict):
        for key in ("game_id", "title_id", "map_id", "serial", "id"):
            value = game.get(key)
            if isinstance(value, str) and value:
                ids.add(value.upper())
    if ids:
        for key, title in TITLES.items():
            if ids & title.ids:
                return key
    if controller is not None:
        module = type(controller).__module__.rsplit(".", 1)[-1]
        if module in _CONTROLLERS:
            return _CONTROLLERS[module]
    if isinstance(game, dict):
        # last resort: the platform's known Mercenaries editions, never guessed across platforms
        platform = str(game.get("platform") or "").lower()
        name = str(game.get("title") or "").lower()
        if platform == "switch" and "5" in name:
            return "re5_switch"
        if platform == "switch" and "6" in name:
            return "re6_switch"
        if platform == "switch" and "4" in name:
            return "re4_switch"
    return None


def title_name(key: str | None) -> str:
    return TITLES[key].name if key in TITLES else (key or "this title")


def _reported(controller) -> tuple:
    """The live controller's own kind rows and whether its read failed: ([], False) with no such method."""
    live = getattr(controller, "grenade_kinds", None)
    if not callable(live):
        return [], False
    try:
        rows_ = live()
    except Exception:                                     # noqa: BLE001 - a status read never breaks status
        return [], True
    if not isinstance(rows_, list):
        return [], True
    return [row for row in rows_ if isinstance(row, dict) and row.get("kind") in KINDS], False


def rows(game=None, controller=None, ready_error: str = "") -> list | None:
    """The three kinds' honest rows for one session, always all three, or None when the title is unknown.

    ``controller`` is the live native controller (its ``grenade_kinds()`` wins for the kinds it names);
    ``ready_error`` is why the controller cannot act right now (no player, paused, changed build) - it replaces the
    reason of the kinds that would otherwise be available, so the PiP says "no living player" rather than implying
    the kind is unbuilt.
    """
    key = identify(game, controller)
    if key is None:
        # An unknown title (a test double, a title without a table entry): publish only what the controller itself
        # reports - never invent a kind, never hide the controller's own refusal.
        reported, failed = _reported(controller)
        if failed or not reported:
            return None
        out = []
        for row in reported:
            available = row.get("available") is True and not ready_error
            reason = str(row.get("reason") or "")[:300] or (CONTROLLER_STATUS_UNREAD if failed else "")
            out.append({"kind": row["kind"], "available": available,
                        "reason": "" if available else (ready_error or reason or CONTROLLER_STATUS_UNREAD),
                        "source": "native"})
        return out
    title = TITLES[key]
    offered: dict = {}
    failed = False
    if title.ring:
        for kind, spec in title.kinds.items():
            offered[kind] = Kind(spec.available, spec.reason, "title")
        reported, failed = _reported(controller)
        # A controller that attaches its native harness ON DEMAND (re4_switch_native.Controller.ensure_attached) is not
        # "unbuilt" because a status read has not attached it yet: the click itself attaches and fires. Before this the
        # PiP advertised every RE4 kind unavailable ("the harness is not attached to the player") and the queue refused
        # the click, so the operator never saw a ring on RE4 ("I never see the bot deploy grenade rings in Resident
        # Evil 4"). Only that transient reason is promoted; a real refusal keeps its reason.
        on_demand = callable(getattr(controller, "ensure_attached", None))
        for row in reported:
            available, reason = row.get("available") is True, str(row.get("reason") or "")[:300]
            if not available and on_demand and ATTACH_ON_DEMAND in reason:
                available, reason = True, ""      # the click attaches the harness, then it fires (ensure_attached)
            offered[row["kind"]] = Kind(available, reason, "native")
    out = []
    for kind in KINDS:
        spec = offered.get(kind)
        if spec is None:
            reason = title.reason or KIND_NOT_OFFERED.format(kind=kind)
            out.append({"kind": kind, "available": False, "reason": reason, "source": "title"})
            continue
        available, reason = spec.available, spec.reason
        if available and controller is None:
            available, reason = False, CONTROLLER_ABSENT.format(title=title.name)
        if available and failed:
            # The controller owns the gate (RE4 GameCube's hand grenades need its verified unlimited life): a failed
            # status read is not permission, so the table's "verified" never becomes an advertised click.
            available, reason = False, CONTROLLER_STATUS_UNREAD
        if available and ready_error:
            available, reason = False, ready_error
        out.append({"kind": kind, "available": available, "reason": "" if available else reason,
                    "source": spec.source})
    return out


def ring_available(game=None, controller=None, ready_error: str = "") -> bool:
    """True when a kind could be fired now: a title with a ring, a ready controller, a kind that is available."""
    if ready_error or controller is None or getattr(controller, "grenade_ring", None) is None:
        return False
    rows_ = rows(game, controller, "")
    return bool(rows_ and any(r["available"] for r in rows_))


def summary(game=None, controller=None, ready_error: str = "") -> dict:
    """The status block for a session: the rows, the title, and one sentence for the ring button."""
    key = identify(game, controller)
    rows_ = rows(game, controller, ready_error)
    if rows_ is None:
        return {}
    working = [r["kind"] for r in rows_ if r["available"]]
    blocked = next((r["reason"] for r in rows_ if not r["available"] and r["reason"]), "")
    return {"title": title_name(key), "key": key, "available": bool(working), "kinds": rows_,
            "reason": "" if working else (ready_error or blocked or "no grenade kind is available here"),
            "verified": working}
