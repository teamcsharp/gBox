"""Read-only player scoping is a prerequisite, not live co-op acceptance."""
import struct

import pytest

from gbox.mercs.titles import re5_coop as C, re5_ps3 as R
from test_re5_mercs import PLAYER, SPLAYER, with_inventory, with_prompt, world

P2, AB = 0x304F8A00, 0x38838370
BTN1, BTN2 = 0x328E1FE0, 0x328E3FE0


def duo():
    memory = with_inventory(world(hp=900), {0: (0x136, 1, 1, True)})
    memory.u32(SPLAYER, C.PLAYER_MANAGER_VT)
    memory.u32(SPLAYER + 0x38, 2)
    memory.u32(SPLAYER + 0x2C, P2)
    memory.put(PLAYER + C.PLAYER_INDEX, b'\0')
    memory.put(P2 + C.PLAYER_INDEX, b'\1')
    memory.put(P2 + R.P_HP, struct.pack('>hh', 500, 1000))
    memory.put(P2 + R.P_POS, struct.pack('>3f', 100., 20., 300.))
    record = P2 + R.P_INV
    memory.u32(record + R.INV_ID, 0x10B)
    memory.u32(record + R.INV_HAND, 1)
    memory.put(record + R.INV_USED, b'\1')
    with_prompt(memory, R.BTN_STAGE, PLAYER, 0, btn=BTN1)
    for offset, size in ((R.AB_PLAYER_ENABLED, 1), (R.AB_PLAYER_INDEX, 4),
                         (R.AB_INPUT_MODE, 4), (R.AB_ALTERNATE_CONTROLLER, 4),
                         *((offset, 0x1C) for offset in R.QTE_UNITS)):
        memory.put(AB + 0x2E8 + offset, memory.rd(AB + offset, size))
    memory.u32(AB + 0x2E8 + R.AB_PLAYER_INDEX, 1)
    memory.u32(AB + 0x2E8 + R.QTE_UNITS[0] + 0x0C, BTN2)
    memory.put(BTN2, memory.rd(BTN1, 0x74))
    memory.u32(BTN2 + R.BTN_OWNER, P2)
    memory.u32(BTN2 + 0x30, 2)
    return memory


def test_default_solo_chain_is_preserved_and_explicit_p2_requires_native_identity():
    memory = world()
    assert R.player_pointer(memory) == PLAYER
    memory.mercs_player_index = 1
    assert R.player_pointer(memory) == 0
    memory = duo(); memory.mercs_player_index = 1
    assert R.player_pointer(memory) == P2
    memory.put(P2 + C.PLAYER_INDEX, b'\0')
    assert R.player_pointer(memory) == 0
    assert R.selected_prompt(memory) is None


@pytest.mark.parametrize('index', [None, True, False, -1, 2, '1', 1.0])
def test_invalid_scope_never_falls_back_to_the_human_player(index):
    memory = duo(); memory.mercs_player_index = index
    assert R.player_pointer(memory) == 0
    assert R.selected_prompt(memory) is None and R.prompt(memory) is None
    assert R.snapshot(memory)['player'] is None


def test_native_display_blocks_and_button_masks_are_independent_per_player():
    memory = duo(); before = dict(memory.b)
    assert R.selected_prompt(memory)['button'] == BTN1
    assert R.egg_square_blocked(memory) is True
    memory.mercs_player_index = 1
    request = R.selected_prompt(memory)
    assert request['button'] == BTN2 and request['owner'] == P2
    assert R.stage_prompt(memory) and R.egg_square_blocked(memory) is False
    assert memory.b == before
    memory.u32(BTN2 + 0x30, 1)       # P1's mask cannot authorize a P2 prompt
    assert R.selected_prompt(memory) is None
    memory.mercs_player_index = 0
    assert R.selected_prompt(memory)['button'] == BTN1


def test_player_local_input_mode_does_not_consult_the_other_players_block():
    memory = duo(); memory.mercs_player_index = 1
    memory.u32(AB + R.AB_INPUT_MODE, 1)
    assert R.selected_prompt(memory)['button'] == BTN2
    memory.u32(AB + 0x2E8 + R.AB_ALTERNATE_CONTROLLER, 0)
    assert R.selected_prompt(memory) is None
    memory.u32(AB + 0x2E8 + R.AB_ALTERNATE_CONTROLLER, 0xFFFFFFFF)
    memory.put(AB + R.AB_ENABLED, b'\0')       # enable remains a global field
    assert R.selected_prompt(memory) is None


def test_p2_snapshot_uses_own_actor_inventory_and_never_p1_camera_or_laser(monkeypatch):
    memory = duo(); memory.mercs_player_index = 1
    camera_manager, camera = 0x38000000, 0x38010000
    memory.u32(R.S_CAMERA, camera_manager); memory.u32(camera_manager + R.CAM_CTRL, camera)
    memory.put(camera + R.CAM_EYE, struct.pack('>3f', 900., 900., 900.))
    # laser() itself is guarded, and snapshot may call it safely.
    original_read = memory.rd
    def guarded_read(address, length):
        assert address not in (R.S_CAMERA, camera_manager + R.CAM_CTRL, R.S_UNIT)
        return original_read(address, length)
    # Stage bonus/unit enumeration legitimately reads S_UNIT. Suppress those
    # independent world lists to make a foreign laser/camera read observable.
    monkeypatch.setattr(R, 'bonuses', lambda _memory: [])
    from gbox.mercs.titles import re5_mines, re5_health
    monkeypatch.setattr(re5_mines, 'ground_mines', lambda _memory: {})
    monkeypatch.setattr(re5_health, 'ground_items', lambda _memory: [])
    monkeypatch.setattr(R.re5_nav, 'read', lambda *_args: None)
    memory.rd = guarded_read
    assert R.laser(memory) is None
    snap = R.snapshot(memory)
    assert snap['player']['ptr'] == P2 and snap['player']['hp'] == 500
    assert snap['player']['pos'] == (100., 20., 300.)
    assert R.equipped(snap)['id'] == 0x10B
    assert snap.get('camera') is None and snap['laser'] is None
    assert snap['recovery_active'] is False


def test_changed_player2_actor_during_prompt_read_refuses_without_using_p1():
    memory = duo(); memory.mercs_player_index = 1
    original_read = memory.rd
    def changing_read(address, length):
        raw = original_read(address, length)
        if address == BTN2 and length == 0x74:
            memory.u32(SPLAYER + 0x2C, PLAYER)
        return raw
    memory.rd = changing_read
    assert R.selected_prompt(memory) is None
    assert R.prompt(memory) is None


def test_solo_recovery_fields_never_create_a_coop_self_revival_request():
    memory = duo(); memory.mercs_player_index = 1
    memory.put(P2 + R.P_HP, struct.pack('>hh', 1, 1000))
    memory.put(P2 + R.P_DYING_TIMER, struct.pack('>f', 12.))
    memory.u32(P2 + R.P_RECOVER_BUTTON, BTN2)
    assert R.recovery_active(memory, P2) is False
    assert C.for_player(memory, 2) is None       # no input readiness invented


def test_p2_observation_and_save_cannot_run_solo_mod_helpers_even_without_outer_flag(tmp_path, monkeypatch):
    from gbox import re5_mods_tool as mods
    memory = duo(); memory.mercs_player_index = 1
    memory.adapter = object()
    memory.mercs_no_modifications = False
    for name in ('maintain_fire_animation', 'maintain_item_animation', 'maintain_health'):
        monkeypatch.setattr(mods, name, lambda *_args, **_kw: pytest.fail('P2 cannot maintain P1 modifiers'))
    monkeypatch.setattr(R, 'save_crossings', lambda: None)
    bot = R.Bot(memory, learn_dir=tmp_path)
    bot.observe_round(R.snapshot(memory), 'playing', 10.)
    assert bot._control_state is None
    bot.save()


def test_p2_tick_never_invokes_solo_mine_placement_or_inherits_its_weapon_requests(tmp_path, monkeypatch):
    from gbox.mercs.titles import re5_mines
    memory = duo(); memory.mercs_player_index = 1
    bot = R.Bot(memory, learn_dir=tmp_path)
    bot._control_state = {'rotten_eggs': {'on': True}, 'weapon_pin': {'target': 'p1'}}
    monkeypatch.setattr(re5_mines, 'Controller', lambda *_args: pytest.fail('Planter identity remains unverified'))
    monkeypatch.setattr(bot, '_tick', lambda _snap: {'hold': {'r1'}})
    monkeypatch.setattr(bot, '_idle_breakout', lambda _snap, action: action)
    assert bot.tick(R.snapshot(memory)) == {'hold': {'r1'}}
    assert bot.mines is None and bot._control_state is None
