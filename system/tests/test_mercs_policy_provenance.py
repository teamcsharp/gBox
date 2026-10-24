import json
from types import SimpleNamespace

from gbox.mercs.notebook import Notebook
from gbox.mercs.titles.re5_ps3 import Bot


def review(rid,stuck=0,policy=True):
    return {'id':rid,'observed':{'stuck':stuck,'reflection':{'policy':{'bonus_commitment':policy}}}}


def test_actual_validated_recall_records_consumed_source_ids_and_real_patience(tmp_path):
    bot=SimpleNamespace(stats={},bonus_commitment=SimpleNamespace(patience_s=0))
    Bot.recall(bot,[review('a'*32,stuck=2),review('b'*32,policy=False),review('not-an-id')])
    assert bot.bonus_commitment.patience_s==16.
    assert bot.stats['round_policy_source_ids']==['a'*32]
    n=Notebook(tmp_path,'BLUS30491')
    n.finish('geometry','mercenaries','Jill','completed',bot.stats,round_id='c'*32)
    with n.connect() as db:
        data=json.loads(db.execute('SELECT data FROM rounds').fetchone()[0])
    assert data['round_policy_source_ids']==['a'*32]
    assert data['bonus_commitment_patience_s']==16.
    Bot.recall(bot,[])
    assert bot.stats['round_policy_source_ids']==[]
    assert bot.bonus_commitment.patience_s==12.


def test_notebook_only_persists_bounded_exact_ids_not_prose_or_payloads(tmp_path):
    n=Notebook(tmp_path,'BLUS30491')
    n.finish('geometry','mercenaries','Jill','completed',{
        'round_policy_source_ids':['a'*32,{'route':[1,2,3]},'instructions','b'*32,'c'*32,'d'*32],
        'round_semantic_round_ids':['e'*32,'bad','f'*32]},round_id='1'*32)
    with n.connect() as db:
        data=json.loads(db.execute('SELECT data FROM rounds').fetchone()[0])
    assert data['round_policy_source_ids']==['a'*32,'b'*32,'c'*32]
    assert data['round_semantic_round_ids']==['e'*32]
