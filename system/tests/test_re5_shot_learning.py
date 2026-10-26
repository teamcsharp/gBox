"""Learning records must describe the firing weapon and a damage observation inside its time window."""
from gbox.mercs.aim import Shots
from gbox.mercs.titles import re5_combat as C
from tests.test_re5_combat import world, ENEMY
from gbox.mercs.titles.re5_mines import GroundMines


def mine_list(rows=(), *, verified=True):
    ground = GroundMines(rows)
    ground.verified = verified
    return ground


def test_late_damage_cannot_rescue_an_expired_shot():
    shots = Shots()
    shots.update([{'slot': 0, 'hp': 800}], 0)
    shots.fired(.1)
    shots.update([{'slot': 0, 'hp': 600}], 1.)
    assert shots.stats['hits'] == 0 and shots.stats['misses'] == 1
    assert shots.stats['accuracy'] == 0


def test_newer_shot_receives_damage_after_older_shot_expires():
    shots = Shots()
    shots.update([{'slot': 0, 'hp': 800}], 0)
    shots.fired(.1)
    shots.fired(.6)
    shots.update([{'slot': 0, 'hp': 600}], .7)
    assert shots.stats['hits'] == shots.stats['misses'] == 1
    assert not shots.pending


def test_expired_headshot_cannot_steal_a_newer_body_hit_or_train_the_wrong_weapon(tmp_path):
    events = []
    bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=events.append)
    bot.start_round(0)
    bot.character, bot.wid = 'barry', 0x12
    bot.shots.update([{'slot': 0, 'hp': 800}], 0)
    bot.last_dot = ('head', ENEMY, None, None, .1)
    bot._on_shot(.1)
    bot.wid = 0x16
    bot.last_dot = ('body', ENEMY, None, None, .5)
    bot._on_shot(.5)
    bot._observe_impacts([{'slot': 0, 'hp': 600}], .6)
    bot._score(.6)
    assert bot.stats['hits'] == bot.stats['misses'] == 1 and bot.stats['headshots'] == 0
    assert bot.tun.weapon('barry', 0x12)['hits'] == 0
    assert bot.tun.weapon('barry', 0x16)['hits'] == 1
    assert [(row['weapon'], row['result']) for row in events] == [
        (0x12, 'miss: dot on him, he moved'), (0x16, 'hit')]
    bot.end_round(1.)
    assert bot.tun.weapon('barry', 0x12)['head_r'] < C.HEAD_R
    assert bot.tun.weapon('barry', 0x16)['head_r'] == C.HEAD_R


def test_swap_before_impact_keeps_firing_character_and_weapon_in_learning_record(tmp_path):
    events = []
    bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=events.append)
    bot.start_round(0)
    bot.character, bot.wid = 'barry', 0x12
    bot.shots.update([{'slot': 0, 'hp': 800}], 0)
    bot.last_dot = ('body', ENEMY, None, None, .1)
    bot._on_shot(.1)
    bot.character, bot.wid = 'sheva', 0x16
    bot._observe_impacts([{'slot': 0, 'hp': 600}], .2)
    bot._score(.2)
    assert bot.tun.weapon('barry', 0x12)['hits'] == 1
    assert bot.tun.weapon('sheva', 0x16)['hits'] == 0
    assert events[0]['character'] == 'barry' and events[0]['weapon'] == 0x12


def test_mine_damage_is_unattributed_and_gun_learning_resumes_after_the_observed_window(tmp_path):
    bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=lambda row: None)
    bot.start_round(0)
    bot.character, bot.wid = 'barry', 0x12
    bot.last_dot = ('head', ENEMY, None, None, .1)
    bot.shots.update([{'slot': 0, 'ptr': ENEMY, 'hp': 800}], 0)
    bot._on_shot(.1)
    ground = mine_list({123: {'detonating': True}})
    bot._update_attribution({'ground_mines': ground}, 0, .2)
    bot._observe_impacts([{'slot': 0, 'ptr': ENEMY, 'hp': 600}], .2)
    bot._score(.2)
    assert bot.stats['shots'] == 1 and bot.stats['hits'] == bot.stats['misses'] == 0
    assert bot.stats['mine_window_enemy_hp_loss_unattributed'] == 200
    assert bot.stats['shot_impacts_unattributed'] == 1 and bot.stats['accuracy'] is None
    assert bot.tun.weapon('barry', 0x12)['shots'] == 0

    clear = {'ground_mines': mine_list(), 'mines_enabled': False}
    bot._update_attribution(clear, 0, .5)
    assert bot.mine_damage_confounded  # disappearance does not erase delayed explosion damage
    bot._on_shot(.5)
    bot._observe_impacts([{'slot': 0, 'ptr': ENEMY, 'hp': 400}], .5)
    bot._score(.5)
    assert bot.tun.weapon('barry', 0x12)['shots'] == 0

    bot._update_attribution(clear, 0, 2.3)
    bot._observe_impacts([{'slot': 0, 'ptr': ENEMY, 'hp': 400}], 2.3)
    bot._update_attribution(clear, 0, 2.4)
    assert not bot.mine_damage_confounded
    bot._on_shot(2.4)
    bot._observe_impacts([{'slot': 0, 'ptr': ENEMY, 'hp': 200}], 2.4)
    bot._score(2.4)
    assert bot.tun.weapon('barry', 0x12)['shots'] == bot.tun.weapon('barry', 0x12)['hits'] == 1
    bot.end_round(3.)
    assert bot.tun.weapon('barry', 0x12)['head_r'] == C.HEAD_R  # unowned impacts never tighten aim


def test_unreadable_active_mine_list_blocks_learning_but_verified_empty_list_does_not(tmp_path):
    for active, ground, blocked in ((True, mine_list(verified=False), True),
                                   (True, None, True), (True, mine_list(), False),
                                   (False, mine_list(), False)):
        bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=lambda row: None)
        bot.start_round(0)
        bot._update_attribution({'ground_mines': ground, 'mines_enabled': active}, 0, .1)
        assert bot.mine_damage_confounded is blocked
