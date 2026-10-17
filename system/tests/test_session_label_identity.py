"""Legacy and native-demo labels must not stop the Spark scheduler's operator gate."""
import json
from gbox.store import Store
from gbox.spark_grunt import operator_session_on


def test_labels_written_without_embedded_identity_preserve_agent_ownership(tmp_path):
    store = Store(tmp_path)
    body = {'owner': 'agent', 'task': 'native demo'}
    store.put('slabel', 'spark-demo', body)
    assert body == {'owner': 'agent', 'task': 'native demo'}
    labels = {row['session_id']: row for row in store.all('slabel')}
    assert labels['spark-demo']['owner'] == 'agent'
    sessions = [{'session_id': 'spark-demo', 'state': 'running'}]
    assert operator_session_on(sessions, labels, {'spark'}) is None
    sessions.append({'session_id': 'spark-player', 'state': 'running'})
    assert operator_session_on(sessions, labels, {'spark'})['session_id'] == 'spark-player'
    store.put('unrelated', 'x', body)
    assert store.get('unrelated', 'x') == body


def test_existing_labels_are_backfilled_and_direct_updates_stay_consistent(tmp_path):
    store = Store(tmp_path)
    store.db.executescript('DROP TRIGGER slabel_identity_insert; DROP TRIGGER slabel_identity_update;')
    store.put('slabel', 'spark-old', {'owner': 'agent', 'task': 'legacy demo'})
    store.db.close()
    store = Store(tmp_path)
    assert store.get('slabel', 'spark-old') == {'owner': 'agent', 'task': 'legacy demo', 'session_id': 'spark-old'}
    store.db.execute("UPDATE docs SET body=? WHERE kind='slabel' AND id='spark-old'",
                     (json.dumps({'owner': 'you', 'session_id': 'wrong'}),))
    store.db.commit()
    assert store.get('slabel', 'spark-old') == {'owner': 'you', 'session_id': 'spark-old'}
