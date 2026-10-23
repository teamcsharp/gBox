from types import SimpleNamespace

import pytest

from gbox.mercs import engine, notebook
from gbox.mercs.titles import re5_ps3 as R


@pytest.mark.parametrize("public_url,expected",[("https://gbox.example","https://gbox.example"),(None,"http://127.0.0.1:8765")])
def test_engine_configures_semantic_recall_before_first_round_recall(tmp_path,monkeypatch,public_url,expected):
    calls = []
    class Notebook:
        path = tmp_path/"rounds.sqlite"
        root = tmp_path
        def __init__(self,*args):calls.append("created")
        def configure_knowledge(self,server,token):calls.append((server,token))
        def recall(self,*args):
            assert calls[1]==(expected,"mock-test-token")
            calls.append("recall")
            return []
        def finish(self,*args,round_id=None):return {"id":round_id}
        def publish(self,*args):pass
    class Driver:
        frame = None
        def snapshot(self,m):return {"player":{"hp":100},"timer":100.}
        def screen(self,m,snap):return "playing"
        def progress(self,snap):return {}
        def prompt_source(self,*args):return lambda:None
        def prompt_keys(self,b):return []
    class Brain:
        def tick(self,snap):return {"hold":set()}
        def prompt_ok(self,*args):return True
        def save(self):pass
    monkeypatch.setattr(notebook,"Notebook",Notebook)
    counter = [0]
    def stopped():
        counter[0]+=1
        return counter[0]>1
    memory = SimpleNamespace(adapter=SimpleNamespace(config=SimpleNamespace(public_url=public_url,token=lambda:"mock-test-token")))
    engine.play_round({"map_id":"TEST"},memory,lambda _:None,stopped,{},driver=Driver(),brain=Brain(),sleep=lambda _:None)
    assert calls==["created",(expected,"mock-test-token"),"recall"]


def test_kill_clock_credit_and_unconfirmed_removal_never_claim_an_hourglass(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    player = {"pos":(100.,0.,100.),"rot":0.,"hp":1000,"hp_max":1000}
    bonus = {"ptr":77,"kind":"time","pos":(200.,0.,100.)}
    bot.observe_round({"player":player,"timer":100.,"kills":0,"bonuses":[bonus]},"playing",0.)
    bot.observe_round({"player":player,"timer":109.9,"kills":1,"bonuses":[]},"playing",.1)
    assert bot.stats["clock_gain_s"]==9.9 and bot.stats["clock_jumps"]==1
    assert bot.stats["bonus_actor_removals"]==1
    assert bot.stats.get("bonuses_taken",0)==bot.stats.get("bonus_s",0)==0
