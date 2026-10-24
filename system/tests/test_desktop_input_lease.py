import unittest
from types import SimpleNamespace

from gbox.desktop_input_lease import InputLease,MARKER,attach


class DesktopInputLeaseTests(unittest.TestCase):
    def setUp(self):
        self.sent=[];self.secret='private-local-capability'
        self.lease=InputLease(lambda events,**kwargs:self.sent.append((events,kwargs)),self.secret)
    def remote(self,key,down=True,**fields):return {'key':key,'down':down,MARKER:self.secret,**fields}

    def test_disconnect_releases_remote_key_but_preserves_shared_local_or_autobot_hold(self):
        self.lease([{'key':'fire','down':True}])
        self.lease([self.remote('fire'),self.remote('forward')])
        self.lease.release()
        actual={event['key']:event['down'] for event in self.sent[-1][0]}
        self.assertEqual(actual,{'fire':True,'forward':False})
        self.lease([{'key':'fire','down':False}]);self.assertEqual(self.sent[-1][0],[{'key':'fire','down':False}])

    def test_forged_or_previous_private_lease_cannot_clear_the_current_remote_owner(self):
        self.lease([self.remote('fire')])
        self.lease([{'key':'fire','down':False,MARKER:'untrusted'}])
        self.assertTrue(self.sent[-1][0][0]['down'])
        self.assertNotIn(MARKER,self.sent[-1][0][0])

    def test_down_up_batch_preserves_actual_order_and_normal_optional_arguments(self):
        self.lease([{'key':'square','down':True},{'key':'square','down':False}],polite=True)
        self.assertEqual([event['down'] for event in self.sent[-1][0]],[True,False])
        self.assertEqual(self.sent[-1][1],{'polite':True})

    def test_analog_release_reasserts_local_direction_instead_of_centring_it(self):
        axis=lambda identity:(identity[0],'left-x') if identity[1] in ('left','right') else None
        self.lease.axis=axis
        self.lease([self.remote('right')]);self.lease([{'key':'left','down':True}]);self.lease.release()
        self.assertEqual(self.sent[-1][0][-1],{'key':'left','down':True})
        self.assertEqual(self.sent[-1][0][0],{'key':'right','down':False})
        self.assertIn((1,'left'),self.lease.local)

    def test_local_axis_release_restores_still_live_remote_direction(self):
        self.lease.axis=lambda identity:(identity[0],'y') if identity[1] in ('up','down') else None
        self.lease([self.remote('up')]);self.lease([{'key':'down','down':True}])
        self.lease([{'key':'down','down':False}])
        self.assertEqual(self.sent[-1][0][-1],{'key':'up','down':True})

    def test_unknown_remote_event_shape_does_not_generate_input(self):
        self.lease([{MARKER:self.secret,'mouse':{'x':100}},{MARKER:self.secret,'key':'a','player':True}])
        self.assertEqual(self.sent[-1][0],[])

    def test_expired_press_never_becomes_a_new_input_and_dropped_up_clears_only_remote_hold(self):
        self.lease.expired({'key':'unseen','down':True});self.assertEqual(self.sent,[])
        self.lease([{'key':'fire','down':True},self.remote('fire'),self.remote('forward')])
        self.lease.expired({'key':'forward'});self.assertEqual(self.sent[-1][0],[{'key':'forward','down':False}])
        self.lease.expired({'key':'fire'});self.assertEqual(self.sent[-1][0],[{'key':'fire','down':True}])

    def test_native_aliases_share_hold_state_and_actual_scoped_player_stays_separate(self):
        sent=[];scoped=[]
        adapter=SimpleNamespace(name='rpcs3',send_input=lambda rows:sent.extend(rows),
                                send_input_player=lambda rows,player:scoped.extend(rows))
        lease=attach(adapter,self.secret)
        adapter.send_input([{'key':'b','down':True}])
        adapter.send_input([self.remote('cross')]);lease.release()
        self.assertTrue(sent[-1]['down'],'cross and b refer to the same verified native button')
        adapter.send_input_player([{'key':'circle','down':True}],player=2)
        self.assertEqual(scoped[-1]['player'],2)
        self.assertNotIn(MARKER,scoped[-1])
        self.assertIs(attach(adapter,self.secret),lease)
        with self.assertRaises(RuntimeError):attach(adapter,'another-owner')


if __name__=='__main__':unittest.main()
