"""Versioned, attributed research summaries consumed by round evidence.

Human guide prose supplies hypotheses, never RAM addresses or navigation points.
Rules shared across titles are objectives; scoring, controls, and engine hooks
remain title-specific. These short original summaries are not guide copies.
"""
VERSION = '2026-10-23.1'
SOURCES = {
    're5-basics': {'url':'https://gamewith.net/resident-evil-5/article/show/12370',
        'author':'GameWith', 'scope':'RE5 Mercenaries United', 'access':'read',
        'summary':'Find clock extensions, maintain enemy chains, preserve health, and use environmental crowd control. Verify each clock value in the loaded edition.'},
    're5-original': {'url':'https://gamefaqs.gamespot.com/ps3/989571-resident-evil-5-lost-in-nightmares/faqs/55979',
        'author':'AbsoluteSteve', 'scope':'RE5 original Mercenaries; separate Versus sections', 'access':'indexed',
        'summary':'Learn stage layout and spawning regions; character loadouts and enemy behavior change the plan. Versus tactics must not become solo Mercenaries rules.'},
    're5-reunion': {'url':'https://gamefaqs.gamespot.com/pc/958470-resident-evil-5/faqs/61756',
        'author':'Jerecaine', 'scope':'RE5 Reunion', 'access':'read',
        'summary':'Choose stun and melee sequences for the actual character, weapon and enemy. Timing and damage assumptions require evaluation under the current modifiers.'},
    're5-bow-community': {'url':'https://gamefaqs.gamespot.com/boards/929197-resident-evil-5/48465634',
        'author':'GameFAQs community', 'scope':'RE5 Tribal Sheva bow', 'access':'indexed',
        'summary':'The longbow lacks laser feedback and long shots need projectile compensation. This is a calibration hypothesis until owner-linked launches and impacts are measured.'},
    're5-route-community': {'url':'https://www.reddit.com/r/residentevil/comments/1j31t50',
        'author':'Reddit community', 'scope':'RE5 Mercenaries', 'access':'indexed',
        'summary':'Players discuss collecting time early and keeping combat productive during travel. Compare routes using measured completion, combo loss, travel time and damage.'},
    're4-manual': {'url':'https://static.capcom.com/residentevil/files/ResEvil2.pdf',
        'author':'Capcom', 'scope':'RE4 classic', 'access':'indexed',
        'summary':'The classic mode has five characters and four battlegrounds. Five-star results belong to its own scoring scale, not RE5 S-rank thresholds.'},
    're6-manual': {'url':'https://game.capcom.com/manual/bio6/en/page-61.html',
        'author':'Capcom', 'scope':'RE6', 'access':'indexed; direct fetch 403',
        'summary':'Melee can extend time; skills and combat mechanics belong to RE6. Do not reuse RE5 button actions, bonus values or movement assumptions.'},
    'mercs3d-manual': {'url':'https://static.capcom.com/manuals/retm/RETM_3DS_DMNL_EN.pdf',
        'author':'Capcom', 'scope':'The Mercenaries 3D', 'access':'indexed',
        'summary':'Treat this standalone title as a separate mission, control and skill profile; sharing assets with another title does not establish compatible hooks.'},
    'village-additional-orders': {'url':'https://blog.playstation.com/2022/07/21/new-re-village-the-mercenaries-additional-orders-details-revealed/',
        'author':'Tsuyoshi Kanda, Capcom', 'scope':'Village Additional Orders', 'access':'read',
        'summary':'The additional characters use distinct ability gauges and combat styles. Model ability state and economy separately from the earlier survival modes.'},
}
ACCESS_LIMITS = {
    'https://www.ign.com/':'Search and direct access blocked by robots.txt on 2026-10-23; no unread tips treated as learned.',
    'https://gamefaqs.gamespot.com/ps3/929198-resident-evil-5/faqs/55979':
        'Original requested URL unavailable; matching author/guide number found in the indexed alternate platform listing.',
}


def profile(title, mode):
    sources = {'G4BE08':['re4-manual'], 'BLUS30491':['re5-basics','re5-original','re5-route-community'],
               'BH6':['re6-manual']}.get(title, [])
    if title == 'BLUS30491':
        sources += ['re5-bow-community']
        if mode == 'reunion': sources += ['re5-reunion']
    return {'version':VERSION, 'title':title, 'mode':mode, 'source_ids':sources,
            'sources':[dict(id=key,**SOURCES[key]) for key in sources],
            'evaluation':['time-bonus coverage','combo continuity','damage incidents','travel and stall time',
                          'native result rank','assistance classification'],
            'runtime_rules':['Native actor and floor validation before travel',
                             'Emergency recovery, healing and mine departure take priority',
                             'Time checkpoints before optional combat detours',
                             'Optional combo pickup requires an observed combat opportunity',
                             'Use title-specific rank, movement and weapon models']}


# This is coverage accounting, not a declaration of playable drivers.
EXPERIENCES = (
    ('re3-mad-jackal','RE3 classic: Operation Mad Jackal',None),
    ('re4-classic','RE4 classic: The Mercenaries','re4'),
    ('re4-vr','RE4 VR: The Mercenaries',None),
    ('re4-remake','RE4 remake: The Mercenaries',None),
    ('re5-original','RE5: The Mercenaries','re5'),
    ('re5-reunion','RE5: The Mercenaries Reunion','re5'),
    ('re5-united','RE5: The Mercenaries United',None),
    ('re5-no-mercy','RE5: No Mercy',None),
    ('re6-original','RE6: The Mercenaries','re6'),
    ('re6-no-mercy','RE6: No Mercy',None),
    ('mercs-3d','Resident Evil: The Mercenaries 3D',None),
    ('village','Village: The Mercenaries',None),
    ('village-additional-orders','Village: The Mercenaries Additional Orders',None),
)


def coverage():
    return [{'id':key,'name':name,'scheduler_title':adapter,
             'state':'verified_adapter_available' if adapter in ('re4','re5') else 'native_driver_required',
             'unattended_ready':False,
             'reason':'Host ROM access and native launch/terminal verification still apply' if adapter in ('re4','re5')
                 else 'Mode inventory only; no verified unattended native gameplay driver'}
            for key,name,adapter in EXPERIENCES]
