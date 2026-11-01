"""Independent, conservative observations of captured English PSO boot menus.

Only static game-text masks are retained, never a full capture. The current
layout must match its labels and a unique orange cursor. This is visual proof,
not a native menu cursor or a claim that input changed the game. Unknown layouts,
transitions, occupied character slots and character editors remain unsupported.
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


def _text(image, name):
    row = _TEXT[name]
    ref = np.unpackbits(np.frombuffer(zlib.decompress(base64.b85decode(row['data'])), dtype=np.uint8))
    ref = ref[:int(np.prod(row['shape']))].reshape(row['shape']).astype(bool)
    best = 0.
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            box = tuple(v + (dx if n % 2 == 0 else dy) for n, v in enumerate(row['box']))
            mask = _ink(image.crop(box))
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
              'reason': 'Boot menu and selection are not independently recognized'}
    if not isinstance(frame, bytes) or not 0 < len(frame) <= 8_000_000:
        return result
    result['frame_sha256'] = hashlib.sha256(frame).hexdigest()
    try:
        with Image.open(io.BytesIO(frame)) as source:
            if not (320 <= source.width <= 2048 and 240 <= source.height <= 2048):
                return result
            # Capture coordinates are normalized only for the demonstrated full
            # Dolphin framing. Crops, unrelated aspect ratios and window chrome
            # do not create evidence by being stretched into the template.
            if abs(source.width / source.height - 687 / 580) > .018:
                return result
            image = source.convert('RGB').resize((687, 580), Image.Resampling.BILINEAR)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return result

    found = []

    def matches(names):
        variants = {'online': ('online', 'online_selected'),
                    'offline': ('offline', 'offline_unselected'),
                    'options': ('options', 'options_selected')}
        return all(max(_text(image, key) for key in variants.get(name, (name,))) >=
                   (.72 if name in ('online', 'website') else .81) for name in names)

    def record(menu, labels, index):
        if index is not None:
            found.append({'menu': menu, 'selected': labels[index], 'option_index': index})

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
    return result


def next_key(observation, players=1):
    """One conservative input toward the authorized offline campaign setup."""
    if not observation.get('recognized') or type(players) is not int or players not in (1, 2):
        return None
    menu, index = observation['menu'], observation['option_index']
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


# Small monochrome masks from the observed game labels; no dates, names,
# screenshots, desktop chrome or model-generated image evidence are stored.
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
