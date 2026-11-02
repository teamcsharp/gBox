"""Independent, conservative observations of captured English PSO boot menus.

Only static game-text masks are retained, never a full capture. The current
layout must match its labels and a unique orange cursor, except for the separately
observed title screen, which has no menu cursor. This is visual proof,
not a native menu cursor or a claim that input changed the game. Unknown layouts,
transitions, other saved identities and character editors remain unsupported.
"""
from __future__ import annotations

import base64
import hashlib
import io
import zlib

import numpy as np
from PIL import Image, UnidentifiedImageError


def _ink(image):
    a = np.asarray(image).astype(np.int16)
    return (a.min(2) > 145) & ((a.max(2) - a.min(2)) < 115)


def _text(image, name, *, offset=(0, 0), dark=False):
    row = _TEXT[name]
    ref = np.unpackbits(np.frombuffer(zlib.decompress(base64.b85decode(row['data'])), dtype=np.uint8))
    ref = ref[:int(np.prod(row['shape']))].reshape(row['shape']).astype(bool)
    best = 0.
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            box = tuple(v + offset[n % 2] + (dx if n % 2 == 0 else dy) for n, v in enumerate(row['box']))
            crop = image.crop(box)
            mask = np.asarray(crop).max(2) < 115 if dark else _ink(crop)
            denominator = int(mask.sum() + ref.sum())
            if denominator:
                best = max(best, float(2 * (mask & ref).sum() / denominator))
    return best


def _orange(image, box):
    r, g, b = np.asarray(image.crop(box)).astype(np.int16).transpose(2, 0, 1)
    return float(((r > 110) & (r > g + 25) & (g > b + 12)).mean())


def _selected(image, boxes, *, minimum=.16, maximum_other=.07):
    scores = [_orange(image, box) for box in boxes]
    found = [index for index, score in enumerate(scores) if score >= minimum]
    if len(found) != 1 or any(score > maximum_other for index, score in enumerate(scores) if index != found[0]):
        return None
    return found[0]


def observe(frame):
    """Read a bounded, complete frame. No input or memory operations occur."""
    result = {'recognized': False, 'menu': None, 'selected': None,
              'menu_visible': False, 'gameplay_visible': False,
              'reason': 'Boot menu and selection are not independently recognized'}
    if not isinstance(frame, bytes) or not 0 < len(frame) <= 8_000_000:
        return result
    result['frame_sha256'] = hashlib.sha256(frame).hexdigest()
    try:
        with Image.open(io.BytesIO(frame)) as source:
            if not (320 <= source.width <= 2048 and 240 <= source.height <= 2048):
                return result
            if source.size in ((960, 540), (1031, 580)):
                # Both exact sizes were captured from this same render viewport:
                # adapter PNG 1031x580 and its API preview 960x540. Normalize only
                # these observed sizes; retain pillarbox and all label proofs.
                image = source.convert('RGB').resize((960, 540), Image.Resampling.LANCZOS)
                # Separately observed capture layout. Do not stretch a crop or
                # a different render viewport into the old menu coordinates.
                pixels = np.asarray(image)
                if any(float((pixels[20:520, left:right].max(2) <= 12).mean()) < .995
                       for left, right in ((20, 140), (820, 940))):
                    return result
                result['layout'] = '960x540_pillarboxed' if source.size == (960, 540) else '1031x580_pillarboxed'
                return _observe_wide(image, result)
            # Capture coordinates are normalized only for the demonstrated full
            # Dolphin framing. Crops, unrelated aspect ratios and window chrome
            # do not create evidence by being stretched into the template.
            if abs(source.width / source.height - 687 / 580) > .018:
                return result
            image = source.convert('RGB').resize((687, 580), Image.Resampling.BILINEAR)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return result

    found = []

    # These observations are demonstrated only in P1's top split-screen view.
    # A matching lower-view panel is a reason to pause, never permission to
    # send P1 controls into a menu whose owner has not been demonstrated.
    start_names = ('start_item', 'start_customize', 'start_status', 'start_options', 'start_quit')
    def start_labels(offset=(0, 0)):
        return [max(_text(image, name, offset=offset), _text(image, name, offset=offset, dark=True))
                for name in start_names]
    start = start_labels()
    quit_names = ('quit_question', 'quit_yes', 'quit_no')
    quit_labels = [_text(image, name) for name in quit_names]
    after_names = ('after_title', 'after_mode', 'after_characters', 'after_quit')
    after_labels = [_text(image, name) for name in after_names]
    result['menu_visible'] = bool(sum(score >= .72 for score in start) >= 4 or
        quit_labels[0] >= .8 or after_labels[0] >= .8 or
        sum(score >= .72 for score in start_labels((0, 290))) >= 4 or
        _text(image, 'quit_question', offset=(0, 290)) >= .8)

    def matches(names):
        variants = {'online': ('online', 'online_selected'),
                    'offline': ('offline', 'offline_unselected'),
                    'options': ('options', 'options_selected')}
        return all(max(_text(image, key) for key in variants.get(name, (name,))) >=
                   (.72 if name in ('online', 'website') else .81) for name in names)

    def record(menu, labels, index):
        if index is not None:
            found.append({'menu': menu, 'selected': labels[index], 'option_index': index, 'player': 1})

    if min(start) >= .72:
        record('ingame_start', ('Item Pack', 'Customize', 'Status', 'Options', 'Quit Game'),
               _selected(image, [(31, y, 130, y + 13) for y in (116, 135, 154, 173, 192)],
                         minimum=.45, maximum_other=.12))
    if min(quit_labels) >= .8:
        record('quit_confirm', ('Yes', 'No'), _selected(image,
               [(400, y, 495, y + 10) for y in (138, 162)], minimum=.35, maximum_other=.12))
    if min(after_labels) >= .8:
        record('after_save', ('Change Game Mode', 'Change Characters', 'Quit Game'),
               _selected(image, [(170, y, 465, y + 12) for y in (221, 282, 342)],
                         minimum=.1, maximum_other=.04))

    if matches(('main_title', 'online', 'offline', 'options', 'website')):
        record('main', ('Online Game', 'Offline Game', 'Options', 'Website'),
               _selected(image, [(211, y, 477, y + 12) for y in (377, 413, 451, 488)]))

    if matches(('mode_title', 'single', 'multi')):
        record('mode', ('Single Mode', 'Multi Mode'),
               _selected(image, [(175, y, 236, y + 12) for y in (252, 313)], minimum=.12))

    character = matches(('character_title', 'slot_a', 'main_character',
                         'temp_characters', 'empty_first', 'player_one', 'player_one_number'))
    if character:
        slot = _selected(image, [(128, y, 217, y + 13) for y in (239, 290, 341, 391)],
                         minimum=.65, maximum_other=.12)
        if slot == 0 and matches(('create_question', 'create_yes', 'create_no')):
            record('create_empty_p1', ('Yes', 'No'), _selected(image,
                   [(558, y, 654, y + 10) for y in (261, 284)], minimum=.5))
        elif slot == 0 and float(_ink(image.crop((462, 166, 667, 312))).mean()) < .01:
            # Do not reuse the underlying slot proof while any unrecognized
            # modal text covers the otherwise empty right-hand panel.
            record('empty_p1', ('Main Character 1: NO DATA',), 0)

    if matches(('calendar_question', 'calendar_warning', 'calendar_yes', 'calendar_no')):
        record('calendar', ('Yes', 'No'), _selected(image,
               [(84, y, 604, y + 9) for y in (451, 475)], minimum=.65))

    if len(found) == 1:
        result.update(found[0], recognized=True,
                      reason='Static English menu labels and one orange selection independently matched')
    result['menu_visible'] = bool(result['menu_visible'] or found)
    # Used only to verify departure after a permitted B cancellation. These
    # small HP/TP label masks contain no character names or mutable bar values.
    result['gameplay_visible'] = bool(not result['menu_visible'] and
        _text(image, 'hud_p1') >= .85 and _text(image, 'hud_p2') >= .85)
    return result


def _observe_wide(image, result):
    """Only the actually captured 960x540 English layout and saved buddies."""
    found = []

    def matches(*names, threshold=.8):
        return all(_text(image, 'w_' + name) >= threshold for name in names)

    def record(menu, selected, index, player=1, **details):
        found.append(dict(menu=menu, selected=selected, option_index=index, player=player, **details))

    # This observed title also occurs while PRESS START is faded out. Require
    # all five static title/licensing regions and exclude the main menu.
    title_start = matches(
        'title_wordmark', 'title_online', 'title_episode', 'title_license', 'title_copyright', threshold=.84)
    main_options_visible = any(_text(image, 'w_' + name) >= .6
        for name in ('online', 'offline', 'options', 'website'))
    if title_start and not main_options_visible:
        record('press_start', 'PRESS START', 0)
    title_main = matches('main_title')
    title_mode = matches('mode_title')
    title_character = matches('character_title', 'slot_a', 'main_character', 'temp_characters')
    title_ready = matches('verify_title', 'verify_p1', 'verify_p2', 'verify_question')
    title_options = matches('options_title')
    start_names = ('start_item', 'start_customize', 'start_status', 'start_options', 'start_quit')
    start_scores = [max(_text(image, 'w_' + name), _text(image, 'w_' + name, dark=True)) for name in start_names]
    hud_visible = bool(max(_text(image, 'w_hud_p1'), _text(image, 'w_hud_p1_town')) >= .85 and
                       _text(image, 'w_hud_p2') >= .85)
    quit_title = matches('quit_question')
    after_title = matches('after_title')
    # Only this observed P2 single-destination panel is supported. The static
    # label, both HUDs, orange row and four dark panel edges must agree.
    forest_label = matches('forest_destination', threshold=.85)
    forest_panel = all(float((np.asarray(image.crop(box)).max(2) < 95).mean()) >= minimum
        for box, minimum in (((337, 318, 623, 323), .9), ((337, 350, 623, 355), .9),
                             ((334, 323, 339, 350), .85), ((620, 323, 625, 350), .85)))
    result['menu_visible'] = bool(title_start or title_main or title_mode or title_character or title_ready or
                                  title_options or forest_label or quit_title or after_title or sum(score >= .72 for score in start_scores) >= 4)
    if (forest_label and forest_panel and hud_visible and
            _selected(image, [(340, 328, 620, 342)], minimum=.45) == 0):
        record('transporter_forest', 'FOREST 1', 0, player=2, observed_episode=1, destination_floor=1)

    # Preserve the old sampled text and the independently captured current
    # Online/Offline glyph variants. Each label still needs its own high score.
    main_labels = (max(_text(image, 'w_' + name), _text(image, 'w_' + name + '_live'),
                       _text(image, 'w_' + name + '_live_other')) >= .76
                   for name in ('online', 'offline'))
    if title_main and all(main_labels) and matches('options', 'website', threshold=.76):
        index = _selected(image, [(354, y, 605, y + 10) for y in (352, 387, 424, 460)], minimum=.08, maximum_other=.04)
        if index is not None:
            record('main', ('Online Game', 'Offline Game', 'Options', 'Website')[index], index)
    if title_mode and matches('single', 'multi'):
        index = _selected(image, [(320, y, 615, y + 11) for y in (232, 290)], minimum=.1, maximum_other=.04)
        if index is not None:
            record('mode', ('Single Mode', 'Multi Mode')[index], index)

    if title_character:
        index = _selected(image, [(184, y, 360, y + 14) for y in (219, 267, 315, 364)],
                          minimum=.35, maximum_other=.15)
        # Name and class proofs intentionally limit this path to the existing
        # observed campaign buddies. Occupancy alone never authorizes selection.
        if index == 0 and matches('lyra_name', 'axis_name', 'p1_prompt', 'p1_digit', 'racast_class'):
            record('saved_p1', 'LYRA95 / RAcast / Main Character 1', 0, player=1)
        if index == 1 and matches('axis_name', 'p2_prompt', 'p2_digit', 'p1_assigned', 'hunewearl_class'):
            record('saved_p2', 'AXIS92 / HUnewearl / Main Character 2', 1, player=2)

    if title_ready:
        p1_ready = matches('p1_ok')
        p1_empty = float(_ink(image.crop((296, 379, 356, 404))).mean()) < .015
        p2_empty = float(_ink(image.crop((610, 379, 670, 405))).mean()) < .015
        if p2_empty and (p1_ready or p1_empty):
            record('verify_saved', 'Player 2 ready' if p1_ready else 'Player 1 ready',
                   1 if p1_ready else 0, player=2 if p1_ready else 1)

    if title_options and matches('difficulty_label', 'difficulty_normal', 'mode_label', 'mode_normal',
                                 'episode_label', 'episode_one', 'start_game', 'game_will_start'):
        index = _selected(image, [(216, y, 647, y + 10) for y in (175, 233, 291, 350)],
                          minimum=.08, maximum_other=.04)
        if index == 3:
            record('game_options', 'Start Game', 3, observed_episode=1, observed_difficulty=0)

    if after_title and matches('after_mode', 'after_characters', 'after_quit'):
        index = _selected(image, [(303, y, 598, y + 10) for y in (204, 262, 319)],
                          minimum=.1, maximum_other=.04)
        if index is not None:
            record('after_save', ('Change Game Mode', 'Change Characters', 'Quit Game')[index], index)

    if quit_title and matches('quit_yes', 'quit_no'):
        index = _selected(image, [(533, y, 624, y + 9) for y in (125, 148)],
                          minimum=.35, maximum_other=.12)
        if index is not None:
            record('quit_confirm', ('Yes', 'No')[index], index)

    if min(start_scores) >= .72:
        index = _selected(image, [(180, y, 277, y + 12) for y in (102, 120, 138, 156, 174)],
                          minimum=.4, maximum_other=.12)
        if index is not None:
            record('ingame_start', ('Item Pack', 'Customize', 'Status', 'Options', 'Quit Game')[index], index)

    if len(found) == 1:
        result.update(found[0], recognized=True,
                      reason='Observed English labels, saved identity where applicable, and unique selection matched')
    if result.get('menu') == 'press_start':
        result['reason'] = 'Observed PSO Plus title and licensing labels; main-menu options absent; prompt may be faded'
    result['gameplay_visible'] = bool(not result['menu_visible'] and hud_visible)
    return result


def next_key(observation, players=1, *, finish_save=False):
    """One conservative input toward the authorized offline campaign setup."""
    if not observation.get('recognized') or type(players) is not int or players not in (1, 2):
        return None
    menu, index = observation['menu'], observation['option_index']
    if menu == 'press_start':
        return 'start'
    if menu == 'ingame_start':
        return ('a' if index == 4 else 'ddown') if finish_save else 'b'
    if menu == 'quit_confirm':
        return ('a' if index == 0 else 'dup') if finish_save else 'b'
    if menu == 'after_save':
        return ('a' if index == 0 else 'dup') if finish_save else None
    if menu == 'main':
        return ('down', 'a', 'up', 'up')[index]
    if menu == 'mode':
        wanted = 1 if players == 2 else 0
        return 'a' if index == wanted else ('down' if wanted else 'up')
    if menu == 'empty_p1':
        return 'a'
    if menu == 'create_empty_p1':
        return 'a' if index == 0 else 'up'
    if menu == 'calendar':
        return 'a' if index == 1 else 'down'
    return None


# Small monochrome masks from observed game labels, including the current
# generated buddy names. No full screenshots, desktop chrome or model-generated
# image evidence are stored.
_TEXT = {'main_title': {'box': (199, 314, 535, 346),
                'shape': (32, 336),
                'data': 'c-oDWL2Khi6vv;UU|od9?a2#5^A#NSqG03cse9~K2<)L(n?0;T)r?A@qOgs>Kxn?g9(&r12{;#He}s-ni7q9K2`mab%<CIFA!Xarjxo}k`RToR^XC5mo=4!|Uq)DcHX*Cs|G!D0AjI~cNcGtSHxQxyKV;;9BYyRFG9XeQYDB|bfJhDv*#;z{B16M=o%R?|Ae!7DI*AcYkwdZ((Bo`NZa;!>4sZl;SOM436kezi1*hFATI)j$nk!oOk)sYk0q{b{q2=cyP_2l_L#Pcv4lLBtK#@f%#14_AaNOX`iC<CA*64rQw9@u~)oWAGI#Uc6RFhKTg+cAa2F>~k4UwiOB&HD6>pJyh#b+&LluBG0G;TP-_NK;GuF(#2iRTd3r~C|3!Juf5DY^K2ygSfimrovS!;}?kbXjkL3kd3vFCi8QG#?HrtN3{3zR-P_kI^*@hMdTx_uYkkA_qzE%jjSZQ7o6XtNS1Gu^?xV5s67pp6|%1iwAM=Ve}F+PTtEd>W_IIpi6gT)RQTlUL8(3dh%rS^3!D=Ljql#-R5-acPS)nOF{~sRH7zw@1%Tv(~M)PMHf$Rb5TX!=U>UFDnr`m-km4Ej>S9Z0-NW;!ZRtiWRmfVc#!S?UNrZ&-^5~(^$~xhBUC5P`#c{~MyZ@$dU6pq_w!e=TnHjN`CDwCNJiudkv&-pPg;51EMLXP?rk4!C;xV3M+u~lq`mdz{grq(NcT%5@^w7M=DmSV{zg%WVd!hbsYY{8uJvRw$oBHhsyW-l1zx|`L{4-m>Z<T{_tiY}q|xS&K@uLS)%A3f3arUzG90(1JZ%h-?TFG#h|CLPtVqHKB6&;qlNn1<jcDII-p{g-Hltf-g(<CIKWy~R%dDWPF>RsbhOIY7o}#XTmL#77iyT*_9Wk{wKdCQ|Nk_a&;fO+n+L6rYOQSp)140&P($TD~uaX0=MQR50utG`gExPzforEEN!r$msHSKD3aY@L-mb~1l_=)r?zS)^-JAu9v5GjzOqh_!j?Usyu%kcWIq%O;rG`RoRQ5ba@dA&n}T_4&b*&q2A${YR!v!png'},
 'online': {'box': (274, 370, 413, 393),
            'shape': (23, 139),
            'data': 'c-nQ4KTg9i6vlr}OyVIz9zm*#dxMM}DiOg&!VNkyRH{o5a4eUJV`O6H0F}!3V6JWHS?_!P{unN=;lH?3aM_jiobPi_b^f8OV<HL)9=ZUrt_wp8574>;c+xY0nUEcGpCJ1dM+b>{(RizQWOP}xn>rWOrQl9nU-i3$;+|>d!@X7#8pj6JcoIjS)mU^<id46m^k!D-!%L7Nk6V2FG~e6aX_~NuX{{_#s!7|mIkIQuo02{Lt|TV;kvHENmGQ@MU{&yTx2QvPE%LR2ifYk09u@ZQhju2+a1&Bx@6G9xI*m>o40DCN60}iAj90Yf!k_;FCpt3b'},
 'offline': {'box': (268, 407, 421, 431),
             'shape': (24, 153),
             'data': 'c-oDTF>b<842D1RXkLaW$;glby+NujsT2Xd38)7sBLjjbb>I>`N{7c%wqAi(v2@H-Wr(2W2H27%TfgkjHr!;!O<nDT?97BQ+y#=@ejGjCHk7lRd=7<is*PU)%m+}FkcbEAvm}~FepSS{1eNkdg=r+zsftr_Exl48jWoju$|#Me@4t^O;;k*)%=EI>WNx%S-+N)&)hpxNt~0y9*rWl+x-K4cRw{=^d)bwSNs;EtVmY<f9Xbu8G>R2V-13?&I)Q9wP+IZTnvH4Bc)9%S6|+C}$uPfU?N*5|P2+p?M!^zqcb&KjX-h=C5|=!m&di3ehM>zNglMohFwWo!+TMVO(#Gt`jZ%6xlIR)w_Ij~oCXT$G555(RE35s3W3ZnTHtTMC5&s>%T-E'},
 'options': {'box': (289, 445, 401, 468),
             'shape': (23, 112),
             'data': 'c-noC!3x4K42J)XAvug}#~y<2Fnj`$9?IsU_#iTeyX>(BzKD-v(zyv9OrXt|KW)<hf2_w{9XDLirNjU@TQEa&Y8k*usnx>~4Hrfyc=(8Br(zB<3J@a_5kLCiC1VCf5jRdD3fR4<)x%E;y%Mg}@=7IYI;-|rXh5pW7MksrL{TdCRRK8|L3}}#zAhhPC`IeJK`v}TZO!INr3LGc_TLG(Z4%qo{S4_1mM9sz'},
 'website': {'box': (289, 482, 401, 506),
             'shape': (24, 112),
             'data': 'c-no?K@Ng25CzZ=Oj?N8#=Qv~K`$V90<VA<5sW5oJQPRaBx3&*7rKxH%9}qaOo6|b33sx**J!3@tVYa35A3fjwROyPH(0JEwk$tXP9-XVi2~)LYJts8#-}cCpXfvrk5_)YYo<O>;YWPXdT^Sh+K18QXQ5Wy5vndlk<Hec&?(gv#C?PU7KP4)l1-G3$O^x(Oe<gKP{MwK3m<+c;=ujSfxQ7rbQvc'},
 'online_selected': {'box': (274, 370, 413, 393),
                     'shape': (23, 139),
                     'data': 'c-nQ4F;2rU7=@qXC`lzNakmUnlZp#?WQba;NSvdH3uLSWDt~FDFd(=9hjCj*21W)3hhD&AhltRMxo`QV_w@7u=cE6@IuRQ7ne;R@MeOwswp0pIYh(h*B0%x=J7x)RjgMr#0b*2(Ce;=LlaQ+l#wZBoKFYuybECk=yqeQb)-u8p_uLo~VkE`YccFN{ex*e!A2y9;Pj|I<>^K*~!$Nf!#uWjRES45J406KwR|4T~^_U@o-8uNv?eX@ZQk)plbO~w>GlYE{K%wY)SS#5_bJkl+0sP!ny77`$An$~P0c9~#r~R=(VsIRljBGfHP?um|;4Nm50{a%SAq+`&7eae5m!<Ng)JTItefxZp0DrPYe!$AGmzy`B1h_eY(;4S~m8@S?'},
 'offline_unselected': {'box': (268, 407, 421, 431),
                        'shape': (24, 153),
                        'data': 'c-oCoJ5Izf5PgnK>>@%gQ$)yOFA#|)4PeAYI0E#m)j+{EdjLufLXnPRkctvTqFJGpV4leV){@_RJfAmX;HYC|WA-ZjFRp2yjKo&&XwT7SRqlXbr9{61NyVTyfRPUObmgHdhK8czbHda$#T69|sAD><`CcPPfK;l-*&CAZg7GS5>ce0~5Y3k51G~AlONG_@M2iK{xX4~u%}fuaY=xe#$Z^b$U~QQMVXct9kj>%dQIyN2xE9}jzEGk+X;RKOQwR^+7YI`#$VI{Rw+{dGmy_#=CtX-E_El-=mt7LqrVQ?BG~6FL#OHp=_Md`}$-n9Ta5(OZ@CSzbFD('},
 'options_selected': {'box': (289, 445, 401, 468),
                      'shape': (23, 112),
                      'data': 'c-no?KMKMy6bA6G2K)mh$(SLe9-(d(LfXSPi-JRk5+h#1qc|3O5qpD<PU=f_aWRC19|^qoJ>bvsIN}97aYqS+aVIA_s+OU`5(Puc7onQcSBu(XBLtRHxTppVNv0$h<z^&pjV{lR+B(MhPCHWfsJ)vAHYjf}%0OUHM}u{D{b(28R$qmDPS<{v6nB|A!+KKVa-n6aP1bjprmzK16;;npoucXmhosIlqP)$JQ`ZW&`4$H&kSCM~6Hp>UiI9Xif$^+biuWA|P=?<jy#e+|Kt2'},
 'mode_title': {'box': (154, 64, 534, 99),
                'shape': (35, 380),
                'data': 'c-qyJL2lbH5Jg8|04{lf0=z~RLD+-zAYF+HvhdPJ@KK^53oUyE8ZO{vD5OAWgy8hgNOp|&1QBFW<j~LKKYvK{1+Ux7Td0P4%H)`bP~}OnlB*Pl@Wz}>BMEd|iMf#F6uI^!6URxGFc2pTPGF{xJObHs5?04-flq>eU|yF7-zbh@&zw!`B!GJmmgfR|RD9qfOBg!EH!t|?5vZOuRZ0Dv{Uh@hOIGktz(>Wi;SKXM^Qf$cddWUcRhHsZx{qv|1-=0v5Rg~JXZMoGAp4PQ_9F(DJq6%X+-D+#U)^T6FFsY#lIUJ<OnS;PG;Ep|ylg0;;II230!1bZd%?T$W*M*v;milcZ+JVJxtOf@@e?oeN?jFvvFw^3q?WN1`F>D5kM@H%qP>whK7RN?J@6+!KoJA+c0+es@t%jsMa7v{d~waDYI(;hPK_s&Xg7EWjcx5xT7SlKYHo}Gh;#VYg6~kr4CmwvzFhE5@Vwv~U*o-0bd&$Xr=H&x|Ni=Pg(nB+l=x5f4oSXpRD3wCcqe%BD6LIr(FH#;ER*{9F8P@^-fahS76-s9?Y}SDi%;yaMJ;WZOI@@_C2rEEbKK|#9jrLAkH<MH-fxqY(ux@U6}|^qoztVA6fdRq^VvC=!Hm<NTlmNQCR@T{Ooy75J{&dsnZu^|i!oot_mMMee+eEg4==nq)TnLc4+va*&(buLHWZ2=*`r9u+yOt$(pGZ|kJ?sgZBfNbzoLT$AGr18r+w`e?+y}JyLLSkmVQMP_)eVEVe>}2HrIeaw;l>ObHW*Kc@#WOn4a9UFZT=n8G+<E>-n`DX^JNgts$5%Hv`>$b4Ds`#-AQ59ng0n)7QTK0!BEvbp'},
 'single': {'box': (269, 245, 450, 272),
            'shape': (27, 181),
            'data': 'c-qC$v2NQi5C-5QSb&|v7cj&=h6@<ttK<=yO+krDg$Ip#gXA^3g@Ff+dV_$528}txLl~IlU&=-IY`q(J!yWPAj_5=2`R`-Gm)jdkg2dCUq^*iFN^}y3p=)g1kp=xw3~r-=x7cKLz%d9!#dg3RCuE7Z#M(fUE-i-y7z|+3_xAY|xuN!x$Ywdll-i0CZJ~#~^wN`NI63~D1F0a!<RVoisqHVp?DS*N@r|7q@0s9bZeQp=>@pF;9Uf~lb_&6qGs}q<@QSYAIbYGh8&!?6C_S5dO#SJK27b}me?=l0=P^4o6m)0tJE#XST|B9!GUwnLYDm0YUdeIgh@#nYJBay;ewv(Ix^qDv-=}?Yx*|j5@^`LlQ!0xGr)R{HNiOqLb`+5b=`OSyBbI`;Rg1NbD_TUGEee`>-E^|>I&HqG4$teX?E5_=eEGv%Z^r*_r~>_$_yZKh@45'},
 'multi': {'box': (245, 305, 413, 332),
           'shape': (27, 168),
           'data': 'c-pnlF>b>!3<XdJ9yIC#MRko#(X}$TrGO3@eFPn)E;?k)5keqCMr$Zg6_E8q*@|1BV^L1T14)o<nm<K5>>f53r}6H(O)zX&VNii~?bR844s?hVDQU2Z$SnlH=o1n_P=5gxsh^MmFO|~|lmfb=f@`v7Iw1i#JJwiHvPjwf!eFzNK?@EQ*=Ai)f1_EEz-^`=*@s165o=|z(uPp5$D1oF&1mp4SB?wLE5WXKshH+r%ghlhIL(5yoC*JmtDxd1#QQ@=?{Ne_7fhwU{PW~B4&Y94m&%iK!Q*2qck)&Z`+d}GW4Z4i;sys9EP('},
 'character_title': {'box': (154, 64, 536, 99),
                     'shape': (35, 382),
                     'data': 'c-qyJv5pfl5QfKCV(HvaP+@qBtKwJTLC|`o6xSf-5#UYmDbl4Q5>MdhifiW-3QLSU{NqhdLWmx6zU(SHp85RGKTGt_e_Z+dvn-S9ZKbG6iG%7wq#TN`9zQ7KN1D{BK8>~2hRC>3R`JS7JK-@W3QH7Ht)vCdkn=EBP)6iTNPvwM--N71Xr|0wwM@Er?UqyZv-YGX)M?0R!3Rr-t$TLOX*IgofhyTn&)UF_uz`=8o#7+O@PjT!myPP_y3Q4)`idXVs3yQUbi+?G0-O8EzURj){?WCM1Xc&^?uBr{wFzygiRVzmvBa8}h(F75Lym3vN}fF^pbk%4rZzo5)VQQXne6m4A%{TQV#{`ySI9u?t*>!c5`tv5(l|Z7n?JKX#+nVvGK_0F=rTtV-~6cst63)i0IpHqv8gZb4ITfU(O>P3XWwFtw>6Q~4CPxWISIr*4fSCOI|Wz>ZEE4Jnfh}?>#QcEPf-8aJf`WuM>+)7G*yV}Te5oAJnQQNM8BxtuK3mfB$l{fSEzz|hCkZr%sg$F=kz=N#M#V~w!GpaZ9p$GiroEy-zQj4KxO{C;={U)62hQV91U3UP5r6b^L<C2?W#U@3512n7xg#v?xOyOL~(10p(iNni>vza)5Sc-EyQ+l;y^HiWy=!`F0s6&i+MIT{>0`qGfx{yV4m=RjW9CIgDRY<ujZMlalHNEO?{!jxr`&!yel3mNE%g253r8wNbAq%b<AvdKspSB#PB|(W^t0fs~u#hf2h+@+ZZ#94Q_@5O*i1fE_?P*xI^SnUork)$LOv@Yl97ZvU9rDDeX!)R0j{Wp}uTr*2`NWTBG~u0DKDX<HU2K6c^8UWeoE$22=SNAI2E?9!8_ED-IJW9i2-Z>cbiPIz8%wNNmM&O3)wi-ClXGiN26KReD3I(o6XDp8o&OFTv@Kz5'},
 'slot_a': {'box': (174, 149, 294, 180),
            'shape': (31, 120),
            'data': 'c-p1W!HvWq3<c1SJQBy0KqsNGQP@t>3Z+m2M;{P>?If%;(%yy>&j<W%fG<vNFCY+w6|tj?1VmP{VN-A#6Pq(>Akz;r`^B-S&OAhmu~5s+o}6NJ>vBkkabN`F@lf%;xXUz#hwm(`7mu5PYV6pZ7LenEd44eRk6~tj=X%Nl+cf9uYn0}^Q;D%VXIRvHR+P9%o<5yA`{v_QZ5zhe;?49>e09`~)uO~I$aYsDE(UDXmp}ghlV1k+r}_'},
 'main_character': {'box': (25, 197, 183, 218),
                    'shape': (21, 158),
                    'data': 'c-pnlF-pWh6oBEUflW743t@8wVVf+09q=SMLV|@6g#<=SBi0teTtg7tNQ&+B0tyoXPPdtmA`^C)r=CIl5AYQ~z`vL3e8nM8q$x@r(t|5XuWMva{DJcp{n`~cBTzw`ms9pd!pen}#X?!wTr*<i_!wO*jazCd0}VLXc&cuS;p4J1+T-O_?cpx!U2ud|hWBGh=r4ys_iR$%t(DE*AYwlpvv}9Hb!bq`7=c8gp&xN2s@qh#OgYWD9&2y=Zuc9yZp7SdXSJa7t|U`_{$!Y1q!SsGjo3sW{*?Px7QxA@jk%BsK16T^;BiO+jv)d1=Xc-iQ;xp'},
 'temp_characters': {'box': (245, 196, 403, 217),
                     'shape': (21, 158),
                     'data': 'c-qB}v2KDu7=ZsP3AePcVnWqNpmD*)dli|wHEgB}hjCzY?m*I4=;&Y~$iQO4BNRj8h}XD4IPVwx3{Cnyz?bg>_*2;VlCv;yyi(C+i~Rd20I?XN)}~P=hbCT;7bP@u*2VThADKc<^XQ20Az39|?fAA^PcxAiHhpeDH!rwLLtcI0Qw}cwtOQuBP^c4JS90+Pp5jpn^OAMKq6S<4C|`?6ttDgy>J9vOfG>Hw*R2PO-gWI4IXka1+f`ea#}nD>4yQzG(#^z33*o7GUpEf=6}taDGJ!TQ3gLga0n$}$8v'},
 'empty_first': {'box': (28, 220, 122, 245),
                 'shape': (25, 94),
                 'data': 'c-obZF-k*G5Jm4eFyG=4El2n!S;B)r_#uKWWyB)wPiGNuLfS0BMYw<z^RY;i1*8nP0l~&1M4zreZ+*C&1N>{62EY+E_!PAH1U^zc9cqegjr3SS@m_J$AlnU$qo2aC^ga27FGdu?Y=SYp>?)k6YggLKLrxgx8BFYI9U0y|lTTt+@H6hUf;U?4xZu-J-pKS9|MH@si}K#R3i<qS|FLowRiSRV`jKg@RS~KBEk>P(Y0~=EaY{^nmrF^hx%_MPH`JdwbN'},
 'player_one': {'box': (146, 443, 534, 468),
                'shape': (25, 388),
                'data': 'c-qyIy^h;349BVPAbAkti~?$$eQ%(ki-#f!(4ntkBQKC{nPTM(<dz%yI31O`NM53Yf_s3vn+GE)r6m2jqCkNz6+po<Y5qk1X@Gya*z;HBk00dE-b|Yx4jGvQ(dlbA^Xb?nC;E*i`g{DqZx+gH4q<{*U5?>U%zptyz~wc^GGzD}!1WF76v`kPFe910<d}s>2{2OT9IlbF6?1ec>tX{dblD2q%21ApjHcYtRj`G4dldFl3VrJO7v5Ptyq|7+h}-I(?4g6A8Mb!ctvsMI?3f-t$910`=z*M1Lsc|VJ7|U~BMTMO8&&Rotz3aBYo%Rws1Y{_h+c0$O8tg|9BuEFvLs5?M0xor3lAvh=1QX+P#d%!lM|)H#w-eOGPzqndJUWwsO`=J1a*?t&|202A`%hwsp(U31YuA2X=h1;0!8;S?gL;F09C|}1eksy4N$_;E*Ai)ggYY%KsgS$uso>M5@3C+O+F_8jJ(rw$#z~tJ5X>2B<fZ|0H7hjxQ_6~SHRAI*#{~Q==N8@c+K1epnL^No8t91z;+{x=G-DO;{hs9coYDop>P85q0(BF9>DXmNpjMF=h+j_17L6L+ucQjgfv)~@nMf_HxdM>M4zsE5N$OeGo&NNox&~vrT|AZIz@Pl-6TE$wT9Vb=BU>R4csf{1kG5c*HlXwQ3tpN@eYPr4sLm#{NJtiFMr_y{5R_>sdu<c'},
 'player_one_number': {'box': (380, 443, 393, 467),
                       'shape': (24, 13),
                       'data': 'c-muN00J4t2mA~Y3<ua43>X`D7!sJ_90n)=0Aw}<ng'},
 'create_question': {'box': (463, 174, 630, 246),
                     'shape': (72, 167),
                     'data': 'c-q~R!EVzq7{~vPBc}(e$<dRdrM!Ww9S9fF6VKsl5*!IPkYI6^spBve9$?}%xFLt4j?-R%i^~qXAdzDa(~8$N9XTT;geAw(FaExK{{L+Qf6~ZF<em|T-k}j_tlTI;@8=n?)VNWB-N$P17kd4X@1Tp}S5)r@76mm3bhHnfm3D8QEN&A^ZWDv-v^ffz;<S1AHJ?rUE~_-SdPgqfJdN|`@9PP72~BNC6$e}@Db+Vixey>_sXa)}iBYQlXdVkW0QIOVKnW4*vMzsCH&VGW8H0eyniZ*5^aB$k<I3%ENTL;G9zzfdS(kutc@>3W+~?@0a$I?C@ls;+glH~YNSv#gO9z!3)MsQOav@}DufMFzd<I+ydj81D*h;;6+e?7v2;^o!o6NjUHp;r0qnCH$VlC}|*8*p&ZU$ZlW)`bzdB{6Z8B+Jt3(<kKrd}$iU10*}Vm>}M9e4!JSF<<zcSe6e?0sje&O|OC4-kCnKp~-?B1}6_DwsKs^9~#vQcly<c3|Pk4DEx?&+!WIgMZ45uzm6GRNPiuoV3EYo@_)VvtBEV>%$GCwDm@=o!Mma4xorOA(}ph$8AtiEsM}*!7>XhYlE()X(Q}4(bs)!Qz=r3p;7fQr4xaz(wZ_XG?_S?eMz<zX~yYigxuL2k7#?Ta8aD$RzM_6?QbAMG@SLQFWq4!*sg<ngF_bao`O=ly~z1!&IckgFvj2Q1W}%)BdO|A??ga6uHr@y7nhV=M(v%L9J6GBqF&N^IiOqEh8PO{H?8~yFH*QX'},
 'create_yes': {'box': (588, 254, 627, 277),
                'shape': (23, 39),
                'data': 'c-muNKn6?<?LX|;ndLwH<Kr`6?&FbgV3Uz4XyB2MKinX}Am7el!(hkXV8dX+|3i);LH>gr!+`<@KE{RzJUq;d2V^AJm>Vn%c-R>#9!T&rR39+l|549?1_0kS72E'},
 'create_no': {'box': (588, 279, 624, 302),
               'shape': (23, 36),
               'data': 'c-muNfCA=5<_`=O62%S7jXe?!HUb9@FdvlQVX%{INMJ6MU}G=_F)U}WF&NGSGGu44Fc|!7aA4+_;bAbSIM~3<-e<vJU{Mb=iSYmfCIA3+juTJ'},
 'calendar_question': {'box': (56, 219, 597, 244),
                       'shape': (25, 541),
                       'data': 'c-rk$v2NT(5Pi!fmMj(|)h(clNkfIptPvof5FjETK;N;<6>d_T;YNj!Tjqq5i$m&E(Ql|ou@?qZV<5k9=llQ#Hw-`=Jv^PQ+DMZk3y`}z9PYe%^Jann<gj1-hlH+a3Sl1iJj$L9VvmzgkLQi6)RHHSy-)Y)jE*f8O@<%#s<iu)4*~W=kM?9dv%x+V8?DhHDlOz|`iVmw3~nFi@Yy_}apOzn*vH!Yl%JBWF<p%x;U4z_#hB0`uO~D@>;t&RSfh_PfP_%&H*=Z5?T{o_NT5AGuo$?*3+{%5sax<q1>2q3j(7>I>%MkB1x!(bmq%3_d%Z5?hq!gixW)RWb&kj}I|TjQ^6u=WTi@RINVh%Whh4m()CLi6hoBo`2N$<}>UL=>@aosH@pWy5G>w4NO{5^W#52AUzMSO-O3fgp+FA~&^xwazaz&N^<qf-!@~xfmt48SOO9?d<TBBSV<DhA^$+ga2v5H8jER1Q$1!ldJ=E66mhKcaCRGY>RaNO&oN*aSEQI+NLTQ0z=$_jc_T*;8Q6X2fEhG>tZo_abXsK_<5n|q-%jeoXw6;3&Xw(lrX*`{{{oP-zmGE~+S$c!d&yd0=xyqyl}sNyXZ@wJt~?(CuB;D1TqoGXQ6Ul5o&w!;YAFgtgq_>+5J3zCPcZaXT(e35qUT{yoc&8$$IJq)W*;n}4*@f4N4%f2Bn;g2K(&N+NO;?GE&p^_kS3sTyJublABh0G{H<1s5?3WpChQwi0BSL`j7{G7<7IuLnk#6ODD6b3r`ftrSE(?Fkix+L|VAfXcoCxVGm>t&)bkrNWf&uTr^!8wk?y7gP(Q>z8UF(*L!XhDjs)XPOk7L{22+>T9@o3fdZIIx-35oA&e5=S5r@<@nDp)&%dLFAT}tyj6;6922bK%~lRR!6zB7B%aSw~HQv^<T9x*OOC+NxDH1Z}QXkqc}EmU{=%}g1a}{#hp3t-~0ibE`HB~_PeD|TqS`ULK3kK+#DX2@e*jSsE@u!yGz0leBFY*7t}&=MV<>U-tGv07q5}h{gIi^_fY&V@3C>r@c#fl0!FJ04F'},
 'calendar_warning': {'box': (56, 125, 530, 149),
                      'shape': (24, 474),
                      'data': 'c-qaBKW^JF6vjV_hU9^W+>L`^JLm-%WT=4#m4RM_Mu2v8Q547!z!Y3K9o%H?&_nb99q0;ZJLC`yd;y`83K&wKWGa7#E?HVm<OAR1`}q4v;C~(czr+{IdkYC<rkQ92J|qxE4>Ja`+da2;(GVDGU&HJ}9L(4UslBk<E!16<8T6&Ep?%EW&bm#^S7q7yURZ;NzDC!Ux}9~yb+z;<cSBahz&Up{qTdy_h+Q$V1-M(V9a1~`8XJsIKKtm($W?N>mmuY)8o4SekZyLVWz{0zAu8**tih|4s>Q`ceNj@mMZ7H*%Q9U_)rq}%FLf>;R8IFR5|tZ%soYpuY%ax&#2#KAt`G^ewQe%Y8C!|H*jlJrC=WBkdrA|Pus7G(e3-~YVtmT!1ld3BTg$S(bV^8#sa|=qJdu0}%5sTp$Y!4<ls*VTy0MA9CbEJ2rWB?jSAz2akv%fr2S2KauBAj0RV~@q6){RpRvT36xFNezS34+Xt~u&8krmea;K)UvVoKsSwk7+-QrjnbJO|#bg>A&HpBnU_k6{%fve_5!1EG0<H`GI-(TXK-*;+R4P&2N)STIOoRi8{U)#sipm#~yi$I8~mS(EcB45$$yZ^gokMI(0DnLZEIY$*m9=V2@MWsh<)V>V>2!O=x4cGZVen>B}BiC)N!7pu0HC$pC9wjnDA+dbKdMZOkqTd_ozCzCC#Y{(ir_hLtzIws$+a%3mq-+QUW;;M|}IiBC}xWJIaE)43ZuqrB2bEZ|&9y<+~dogun;}d4-b<ROHj_`{$HvS3Yz`qTG$RI{Z5C4qYgFzBJ`s)}z{?`fr>7VxpYb4u!'},
 'calendar_yes': {'box': (326, 442, 362, 466),
                  'shape': (24, 36),
                  'data': 'c-muNKmkk)3<r|`$+xf>F!v-JVlYUSP+(#)Y+^8A+@QeRAkWMo!|=fVzy}uQKa33y3Jg3fKn)2F3QTM~ObiA<1~VHEGlRtg2m6D67#JMbQ4I$G0X7mc'},
 'calendar_no': {'box': (328, 467, 361, 490),
                 'shape': (23, 33),
                 'data': 'c-muNfB-fo_6N+3?LQbF9G7AEkj~CfW88Sa&a&Zwe9wUb-eU<CY{dpL%+@pb80X(%XE^?hxgqg$V}rrZg9jvR3Lo(B$v<FYW`Dqd4gi7L8!G'}}


# Observed split-screen P1 menus and static HUD labels only.
_TEXT.update({'start_item': {'box': (40, 114, 121, 131),
                'shape': (17, 81),
                'data': 'c${NkfB_B=!GC~(L4gI#`oO>-!6X1=F-b5m@Gyd;8QB;Z*cjTF8ILeDvoSU^xHljE&*0eK{BVY1vtdtzVoS2X4S_}u7YF+Th7B1U4u6sq_!uf0Y*-ZP3<Y=?{y4}n2^es6Fflw*;AP|x;BjGQP?TUh(86;_iJ?KTCt1O{`Jf<!1OMTN9SR44E@5D1NMJw$0Bjl};{'},
 'start_customize': {'box': (38, 133, 124, 151),
                     'shape': (18, 86),
                     'data': 'c${NkfCG65#RSA>7#J9V6bAzXn*;*`3q(Qyih;m^f#Jc20?PwT%*+e|?S~IP{Lk^vj)TF;kVWE1nu0-(0wc!(0Y|}(hBku(EQ${tSzMG@<PS3lG#_LU6zDLhXJK$+Y!PsAQfzFHNaSD>U>4+PVPhz6NtAHtaZ$41ZTKVKe(>-^fsQ|R3<rc5n1N1E079$)07C^Mzy'},
 'start_status': {'box': (54, 153, 111, 170),
                  'shape': (17, 57),
                  'data': 'c$|}G00YSbV2UHLfuVtcfra4!LjnT>6GK6T4FelvgGG%EBWFW_gffpni-Q~wV~a!*17jQeVHU#&436xHZ2}e?3QYoyJS;2*juH-SO3W4sJqGTQ3_oP*`0V)`3|IshSQr`5001V(6l?'},
 'start_options': {'box': (47, 172, 114, 189),
                   'shape': (17, 67),
                   'data': 'c${PYzyJZy7?{AcKmtPoh-Twq-~kIXv>$xL&wucNfWR3G=fpE<OiU8TIF1=~FgQ3#929U7Y~bK<lu+Vml4E4#P-bxyaCl&l$dk~a#KFQOVb~+s!^qH3&z{&M&7rt~{lE_y#|JDj3=9$s*Z}|^LK@='},
 'start_quit': {'box': (38, 191, 124, 208),
                'shape': (17, 86),
                'data': 'c${NDz`(%3-vA^S3>z3&7?MFOh9(9E0cI8ui;ahY;Q$YVfC5lNfW`Sh0^^7O%?BLZ1o;>nSPmC)HZpR!2(Za9cAQCKVNn!t;IQCR66_HaXmMmvQ25c|{=xl_APYl7Uy`DHW4nZl05g+eM@s^;jIw|On?#$EU<dz)KaLIZhktZ9Kag|$$j%_g{z#FXfe-)yGd?5m'},
 'quit_question': {'box': (180, 75, 347, 119),
                   'shape': (44, 167),
                   'data': 'c$}q^v5Ffp5Qcx94(%4g>+57#ybgH*EiSUf5j)L2hs*}2wYefG0@h|t+?b@jA`hcIhrPy-Hl+{0z=kv?EOus{#^)}aU<CRH&3u{}0nb|3faw7jPsBao41_q<_!7)INO>wYCuX74si=G)u=w)|6R=ufYbSv2WOm?qJ<E0o>X~=QD@xMmDg-v$MS|q<p>^A$8+I(T0?YDH!>ok5PYgKL(r9olw86;Acy5S~-Kis{d~0yPht%H?AJ_2_Qym<ugQ~nb5Z{eSkC?HAhj6rf*<k*3B`2_63V0i{Qa2>VRkpmOl9-a-P!)5%ByqZ3D0-;Nz9?M(%KeelL)@;q|1gQ!^uMb6@X=wmsLgAztq2@kx{v44%Hk@c)J>Tv@NY|-&z|;R|GXCd-)fqw&cy*)axT6no1AIvGuh@$<WwAPTAl^oR2X8{evxzqB@sm(ITVY^QRmIOY6cB-ayPOpS8)cRhCf&diWe_fVcAlr9I~B#^8}}0X^ZFJ%8f4(GM-3D?5tGY9%5?O65)j~(T?))S_eCb6%7O;DcxX0dA!<?EBM5951!w#20bdha^&htVTKUxK3v036GIIRWms4murZ28G<_O0B;hnC%+Z>a%@=WF%*YiLgfKbWHPa1-@Aycrh}H1yzRjxUi~I#>aH4b'},
 'quit_yes': {'box': (427, 133, 468, 154),
              'shape': (21, 41),
              'data': 'c$`JSAr6B;5J1sCEP;v*MXn%$Bj6Emly$YOM~p&osNHapIRXbjR1w~TTjlz571{ZaH-71RFvc!xpfYU`TbyEZGGcEXt;g{yA(f6H7D5;W^+7b&o@L4x!~0x$`~fO#7PS'},
 'quit_no': {'box': (431, 157, 466, 178),
             'shape': (21, 35),
             'data': 'c${Nk0D}(<783Oh?94m{3?Gu28RU2p5||&(U}MNJW;noeEJ1>C#u;V?!<h{UY}N)m42PdFHb~SQNML5~;bBPl*xbOwC-Z=@@!$`jNh}O-001I@7O4'},
 'after_title': {'box': (100, 72, 590, 100),
                 'shape': (28, 490),
                 'data': 'c%0o-JB}ka6nq2+rlaA;#(=zn!wKkaAH_$Qum{^1av=i>b%W7OYzhkGtbGETf&xXxQ0TxEmgwiAJPY5zfX$!*R=*GHRgpyh%_TBDill%1{JmJnQu&o^>?qJzRNLQ(kB<F9GJj3jbU)Cy0Qi^goA#Tj4=-xwLL9j;J6(0iBm?h~5mhCp7t2wxra@)f!gcL=%LfjEv(ENY<%K-3o+rht+@Ys0g9<E)R*1`z_sPhrIN7Xt!)Km36IVdl_Z)g)Z#?fgFFH`}*@)C9FZX=mD!7(bi>s;<iC1p@dMn;U?I)C+P7S-%rC%i)^yUx-J=k=q#WTJ5P9&c^@<pv&Jx&>{py%ZEDUym~HZnS-<tKVj@q&Z?rivTyERj*0Fqpxp_&JSQBtuFh703*BUowegoeEiZVy=$vMfxzPPv;$L#6{91lToh-=!T9kydWZU`k-Icl>rnviR9!&jyI%eAj@gU{xk&$DkCwk&bvHngOM0OPligr+V2)Wadb2vi>5j1@8&2Wx8l+{Tjsccbf%tD$$pUsj6?+w1%uNm=Z{+`t<iD;=`1Ig;T-6==*{|fSNyh>)?A#k{OOWQ<H&1{dR0be+T>-_JvwNdVET!kWFpV2({W~J&#(hYUaVeo8pj)HK0^M4{_CGH`9>NiX{0Y49;txzk;}-_`pV@-dffoaH`1Jag`$Ao{+!@knwf5-U7sEZQx1b?W9RfT5J-2T)#^2$8tDOY1|v>fp06{M4r3duD{7<jJ+{YWEFV@d*A}HElx8++&!yadQ93s01$iQO4jr_Wr(K1R`DIXRz9hEd45fE-GCdzc26q|Xl`b8i?e=eb6FGVKqvReOdw#{Kmcbs5*LQnwP|JBfTr)_Qr+aECm-89+*1T_C%3Pg}3EIHk1s*~#DD9U{oSJ>NA~UXu=Ld<qdJf%ifzpE0jkH~~fWHNUv=ir0E#ppW-h}6@U*$O<qA7jA6cM9eoojb2-$+YFg-616kXss)l@JMW`)Eeg`j`;Wl)k_^umjQE`>S+Y<{e01o+}&fKq&n4e)a#t8~Hz7e*yA|QM3'},
 'after_mode': {'box': (278, 216, 474, 239),
                'shape': (23, 196),
                'data': 'c$~G7KTE?v7{)K$kfr8z?2wYL;CRx)4Stb;gKNY=g^;9E79p!c(XZg>)`WstO705?JqYM#uVm<zo_Rh0%x-<&`N#7<&qK(eMRmwxaAAQYrSc}mN~#1D%Cx4rRF^&1pcBZ237}9|^w5W_hn%<4!CdLMb2dACG?;DPX(9Dh#)yBMLfw!cc<|eXctq<DsH3xzW^QDRbawl4=_?{#oT>gAxMHj=gwO##A63G5B;D13QHL~d7#f`7J~JMc7MQDg3%q187AQgsK)JR+G{(C$!i+9f2Cc(tKYjHjQENKai*2FFgrmTQjBqxxFS)%MZ<hh@&_PTttb;iH&QPW=^l4IUkgMQx`gSXf-~EKPEsdR}2d!=CesDg-syRtOrgHGx;*f;){!|`(w14#l&q%#1'},
 'after_characters': {'box': (250, 278, 482, 301),
                      'shape': (23, 232),
                      'data': 'c$~G-KW@S>6b5idsp<vAJpdx@4d@mmB%g(;W77>J1VNR`R&G%B7#*S#%R@G}0D~h2kG!ahD_K130PP9#CQCp0&-a;-R^}!QMNwD|REP|CF%4jj78l_0J)}ZaM-Fi<gqg#PT68F_#|@<d_Q-+PLK+S;X8lfW{!qX5$?(Nt;&8}%q}G{7wqzrtNuMMSQszne9FgcBF&fzeTdQ$^a>(JSN21sr3s=MomR$~I*P*#Qh+$lB5A6HiV?GBwV=--zHuy!7K$gcb;D^8Sr|2{}9hRCpd=%Sbn&PVCu+p7#6#gsqa;;oWhZ9`oQLL2SH5ldtxyQ9{Xv5OU>(buFR%v^#&kRK68e)~$(R8qo#^c^x%g@L-{0s}fyd!}kG;8ORTb>i}Zn(z'},
 'after_quit': {'box': (246, 335, 379, 361),
                'shape': (26, 133),
                'data': 'c$}3`F-`+95Zu!hu8@C#KZ4>X@c>X(QHqp)LVm&>x`L7?#HSQ#7g59!8xQLcXi?VkS~I(2kC*7y=+&*>1`v-SKZk^o%hEH{fzW55I_%{M$XvZz9fh%71Lz?<D+3dt(fEiB($N6#FymBvs4Y`E>+*P%u>Hi|2*k;5DcrT{VEb$h6JCoy;wRn@sG<6iueinm0$FxfjE^(ywYB(PV$)1$pqMUDDYhe*KgHbAiyPeq?V3Vyk_CnK#cC37=F&=tA>qrM<fvXAJaxDyqy?%?>+a_H{uAFF0ONQ'},
 'hud_p1': {'box': (58, 56, 82, 85),
            'shape': (29, 24),
            'data': 'c${NkKmdv44-!cdGRYG1k3UE}267oBk{BeM7{~wsy^sdc'},
 'hud_p2': {'box': (58, 291, 82, 318),
            'shape': (27, 24),
            'data': 'c${NkKmY;f4-&}|KqUWIK>jh1%^;BkLYRR6@CSBg2__H{U}FBj#LNIe3``6F(bWn0'}})


# Separately observed 960x540 capture layout; compact game-label masks only.
_TEXT.update({'w_main_title': {'box': (339, 293, 670, 324),
                  'shape': (31, 331),
                  'data': 'c${riF>fP96n@Jb*&s|N#T7nj&qFF&N7rnG@#u6F6@MX7itErGAkHTl?--+OgKQmDio1lLKuJNdVNtdTaZ8t3trRy`jAaQX%G^HQ+DIUWk-eJv_S-k}zIopR_;)Zz4+D2cunve680x!3rq%$jA|n1z$Y>ql24b{#iGKZv5h;v^TA=pO3dEXCaYa?{ikL39qBWvLbaBPe0WOEGG4PkiMXX7Zri^~a;5#o%AEr{pgjar@fR_f$KodL)xzSji^tqypzbSN+vonh0X;Z@;e}sxD-G}&WNQrZfiH*}r8XS!h<R}~$J|@62V|vgVNRZW2`qV4XA+JR4q-z&w;}Z3Jj!qLNWQy}#i=nG8qapF~01G>xU>?SpxEOgL@dA9l(G8)n#=qj7TA@VXcVQrd_Kmw1%Hjk~k?f&@gLFEBdmjhhiJjHN=1iJ|CFK#vx0w=rj#Us62KT}}Ize)%o==*80S6|o2irPwk&e+Auc#yz=OQ1_UQ7zN{U-Wgv5<?*!ef(tE8HjJ7Q|Hm9hsvGADfwiZT&3AUmuRWLI3H@m8wCyKB@TbnE}j{pU_n$n{{=)6SSBP59jG;)9=mA4{a|Q!6vZlP^P|(AVNXuygMS1pNz&`-uOCv|7F=~eO1A(+xLLkoMS4tpe0I5XQ!e&+l<PxEXFx}u{T>>o~9e}va^F#v!GHcQkIdF*^#{HfVb7II&Sw5y>;%~i<buSo9Tr_7JP}eA3`slpp9~zrm%A^%hMy0@&->&9<`uZ-o8#y9gc~Usg@uqTg}<+E0QvK^-(83R41}rOb-+b;_@d0jc56AZbO!ll%tF=1xZ+>+0SpH2bT@^qH05SW&dme8;AX_Oj3h6YExcW4eeR0-;rX>_RdbnvV<^pBGWL(5l(v2NsG4Ai(Nnx6qw}M+;qc7i{zJm?pxmupd*aPva^a;T=NNGRF##`J=+&7|LyY+XU86?YrS*>NIm+%CwK9Z3P!^|H(najEV84laR}`nKaGzqoX4mtW_>J`u#tMtL1TzRC&u@KE&0HfziXfD7bBVSio7aUcI5O258tj<Lo9A<d(xCrWw;<Kd#hJe9As;W{&Ho6?RKsEPh*G`HLMji-TbFbty+@5-i2z6XtVW3<SqGs10}jG4*'},
 'w_online': {'box': (413, 347, 551, 369),
              'shape': (22, 138),
              'data': 'c$|$;ISv9b3>=e)O|d{kMX}=eLCP&xqU90r14_!2Jj+kv30qP!b|h$Vk&LbJ*dFZQam2O(uuzyjku9r0>hO#4Xs^C7wd&CGSs;(dq6Dc6UXM#e>Il}NY6X!hAbIL)apecDn1tZ=>b>KD)Ml2^HKb=_G}K49#<>6|13?-yzqy_oRCQ+DqlP(Rqhq1=%2q14NJZwp6WP>VlX&&aBjL;|2iL7W7-a_hKADrdGYnq`LMCa+wqUODq^zac)>ZrNZWI2953hqBN&'},
 'w_offline': {'box': (409, 382, 560, 406),
               'shape': (24, 151),
               'data': 'c$}3{u}*|Q6r5!*Ktb5O?h;W*`~mDJE`reyf%^hV3v;ZwM6A5l!Vj@r#oBLJV_|2oqabh(>T8^2XY*#?&TQTSM<C!5b2D!<+;mJe(_+AuspvN(ML;rG4q#c3{?wWKL{guDJ@b4WNUF3)RH%T=xV}vy4nCXyAc3QWYRk-q9iS3_pNO4t7c!IWdIXo)hTkuU#Ne-)zIQsrJr<~6k>M^$u9bxnMF+5bOMYEh)^wbsp^Arw^wwyfvNWp=B0JTjf4wOWk}JMfY13CKXJgY~g=hq~-Ky>?Y9E^i#JCz@Lylo<GYz4D2z1v+@st>FjT6eeS(3kpcdt-z6wWEr-9TbN1+a7$#7(~Xm<Kqm4NeVpS{IMg!zY<$L}u-=PxuE8i&|MW'},
 'w_options': {'box': (428, 420, 535, 442),
               'shape': (22, 107),
               'data': 'c$|%nv2DXJ6ht3Q!6X7jB9MlKpvW7zR4F4(Mo39yfPkf|fVLLNC=9d+N8kV{LMjX7fV=+>_kn-h#Sd4M1DSD#2?W?Gb(1W}J3G$!%-6Y`BEyk(WH@%kOr9v#n~az5aOk^^&G_rg{KQL&*!S*Pp>X=cBDL63A~oW1g$wiNzzC=8&?nWeK?a(!g=R|G2N$`?H4+9r+Sa1+4kLryL@4DRbou_uo1ek_HHJ=A4OL3Klwp=Vh=m8pyXh+f|HUsTtts#'},
 'w_website': {'box': (429, 454, 534, 477),
               'shape': (23, 105),
               'data': 'c${^QF>b;@5JlfI$h(CFE?ppHa|7ro5HhK93>P_oOUeOqAdWEHWRE~emy97&NReO7)BiL37yfEN&mOU0WXE0w9|zh_e?xUPQM9dD!=&khO^B86(x-tEOis*T>Gsf--9;lLw;iR_D`o2Tf{k3Ow!?QFx9mg81jN&G-SF9fiA5Eg@s=Qm@^v{JBd^mJZ8%e~lQzfk_PbZ~8mYr?fA~X7ckjw$tskhKe;PfBjZ?UdSn7v=<9~evW=1O<'},
 'w_mode_title': {'box': (300, 54, 665, 86),
                  'shape': (32, 365),
                  'data': 'c%03YF>)I*3`N1PV96t}$pzA-5-z4$t|x^`9U(_CJuX!03iPN@%N-Y{Ck%f+)=th4$;D~`0-p~b7WrR3c}?hF#Q`Ob0Psx}t-i}pbjkdt=1?4}NW=qhYmxwmrWkxvJXWn~18V4gc(jC)Fj;a&Agu!QglES2BxyJZ&V16!FAA^%jfHwfA3_OFJjHlqc~puT3^+FQK)_^zmAnBL3dKwqY``}yV9hn(>?S>Ss^bMrW2l*WR4fONjIUup7E1Lnp}Df9zU+-z(zPM3NhlI)7Bxi8ztz+e<%vg_spz>N7TNQv#8nO=i);Mp+ZRbmSc~!`b!D}&xPBySo?yA7e5Uaj=}0H`X!7jPsrXw9&vl=S>*Dw77UZ$c5|^qyZ+r?!W0CZ8)g&gXkQd8kyfEkqwB)j=!=12)Xt%kI;rje$b1WGYMxtllg2$GCP)CFkHphKI5`VAZVuny7f2y218;bB))2^htPhpKS_by50V1^N@AbEq$hDIkn;HfK1JTf5p7cNEKyQ5(WJ<?!;Ka67c9C60$NRPiehvDCFI7qmbc;=jl<g`sf%$eE^N2tp4b>M13lfDzovdGBE0M5U#L;Ym0CtBz}7vuRG*K_f&EtpIa+uA4WB;RGRYYwxJzV5K^<9Og)KVXNF&X&jOGJNyaA>8aD_-Q;3dVA@vGsL58JN9x^5t^>Nr?LzXFT(-^kz!TOm59a7WX`5t$?;ANeB+5?EPC0UeSYuxzAM|eZ<@2QnX|cn)z;@)<87O2&R+CPPychaB{7xD_k%$~V9p|%P8&NkzYV&8J8Nre^9z<bGiZxy-pib*8$%;uuPNTR==1>pXw&__LB=cl=rq{Q+!)AVF`<1)Yn~q5IZi!tnaw(ECH#3b`wA_T!oz-zr+O6g^BPIuzxn(D8OwaB'},
 'w_single': {'box': (409, 224, 584, 253),
              'shape': (29, 175),
              'data': 'c$~eFF>c&I3`HpnV3pIRFf><4N&}PSVSEHPT41r7z=ccQVD};hG7A;zq8k_^s8DGNTV#w(^gV0Co!f*2NRSQR|0Mc1QHER!`54W6W4R4h$7?d6s83M%fkas5P;;uOS&PUm9?&5woQEKYk&sGh7#cmK>?Y&Kmr)9cmUYhtExdM`PhB_#708T##cWKKZ@Q}K2d8}LiMv0csw<ljyhVGsDxG%J48NU~>)i!xi=#Ei3mA^ibQ8X0FqUa}ta(Gc7QhqT`EQ71mbs0xx6~vBJksoLA*7bpEFp_Xp~Q2ohNAb5in%gVh?1SqKMztKR7<4QFKc>#e#7POVywR4>O;-_Y4+troBcNKcN_jn3@h1^A*bJ^Ga^!h%(D%wam?vnmI-6tuhhglztgJ$gT|@LE{<7*@g3DVa^h5U_eHvRE}y;Zf5$6%%i0q'},
 'w_multi': {'box': (386, 282, 550, 311),
             'shape': (29, 164),
             'data': 'c$~e_J5Izf5C-6pf;6QsfaEK1f(=K38&E<MN1~wQ2sujJQF4Se6|Ex|WEE$AW(d0r7uc~BNAj0>I7AnTj^FyH#3-?AQX3IlA)Zj35FjqY>v};Z-6E0$5?%`qr~%}b6Pz((k57Z6K{hx*Lk#NXg__*C6?n(+74P&jd>~Qa1jDmFkC3zITV<_m8UMl<=5U0FTGyca58WB|dJHdDTShs<3Hf$|6)UQ@jMgn{kNAxrhy}T`(#vU>G3b!b$zZEP+SF?)D42Jg4w`z}u4ljV(i-Gpbh6#!<9#0@@^uq$9+L01O}WgUCi(_b^%H9'},
 'w_character_title': {'box': (292, 54, 667, 86),
                       'shape': (32, 375),
                       'data': 'c%02sF>V_%5S$AO0%@2sND+P`mH4d`!W|74D*XgMB{WpH^b<lsAE1yT3_#pwhOm<_SOO$)cgUTcodw>}$L-kc(%{XIYTO2}?D)>_mV;G%t?-@6lkH(Ih<0aot^Bve+Gd1DTRQq;Ia<S3vF*Vu+MaZ@d$Z??WV^R!)}c^anrAiUtt_@r?7r#9GWL*(8PRUW@{5_Tt_HDe&WaayFwdkjQzh^knfwx5q2f#28LQsd0kPfYTfVN*#z9Y3`*AhP2sev4<TMluKS^m!ER!YV;{iCrHMky2DC{)v2@#{a8cR&rTz5_R8gmjB9iDpCKoqc|tvD=yItk@<U4~;P%9n^u*rkEbh77P02J*nsT^k8u9QiJhGk@SL7L_3bu#hV8Owv7^Ys9`Z)&P;rlOH6NF_NsWP$kh~sKrxFr|vJEKq8q>uER9oAldtvFN+pKHHAXi!?~r|&L*8JYy=K1Q{o$;WF=ahL>V#jH=XJ_+mX&1@OYE`T-6fP0{wH>6JvP`RYhqad!h%i4YE3l?Wtml!`G6TYa3&*_{4Uc8oU=gbW-YKJ0~;?^TrzFIC|9XCP&{t(mJ~MCVPC9z3ax26hqOC`~R{Je0G;9dywqkrtIDE!A_%4_8@cmf3nlnXH8fAae|mU{h4m3um@0vJ<usp`2%R2a4KTL{^+DdQ)=<Kx(f$&T-X=k8<ET(`F7vtUeV3X9-CzM-5!cRGe932DgEBbaUN@U-K(46G{5YjsfCB?FO3dZI(ydMa{Jk^jk#CXIkYU<6+)!*&ox}DYuwjGvhzr|mYJ(feJQJCXNYc3U{mp>2wo^Vr%3Zhjh0MaG{8P(=W<f^f%uT)WA-(fWS0&3gyweDc603ug{P35Dn2!Qp?U}S96N#<`Y^Na=kph0R9J`'},
 'w_slot_a': {'box': (320, 135, 440, 166),
              'shape': (31, 120),
              'data': 'c$}5dy>SE~3<coF5D>~8(8<!um2uInJPzEIhf*kkkO1$qwCtVZBVhPu1o{DZXFYsNdMQxvK<SwSX&|x<faByuVjmWAIAuaOJY?}$Or%__M(I0tApb!0W~^B^W3dyADo-|JUM$(K8*y^WnpmBwIz`W_E<QwqSM^Wi@#3B<;yj;nk`<V*yhd5fi%rzo%9C~eQpS$Wx;Ao>-=uTIZhewpJe)mt8xHx&X^cJez(%T#!q`FwYoV5g4}^;L)))N&;n11%'},
 'w_main_character': {'box': (179, 181, 324, 201),
                      'shape': (20, 145),
                      'data': 'c$}?}v2KD;7)Gxl>FrW@fKqt{$J>CpY<-PB0*1jhA^sQ=SxmY**!T(^nHmU#8?4=cFff8~K;z~9)n{nG;pD96Bjo?)6Jpypxwo`(LdS;M#S7+~U|B9WUZk?qLhluH=JBe79S%5Z!}@!|GaZahOw-gq`u+Y;Y}ku5KRjvKRs3E;9koJN@M$mHEpd>S{E*G1I>NOppEJUs=!`R(ND1a=<UO%?e$oVf=E2HoL|t4~>X=%060#;~m@8-P(1+SFRN!qsD`9J<U!X!jhjeL1kC9`nACezVc@oGfzV#4#<uy(5|8UPQtC@6&'},
 'w_temp_characters': {'box': (390, 180, 539, 199),
                       'shape': (19, 149),
                       'data': 'c${NkAPX=)JmJvaAOU0@U|~G`@I(ze1ONT!^ZqmcZ06_x@WX!p`R_meFx36G`ToQHj6_X+`{6(T>h0e>U~X@GzT@DL#N&_W*hw%RW;|cSz+->@?>ipmf5!5UcO2l6KmPdxL*l>s_a74EKhF3sdyFCBUw!`pW`5@X^~?;v=Rg1P&w!bo`42yXM1lP81_?Hv{|3i@Hb@xoBv>#UesJ#&!*hf5pKbN$3J%_I-g$sc{#n`q=8w$<Z>-ts+4!Hy{9$0I2fCV{fq@A~{Sc^UV1Gbf5D*IhvrS*&'},
 'w_lyra_name': {'box': (179, 203, 255, 228),
                 'shape': (25, 76),
                 'data': 'c${NkzzrCIID?@<hVh31GvoXRJj@U3n;8rYn;8!jvoRPjwo6#Zu~{TAGsrw_ZhVl~#$dp3PC~+tO#&#yez3XOAh9jMfT2R7z?jXVo|%EU@gK86a{CSg1_PM`$?ZQ9n;DoH``9h)8zg{25()JU5{w|BHa-c*7O;@Pfnye6Rn0s+$!!uAKq1Qmj|+?&|1mK(&fu|Q`~Y;I0MMNccszju0HKsE_5'},
 'w_axis_name': {'box': (179, 252, 252, 277),
                 'shape': (25, 73),
                 'data': 'c${_4F%E(-6adg)niPj0AaVI72CneCF?p6IT%a!M1T`eOF*|q=#~Kq|I7D4^Wn^IR0`gAq0OlBAT8(w;CLko+Bw-J^MAA>*x>WQ?6|#?Atrp7@8D%z7i3eE8sc8M%vAD#}58AWnq&ImHEPQ2Pc^*n=jw6A;m9PsvvOxmok0RZzfv9Q|dLgXQ+}mrV0Atp}RLCh3S#~HRu(Rp^eqBy4iv'},
 'w_p1_prompt': {'box': (294, 414, 672, 439),
                 'shape': (25, 378),
                 'data': 'c%0Rfv2NQi5QcwR0;PeF-0g}Ak&V6py?F>41sVDp6#N1Xx^!yjD3F#Qa~?;oi*(6DFbL4D&Za?7daPZzMbN!HKm`9IDSiC!1pGHaFEaV+Fdy+FfG*x^BY)p%{Sa-7KQjeB)O&d>eB#%ci5~(vK5X}yF=%FYGKGJY*sI+)i>t$Sp9vwA+3R-4bU+34RJbf~8N~Kz6twSBCn`D$aRdjA)Z#dA=dV_69&J6GqN2~&ecob7-Kxts9n4+&P^Ie*im!&e=`NawK7APS#(DU%rc%x^YiP1bG%<Wl<|}OxKwLx3HdMCjhLoB);Q2}~B%Mj9X%(AI7$WLRsTLJ^_!2TSU&xHh%Tc73-g%{h8fzQCe5Th{K=j1??LA+ND<v%HgfK6#THS&H&xXjk6NhEKZ3e^c85z0zlPA9xSyn2q@kwKH@r|9w*hQ2p_E}=ul6PKIw{H?Y7XTl<N=kcvjX3i)C_)`bJhG{!Ra|&>9_3}UVHAcBtYoWVqZb%SUjr=^lM~lOnSkKoEfv<a%EQC3nvIAJ$I6liJgs#pwc-2ejnc-$lbO?7zorP2J9T;$NYWF1_Y;0`Gha09e3ebUCz|0=AFGHwytsinujmPn6~)Q9U7`)s^^mqbQa8k0;fQgk&jE(9Z_*Qp&b;r7+zr9HGnwzYHb%=6moRt6-NG2cv-=hY=D?KygapfM-)S#HxW6p?WAOur!ln)'},
 'w_p2_prompt': {'box': (294, 414, 672, 439),
                 'shape': (25, 378),
                 'data': 'c%0Rev2NQi6h$vBgVI1q?)HibmW}=Zy=e$)2O0Vs6#N4Tx^!yf$dHyIb3TWzi*(6HFbL4uMHdZ%(ns5cTNK?}0wi=P>hb8_2mCjK{@6)Yr{@7r0kqLkzn8zBEd3I;i{Ez^cz1J@^OfKD`OU;HfgGKVYn~&}tUSon_)_Ai4tLu1>A2q+LMn5R^1yCRs9bR>TpHLEVmBTH_D$kMMdKmHaH2+1;w-cIi<Qm7-5Fn`qD7Z&y3C?a+^WsCEzEuPSS6d5Il>*XroC<+yX3LY8t37QnhKd?*3e`dYhw7C%oo}*saQkJwp7^jhLoB);CZc=k}f3Fw2I7@;lr+wYFXtTyMP>;&tyi$%^*~lK(<mUsIe&nm{0Vw6c8OTzkL95PD+%dV?w^bs=5OdF8a{9xr51eO>fwFBSZHv|ISt-C|Rkj#s`hb^;dQtBNx(Gal#T)OWt`=-Mxxo5p%R&#RaZDB1(M*cBli1CpNVxBO|@@C~m?nrxtLvQnFQ%(Mt@Z&p->s<Ybx41OyLX(xP-$?GrVuW`mI;hA+v(pVzvO+VKDBN@?Ta$>j9fTQej~?$!A^kfbO2eh<IA&6f>3U!{|$STj88GZk_@Hs%)Us-karYAA}Y%1ee%Hhp3{B(9G*;gE5s&jI=oH!S85t$EumGS>&2)};GJiv+g~T+FyBI6Nr9?E4n?_G8K~VqB)jPWy8R_m>y{*!ThMEU3='},
 'w_p1_digit': {'box': (515, 414, 527, 439), 'shape': (25, 12), 'data': 'c${Nk00ADx2XYJvZ0N{=0SW+6B?GV'},
 'w_p2_digit': {'box': (515, 414, 527, 439),
                'shape': (25, 12),
                'data': 'c${Nk00Dl+KNg313=Z%xHW;uoJdgoW%nSz1e;A+u0E_Jgrv'},
 'w_p1_assigned': {'box': (204, 214, 344, 243),
                   'shape': (29, 140),
                   'data': 'c$}TlF>V7P5CzbWh(yT^!bL2&*vc6z2k?=Clp@Cn))py)I|{_)vvxL0>nWx{kNJZD9w_Yr2-V9m>8iyPua^d+=x)`KR3cP^khsz(>4D_hU{#LceUi%{ISW#=*OruLB&SC5E#b`;L{CyZN$f^zge{Q-B<>^oL2}>`nm+@}f|r~~j<)#ER!NHMRvDh>E*|I+NoG(d(c0i&i>W&qUf2+@6KM!qNd`8;8)8&RxJza}ht@mcE{?m@e<W^XKDKQ^(cXxz#mfv@%P-;dNybjTvdcH}d?yQ*ZOXxr{MFOe<&j^+4_jusV*'},
 'w_racast_class': {'box': (648, 327, 745, 352),
                    'shape': (25, 97),
                    'data': 'c$|%oJr2S!422zx+76LmG-9AfFbiU+1l%MQD+5PJf7FQsaGX?Jq({iup$fQVVM2X_{n^8NHoy!i|HDDqsY_Lr?WUyz;Iq3=Yyc=VH{}RzkeT^_{)GN5Oti%ZzqA&Pj+>%f=S?IW_d2)04uw%i?4ai<pox2<hLx27xKx2v37r{3+KQkMZvf4CTPJNzB%TSmtKNSDmfCRG`2oj!7b#@;%v3k$-#_{Q;Q%iF'},
 'w_hunewearl_class': {'box': (648, 327, 790, 352),
                       'shape': (25, 142),
                       'data': 'c${NkpbiiaWNd)3S-_-23L9Kj0z@2SoFD-gNdRJI7B+{34}3t@0Um}#u&{w7<NODI1dj0^_#@v2Gp69UM6yI-n?wOvJ7e<%$z}<|p2RkR#0CeD2>Tz0G@gV*l{`F*Z4g%gjhSKmpYx6V2Ri{am@x_Gf7pNc-~7V?VhkhD7y*X=hZ!Uk8NkM{uqCANI53~*VQ_2#8^a?Y**L?niQPg%kqu&ufrB$o!f^?S2Z?PK4gwHk_#Za&KS*r&C;t&*3<HCF0|U@gj1O#B7^xAoH~|1h{5hc'},
 'w_verify_title': {'box': (299, 53, 670, 86),
                    'shape': (33, 371),
                    'data': 'c%0RfJ&q$c5QU3oz|6eC@){c~nm&e);n0E5O<{rwb%ebN1qBLqgymp@O*z<v0*J2ts<8%q1X~~=kj<+1Q;#D5*I$!U*0HI4Njg`V;<S8{B)J70^4pNGJJom97j43Me5hV@#JlRFrYhSE)weiBwK!Wn>r@?V#drUq$~v=s&d?=m9ddG70h8P*3aVdKZ7Zv+S@%sxPMln)1f2kuJUrc^O46?S<6u)H)`J5b*uIYpwBDNQK?^OM!k@OZn`}jfr<T=hn=eiBW1M7xZ&Z~$oo??(JKIVsYbvPS)1``k4vB4xCDgpQ5nKFL@_FLb5H~_YXS{a7g<A(H?{><;2=|(0x+f*3BZ({&0ooVAg|TuHv?BbEMUopcv{aVthAXc7CZR$iv^7+!*LY(9TSquW+Hx!t;9JXLeNTr(kr}V5*Zu1i%Uduig3B{pM|$i)LYKY~XA4x~Z7}_OSiZ|vWJ9~nE1Ts@tlWVP&YI;`ZU*gUd5z7eaIfdkHo$;@N|qx}z~op}-?)k8-GoDBqqt4r-AFG+r5zpl=-&n@pf+8gk}PWytvDg5<k!B^++t>1!m@hHq`nX@0*L!Y^p~2TJJgtBvN!@8AC>Y`=w`WjwVG!MY^a~<$sK=Ke%SdO|FS$<)_%8?Bb5-7?<}9`a9D1SVzD5Q0RqLpIOa0!S?$CKh}TY5YqUH8>j}T%PX=ftB-NdCyy9`U+4aq%!&#mnAsb@!Qq${Ox50^@o28tQuBKMwlk{RM*l1wjyflI^%`FR~eOR-QW2O|Eg`#2W#nLDYQ8mkIDL218zLj`y{$sGn65jDL^uw%?XhHb?E9G{O^-RjA^=C2d{jhvrOs7)==au|pIl{3#OQ6NQ@s6}$x$3>ztbDZ~NDOB-k&4)Sb?;67{9DG5PqJ0{LdX7>$@&ldega=mPoD'},
 'w_verify_p1': {'box': (275, 127, 374, 151),
                 'shape': (24, 99),
                 'data': 'c$}4wF$%&!5JmrFgWJfa-C{|Opk)dn9wkRuu@zzvv=O|3hZzZYju9J6!DfraHTE{X;<xX8;18xWPTE1sbCrf*P=yxJluhUqQ#zvRhr_;-fX$jSlp<<h!Av}s6dimf#8+6EDK6#?i<<SBq`M`x)o+Uz*G25aBMoSRrpqag3bZ;wYPt|BHb~+MSk&;urBl67u3^yJiM@@jj0*i|ZJss9sr%+)j4p0a{~Z0n2hlJ>g8'},
 'w_verify_p2': {'box': (586, 127, 685, 151),
                 'shape': (24, 99),
                 'data': 'c$|%oF>1p=5JmrHK-(CtN)^Jog32{E$Vahnu<3&}Cg9R1ND<=;q{snQ7_81`kV%m;GHx~ycH$~sz_0q%<3HdIi2vq0#T2G(KSCL5UtT-~Yn#33piUM-Tf@z{!~7G)e0tz?RJkngZ-U^|dXwnq7d-OHxOyNjR~}o_N*6Jd(a`}z9fYHjEmp43Z(~<u25+L`p0wr!xstvruvqr+#P%ssew5CTLr%oL*{!=*Liz1oW@0t@xm}n10r)ynHr!MCKfgPYOkD'},
 'w_verify_question': {'box': (400, 415, 563, 441),
                       'shape': (26, 163),
                       'data': 'c$}qCu};G<5Peryb_XlYXru`I2}Ud+A(~HdKw@GbVkrxC2uc|$W<G;Ya0DYCkuJ;~J5()39T3@olTNyOr_;Ol4){-)K0qC04|14-!cR;hbC~p2JsU#7p2m7VCKrApmT;b4?o>b}78O*x8dn<^EG`o^hb|iHD3pyZ-*f`m`XZ2Y9}+gRwbb{_leC$};XKYb6Ij$bIFt?Bf*16h!cV)kxkyJ)OMeYqnWF*H1h)_Jj6j<-s!>Dk!hpO?t64BG=j4Gdyldo^ac$$8l({y@^hu2olkPQ1zVtlC6B#|}jw0jnP3tYp9>yN-pkBj>ZaZ69zS9m(T^6g@N6vg_iTZX&_`m+>xA6&1sz>D'},
 'w_p1_ok': {'box': (295, 377, 358, 405),
             'shape': (28, 63),
             'data': 'c$|%nu?@o@6hseE{4OkD!5S%uS;-}xky2zWA{UI2A9;bFj>3}tBM*>V^O}3Q1OAJxCj(!oMqro0A;a!+9U-8`Q#XuY-YaW2+NBjL$hN)U0H((V4^y4%h_J;6QJqS>iRup1M^yKQSJsu0p39eMraP;iHb?A%xu5H)4z}c<rw@1EFs}'},
 'w_options_title': {'box': (356, 54, 603, 86),
                     'shape': (32, 247),
                     'data': 'c$~G9F^=Of3`J?EP^or-1(r9lt~G^WYcNI193fXxFh$B-L4k{ut02X4FoOPm<ql&Q)`v*be4nz&PhK%e%&xi?VdA>{?gHEj)y$|v5#&(40aX-?oq>B%BrqYMOh{Vw0VZyE2R?yors}eAqj;oP;tpg7d;kaF#4Oh*W33V(Tiz}}@&NB65Qploj*_yO_pvGbLI4zP)h9x8#g{)auM=x(8WcUGRaW6kt2UoC|B}`mD@9^7S(W{?$*5w}#Lel;d=G7<GHLS&x(C%}k#)q~EcD2HaYbxlu=>4<!B#PE;j?Pnh@C@bRnLCHB~M?dZK`T|DA7Rdq{%&BS$d*+R&yoR+2`#W#Fi-j{>q9`+<kx4khju8{{Bbo&PKwO3p-lHUoU&ngma7UPn_rlx%9}f5u56C_?zP}1n!P`jMHRR&V^(qF$Ru8_=LZ<WnfoXh7ZK1S~&_DsOaHnFYG$mG8ST!Fm&m37ftm+o5WXF$3pB%-?UBq4AADd(<X-X%!Sy8s`SdH?&+2-+hI&Q7(R*!v8fJ4>jdnh;uglV1G>*Lu&F|hg@@-_{H=CngACgkI<a3WX1=Y-?>8fM8>dn^beoJS%9bXyDB*Ih%SKn|!#wC+rCMbZp72G&@uSp@huk-LW4O5dQg1){_x%T@TBox'},
 'w_difficulty_label': {'box': (309, 166, 495, 194),
                        'shape': (28, 186),
                        'data': 'c$~$NF-ikL7=_=slCh9X8zJuG2(eSxxE@8YNV{O+29%kwh2>sAlA|~wpj~o-s1pLFT}hD%+3fF_GYEO@d;iDd{lEd_fT%7D(PAXZo5$0m7OUDPP`VV)Ulp%9v?iy<Y{rP{h;1Cq*VLz}+EFDpMnP>BS~jG0Pg||F(^8G|Fp-Aap5dCiYndXHD;=Vn4S0f7*ub!fm=3_Ro#pz>^8O4Vb10HkMoVI*Qa|*Tz&?QM2vHOj<j5xR&>JsE&keHzg3B_lVi$@f4a+XVKR7dN^iDbD9=<6&-0b1-)&(tI?=_o~57pB49^Qlum0NxkP}@%=EDxiOWtJnLNL+m@C(E@D-BDgC>+e7lHtFSl7T+2TH6rPn9$p7->j7!1T|yrV8)s#J<{{qsPx=MqLZB1'},
 'w_difficulty_normal': {'box': (572, 164, 695, 194),
                         'shape': (30, 123),
                         'data': 'c$~G+F>1sx5CzaND%7nm5aesP5UVQ%(kQUWXi1UMH`u*M3NJ3U3HS;Mg1F2WH(DYzu^>lCrur}+9(;g*JR_h0dy?KX1ArPFk}X!GEdexHwJdoi6j^O;dyGt+iwbxQ05Tb8_v$=mMP_@mJc)Q&GroLE575%;joV{SE)alVeJ^{SmZI+T*2ee_4}4=B<5+2X^E)h-)4^3bawo1lGpni6#?IhU=I_WKm43~k)#`)>OQi`<G7jrB_k7)GEte%x>+;H}3?PPQ%RBMa>VrD7hfa-r8J=RCU}XXcWJ4$4++)yK>MRZY?$d-n9{dNVDv78'},
 'w_mode_label': {'box': (310, 224, 454, 251),
                  'shape': (27, 144),
                  'data': 'c$}@!F>b>!3<c017^pH7(FF|a8W|k%N*y%>iZk^Xy-3i}xki8h&Z=$(N=W^(r*0X-Nq8XmMFOuWGdDMHJ_}OYB$q_t)Ff}OWl(R`sbmO6C};I9yUZTxSAlw=c;L8wql}<L>+K#0*o8%M4CZ2cN=x~=4y%|5e8l%4g>y;{M$JhnZC_<ma$*m&LgXj@OScG6raGr)?Ig=D<uL`@)%0U0`LK$2&M{rS`|j|=Igd%ovW3gR?kVT{Sob>JV0D$@K63Y25}H)6#QR`*%KW0cKUaTTtcBD'},
 'w_mode_normal': {'box': (552, 225, 658, 252),
                   'shape': (27, 106),
                   'data': 'c$}@!F>b;z6oBD}Tqz5xFHn*zFs4$755onJSb~UfPzJ`_AiYQjBcyip4d9^+9&yBg2iLFW4DG*v%MbAPnvw+o%Nqp@SMo@M-7%X3_&4FC_u1aR0*EA|j6{O6ZGd0(!L)jC0uh*Bs|~JQ;CVzevuRxf(RNQ{D)vF*ave?)EzV%*n_Oih(vRkyMhaOG(daSV`3H3rQ7((5=Zl|#o``E^+FMzXi)eqR5x2UpOW^=(>8tc^de#NVIS*;_xiPRL^)gX`!Pj)IK;l0f`UMXQa5M'},
 'w_episode_label': {'box': (296, 280, 408, 312),
                     'shape': (32, 112),
                     'data': 'c$~G+I}XAy3<h9FmhgsGrurhNy%s|y28NEk0bGQkQiqPYLL`Q)9XmuZd4S*o&6H0{{M!cD>6qzrA?58r8wPYno#;cE11l-&nl*A19rRXZ<(f4ofsk#EEiF7xAkd&~;EbMr>W#-&lBSokUW_-doFHmBWcgfEbfowvHd^IULS*Rr{IApmK1q+YX4X?$TuPoMN!RgGI@5cSe*4Vg$Vo#LaiB;s%~uwHtJ%=)wB|QLI(c6'},
 'w_episode_one': {'box': (504, 282, 640, 313),
                   'shape': (31, 136),
                   'data': 'c$~e_!EM7Z3<c0Hc!2iUQ`9kXFzk-ipa!hb1ayF|KqCuK&_zZBvtM?aZV>ABAbpY$@QiXlI){%r`0y2c#Tz;+wk#&In2Z}H!fGj*@)SaaBdpmHFV=B$1a*43$|BXa9t~uNF7{<O9{{~%CFto4hB|xK&um>hsUIfvdzX^zoAAOecTl@Nz_Fu>&v78s1_F!HWrli&@<{|I!R;Re;&Qyjsm-y6Dq%@l>ULz<DtPSj2g&5VZG*xTi=)iC!%<`Kn1R=)d{V1l_=u_R'},
 'w_start_game': {'box': (360, 343, 517, 369),
                  'shape': (26, 157),
                  'data': 'c$}?JyKciU45XpKqdq}DQk40u7HA;@9{d^kkphk3!DBul3Ock~1aydkD7>B%bjY5YNZ#@I5P1Yv|3RFQss|vN!dO&IT0{&f0<}eFet$t0WfptNQZ%1q06NEPs*K=}F;~EZnQ3OJC<f?(vWBt4Oi53R6S>L>O$nyxf5H~zs24S#a7GO)qY0;D!`9ehhh**u{9@VCVJb?x&EXT|Zml|#F3;VCt&5Dy<*Hb($Lf!`B6GQ64=d3xw_VW*s`B_Lzss$%TPBPp1`B;^$t;FNy!k%I{1#|Z{m1DW8~*FbHwTwqM9=B<Ys=3O-QAm;`}6_$0~qn_T>'},
 'w_game_will_start': {'box': (396, 414, 568, 440),
                       'shape': (26, 172),
                       'data': 'c$~G7v2KGf5Qcwa1Pm5p^nesU0#O#S(Kj(-=-5gO-BOZ9?czu1!$7IvEg~KPbz(qG&uNjeb!jc#>2&&Z{>}#e<M3gr>Z|U<Qiv!6JX}JgOP9Hn^d;E7TDn)L3}XM}SKp|=pF`v`82s@(enR9Homc&|Th)lriZa&dlE#J5I)AZK5v1Mv32sROta4nb9lBuRrjQA4)eWIg?3qx`+Ns-|;eEI?b@bSzNgx%aDaiM3Ae7f?d$dz4BfB;2e6nkWju&LsRW_!GfbBp6P)b`AjUj;p_^TB-kbp(Qq&0=mkhK-is(6RK$D=>JMLRHI1!msQ8SlYr8p(g&hF3A=_-}vim-7X%IZ0~'},
 'w_start_item': {'box': (190, 99, 270, 118),
                  'shape': (19, 80),
                  'data': 'c%1wH9|jn3fjST&03!Y|FfcI~fLMpYtOg*<5yUb)a3F!fk&UsL!SLb3{|t`&?1vQ$nhj?#9OrCfb}(QTkZAbF*u#9lp!oww!vppn<^}-}>i~ZTbAv%M1CS-r0#t`!9elvha6q!{kb=R(2Mi1j{LP23It>7?bufe'},
 'w_start_customize': {'box': (187, 118, 273, 137),
                       'shape': (19, 86),
                       'data': 'c${Nkzy@sKEXE%Yx`Ba#CxL-M0m4&&h(IKmnVTDW7#I@R7@Xwf<oSObKYT!dk>h}Yo3b*yWP<~XGQ$Chjt&VYMh1a)CI%%X1IHggrTiQU9UaZ=4<r~lSQMI+lq4h=3|bTf8i7h35*Xe|wmGvoDJeJJVEkYw$0pCw(SP^=R;MBZ06I1wn*'},
 'w_start_status': {'box': (202, 136, 256, 155),
                    'shape': (19, 54),
                    'data': 'c${NkKn4Y1lKlagk~qY`1f(1}7&sUh7#R!<3>aA07#}`-z)``+%yXD0NkNW-nZvMyfk(kcq0NRtpz*^Y2@3`%9w&|j17{9H4#S3ncNESTxEV7)c=)04M+E~m007?R7Mu'},
 'w_start_options': {'box': (199, 154, 263, 173),
                     'shape': (19, 64),
                     'data': 'c${NkKm~kITE2mS2}Bz<Ff@Q@g#!>e!HMAj8#iM^g7e2m^8D=w64DHt1bf^V65Iru6gz;llR%R~hcl3t0Md>J6x;-Xv_pcyF+rfbgMxLlL6b0tQvyHpgGYQE%m*O0009%KI{@9<99R'},
 'w_start_quit': {'box': (187, 172, 272, 191),
                  'shape': (19, 85),
                  'data': 'c${Nkzy=C{n7IMO;y=L9z+eX!bY@@>V3q)}*f<y%8w|jL3JwfBj16qO0uqdj0v!b$3_t1*KH%VJab|FCNj8#faBxu)V3K1Nl;~k%QWQ8KU{KM~{y^{{M-xLs{}C5^hT|MA3T!M+N`?$f7EX!`0!fB~91OCL4OtkTNp>{kFx2yR7%)Hh<Kp-L?l=~#PG$fAU=AQD'},
 'w_hud_p1': {'box': (208, 46, 232, 73),
              'shape': (27, 24),
              'data': 'c${NksQ;h900au`2MqcW40{s(_a*%AKk%W4!Jvo3phtp<Lx!2b{<!6TAb9YDr-1<hJ^+yd0~!DTTbdRa'},
 'w_hud_p2': {'box': (208, 272, 232, 298),
              'shape': (26, 24),
              'data': 'c${Nk00D*e0|xyM40{r6dlKyX4;b_?0Fgoq116AfKfuD0z`~-y!hV2-y@7>=0fHa^0DC_STL'}})

# The captured P2 transporter offers only the independently observed FOREST 1 row.
_TEXT.update({'w_forest_destination': {'box': (430, 323, 527, 346), 'shape': (23, 97), 'data': 'c$}5ZAr8Vo5Czb`nWSqrT{}3AFbSpxxJpsjHW&<a8xoLMj<bXW3;~PWgbN@M4P}c!lJLLyW-<@>Gu0|o)QoHcgF-*c1I8}ELTD|e%R(R4v0Clevk1r=<<BNJ%s`&NPqk>Ii08-$8&)9!SiPjzZXa_(eA;r_+Quq}1Ph~QryKbIf+UpPofHL>W2$#$1Tr83`!j!m$uSje%m*0WiPc4SfYYJAK9{NkTx_?$@&?P?HLL'}})

# Additional exact observed wide-layout HUD and normal-save text masks.
_TEXT.update({'w_hud_p1_town': {'box': (208, 46, 232, 73), 'shape': (27, 24), 'data': 'c${NkfC2Uc25kujEeVz_3HI#=3|bf<h*SUo)cFUo'}, 'w_quit_question': {'box': (323, 64, 485, 110), 'shape': (46, 162), 'data': 'c$}qDv2N2)6g|%`vfuDX&GxF6=0SeI-i)Y38l-&3OR_SgGe~)ErKE!eBTRe=!%K|J!biAb=!VRep^CY71xhLgDz5bIaAco*&bb%(_p<ka6CeV-&Mww1AtjLRVu6Im0X^8k*d;Xw74ClM4A>UEuO%^W1AI?QnxIlKx53YC&!Jvcb+rYguZKiv#)|||-i^PVTX1$2S_h%}3&<$Vri!$=Nk>PdP&mgwB3FgHBWx6UFH3Csrikl?&<tCJ?|@TQ#2F3dheT*0!aljeDw`4?Zi<f9Eg|@A^h$jpOjVb6gv#J1ON#h{em;)ZE#WeO?swztd<oR=E4#r#sBa<UJR1ks4!)tlz#KL1du=9rHGjZ@{;$Xal6%;JYrOAQKsj)`kFn+kDlmeZ*PhDYjQZ<Gs|w-M4efrTN99`>;E1~)=%}escq0zWxg|p1xS3;%XyQW+J2PdDX^4twhhw2q>myZN*(fOlU6WjU+Aym}`~!uI=NGI7*Y--`R6Mq|Bh|gi(x{Do=7X($6G77usTEzV5G#u$RkBr{3ZFc2KQheMBi7n66Xdj$JWFt$#TYksB4uA#m|p$~Px8-$ZaJgKJaD>UUd}-;WR?6K$jM&<4j#6TKlKYe|BFc'}, 'w_quit_yes': {'box': (557, 117, 600, 141), 'shape': (24, 43), 'data': 'c${sGF%CdL5CCVbIEBQO5{)NZd8MbEU#Mi`WeT-7c!E+TsF`{)1Alb>a#j>kPx_U?s$gZ1%?q?M0ojv-SRW%Qml}Pbq0A8z9+j@qj9f_zmR!Ww$MlBXXLSR-GZEY'}, 'w_quit_no': {'box': (560, 141, 598, 165), 'shape': (24, 38), 'data': 'c${NkKmaxd1_OhC42%zs&tYJ1wlQFk=Xvmep~kqef$_%~b_V8R0|^G+GY1kFls7XrFrGid#=tHQ6q2X`s!I6W%)r=uT!w*(o&Ny?2ZuZZE&u@2!4}*'}})

# Exact wide-layout menu reached after the authorized normal memory-card save.
_TEXT.update({'w_after_title': {'box': (247, 60, 716, 86), 'shape': (26, 469), 'data': 'c%0=_J&x-(5FUoX<0}HQO|c+fZm^{b!Yp&0?Ls4hMZtwj-N49A9v3cDDklhNxNy3RU<8kgFq#ZE$PI!tp@0#FqUPuOz9GQ>X6Yp21_~AM(Z~K*uxZQN&nmNhf%vUNOQ7<zi~xT|8AY|Ee-}T2ApW81iLzQ1jdVZKF*}fvUXxR3MW!o<rPutVP!sgvkt)@`fL+C^^1<_F^=nVguXf1rq{)cff@+SJHCf0$QI%EFM0dJT7F0C)<3dHzLVwWPjj(DEi3)1DDh!-p1*)hAt_p4T)E-MwpW+Wg_2Vt>^w>{TTQy;TCpFz;FdTHcUT#0D`z-}qyd6kjVT+{${HV_QS_8=Jf{|&D#$S?1-NwoEWmt{-+5mJL{`7c7r?*zdpg;{-MR3^bTLJ@*ghtM=Uk&iV@3PTnjgJfnG65P+G30&5k1_>t8l08Wv2x{r>Z~G~Am@UR4QRrE{dAV!6MNichX<=>&SfNtTtu$M*n6R>qHE@n%#U}b8KI}+bRjN@v2WgmJ#<?Kz%-8xlFo?4XlEzxY}6SZvjgr!Qr+#${(gL8?Acp61r6701{E3e3c;)K^m+BG$hsNFW%qdl4lG?4T*%p(QuCIDg<!1)aH^3iUrWC_S~6(ZQ_|ud-9nHBW5ZH7jc<AFfW4r{RvIxABJaRxZummW{mTfz=&;dT_Njc}K&KcusGqrc(1J1T*PTAmEq~H2u7k4Sj=lSvRHh)HaW=g`XPlg9xvm{I51oEbfvzXZXLKV~=7rWhOE2qVV^&VDOI{U-<t-aeqgt?|%JN~E&^+9zb~~94JQZL+kHcf0S&luiWZHpI;tNwc!%_~x^BfUR%N!RxblOVRH<P;LEssi2XUF;$l#xM4D#4xreA{Pn)u!|4Yo|td<j|0NCsiatQ*z6#O)9ZSwu&b;b<Y5FNsT3$`-Lh`YT6a`i~KDHUmB@l1ETOX@S$B4DzS+m@f$Hj5ctmp!sVp*Q*C_$IPmMM|L*?!_tsyDAtIj'}, 'w_after_mode': {'box': (416, 198, 607, 222), 'shape': (24, 191), 'data': 'c$~G7F;2rk6h!}O5!-pw<77DkbU}cZqohlRETzCS*vN&OD84|z*PsDx8IjJp03wbe;f`$NBDUE06DgbkDX$q#H+loGU+6A+HgIy)f@9*vb_*<!?~MCNutLwJxvG)*X@x-pI5s3pqXiP=$$YJO7}gk7boykvJh+{BY$*J62|`$d*#)ozr`w2;;$VObrWsh4)922%VL6sj8YvU{JbK9QHu*J2&m>rwE{0OsbtX{8h@Nhv*QGdh3KVX<Dj#Lz-XoIg9Kojk>uTC`6wH^})j7o_vu^-Y#@sUeyo^bL8ta&0X3W0<@Wa4@zhFZrn|fAi<7afXolmgaPO^?%Hx$+2xzJ`I7L8OypB#~)DML+l{B;_t)|>DvnL}@<jVQ?fL>}(>sQ>T_<p`wO'}, 'w_after_characters': {'box': (379, 255, 584, 280), 'shape': (25, 205), 'data': 'c%04Au}%Up7{KwbX>xTy8aGTD>LcKG1f;LR=4NV0fB|zyF7X@)tPY0fV6)^BZi6?_UKm`AIkpnde)<Hi`rH50AK<^@Yce%<?Ua%C0Z%-Ol|)p=0XAw)&g9-x-_jH5daOb`;==OEST|{-EafptOZ<ro#GU^Hoim;twqVG5CRAEK&2pN8#+X8PJe2d2K^;cLOQ>%Ih>)f|Xb{XE{fIwXO|f>1X=tH9=_)YXU**y24rwgi+oHP6fpLdP8Nm49+h5r`2*A9G3LiqKnWv^jlf^Or;C-+`UF}nTFeHn^G9bAS(N>K+F<Z0-_!Q!<Sr;T*YVOSSTp#hZl!s*5EjB%6HO>XbYC~6@B==Dq&4e8WEsZqwdf>oaoKGKWJgZ0veFA4Bu_vma?5|(`;v1)uqE7'}, 'w_after_quit': {'box': (383, 311, 517, 338), 'shape': (27, 134), 'data': 'c$}?}F=_)b5JhKMgPMR^cS@0C1ay@gAqOxT!4@uk1YboaMampuwYYHUb(MkG^E1MmDrNEu!94V5{tVII<@4*hhT`k$aqT^*!(06XGHN``2}&NjVT3vy;EuqR7|8<?;56)jxi=Vr3XQ@HlyJrcxEY5T^oiKx9orhl6Fv+|CsBijoOpyeQQZV#N#<a+8pY^@$!6SIX(<f177=$zXHRRv3n<P~KvMVf!E&1>=@$TM-m$N4soNrZ-FOPNT$?%*U*lzdHX#1%WH+EhamX(ehWt<{>OY+Ox4r?-TGBT'}})


# Observed PSO Plus title labels; no full frame is stored in runtime code.
_TEXT.update({'w_title_wordmark': {'box': (239, 180, 746, 219), 'shape': (39, 507), 'data': 'c-oCt&59g15H4AvwTGs)x5&_*_9L{(rA>xuKT0oof!<T*uz1u=*u5D05%MAd*D~O_1o8rgXqiBcR!ATXX-4^~$HCxu<7k)tk*Z3ns_*-1h(0Xi>AqFnfAnF+dr#E(KisSTIO5N{tML9eZ2OPSruiohnvde9L^?&CMzK*TQW`f2o3z4dn{tz)No3iigO>v@uY}hrAB!CgYuVp0Z4$nJ#$F^FXS0Kxk2D#0;9vY{@SWcKYfpCSse4LmS~QeXUr>wvjPy$cXM5}^^xB)-k<u0&(4_W~pH6c<I<)LZ$}@4$UU{RumV-c{Bm7mrr5r)&`AAtK)#<6P=MpT5aJQt$+DB9_G}!N#bDwf@g#@98-VC86Gm+Qj{4U(3<>B-7V|7$XM>|a94C!EWIO^CAY*6W@9rbG!Ru+{(1;5o}#X<Xyo|}Z2h-FduDy(U}B!ibNaeaGxG?ODPsj!K^3QN87WNy=F?~*>|)D>hnCFLLBhOV#lgbjnn7No9?+Q-C)oo@!Owqa!o?R#X=Zw!x{aCwKYc$cGy3OK1ud@^`q>~Wx)d-rDPTv-=QLv^o02u%sg!t%0O<ay!DSxMSZfeJhz8hnw}HJv#sTuE7JwcBg0-l)B%%+ew+j6oUI?WlJLSRd$s+q!4c8?5tM@f%cgi<S;dJC5Hx;;wtdedvitx*NhJk|$U3vJI{-g6kW3beSV4J;;y=p5AxVBOiBV%Zr%jDi*7ZoQ*|Snuz4JO52}CovG1OK+oU}K$kzJXPjv~yU3|%wb$1F`QjX>q;439Xn&s+UrEb*fb|6hKBFDpRj)N(fBqe^)_ef+Z@s?3{>4~adZa{j`8EfTK!noX2th!RK&1omj)1965kb$rLhH+JlVVMmM??A7!?Bi>D1SQOdP=PLj%P)wMyU}M578q|<4K~r&1mu&kY&qJT{qR9kP_)vXz!8~0C^@7U}w6bMrx0;xqmcbZi@tB{R#-G_ru8KaD0(aiwKNqzYxPCKrS_+KH**PniWpLHP%%cOS(%#$lSVeq;Ooep{5G?Qllk&HG$%CQ_&*t(3q19o#TNS>beygmb5d&f#`7u76=iLyVqXcS-l=n%chnKwJ)td&hFZzBTA8CXM~Ba>&uS5$Y;iO)sWZ;$Z-^*U1YLZ4I4F#_N3v@(j>_ut+0N))Va|w1Q<ZtSeQm1^-L+EUv&aq15^Ix4~FWEKgl})54Dj3y3Nt}3*SFsX}zfu^Uhn8pp(|QuAOqq9h#CtmlcgYsk7)u*O9B?5Y~BZkRw{Jc2iTjo)($-;EDnw$6|f=%T+;$e7YWW5*Fx;c0RZ2nvkQkz6pBR-a!9YZD)wYc64H0_J-Nj%Q+`;os(s*gW_1TMcHN!Q{D8NFg7BQK$hJmBi7(>Q-aq#j}&nwu)cH!np|Bwf|f}&Zpi4D=qcnOn@3Gbfnlw7UJu-b<q5bE9bXu4xBDAtYuYh1N{1_o(BKWXK$&4_y~EsTR9w-xrr2KDfuD=}$^?LO(qR)v6{~TD@jzFWuNJg4lR`Zqv-6y2Co9&gidH%eacRPg`w|eg5Pa}xNs|hT0t8tXDp+d0;>!Oq5AjHA=(=A3j>cEe3|`E*$LQ$=Tnm|0h^Fs&7L^=X{Knw=Bp{Yqret2-$|L~gx}}U>s__L8fGzYI3<t@28A-kJqeup(Da!yd?}AFt8o7vt&belpSps`ZT2u++R)%Q+KW#czDW(q#6I@n+^*q>Rm{&7#HW<=Y#`#|f@nr;Ck1OA$PplEM-?tM+`1csK>E9oIQW7rfbkF+ihZT8DO`mpFyH9+O`WqDP-hl'}, 'w_title_online': {'box': (370, 232, 594, 267), 'shape': (35, 224), 'data': 'c-o!Qv2N5r5CG6wM)DR!w<%Msyy6c`cSRKciccp&Yq}KCd99!`1qwe9iBDl7r0^SKxkzh7V<dCKtdArW6l^u}vpwVSjL3f-{)bJ<&0lPm2~cJz4-hnvXeMYTxB>vHj{(RI!XKk&LkY3ri;|p>jHTvq5=%j$=3qESnR3Tg`lAJjLAq39%ja&|S?uxdXmgPFPP$f&c^$}M91Qi>k7m0)RMd=Im(i-Vym_=ew#jyv6*m!E8i+TsK3a!&$=-P8h7Hlc^)?nuEw*d>WDkz$$717J?ZRly*wJ^j{@zBt3{-7LzllWwaOtt*cWQDEKs+Uz@_w;1Z@RHe_5vW%6>zn^b;Hrl%)Sn4u-HYi8{0qGda*27NcIVz&ATUaQB4bfvXxEw_F4;B(puWM*vhL}O!iHQu_xZPw0uK2QCoV(56Hykr&{F2%8zO$E`71uY$K7jv3`~8^#?VeOzrKes0xslwy-www1EEBt8ubjUes%7Fm93+1s<(d<MXRxox{$;03Oxcb;<|pWPYr@i?f3vt}y*0ywzTV&rF($YK1c9_HMMM9n0BHA#~(3s}|Wtp>szQw#Yfy$$ddyWtLtN5E8(A0%ztc>b$x%*OkpqG&Tei*n=7j$--iIlcl+ipqp}VGJ+1X$S;x4!e+K<SM*k$EvvRO$F&MV@MyXtPV;J@NlwA1cctS2eghp6*%S'}, 'w_title_episode': {'box': (340, 292, 671, 324), 'shape': (32, 331), 'data': 'c-n1LL2KkT6n>6FoWkrV(94uM<4!NRl?=UjSnp^{5B(X<l7;r@P$)T=kxR<DhwS*+EtKwGXm34r6%6akl3e%HmGQz{N-HymDj@XwoKOm#$k@oAKD{S>()R%VYfQo2E&e|s=uPe*1{;6|KywFkBbCU3queBpH$qy7&}|a^esY8;5p!VzOhLE+v1g-#0CO6~o3&6X=tnqWglCA9xNkIv;(9j}LWsnEr7nfNBot0`kTS^#=eg|R!vHMo0Hgq3MZ^$bpAzZlG!A@e1jWgc9%i0K<*9fKkv=-2l~&leNQ=^Pr5bFpLcb<VdfFyq7)K?g`N2}iOdzkY=&-~=EF3pzl1#XmI7?7|)tNvE-fy1a`k62b-ePwdQOF3ZnlM_~MY)7gmUwM-)yp(lVKWR^9nQt9P;;7K<43hnFiJnZmfo<2FMgZ#Qtmvsv=iC9Zb+e22bC3AJegft@P<1ghUsf{uYEa_o`U-N`L{`UKa3-^37m=&O<H$va+t`g8h7r8erB(%cCeQnssh<@kw;iSz&ga?D4QzSj>8kw^>P0B^Y^Y_#L6dK_po}EX27+A#&K+_UTY|V+zdy5r0=fVWd8USJkoLt;Cjh4xDXOv({?^d>2~d@wmhr$ms@X7>*6WT2Vw*dJvXgTvnme?gIMeeI<u`XHrM9(7rB2vGwTEGm20*u@JTFCniMoisT;xoK0W6pAABAAKSzB2ID;u3cMN46qKk%fBrUpdf@=-CC#6|6%NiD9wK}i!o!G7>C`av2QLB|-+)C+IB;`r{&Lv5CP+HqPJAxuIZxistsmc~Z%3Y$;H8&C_mvMUdCl9y3`i76iImCav2SpC;a?Hv`XS}1E5u+QyU{;sxUft#{J!nfK#}NkFKq4fzzcXZxJ2oT?{KAN)(>7zvfo=X8`4`S}QO*KOd`-SMGk!&wq-7LlJdc8lu6zHx*$N&4%pvu1{v*tz+#}ceM)g%<&$o~csTa;a(A7u|j(l8w1hel^@!XNKRN%rdVFA7`lqi}HKl96%i+FwNll|VH40;<XcH>66!{lZ1u(<hC!ie6UWXujVphf!L4)qKTj9hf<V#mrC<cV#cUV8c(<lTlu`)~EhAf;V+cNM%o#zrB!seu0gO;RTm'}, 'w_title_license': {'box': (252, 480, 453, 503), 'shape': (23, 201), 'data': 'c-qC0p-uxq5Qb;Fo4sqYa0{3fO?yX>h&@wI(QVK25PKm(AuhopraiKX2Pl$9;0=~LLQrS~q76t)T?HXPNC^go;1`oW`DVoYKfphVfcY}5&!J?)22ZbLz6@sgy<q{?!=j=Dv&3;_R=21D0;cC<#IC%auy_TG0-(7py)jW}b0R@d)ETEXLLir7$Htm7o#2#4)#9<gR+Yh(gFCmWWv|&*5|4?<r?nJ^ii!~&jl!vl<`*I~eQ@NZ5JAd_OCe3p4g`lA$MhDA;7wP}aso{oRax)z78H3)wJ`y!Oo2lv9Exlh5rTSAG2vCM&tp}ms2k5ax<W*ieLPZ%J#oA7a1#2ipHZ%c-dNEo@V@ulr9M23=q&IS#v(THz_S7D{)|-rmi4bd{;|Y&=GIds'}, 'w_title_copyright': {'box': (506, 480, 795, 503), 'shape': (23, 289), 'data': 'c-qa9F>ez=5QX1*PrJ5Q@HsRaVI}LtqTUOQ15$EFq9}z6e!}4tp`eH>Qbh4yE^>@?Maug*d$vU=A_{)NxuG_qabX2EG!#gP3NgiK^z>;o?`eR4Sm%Gi^zCob^Isz&_r26u){C@rzW!|~7<0;Ukj@22xj5SapUmc`ILa^)y2$%UVmPOcnP@6FNIpFZOr<4nd+2Q-6!K)MLTh-M8X(GP$_*~}g51)^<+z2dhEX2t^t6gY8qM5wT9AZVylh=}6~y?pF%4K*p=*JJ)<n%qKr&dOLHxtE4;E<~R*m9>yq6=$^<wn)6~NO)OhzEGy;22Jd0cv-kD1x;9zfK~>DC)}^w*^dry$u%%>(zl`lO;Hn&Af9gfsqbwe6Uum7VV(!<u&iUVSR7<T`T;g9nWytzeLSb_|P!7#LD`7ZE6XEEuNyNTh!?3X25#pzoMOSC}qghkJpcbagmE@BvXKqucv{^fUQ0Ad+eg+Y3gPlI%<0G#R!hxjGhQ9Ls9vENp+mab83D;^Ebp*t4A{hCc!~r~amkZTF)WDrf#?v3BU$0i{WSyJp>me)p%hF!(R)2j#Pa7X'}})


# Current main-menu label variants from immutable actual captures.
_TEXT.update({'w_online_live': {'box': (413, 347, 551, 369), 'shape': (22, 138), 'data': 'c-n=Kze>YU6o<c?gys(6HiJWk+NAgbDK2*iE$E8`T}28m9fV#DScg1}k8q`87wI$H=nK@XL$O|{yJt8Y&Y$o6_`xv>hJRHCnlju_*)(Epk#XFT=$cIWQ2|Q4cJiVRt$3-FKZz;zyMC}tsQQf|6(&;S4Ks3+3uj4iooMe&!oe-gJY|8NbA9Rri|w}?MsjM^6uH(G?zO%&0kg1g8Es0)l}a5R^0h@STK{j=c#VYUeGufIDPrqv1j4EbcDZ{Z-|JEk<SuNYviKR9@DL}|G<#~Hr0~*Wk4z~-2CN?OnH{ka&)CqETf^FL=E3sHZ`FgU=#4u=o!x|)fu7{H`|uR0NZ-zDm>=Cc@x7yo|Hm(7fKa9'}, 'w_offline_live': {'box': (409, 382, 560, 406), 'shape': (24, 151), 'data': 'c-oy%J5Iwu5Pj>lye=Z!>4LDZBQB8AMNop^06D^jf)cr;K=GnTaf8GKkhlirfF(*!K(VQybm_vf8B3(2Vv47kH=j2%z#pdUfbtuYUqXB)?K24qJ8T5uCIS2q5#T5vj)N%hxk?8N5uHFxq@Kr|28|fjCWh3KZnIQEVkrGW21TK%^QDI%MiK5mFjM_D5q7z45pS?bswbqX3+96ERfAaz7v&3<xXZE&;~>Yn;Zb4D(Byf^=^WJ%CA`0=Ed{J)MQNek1*MStS2IE+Nj{oI)fPsJzN+}hX%FT3McEV}rgoU&yn~0RPil|v4GoZjdjqU@XBLuh%$k>D?j7OH)dtGolr{Y;{))>1Fjg)fTj|OB;jP&<jx2cI^x;6Q_|3fD;MVxJ{Qw_nT3P'}, 'w_online_live_other': {'box': (413, 347, 551, 369), 'shape': (22, 138), 'data': 'c-oCnF%H5o3_O#l?GTlW2vtxv#*CeyQh5MRfFCe+%+tb8`h<>*TwGwrL+o76=X0=u#u2BS3V=XBkc4dpo)J|^v|4EBTEHSrK&khp=COkB;Mv0N(kN~V(gKTGQpO<?1&&1-AD+pNxS<zT_sQAZapn-OGdk4}m+~xzvtBg@3LbJ{jB3Nb=uDqdQl{M@n%QEXx<KvqL~j8XiR=M--9xgA2Yyju;B%w8Q3oT;pZ#Q3O4~GFc5i&te{vMPF=2DbUY389>tbxgAMpmY(I4{'}, 'w_offline_live_other': {'box': (409, 382, 560, 406), 'shape': (24, 151), 'data': 'c-oziJx;_h5QU$UC~*-jE>kR$;RGoukTC2$R)G_2i3G*)BWSq+SFsQW$q}|hC_?*Yv_V@?F~y7Lv)}VLz#rAT+2`i~9pAramyf>j;(&ThQXD#3uUgxBVS2U<RB0&=)QG(4t<j@b=(t&8jBKh3MIE2fb8~^51n}qN$<uY(E}b|o!lbdmvb&Ytaq^|A5n+grhE`jOPl|J@484w&PV{aOo6|J{@fR|<>GDA%Cw<Lbvni2*Cz)RrKH7mMj`dsD2uTs^c8@ZmptSt04YO~|#i>4LZ*ilC8!4Qh5&u{@qMtqgtQ{k{E2{'}})
