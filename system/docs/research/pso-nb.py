        else:
            # No enemies: find the way forward, in priority order. All of it comes from RAM - entity CLASSES and the
            # stage-flag array - never from the screen.
            #
            # 1. a LEVEL-EXIT teleporter. The warp family is in pso_class_registry: TObjWarpBase, TObjMapWarp,
            #    TObjMapWarpForest, TObjMapForceWarp, TObjWarpString, TObjAreaWarpEndingJung, TObjWarpBoss,
            #    TObjWarpJung, TObjWarpLobby - and pso_classes maps TObjWarp to "warp". Walking into one advances
            #    the stage, so this is the end-of-level door and it outranks everything else once the room is clear.
            # 2. a door KEY (TObjDoorKey / TLazerFenceSw) which must be PRESSED, close up.
            # 3. a DOOR (TObjDoor / TObjLazerFenceNorm / TOBarrierEnergy01) to walk through.
            warps = [e for e in (now.get("entities") or [])
                     if "Warp" in str(e.get("class")) and e.get("x") is not None and e.get("z") is not None]
            if warps:
                warp = min(warps, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                           + (float(e.get("z") or 0) - z) ** 2)
                wx, wz = float(warp.get("x") or 0), float(warp.get("z") or 0)
                wdist = math.hypot(wx - x, wz - z)
                wcls = str(warp.get("class"))
                if warp_reported != (wcls, round(wx / 40.0), round(wz / 40.0)):
                    log(f"  LEVEL EXIT {wcls} {wdist:.1f} units away - heading for it")
                    warp_reported = (wcls, round(wx / 40.0), round(wz / 40.0))
                if wdist <= 12.0:
                    room_before_warp = player.get("room")
                    hold(pad, "up", 1.2)                       # step into the teleporter
                    time.sleep(0.4)
                    after_warp = state(pad).get("player") or {}
                    if after_warp.get("room") != room_before_warp:
                        log(f"  ENTERED THE WARP {wcls}: room {room_before_warp} -> {after_warp.get('room')}")
                        warped += 1
                    else:
                        tap(pad, "a")
                        time.sleep(0.4)
                        hold(pad, "up", 1.0)
                else:
                    side_w = globals().get("WARP_SIDE", 1)
                    before_w = wdist
                    hold(pad, "left" if side_w > 0 else "right", 0.18)
                    hold(pad, "up", 0.75)
                    time.sleep(0.2)
                    after_p2 = state(pad).get("player") or {}
                    now_w = math.hypot(wx - float(after_p2.get("x") or 0), wz - float(after_p2.get("z") or 0))
                    if now_w > before_w - 1.0:
                        warp_misses += 1
                        if warp_misses >= 4:
                            globals()["WARP_SIDE"] = -side_w
                            warp_misses = 0
                    else:
                        warp_misses = 0
                moved += 1
            else:
                rows = []
                if pso_coop_gates is not None:
                    try:
                        rows = pso_coop_gates.forward_candidates(now.get("entities") or [], player.get("room"),
                                                                 x, z, skip_switches=False)
                    except Exception:                              # noqa: BLE001
                        rows = []
                if rows:
                    is_switch, adist, gkey, entity, kind = rows[0]
                    ax = float(entity.get("x") or 0)
                    az = float(entity.get("z") or 0)
                    cls = str(entity.get("class"))
                    if is_switch == 0:
                        # A DOOR KEY. Its press only registers close up, so approach and then press.
                        if adist <= 6.5:
                            tap(pad, "b")
                            time.sleep(0.1)
                            tap(pad, "a")
                            time.sleep(0.3)
                            log(f"  pressed the door key {cls} at {adist:.1f} units")
                            pressed_keys.add(gkey)
                        elif adist <= 70.0:
                            if gkey not in pressed_keys or adist <= 25.0:
                                log(f"  DOOR KEY {cls} detected {adist:.1f} units ahead - going to press it")
                            side_key = globals().get("KEY_SIDE", 1)
                            before_key = adist
                            hold(pad, "left" if side_key > 0 else "right", 0.18)
                            hold(pad, "up", 0.7)
                            time.sleep(0.2)
                            after_key_state = state(pad)
                            after_rows = []
                            try:
                                after_rows = pso_coop_gates.forward_candidates(
                                    after_key_state.get("entities") or [],
                                    (after_key_state.get("player") or {}).get("room"),
                                    float((after_key_state.get("player") or {}).get("x") or 0),
                                    float((after_key_state.get("player") or {}).get("z") or 0),
                                    skip_switches=False)
                            except Exception:                      # noqa: BLE001
                                after_rows = []
                            after_key = after_rows[0][1] if after_rows else before_key
                            if after_key > before_key - 1.0:
                                key_misses += 1
                                if key_misses >= 4:
                                    globals()["KEY_SIDE"] = -side_key
                                    key_misses = 0
                            else:
                                key_misses = 0
                        moved += 1
                    else:
                        # A DOOR: walk through it; only count a crossing when the room actually changes.
                        if adist <= 18.0:
                            room_before = player.get("room")
                            hold(pad, "up", 1.0)
                            time.sleep(0.25)
                            after_gate = state(pad).get("player") or {}
                            if after_gate.get("room") != room_before:
                                crossed.append((round(ax / 25.0), round(az / 25.0)))
                                log(f"  crossed a door: room {room_before} -> {after_gate.get('room')}")
                        else:
                            side_key = globals().get("KEY_SIDE", 1)
                            hold(pad, "left" if side_key > 0 else "right", 0.18)
                            hold(pad, "up", 0.75)
                        moved += 1
                else:
                    # Nothing classifiable nearby: short sweep so the next sample can find something.
                    hold(pad, "left" if int(time.time()) % 2 else "right", 0.25)
                    hold(pad, "up", 0.6)
                    moved += 1
