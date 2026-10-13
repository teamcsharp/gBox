"""Dead or Alive 2 LE (Dreamcast) with a two-franchise cast drawn at random on every selection (inbox #1652).

"Half the cast is Sonic characters from Sonic Adventure 2 and half the cast is Super Mario 64 DS characters, where
it randomly assigns the character to the person each time a character is selected ... battling in the same game."

Design (docs/doa2_mixed_random.md):

* Every selectable fighter keeps its native moves; each of its costume slots gets its own donor (the existing
  per-costume writer, doa2_swap.prepare: retarget, native skin fit, seam rules, budgets).
* 7 fighters are headlined by an SA2 character and 7 by an SM64DS character (their first costume), and every
  fighter's costume pool alternates the two franchises, so any pick can come up Sonic or Mario. A 2-costume fighter
  (Tengu) still holds one of each.
* gbox.doa2_random_select patches the select screen's confirm path: each time a player confirms a fighter, the
  costume is drawn at random from that fighter's pool (the game's own rand() mixed with the TMU counter), before the
  selection is committed, so the loader, the render script and the actor all agree. Two players can therefore meet
  as Sonic vs Mario, and picking the same fighter again can bring a different donor.

plan_pools() is deterministic for a seed; build() writes one GDI (unchanged tracks hard-linked), verifies it by
reading every changed file back, and writes .gbox-mod.json last.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import doa2_chars, doa2_random_select as RS, doa2_swap as S

GAME_ID = "1de2e7634f3161ff"
MOD_NAME = "doa2_sonic_vs_mario_random"
SA2 = ["sonic", "sa2_shadow", "sa2_knuckles", "sa2_tails", "sa2_amy_rose", "sa2_rouge", "sa2_dr_eggman",
       "sa2_tikal", "sa2_chaos_0", "sa2_metal_sonic", "sa2_super_sonic", "sa2_super_shadow"]
SM64DS = ["sm64ds_mario", "sm64ds_luigi", "sm64ds_wario", "sm64ds_yoshi", "sm64ds_peach", "sm64ds_bowser",
          "sm64ds_koopa_troopa", "sm64ds_ukiki"]
# headline donor per fighter (its first costume): 7 Sonic Adventure 2, 7 Super Mario 64 DS, matched on build/role
HEADLINE = {"AYA": "sa2_amy_rose", "LEI": "sa2_rouge", "HIK": "sa2_tikal", "RYU": "sa2_shadow", "JAN": "sonic",
            "GEN": "sa2_tails", "TNG": "sa2_dr_eggman",
            "KAS": "sm64ds_peach", "TIN": "sm64ds_yoshi", "BAS": "sm64ds_bowser", "ZAC": "sm64ds_wario",
            "BAY": "sm64ds_luigi", "KTE": "sm64ds_mario", "SAM": "sm64ds_koopa_troopa"}


def franchise(slug: str) -> str:
    return "SM64DS" if slug.startswith("sm64ds_") else "SA2"


def plan_pools(costumes: dict[str, list[str]], sa2: list[str] = SA2, sm64ds: list[str] = SM64DS,
               headline: dict[str, str] = HEADLINE, seed: str = "") -> dict[str, list[tuple[str, str]]]:
    """{family: [costume, ...]} -> {family: [(costume, donor slug), ...]}.

    The first costume holds the fighter's headline donor; the rest alternate franchises (other, own, other, ...),
    each franchise's donors dealt round-robin from a seed-shuffled order that starts at a different place for every
    fighter, without repeating a donor inside one fighter's pool while the franchise has unused ones."""
    import random
    if set(costumes) - set(headline):
        raise ValueError(f"no headline donor for {sorted(set(costumes) - set(headline))}")
    groups = {"SA2": list(sa2), "SM64DS": list(sm64ds)}
    rng = random.Random(f"doa2-mixed:{seed}")
    for g in groups.values():
        rng.shuffle(g)
    counts = {f: sum(1 for k, v in headline.items() if k in costumes and franchise(v) == f) for f in groups}
    if costumes and abs(counts["SA2"] - counts["SM64DS"]) > 1:
        raise ValueError(f"headlines are not half and half: {counts}")
    plan, cursor = {}, {"SA2": 0, "SM64DS": 0}
    for family in sorted(costumes, key=lambda f: list(headline).index(f)):
        names = list(costumes[family])
        if not names:
            continue
        first = headline[family]
        own = franchise(first)
        other = "SM64DS" if own == "SA2" else "SA2"
        pool, used = [(names[0], first)], {first}
        for i, name in enumerate(names[1:]):
            g = other if i % 2 == 0 else own
            donors = groups[g]
            pick = None
            for step in range(len(donors)):
                cand = donors[(cursor[g] + step) % len(donors)]
                if cand not in used:
                    pick = cand
                    cursor[g] = (cursor[g] + step + 1) % len(donors)
                    break
            if pick is None:                               # the franchise ran out for this fighter: reuse
                pick = donors[cursor[g] % len(donors)]
                cursor[g] += 1
            used.add(pick)
            pool.append((name, pick))
        plan[family] = pool
    return plan


def check_plan(plan: dict[str, list[tuple[str, str]]]) -> dict:
    """The properties the request asks for: half the fighters headlined by each franchise, every fighter with two or
    more costumes able to come up as either franchise."""
    heads = {f: franchise(p[0][1]) for f, p in plan.items()}
    mixed = {f: sorted({franchise(s) for _c, s in p}) for f, p in plan.items()}
    problems = [f"{f} can only be {m[0]}" for f, m in mixed.items() if len(plan[f]) > 1 and len(m) < 2]
    n_sa2 = sum(v == "SA2" for v in heads.values())
    if abs(n_sa2 - (len(heads) - n_sa2)) > 1:
        problems.append(f"headlines {n_sa2} SA2 vs {len(heads) - n_sa2} SM64DS")
    return {"ok": not problems, "problems": problems, "headline_sa2": n_sa2, "headline_sm64ds": len(heads) - n_sa2,
            "costumes": sum(len(p) for p in plan.values()),
            "donors": sorted({s for p in plan.values() for _c, s in p})}


def disc_costumes(disc) -> dict[str, list[str]]:
    from . import doa2_lab
    out = {}
    for family in S.ROSTER:
        out[family] = [c for _f, c in doa2_lab.selected_costumes(disc.files, family, "all",
                                                                   disc.read("1ST_READ.BIN"))]
    return out


def render_pools(executable: bytes, plan: dict[str, list[tuple[str, str]]]) -> tuple[dict[int, list[int]], dict]:
    """{render slot: [render costume index]} for the patch, plus {family: {costume name: (slot, index)}}."""
    from .doa2_bindings import resolve_archive_binding
    pools: dict[int, list[int]] = {}
    where: dict[str, dict[str, tuple[int, int]]] = {}
    for family, pool in plan.items():
        for costume, _slug in pool:
            b = resolve_archive_binding(executable, f"DOA2/{family}{costume}.CHR")
            pools.setdefault(b["render_slot"], []).append(int(b["costume"]))
            where.setdefault(family, {})[costume] = (b["render_slot"], int(b["costume"]))
    for slot in pools:
        pools[slot] = sorted(set(pools[slot]))
    return pools, where


def _prepare(gdi, disc, audit, donors, family, costume, slug, progress):
    """One costume; a donor whose textures overflow the native pages is retried with explicit downscaling."""
    from . import doa2_rig
    from .doa2_atlas import AtlasCapacityError
    from .doa2_materials import MaterialCapacityError
    profile = doa2_rig.for_archive(disc, f"DOA2/{family}{costume}.CHR", audit)
    try:
        return (*S.prepare(gdi, donors[slug], "", family, costume, profile, progress=progress), False)
    except (AtlasCapacityError, MaterialCapacityError):
        return (*S.prepare(gdi, donors[slug], "", family, costume, profile, allow_downscale=True,
                           progress=progress), True)


def build(gdi, donors: dict[str, Path], out_dir, plan: dict[str, list[tuple[str, str]]], *, name: str = MOD_NAME,
          progress=lambda p, m: None) -> dict:
    """Write the mixed, random-select disc into out_dir; returns the build summary (marker written last)."""
    from .gdrom import GDRom, patch_gdi
    from . import doa2_rig, fit_events as FE
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    disc = GDRom(gdi)
    executable = disc.read("1ST_READ.BIN")
    RS.check_executable(executable)
    audit = doa2_rig.collect_axes(disc)
    names = {key: nm for key, nm, _a in doa2_chars.FIGHTERS}
    jobs = [(f, c, s) for f, pool in plan.items() for c, s in pool]
    FE.plan([(f"fighter:{f}:{c}", s, f"{s} -> {names.get(f, f)} {c}") for f, c, s in jobs])
    changes, reports, patches = {}, [], []
    plan = {f: list(p) for f, p in plan.items()}
    substitutions = []
    for i, (family, costume, slug) in enumerate(jobs):
        if slug not in donors:
            raise ValueError(f"Unknown donor {slug!r}")

        def update(p, m, i=i, family=family, costume=costume):
            progress(70 * (i + p / 100) / len(jobs), f"{family}{costume}: {m}")
        # a donor that can't fit this costume's native limits (spare seam-model slots, pages) is replaced by the next
        # donor of the same franchise, preferring one not already in the fighter's pool; the half/half mix holds
        pool_now = {s for _c, s in plan[family]}
        same = [s for s in donors if franchise(s) == franchise(slug) and s != slug]
        tried, last_error = [], None
        for cand in [slug] + [s for s in same if s not in pool_now] + [s for s in same if s in pool_now]:
            try:
                edits, report, downscaled = _prepare(gdi, disc, audit, donors, family, costume, cand, update)
                break
            except ValueError as e:                       # encode limits; a missing rig fails every donor alike
                if isinstance(e, S.RigUnavailable):
                    raise
                tried.append({"donor": cand, "error": str(e)[:200]})
                last_error = e
        else:
            raise ValueError(f"{family}{costume}: no {franchise(slug)} donor fits ({tried})") from last_error
        if cand != slug:
            substitutions.append({"costume": f"{family}{costume}", "planned": slug, "used": cand, "tried": tried})
            plan[family] = [(c, cand if c == costume else s) for c, s in plan[family]]
            slug = cand
        if "1ST_READ.BIN" in edits:
            patches.append(edits.pop("1ST_READ.BIN"))
        # costumes can share a native accessory file (JAN01 / JAN02 -> JAN_A01.ACS); the writer disables it the
        # same way for each, so identical bytes are fine and anything else is a real conflict
        overlap = {k for k in set(edits) & set(changes) if edits[k] != changes[k]}
        if overlap:
            raise ValueError(f"{family}{costume} conflicts with an earlier costume on {sorted(overlap)[:3]}")
        changes.update(edits)
        report.update(donor=slug, franchise=franchise(slug), downscaled=downscaled)
        reports.append(report)
    pools, where = render_pools(executable, plan)
    merged = S.merge_executable_patches(executable, patches) if patches else executable
    changes["1ST_READ.BIN"] = RS.patch(merged, pools, pinned=False)
    progress(72, "Writing the GD-ROM image (unchanged tracks hard-linked)")
    image = patch_gdi(gdi, out_dir, name, changes, lambda p, m: progress(72 + 0.2 * p, m), reuse_modified_slack=True)
    progress(93, "Reading every changed file back")
    verification = verify(image, changes, reports, plan, pools, where)
    if not verification["ok"]:
        raise AssertionError(f"verification failed: {verification['problems'][:5]}")
    summary = check_plan(plan)
    roster = [{"fighter": f, "name": names.get(f, f), "character": plan[f][0][1], "franchise": franchise(plan[f][0][1]),
               "render_slot": where[f][plan[f][0][0]][0],
               "pool": [{"costume": c, "render_costume": where[f][c][1], "character": s, "franchise": franchise(s)}
                        for c, s in plan[f]]} for f in plan]
    select = RS.read_back(changes["1ST_READ.BIN"])
    report = {"costumes": reports, "gameplay_verified": False}
    (out_dir / "build-report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out_dir / "verification.json").write_text(json.dumps(verification, indent=1, default=str), encoding="utf-8")
    marker = {"name": name, "game_id": GAME_ID, "image": Path(image).name,
              "character": ",".join(summary["donors"]), "files": list(changes), "report": report,
              "writer_sha256": S.writer_fingerprint(), "profile_digest": S.profiles_digest(reports),
              "gameplay_verified": False, "roster": roster,
              "title": "Dead or Alive 2 - Limited Edition (Japan): Sonic Adventure 2 vs Super Mario 64 DS, random "
                       "donor on every selection",
              "cast_source": "Sonic Adventure 2 (USA) + Super Mario 64 DS (USA)", "cast_mapping": "mixed_random",
              "random_select": {"patch": "gbox.doa2_random_select", "hook": f"{RS.HOOK:#010x}",
                                "pool_word": f"{RS.POOL_WORD:#010x}", "routine_sha256": select["routine_sha256"],
                                "pools": {str(k): v for k, v in pools.items()}},
              "plan_check": summary, "substitutions": substitutions,
              "verification": {k: verification[k] for k in ("ok", "costumes", "select_patch")},
              "built_at": time.time(), "build_seconds": round(time.time() - started, 1),
              "recipe": {"tool": "gbox.doa2_mixed.build", "plan": {f: p for f, p in plan.items()}}}
    (out_dir / ".gbox-mod.json").write_text(json.dumps(marker, default=str), encoding="utf-8")   # last
    progress(100, f"{name}: {len(jobs)} costumes, random select installed")
    return {"mod": name, "image": str(image), "status": "built_unverified", "roster": roster,
            "verification": verification, "plan_check": summary, "substitutions": substitutions}


def verify(image, changes: dict[str, bytes], reports: list[dict], plan, pools, where) -> dict:
    """Offline read-back of the written image: every changed file byte-identical, every costume's CHR decodes with
    its model count, its SUP decodes within the native seam limit, two influences per vertex at most, and the select
    patch installed with exactly the planned pools."""
    from .gdrom import GDRom
    from .doa2_geometry import decode_chr
    from .doa2_seams import decode_sup
    from .doa2_sup_plan import MAX_SEAMS
    disc = GDRom(image)
    problems, rows = [], []
    for key, data in changes.items():
        if disc.read(key) != data:
            problems.append(f"{key}: read-back differs")
    by = {(r["fighter"], r["costume"]): r for r in reports}
    for family, pool in plan.items():
        for costume, slug in pool:
            stem = f"DOA2/{family}{costume}"
            row = {"costume": f"{family}{costume}", "donor": slug}
            try:
                chr_data, sup_data = disc.read(stem + ".CHR"), disc.read(stem + ".SUP")
                archive = decode_chr(chr_data)
                seams = decode_sup(sup_data)
                rep = by.get((family, costume)) or {}
                row.update(models=len(archive["models"]), chr_bytes=len(chr_data), sup_bytes=len(sup_data),
                           seams=len(seams), seam_limit=MAX_SEAMS,
                           chr_budget=rep.get("chr_budget"),
                           max_influences=(rep.get("fit") or {}).get("max_influences"),
                           downscaled=rep.get("downscaled"),
                           chr_sha256=hashlib.sha256(chr_data).hexdigest()[:16])
                if len(seams) > MAX_SEAMS:
                    problems.append(f"{family}{costume}: {len(seams)} seams > {MAX_SEAMS}")
                if rep.get("chr_budget") and len(chr_data) > rep["chr_budget"]:
                    problems.append(f"{family}{costume}: CHR {len(chr_data)} over budget {rep['chr_budget']}")
                if (rep.get("native_descriptors") or 0) > (rep.get("native_limit") or MAX_SEAMS):
                    problems.append(f"{family}{costume}: native descriptors over the limit")
                if ((rep.get("fit") or {}).get("max_influences") or 0) > 2 and \
                        not (rep.get("fit") or {}).get("influence_reduction"):
                    problems.append(f"{family}{costume}: more than two influences per vertex")
            except Exception as e:                         # noqa: BLE001 - recorded, fails the build below
                problems.append(f"{family}{costume}: {type(e).__name__}: {e}")
            rows.append(row)
    sel = RS.read_back(disc.read("1ST_READ.BIN"))
    if not sel["installed"]:
        problems.append("select patch not installed in the written 1ST_READ.BIN")
    if {int(k): v for k, v in sel["pools"].items()} != pools:
        problems.append("select pools differ from the plan")
    for family, pool in plan.items():
        slot = where[family][pool[0][0]][0]
        if len({franchise(s) for _c, s in pool}) > 1 and len(pools.get(slot, [])) != len(pool):
            problems.append(f"{family}: pool size {len(pools.get(slot, []))} != {len(pool)} costumes")
    return {"ok": not problems, "problems": problems, "costumes": len(rows), "rows": rows,
            "select_patch": {k: sel[k] for k in ("installed", "pool_word", "routine_sha256", "signature")} |
                            {"pools": {str(k): v for k, v in sel["pools"].items()}}}


def main(argv=None):
    """python -m gbox.doa2_mixed DISC.gdi LIBRARY OUT_DIR [--seed S]: plan from the disc, build, verify."""
    import argparse
    from .gdrom import GDRom
    ap = argparse.ArgumentParser(description="DOA2 LE: SA2 vs SM64DS cast, random donor on every selection")
    ap.add_argument("gdi")
    ap.add_argument("library")
    ap.add_argument("out")
    ap.add_argument("--seed", default="")
    a = ap.parse_args(argv)
    plan = plan_pools(disc_costumes(GDRom(a.gdi)), seed=a.seed)
    donors = {s: Path(a.library) / s for p in plan.values() for _c, s in p}
    missing = sorted(s for s, d in donors.items() if not (d / "meta.json").is_file())
    if missing:
        raise SystemExit(f"not in the library: {', '.join(missing)}")
    res = build(a.gdi, donors, a.out, plan, progress=lambda p, m: print(f"[{p:5.1f}%] {m}", flush=True))
    print(json.dumps({k: res[k] for k in ("mod", "image", "status", "plan_check")}, indent=1, default=str))


if __name__ == "__main__":
    main()
