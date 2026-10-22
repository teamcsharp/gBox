"""The Mercenaries engine: one engine for every Resident Evil Mercenaries (docs/mercenaries_engine.md).

    vocab      the shared field names and signature tags; profile(map) resolves a title
    world      one RAM read -> World (player, enemies with their signatures, projectiles, prompt, bonuses)
    threat     attacks by time to land, projectiles by time to reach; shoot or evade
    aim        aim rates (learned) and shots scored by the enemies' health
    reactions  prompts from RAM (QTE participate / block)
    driver     the per-title interface; titles/ holds the drivers (re4_gc: G4BE08)
    navcommon  stuck detection, portals per stage, height-aware targets, the sight gate, time-bonus priority
    engine     play_round(): the round loop the deployment playbook (gbox/mercs_bot.py) calls
    lessons    what each run teaches, and the analyzer that proposes signatures
"""
