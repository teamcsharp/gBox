"""Measured RE4 path/round evidence for the shared reviewer, guide and KB outbox.

No RE5 mesh is reused. Unknown geometry, bonus acquisition, score and rank stay
unknown. SQLite, JSON, SVG and Notebook work run on a bounded background writer.
"""
from __future__ import annotations

import math
from pathlib import Path
import queue
import threading
import time
import uuid

COUNTERS=('shots','hits','misses','hits_taken','backoffs','replans','detours','evades','vaults',
          'prompts','prompt_presses','attacks_seen','attacks_prevented','attacks_avoided','attacks_landed',
          'thrown_seen','thrown_shot','quick_turns')


class LegacyRecorder:
    def __init__(self,data_dir,stats,config=None,*,provenance=None):
        self.root=Path(data_dir)/'mercs'
        self.stats=stats;self.config=config;self.active=None;self.last_at=-math.inf
        self.provenance={key:value for key,value in (provenance or {}).items()
            if key in ('source_session_id','source_autoplay_job_id') and isinstance(value,str) and 0<len(value)<=160}
        for key in ('source_session_id','source_autoplay_job_id'):
            self.stats.pop(key,None)
        self.stats.update(self.provenance)

    def observe(self,snap,bot,keys,now,round_id,character='Unknown'):
        pos=(snap.get('player') or {}).get('pos');room=snap.get('room')
        if not pos or len(pos)!=3 or not all(math.isfinite(v) for v in pos) or type(room) is not int \
                or room>>8!=4 or now-self.last_at<.5:
            return
        self.last_at=now
        stage=f'G4BE08-room-{room:04x}-geometry-unknown'
        if self.active is not None and (self.active.input_round_id!=round_id or self.active.stage!=stage):
            self.finish(now,'interrupted',self.stats)
        if self.active is None:
            self.active=_Writer(self.root,round_id,stage,now,character,self.stats,self.config,provenance=self.provenance)
        elif not self.active.thread.is_alive():
            # An exception/long pause ended only the observed fragment. Keep new
            # evidence separate and never present it as a complete whole round.
            self.active=_Writer(self.root,uuid.uuid4().hex,stage,now,character,self.stats,self.config,
                                input_round_id=round_id,fragment=True,provenance=self.provenance)
        player={'id':'p1','slot':1,'control':'bot','actor':snap['player']['ptr'],'pos':list(pos),
            'hp':snap.get('hp'),'hp_max':None,'provenance':{'source':'G4BE08 signed native player pointer/coordinates',
            'native_actor_verified':True,'control_source':'legacy_bot_input_route','inputs_observed':False}}
        frame={'title':'G4BE08','stage':stage,'units_per_m':1000,'player':player,'players':[player],
            'clock':{'left':snap.get('timer'),'combo':snap.get('combo'),'score':None,'kills':None},
            'enemies':[{'id':e.get('slot'),'pos':list(e['pos']),'hp':e.get('hp'),'hp_max':e.get('hp_max'),
                        'routine':e.get('r'),'source':'native_EmMgr'} for e in snap.get('enemies',[])[:128]],
            'plan':{'phase':self.stats.get('phase'),'route':[]},'read_atomic':False,
            'availability':{'geometry':False,'walls':False,'bonus_acquisition':False,'score':False,'rank':False},
            'assistance':{'classification':'unknown','verified':False,'effects':[]}}
        if not self.active.offer((now,frame,tuple(keys))):
            self.stats['legacy_trace_dropped']=self.stats.get('legacy_trace_dropped',0)+1

    def finish(self,now,outcome,stats):
        writer,self.active=self.active,None
        if writer:
            writer.finish(now,outcome,stats)


class _Writer:
    def __init__(self,root,round_id,stage,now,character,stats,config,*,input_round_id=None,fragment=False,provenance=None):
        self.root,self.round_id,self.stage,self.started=root,round_id,stage,now
        self.character,self.stats,self.config=character,stats,config
        self.input_round_id=input_round_id or round_id;self.fragment=fragment
        self.provenance=dict(provenance or {})
        self.baseline={key:stats.get(key,0) for key in COUNTERS}
        self.queue=queue.Queue(maxsize=128);self.closing=None
        self.thread=threading.Thread(target=self.run,name='re4-round-evidence',daemon=True);self.thread.start()

    def offer(self,message):
        if not self.thread.is_alive():return False
        try:self.queue.put_nowait(message);return True
        except queue.Full:return False

    def finish(self,now,outcome,stats):
        metrics={k:v for k,v in stats.items() if isinstance(v,(int,float,str,bool,type(None)))}
        for key in COUNTERS:
            end,start=metrics.get(key,0),self.baseline[key]
            metrics[key]=max(0,end-start) if type(end) in (int,float) and type(start) in (int,float) else None
        metrics['accuracy']=metrics['hits']/metrics['shots'] if metrics.get('shots') else None
        metrics['counter_scope']='this_recorded_round_or_fragment'
        metrics['time_bonus']=None                   # clock gain is not object-acquisition proof
        if self.fragment:
            metrics['observed_terminal_outcome']=outcome
            outcome='interrupted'
        metrics.update(units_per_m=1000,geometry_available=False,score=None,kills=None,result_rank=None,
                       assistance={'classification':'unknown','verified':False,'effects':[]})
        self.closing=(now,outcome,metrics)
        self.thread.join(5.)                  # only between rounds, never on the input tick
        self.stats['legacy_trace_pending']=self.thread.is_alive()

    def run(self):
        from .atlas import NavigationAtlas
        from .notebook import Notebook
        atlas=None
        try:
            atlas=NavigationAtlas(self.root/'navigation','G4BE08')
            metadata={'mode':'mercenaries','character':self.character,'game_stage':self.stage,
                'units_per_m':1000,'geometry_available':False,'source':'native_RE4_coordinates',
                'participants':[{'id':'p1','slot':1,'control':'bot','provenance':{'native_actor_verified':True,
                    'source':'G4BE08 signed player snapshot','inputs_observed':False}}]}
            metadata.update(self.provenance)
            if self.fragment:metadata['fragment_of_round_id']=self.input_round_id
            atlas.observed_stage(self.stage,units_per_m=1000,metadata=metadata)
            atlas.begin(self.round_id,self.stage,self.started,metadata)
            notebook=Notebook(self.root,'G4BE08')
            recalled=notebook.recall(self.stage,'mercenaries',self.stats)
            # Retrieval is visible evidence only until RE4 has a validated policy consumer.
            self.stats['re4_shared_reviews_retrieved']=len(recalled)
            self.stats['re4_shared_policy_consumed']=False
            last_message=time.monotonic();last_at=self.started;max_combo=0
            while True:
                try:
                    at,frame,keys=self.queue.get(timeout=.1)
                    atlas.sample(self.round_id,at,frame,inputs=keys)
                    combo=(frame.get('clock') or {}).get('combo')
                    if type(combo) is int:max_combo=max(max_combo,combo)
                    last_at=at;last_message=time.monotonic()
                except queue.Empty:
                    if self.closing is not None:break
                    if time.monotonic()-last_message>15:
                        self.closing=(last_at,'interrupted',{'units_per_m':1000,
                            'assistance':{'classification':'unknown','verified':False,'effects':[]}})
                        break
            at,outcome,metrics=self.closing
            metrics['max_combo_sampled']=max_combo
            metrics['max_combo']=max_combo
            result=atlas.finish(self.round_id,at,outcome,metrics)
            review=result['review']
            metrics.update(navigation_distance_m=review['distance_m'],
                           nav_oscillations=review['oscillations'],
                           motion_idle_spin_s=review['commanded_stationary_s'])
            notebook.finish(self.stage,'mercenaries',self.character,outcome,metrics,round_id=self.round_id)
            self.stats.update(re4_round_trace=str(result['json']),re4_round_map=str(result['map']),
                re4_round_notebook=str(notebook.path),re4_round_guide=str(notebook.root/'guide.json'))
            if self.config is not None and callable(getattr(self.config,'token',None)):
                notebook.publish(self.config.public_url or 'http://127.0.0.1:8765',self.config.token())
        except Exception as exc:
            self.stats['legacy_trace_error']=str(exc)[:200]
        finally:
            if atlas is not None:atlas.close()
