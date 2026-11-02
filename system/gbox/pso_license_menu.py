"""Conservative recognition of the English PSO GameCube boot license panel.

This is a fixed game-UI template, not OCR or a native cursor claim. Only small
monochrome game-text masks and coarse paragraph ink density are retained; no
window chrome, background, or private capture is embedded. Unrecognized layouts,
missing proof regions, and ambiguous highlights return no selection. Two real
Disagree captures were used for registration; see the local validation receipt.
"""
from __future__ import annotations

import base64
import hashlib
import io
import zlib

import numpy as np
from PIL import Image, UnidentifiedImageError

# Reference coordinates describe the dialog, not a required window position.
_TEMPLATES = [{'name': 'header', 'box': [80, 172, 578, 192], 'shape': [20, 498], 'data': 'c-q~QPiq=M7{;G*mT?P%ZYY#lDs@al&Xd?fdeQAAr}R6lO-POr0zHMe8?8yfgGUdAeuaF2!WhMP5Yi9OgH52lD!J@IlD;babM2|nfq{j2o_*)HKNk3RD<w+#F-vMue#%Q_<gb!4pFHq5ve_%klI}+<AF{oBl*b9m-$V`BIH~3Dl(qNyF%Wn9z`z57;8I%QH*<EN?KrHWr?9Wr6*p<+0?{s56dMRLFt7t-H1(kOR)CP6JkK;0I}Mv|aBj9#4(1YO=nD)PPf^Z<(BTePBOJl3oIi6nsO|br07Y+b99d{0>=e0Kb+YL+q_%Q16-1k`Q3O}IaNWniD+){THhn6BIe6$n&=X@^X{dc^M~FqYXSoDJ+zw@Appi;(iU|wl2+P^0cpSHBc-(TR*<OHW;P_2bgzjEcKcj0=)oWW^(^LYd3(UbeV;8W8;b;k7>CO-wOyK3Gv1PNGlu>rP{p1DA7BcRm8Ln?I2iF?9c0ECr!scmG%zm8_xXRVw`3W2`(>WZgI)8p=R^Gjb<PmOCyHPQrsRS+IW~T`Rg=OlC?3u$kIQOWz1ZPmf*pX~xD(e9!Tp72`Pw*6N#{zwaj=po#@aEv{J!&qEd!b+rQ{;tu^16*niMn2sbuHar;55mnuzlIRFEkd${olr27FAkqFx2(OeV97Tj?eWU#x)ri6gHV^<-9;`xkA@g8w=wVGOj93^+tyMDWtKoD1zZ8!i90QG+yZx>6?7;RwWtdts@V-vjpFWl#oYh6?gnxz%wCh-KyJ;&4mQcT1#-%Qv`l1W!$0RC)u+Jju+t9XVzi$babru#J0z#6O`!iq}-d#!ArE`yyasG2joT{B!KwaA5-K1SU&*W1KTk'}, {'name': 'agree', 'box': [299, 425, 359, 444], 'shape': [19, 60], 'data': 'c-muNKm`XN6c2=Ad;p>4n132n@G~$b{GZQ%@CSntPvXI25(k(K4oOHTvoIL5KV)n+a9}t1BOw3y4?}$qBV&UC1DnJ@0SRUX28W)H3{3(KJUj;{@Feyy95^G%P{ZHAz)%h`n)v~;^#FD=9M1'}, {'name': 'disagree', 'box': [286, 444, 372, 465], 'shape': [21, 86], 'data': 'c-muNzzTR^4CWsNaIt~|Fs1>V#c;5}j=kYuj2!a;W;Vk=_5Htp{Ifs6!*R^8&#;}{;xU6kvcwUKV-ga@JPZeV3YZ`NaHv23gPG0XM}7Ze#{cyXcq9&dJZ8Yd#&7_rRN#ojKLZIS28P2t&JvIR97yajV74*rNuMFjaL)1o|AWI1|0$#}f2af7%<&!J-X9D&0RXmuHth'}]
_DENSITY = 'F*-On9zZxZ00000I7T-=IWsdyGCD8-LMS#pNg^;iH$gQ4H7h_aG&C_RE;uRzIWRCWK`k&eDn2y|J1!|IH7YYIFgY_DH!?IREiE}MIy5sSH!wIZDk?fOF(EP;Co(BKEH*SUB?tfjNkc_3Jv%KuH8&~%'


def _white(image):
    a = np.asarray(image).astype(np.int16)
    return (a.min(2) > 135) & ((a.max(2) - a.min(2)) < 80)


def _mapped(box, cx, cy, scale, bar_y, dx=0, dy=0):
    return tuple(cx + (v - 327.5) * scale + dx if i % 2 == 0
                 else cy + (v - bar_y) * scale + dy for i, v in enumerate(box))


def observe(frame):
    """Return a bounded independent selection observation; never raise on images."""
    result = {'recognized': False, 'selected': None, 'reason': 'License dialog not independently recognized'}
    if not isinstance(frame, bytes) or not 0 < len(frame) <= 8_000_000:
        return result
    result['frame_sha256'] = hashlib.sha256(frame).hexdigest()
    try:
        with Image.open(io.BytesIO(frame)) as source:
            if not (192 <= source.width <= 2048 and 144 <= source.height <= 2048):
                return result
            image = source.convert('RGB')
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return result
    a = np.asarray(image).astype(np.int16)
    r, g, b = a.transpose(2, 0, 1)
    orange = (r > g + 5) & (g > b + 5) & (r > 45)
    rows = np.flatnonzero(orange.sum(1) > image.width * .35)
    groups = np.split(rows, np.where(np.diff(rows) > 1)[0] + 1)
    groups = [yy for yy in groups if 3 <= len(yy) <= 30]
    if not 1 <= len(groups) <= 4:
        return result
    found = []
    density_ref = np.frombuffer(base64.b85decode(_DENSITY), dtype=np.uint8).reshape(10, 12) / 255
    for yy in groups:
        xx = np.flatnonzero(orange[yy].sum(0) >= len(yy) * .5)
        if not len(xx):
            continue
        cx, cy = (xx[0] + xx[-1]) / 2, (yy[0] + yy[-1]) / 2
        scale = (xx[-1] - xx[0] + 1) / 416
        if not .70 <= scale <= 2.5 or len(xx) / (xx[-1] - xx[0] + 1) < .85:
            continue
        for selected, bar_y in (('Disagree', 454.5), ('Agree', 435.5)):
            panel = _mapped((78, 165, 579, 474), cx, cy, scale, bar_y)
            if panel[0] < 0 or panel[1] < 0 or panel[2] > image.width or panel[3] > image.height:
                continue
            scores = []
            for row in _TEMPLATES:
                raw = zlib.decompress(base64.b85decode(row['data']))
                ref = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:np.prod(row['shape'])].reshape(row['shape']).astype(bool)
                best = 0.
                for dx in (-scale, 0, scale):
                    for dy in (-scale, 0, scale):
                        crop = image.crop(_mapped(row['box'], cx, cy, scale, bar_y, dx, dy))
                        mask = _white(crop.resize((ref.shape[1], ref.shape[0]), Image.Resampling.BILINEAR))
                        best = max(best, float(2 * (mask & ref).sum() / (mask.sum() + ref.sum())))
                scores.append(best)
            if min(scores) < .68:
                continue
            body = image.crop(_mapped((80, 194, 547, 372), cx, cy, scale, bar_y, -scale))
            density = np.asarray(Image.fromarray(_white(body).astype(np.uint8) * 255).resize((12, 10), Image.Resampling.BOX)) / 255
            ratios = density[density_ref > .08] / density_ref[density_ref > .08]
            if abs(density - density_ref).mean() > .035 or ratios.min() < .58 or ratios.max() > 1.6:
                continue
            found.append((selected, min(scores)))
    if len(found) != 1:
        return result
    result.update(recognized=True, selected=found[0][0], match_score=round(found[0][1], 3),
                  reason='English license dialog, labels and orange highlight independently matched')
    return result
