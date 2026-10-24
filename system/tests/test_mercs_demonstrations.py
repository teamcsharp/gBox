"""Human teaching uses durable player ownership and measured geometry, never uploaded coordinates."""
import json

import pytest

from gbox.mercs.reviewer import Reviewer, recorded_players, validated_suggestions, demonstrated_segment
from gbox.mercs.route_guidance import Guidance
from test_mercs_reviewer import evidence, TITLE  # noqa: F401
from test_re5_nav import bus_mesh


def stamp(e, classification="unmodified"):
    with e.atlas.db:
        for seq, payload in e.atlas.db.execute("SELECT seq,payload FROM samples WHERE round_id=?", (e.rid,)).fetchall():
            data = json.loads(payload)
            frame = data["frame"]
            frame["players"] = [dict(frame["player"], id="p1", slot=1, actor=123, control="human",
                                     provenance={"source":"native player reader and controller ownership","native_actor_verified":True,
                                                 "control_source":"operator_assignment_and_bot_input_fence","inputs_observed":False}),
                                dict(frame["player"], id="p2", slot=2, actor=456, control="bot")]
            frame["players"][1]["pos"] = [100., 0., 600.]
            frame["assistance"] = {"classification":classification,"verified":True,"effects":[]}
            e.atlas.db.execute("UPDATE samples SET payload=? WHERE round_id=? AND seq=?", (json.dumps(data),e.rid,seq))


def change(e, seq, update):
    with e.atlas.db:
        row = e.atlas.db.execute("SELECT payload FROM samples WHERE round_id=? AND seq=?", (e.rid,seq)).fetchone()
        data = json.loads(row[0]);update(data["frame"])
        e.atlas.db.execute("UPDATE samples SET payload=? WHERE round_id=? AND seq=?", (json.dumps(data),e.rid,seq))


def body(e, **extra):
    return {"title":TITLE,"round_id":e.rid,"player_id":"p1","start_seq":0,"end_seq":2,"adopt":True,**extra}


def test_human_route_is_derived_from_exact_saved_samples_and_keeps_identity(evidence):
    e = evidence;stamp(e)
    response = e.client.post("/api/mercs/reviewer/demonstrations", json=body(e, points=[[999,999,999]]))
    assert response.status_code==200, response.text
    route = response.json()
    assert route["kind"]=="recorded_demonstration" and route["adopted"] and route["bot_eligible"]
    assert route["points"]==[[100.,0.,100.],[300.,0.,100.]]
    assert route["source"]["sample_count"]==3 and route["source"]["player_actor"]==123
    assert route["source"]["round_source_id"]==f"atlas:{TITLE}:{e.rid}"
    assert route["source"]["control"]=="human" and route["source"]["input_replay"] is False
    assert route["source"]["inputs_observed"] is False
    assert route["source"]["ownership_provenance"]["control_source"]=="operator_assignment_and_bot_input_fence"
    assert len(route["source"]["sample_digest"])==64
    assert route["mode"]=="mercenaries" and route["geometry"]==e.geometry
    assert route["assistance"]["classification"]=="unmodified"
    reopened = Reviewer(e.root).demonstration(route["id"])
    assert reopened==route
    assert validated_suggestions(e.root,TITLE,e.nav)[0]["id"]==route["id"]
    assert e.client.get("/api/mercs/reviewer/demonstrations/"+route["id"]).json()==route


@pytest.mark.parametrize("ownership", ["bot","unknown",None])
def test_bot_or_unknown_samples_cannot_be_relabelled_as_human(evidence, ownership):
    e = evidence;stamp(e)
    change(e,1,lambda f:f["players"][0].update(control=ownership))
    response = e.client.post("/api/mercs/reviewer/demonstrations",json=body(e,control="human"))
    assert response.status_code==400 and "human" in response.text
    assert not e.service.suggestions(TITLE,e.geometry)


def test_legacy_path_remains_unknown_and_cannot_be_taught(evidence):
    e = evidence
    assert recorded_players({"player":{"pos":[0,0,0]}})[0]["control"]=="unknown"
    assert e.client.post("/api/mercs/reviewer/demonstrations",json=body(e,player_id="legacy")).status_code==400
    assert e.service.round(TITLE,e.rid)["players"][0]["control"]=="unknown"


def test_unproven_human_label_is_not_native_ownership_evidence(evidence):
    e=evidence;stamp(e)
    change(e,1,lambda f:f["players"][0].update(provenance={"inputs_observed":False}))
    assert e.client.post("/api/mercs/reviewer/demonstrations",json=body(e)).status_code==400


def test_p1_and_p2_paths_keep_separate_control_and_identity(evidence):
    e = evidence;stamp(e)
    row = e.service.runs(TITLE,paths=True)["runs"][0]
    assert {p["id"]:p["control"] for p in row["paths"]}=={"p1":"human","p2":"bot"}
    assert row["paths"][0]["path"][-1]["pos"]==[300.,0.,100.]
    assert row["paths"][1]["path"][-1]["pos"]==[100.,0.,600.]
    assert e.client.post("/api/mercs/reviewer/demonstrations",json=body(e,player_id="p2")).status_code==400


@pytest.mark.parametrize("fault", ["actor","teleport","missing","gap","mode"])
def test_changed_identity_recording_gap_and_teleport_are_not_teachable(evidence, fault):
    e = evidence;stamp(e)
    if fault=="actor":change(e,1,lambda f:f["players"][0].update(actor=789))
    if fault=="teleport":change(e,1,lambda f:f["players"][0].update(pos=[10000.,0.,100.]))
    if fault=="missing":change(e,1,lambda f:f.update(players=[f["players"][1]]))
    with e.atlas.db:
        if fault=="gap":e.atlas.db.execute("UPDATE samples SET at=105 WHERE round_id=? AND seq=1",(e.rid,))
        if fault=="mode":e.atlas.db.execute("UPDATE rounds SET metadata='{}' WHERE id=?",(e.rid,))
    assert e.client.post("/api/mercs/reviewer/demonstrations",json=body(e)).status_code==400


@pytest.mark.parametrize("start,end", [(True,2),(0,False),(-1,2),(0,0),(2,1),(0,99)])
def test_selected_range_must_match_existing_increasing_samples(evidence, start, end):
    e = evidence;stamp(e)
    assert e.client.post("/api/mercs/reviewer/demonstrations",json=body(e,start_seq=start,end_seq=end)).status_code==400


@pytest.mark.parametrize("classification,verified,expected", [("mod_assisted",True,"mod_assisted"),("mod_assisted",False,"mod_assisted"),("unmodified",False,"unknown"),("unknown",True,"unknown")])
def test_demonstration_does_not_launder_assisted_or_unknown_samples(evidence, classification, verified, expected):
    e = evidence;stamp(e)
    change(e,1,lambda f:f.update(assistance={"classification":classification,"verified":verified,"effects":["fire_rate"]}))
    row = e.service.teach(body(e),"operator")
    assert row["assistance"]["classification"]==expected
    assert row["assistance"]["effects"]==["fire_rate"]


def test_unsupported_path_saves_a_draft_and_cannot_be_adopted(evidence):
    e = evidence;stamp(e)
    for seq in range(3):change(e,seq,lambda f,seq=seq:f["players"][0].update(pos=[800.+seq*200.,0.,100.]))
    row = e.service.teach(body(e),"operator")
    assert not row["adopted"] and not row["bot_eligible"] and row["status"]=="draft"
    assert not validated_suggestions(e.root,TITLE,e.nav)
    assert e.client.post(f"/api/mercs/reviewer/demonstrations/{row['id']}/adopt",json={"adopted":True}).status_code==400


def test_practice_can_be_revoked_without_deleting_recorded_evidence(evidence):
    e = evidence;stamp(e)
    row = e.service.teach(body(e),"operator")
    count = e.atlas.db.execute("SELECT count(*) FROM samples").fetchone()[0]
    response = e.client.post(f"/api/mercs/reviewer/demonstrations/{row['id']}/adopt",json={"adopted":False})
    assert response.status_code==200 and not response.json()["adopted"]
    assert not validated_suggestions(e.root,TITLE,e.nav)
    assert e.atlas.db.execute("SELECT count(*) FROM samples").fetchone()[0]==count
    assert e.service.adopt(row["id"],True)["adopted"]


def test_demonstration_guidance_requires_exact_mode_geometry_selection_and_live_safety(evidence):
    e = evidence;stamp(e)
    row = e.service.teach(body(e),"operator")
    guidance = Guidance(e.root,TITLE)
    guidance.geometry,guidance.at,guidance.rows=e.geometry,0.,[row]
    start,goal=(100.,0.,100.),(300.,0.,100.)
    baseline=e.nav.route(start,goal)
    for mode,selection in ((None,None),("reunion",None),("mercenaries","another")):
        assert guidance.route(e.nav,start,goal,baseline,1.,mode=mode,selected_route_id=selection) is None
    result = guidance.route(e.nav,start,goal,baseline,1.,mode="mercenaries",selected_route_id=row["id"])
    assert result["route"][-1]==goal and result["demonstration_source"]["player_id"]=="p1"
    assert guidance.route(e.nav,start,goal,baseline,1.,mode="mercenaries",hazards=[(goal,50.)]) is None


def test_native_action_link_requires_recorded_completion_and_current_direction():
    mesh = bus_mesh()
    start,goal=(20.,0.,50.),(450.,150.,100.)
    route = mesh.route(start,goal)
    action = next(p for p in route if hasattr(p,"approach"))
    proof = {"geometry":mesh.learning_sig,"verified":True,"from":mesh.find(action.approach,floor_only=True,height_slack=40.),
             "to":mesh.find(action,floor_only=True,height_slack=40.),"approach":action.approach,"landing":list(action),
             "portal":action.portal,"evidence":{"source":"native_player_traversal"}}
    assert not demonstrated_segment(mesh,start,goal,[])
    assert demonstrated_segment(mesh,start,goal,[proof])
    assert not demonstrated_segment(mesh,goal,start,[proof])
    assert not demonstrated_segment(bus_mesh(False),start,goal,[proof])
    assert not demonstrated_segment(mesh,start,goal,[{**proof,"verified":False}])
    g=Guidance('/unused',TITLE);g.geometry,g.at=mesh.learning_sig,0.
    g.rows=[{"id":"native-climb","kind":"recorded_demonstration","adopted":True,"title":TITLE,"mode":"mercenaries",
             "geometry":mesh.learning_sig,"source":{"control":"human"},"points":[start,goal],"traversals":[proof]}]
    result=g.route(mesh,start,goal,route,1.,mode="mercenaries")
    assert result and any(hasattr(p,"approach") for p in result["route"])
    assert g.route(mesh,start,goal,route,1.,mode="mercenaries",hazards=[(action.approach,50.)]) is None


@pytest.mark.parametrize('completed',[True,False])
def test_teaching_action_animation_needs_exact_same_player_native_completion(evidence,completed):
    e=evidence;nav=bus_mesh();geometry=e.atlas.stage(nav)
    action=next(p for p in nav.route((20.,0.,50.),(450.,150.,100.)) if hasattr(p,'approach'))
    rid='b'*32+':'+geometry
    e.atlas.begin(rid,geometry,200.,{'mode':'mercenaries','character':'Chris'})
    start,end=action.approach,tuple(action)
    for seq,pos in enumerate((start,tuple((a+b)/2 for a,b in zip(start,end)),end)):
        p={'id':'p1','slot':1,'actor':123,'control':'human','pos':pos,'hp':1000,'hp_max':1000,
           'provenance':{'native_actor_verified':True,'control_source':'operator_assignment_and_bot_input_fence','inputs_observed':False}}
        e.atlas.sample(rid,200.+seq*.5,{'title':TITLE,'players':[p],'player':p,'assistance':{'classification':'unmodified','verified':True}})
    proof={'player_id':'p1','player_actor':123 if completed else 456,'geometry':geometry,'start_seq':0,'end_seq':2,
           'verified':True,'from':nav.find(start,floor_only=True,height_slack=40.),'to':nav.find(end,floor_only=True,height_slack=40.),
           'approach':start,'landing':end,'portal':action.portal,'evidence':{'source':'native_player_traversal'}}
    e.atlas.event(rid,201.,'traversal_completed',proof);e.atlas.db.commit()
    row=e.service.teach(body(e,round_id=rid),'operator')
    assert row['bot_eligible']==completed and row['adopted']==completed
    assert bool(row['traversals'])==completed
    if completed:
        assert len(row['points'])==2 and row['validation'][0]['valid_action']
        assert validated_suggestions(e.root,TITLE,nav)[0]['id']==row['id']


def test_selected_demo_practice_advances_only_actual_arrivals_and_survives_combat_pause(evidence):
    e=evidence;stamp(e)
    row=e.service.teach(body(e),'operator')
    row['points']=[(100.,0.,100.),(400.,0.,100.),(700.,0.,100.)]
    g=Guidance(e.root,TITLE);g.geometry,g.at,g.rows=e.geometry,0.,[row]
    kwargs={'mode':'mercenaries','selected_route_id':row['id']}
    first=g.practice(e.nav,(100.,0.,100.),1.,**kwargs)
    assert first['index']==1 and first['pos']==(400.,0.,100.)
    # Reappearing near a later point cannot silently skip an unvisited checkpoint.
    paused=g.practice(e.nav,(700.,0.,100.),2.,**kwargs)
    assert paused['index']==1 and paused['id']==first['id']
    blocked=g.practice(e.nav,(200.,0.,100.),3.,hazards=[((400.,0.,100.),100.)],**kwargs)
    assert blocked['status']=='blocked' and blocked['index']==1 and blocked['route']==[]
    next_goal=g.practice(e.nav,(400.,0.,100.),4.,**kwargs)
    assert next_goal['index']==2 and next_goal['pos']==(700.,0.,100.)
    complete=g.practice(e.nav,(700.,0.,100.),4.5,**kwargs)
    assert complete['status']=='completed' and complete['pos'] is None
    assert g.practice(e.nav,(100.,0.,100.),4.6,**kwargs)['status']=='completed'
    g.reset_practice()
    assert g.practice(e.nav,(100.,0.,100.),4.65,**kwargs)['index']==1
    assert g.practice(e.nav,(100.,0.,100.),4.7,mode='reunion',selected_route_id=row['id']) is None
    g.practice(e.nav,(100.,0.,100.),4.8,mode='mercenaries',selected_route_id=None)
    assert g.practice(e.nav,(100.,0.,100.),4.9,**kwargs)['index']==1
