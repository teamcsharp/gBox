// Per-game mod icons for the compact (PiP) toolbar.
//
// The operator's requirement (2026-11-11): "every mod that we have for PSO, I want an icon in the top bar that I'm able to click on and use to modify
// the game in action even while the bot is playing."
//
// Every entry is a button in the bar. Clicking it runs the plane's `pso_controls` on the live session - an RPC, not keyboard input - so it works
// while the bot drives the character, and it needs no focus.
//
// Shape of an entry:
//   id       stable identifier (also the data attribute suffix)
//   label    tooltip text
//   icon     an SVG path (16x16 viewBox) drawn inside the button
//   op       the pso_controls op name
//   fields   fixed fields sent with the op
//   ask      optional [{key, label, value, type}] prompts collected before sending; `number` is coerced
//   toggle   optional {on:{...}, off:{...}} - the button sends one or the other each click
//   open     optional URL to open instead of an RPC
(function (root) {
  "use strict";

  const ICONS = {
    stat: 'M3 13V7m4 6V4m4 9V9m4 4V6',
    give: 'M8 2l5 3v6l-5 3-5-3V5z',
    equip: 'M3 4h10v2H3zm1 3h8v7H4z',
    multi: 'M2 4h6v2H2zm0 3h8v2H2zm0 3h10v2H2z',
    mag: 'M8 2a6 6 0 100 12A6 6 0 008 2zm0 3a3 3 0 110 6 3 3 0 010-6z',
    feed: 'M8 2v6m0 0l3-3m-3 3L5 5m-2 7h10',
    survival: 'M8 2l2 4 4 .5-3 3 .7 4.2L8 11.8 4.3 13.7 5 9.5 2 6.5 6 6z',
    crit: 'M8 1l2 5h5l-4 3 1.5 5L8 11l-4.5 3L5 9 1 6h5z',
    hit: 'M8 8m-2 0a2 2 0 104 0 2 2 0 10-4 0M8 1v3m0 8v3M1 8h3m8 0h3',
    walk: 'M4 14l2-5 2 2 1-4 2 7M6 4a1.5 1.5 0 103 0 1.5 1.5 0 10-3 0',
    legendary: 'M8 2l2.2 3.9L15 7l-3.4 3 .8 4.5L8 12.5 3.6 14.5 4.4 10 1 7l4.8-1.1z',
    random: 'M2 5h4l4 6h4m-2-3l2 3-2 3M2 11h4l2-3',
    pb: 'M8 2v3m0 6v3m6-6h-3M5 8H2m10.2-4.2l-2 2m-4.4 4.4l-2 2m8.4 0l-2-2m-4.4-4.4l-2-2',
    warp: 'M8 2a6 6 0 106 6 6 6 0 00-6-6zm0 2a4 4 0 11-4 4',
    boss: 'M8 2l2 3h4l-2 4 2 4H3l2-4-2-4h3z',
    clear: 'M3 3l10 10M13 3L3 13',
    spawn: 'M8 2v12M2 8h12',
    drops: 'M8 2v8m0 0l3-3m-3 3L5 7m-3 5h12',
    revive: 'M8 2a6 6 0 106 6M8 5v4l3 2',
    map: 'M2 3h4v10H2zm6 0h4v10H8zm-6 5h12',
    flash: 'M8 2l-4 7h3l-1 5 5-7H8z'
  };

  const PSO_MODS = [
    {id: 'stat', label: 'Raise a stat (mst gives TP). Sent as pso_controls stat.', icon: ICONS.stat,
     op: 'stat', ask: [{key: 'name', label: 'Stat name (atp, dfp, mst, hp, ata, evp, lck)', value: 'mst'},
                       {key: 'value', label: 'Value', value: '999', type: 'number'}]},
    {id: 'give', label: 'Give an item by code', icon: ICONS.give, op: 'give',
     ask: [{key: 'code', label: 'Item code (e.g. 000700 Rifle, 000600 Handgun)', value: '000700'},
           {key: 'count', label: 'Count', value: '1', type: 'number'}]},
    {id: 'equip', label: 'Equip a weapon by code', icon: ICONS.equip, op: 'equip',
     ask: [{key: 'target', label: 'Weapon code to equip', value: '000700'}]},
    {id: 'multi', label: 'Fill every weapon slot with one weapon', icon: ICONS.multi, op: 'multi_equip',
     ask: [{key: 'target', label: 'Slot to copy from', value: '0'}]},
    {id: 'equipany', label: 'Ignore weapon requirements (equip anything)', icon: ICONS.equip, op: 'equip_any',
     toggle: {on: {on: true}, off: {on: false}}},
    {id: 'mag', label: 'Set the mag stats', icon: ICONS.mag, op: 'mag_set',
     ask: [{key: 'def', label: 'DEF', value: '5', type: 'number'},
           {key: 'pow', label: 'POW', value: '100', type: 'number'},
           {key: 'dex', label: 'DEX', value: '50', type: 'number'},
           {key: 'mind', label: 'MIND', value: '45', type: 'number'}],
     build: values => ({properties: {def: values.def, pow: values.pow, dex: values.dex, mind: values.mind,
                                     iq: 200, synchro: 120}})},
    {id: 'feed', label: 'Feed the mag', icon: ICONS.feed, op: 'mag_feed'},
    {id: 'survival', label: 'Permanent Scape Doll: cannot die', icon: ICONS.survival, op: 'survival',
     toggle: {on: {on: true}, off: {on: false}}},
    {id: 'crit', label: 'Every hit is a critical', icon: ICONS.crit, op: 'crit',
     toggle: {on: {on: true}, off: {on: false}}},
    {id: 'hit', label: 'Every attack connects', icon: ICONS.hit, op: 'always_hit',
     toggle: {on: {on: true}, off: {on: false}}},
    {id: 'walk', label: 'Ignore collision (walk through walls)', icon: ICONS.walk, op: 'walk_through',
     toggle: {on: {on: true}, off: {on: false}}},
    {id: 'legendary', label: 'Legendary: unlock the ultimate difficulty', icon: ICONS.legendary, op: 'legendary',
     toggle: {on: {on: true}, off: {on: false}}},
    {id: 'random', label: 'Randomised gear on an interval', icon: ICONS.random, op: 'randomized',
     ask: [{key: 'interval', label: 'Seconds between re-rolls (5-300)', value: '120', type: 'number'}]},
    {id: 'pb', label: 'Photon blast at maximum', icon: ICONS.pb, op: 'pb'},
    {id: 'warp', label: 'Teleport to a floor', icon: ICONS.warp, op: 'floor_warp',
     ask: [{key: 'target', label: 'Floor (0 city, 1 Forest 1, 2 Forest 2, 3 Cave 1 ... 11 Dragon)', value: '1'}]},
    {id: 'boss', label: 'Go to a boss arena', icon: ICONS.boss, op: 'boss_warp',
     ask: [{key: 'target', label: 'Boss id (dragon, de_rol_le, vol_opt, dark_falz)', value: 'dragon'}]},
    {id: 'clear', label: 'Clear the floor of gBox-spawned items', icon: ICONS.clear, op: 'floor_clear'},
    {id: 'spawn', label: 'Spawn items on the floor', icon: ICONS.spawn, op: 'floor_spawn',
     ask: [{key: 'codes', label: 'Comma-separated item codes', value: '000700'}]},
    {id: 'drops', label: 'Enemy drops on/off', icon: ICONS.drops, op: 'enemy_drops',
     toggle: {on: {on: true}, off: {on: false}}},
    {id: 'revive', label: 'Revive the character', icon: ICONS.revive, op: 'revive'},
    {id: 'map', label: 'Open the live 2D map viewer', icon: ICONS.map, open: 'http://127.0.0.1:8802/'}
  ];

  // Games are matched by title; the first hit wins, so the PSO entry catches both episodes.
  const GAMES = [
    {match: /phantasy\s*star|episode\s*i\s*&\s*ii/i, name: 'PSO', mods: PSO_MODS}
  ];

  function modsFor(title) {
    const text = String(title || '');
    const game = GAMES.find(entry => entry.match.test(text));
    return game ? game.mods : [];
  }

  root.gboxGameMods = {modsFor, PSO_MODS, ICONS};
})(typeof window !== 'undefined' ? window : globalThis);
