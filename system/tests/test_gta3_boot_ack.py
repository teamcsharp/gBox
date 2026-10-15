"""A consumed native bootstrap write needs execution evidence, never a retry."""
import struct

import pytest

from gbox import gta_mods_tool as G


def test_read_only_game_catalogue_still_works_without_an_adapter():
    assert G.run(None,'','games')['games']


@pytest.mark.parametrize('fault',[None,'cave','header','boot','vtable','hook','pending'])
def test_immediate_boot_restore_requires_complete_native_ack(monkeypatch,fault):
    profile={'name':'test owned GTA','hook_frame':0x150000,'hook_frame_fn':0x151000,
             'boot_vt':0x160000,'boot_fn':0x161000,'fn':{}}
    code=b'owned dispatcher'*8;symbols={'boot':G.CAVE,'dispatch':G.CAVE+16}
    monkeypatch.setattr(G,'build_cave',lambda _: (code,symbols))
    class Adapter:
        def __init__(self):self.ram=bytearray(0x200000);self.boot_writes=0;self.ran=False
        def word(self,a,v):struct.pack_into('<I',self.ram,a,v)
        def read_memory(self,a,n):
            if a==G.DATA+G.D_FRAME and self.ran:self.word(a,struct.unpack_from('<I',self.ram,a)[0]+1)
            return self.ram[a:a+n]
        def write_memory(self,a,data):
            self.ram[a:a+len(data)]=data
            if a==profile['boot_vt']:
                self.boot_writes+=1;self.ran=True
                self.word(a,profile['boot_fn']);self.word(G.DATA+G.D_BOOT,1)
                self.word(profile['hook_frame'],G.jal_word(symbols['dispatch']))
                self.word(G.DATA+G.D_PQ_N,0)
                if fault=='cave':self.ram[G.CAVE]^=1
                elif fault=='header':self.word(G.DATA+G.D_VER,0)
                elif fault=='boot':self.word(G.DATA+G.D_BOOT,0)
                elif fault=='vtable':self.word(a,0x1234)
                elif fault=='hook':self.word(profile['hook_frame'],0x1234)
                elif fault=='pending':self.word(G.DATA+G.D_PQ_N,1)
                raise RuntimeError('memory write not confirmed by read-back')
    ad=Adapter();ad.word(profile['hook_frame'],G.jal_word(profile['hook_frame_fn']));ad.word(profile['boot_vt'],profile['boot_fn'])
    if fault:
        with pytest.raises(RuntimeError,match='read-back'):G.install(G.Mem(ad),profile)
    else:
        result=G.install(G.Mem(ad),profile)
        assert result['installed'] and 'advancing dispatcher' in result['bootstrap_ack']
    assert ad.boot_writes==1


@pytest.mark.parametrize('fault',[None,'payload','header','counter','pending'])
def test_consumed_call_mailbox_requires_exact_completed_batch(monkeypatch,fault):
    class Adapter:
        def __init__(self):self.ram=bytearray(0x100000);self.submissions=0
        def word(self,a,v):struct.pack_into('<I',self.ram,a,v)
        def read_memory(self,a,n):return self.ram[a:a+n]
        def write_memory(self,a,data):
            self.ram[a:a+len(data)]=data
            if a==G.DATA+G.D_CQ_N:
                self.submissions+=1
                self.word(a,0);self.word(G.DATA+G.D_CQ_DONE,1)
                self.word(G.DATA+G.D_CQ+0x24,123)
                if fault=='payload':self.word(G.DATA+G.D_CQ,0x1234)
                elif fault=='header':self.word(G.DATA+G.D_MAGIC,0)
                elif fault=='counter':self.word(G.DATA+G.D_CQ_DONE,2)
                elif fault=='pending':self.word(a,3)
                raise RuntimeError('memory write not confirmed by read-back')
    ad=Adapter();ad.word(G.DATA+G.D_MAGIC,G.MAGIC);ad.word(G.DATA+G.D_VER,G.VERSION);ad.word(G.DATA+G.D_BOOT,1)
    batch=[{'fn':0x1D8950,'a0':0x200000,'a1':2,'a2':100}]
    if fault:
        with pytest.raises(RuntimeError,match='read-back'):G.call(G.Mem(ad),batch)
    else:assert G.call(G.Mem(ad),batch)==[123]
    assert ad.submissions==1


@pytest.mark.parametrize('operation,pending',[(G.call,G.D_CQ_N),(G.queue_patches,G.D_PQ_N)])
def test_existing_pending_batch_times_out_without_writing(operation,pending):
    class Adapter:
        def read_memory(self,a,n):return struct.pack('<I',1) if a==G.DATA+pending else bytes(n)
        def write_memory(self,*_):pytest.fail('No new mailbox data may be written')
    with pytest.raises(RuntimeError,match='no new'):operation(G.Mem(Adapter()),[],timeout=0)


def test_inventory_and_existing_gta_tool_share_one_adapter_transaction(monkeypatch):
    import threading
    from gbox import gta3_items as I
    class Adapter:pass
    ad=Adapter();entered=threading.Event();release=threading.Event();other_finished=threading.Event()
    def inventory(*args):entered.set();assert release.wait(2);return {}
    monkeypatch.setattr(I,'_execute',inventory)
    first=threading.Thread(target=lambda:I.execute(ad,{}));first.start();assert entered.wait(1)
    second=threading.Thread(target=lambda:(G.run(ad,'','games'),other_finished.set()));second.start()
    try:
        assert not other_finished.wait(.05)
        assert G.run(Adapter(),'','games')['games'] # another session remains independent
    finally:
        release.set();first.join(2);second.join(2)
    assert other_finished.is_set()
