"""Session-owned equipment randomizer: bounded generated gear, no GUI timer or build queue."""
import copy
import random
import threading
import time
import uuid

_states={}
PREFIXES={'weapon':'00','armor':'0101','shield':'0102','mag':'02'}
MARKER=0x80004350


def category(row):
 return next((name for name,prefix in PREFIXES.items() if row['code'].startswith(prefix)),None)


def status(sid):
 state=_states.get(sid,{})
 return {k:copy.deepcopy(v) for k,v in state.items() if k not in ('original','generated','owned','catalog','epoch')}


def epoch_valid(m,state):
 return 'epoch' not in state or m.read(MARKER,16).hex()==state['epoch']


def new_epoch(m,state):
 token=uuid.uuid4().bytes;m.write(MARKER,token);state['epoch']=token.hex()


def cleanup(m,state,kinds=None):
 if not epoch_valid(m,state):raise ValueError('A state load/reset changed the game; old generated-item identities are no longer trusted')
 owned=state.setdefault('owned',{})
 rows=m.inventory()
 for kind,original in state['original'].items():
  if kinds is not None and kind not in kinds:continue
  if any(r['equipped'] and owned.get(r['id'])==kind for r in rows) and any(r['id']==original for r in rows):
   m.equip_id(original)
 for item_id,kind in list(owned.items()):
  if kinds is not None and kind not in kinds:continue
  m.remove_generated(item_id);owned.pop(item_id,None)
  if state['generated'].get(kind)==item_id:state['generated'].pop(kind,None)


def tick(m,state,now):
 if not state.get('on') or now<state['due']:return
 if not epoch_valid(m,state):raise ValueError('A state load/reset was detected; Randomized stopped without deleting game items')
 if not m.u16(m.check()+0x32c):return # no changing gear while dead
 if 'epoch' in state:new_epoch(m,state)
 rows=m.inventory()
 # Never build an unbounded pile. Remove only this mode's tracked generated IDs.
 for kind in state['categories']:
  pool=[r for r in state['catalog'] if category(r)==kind and r.get('rare') and
        (not r.get('classes') or state['character_class'] in r['classes'])]
  if not pool:raise ValueError('No class-compatible rare '+kind+' items in the owned disc catalog')
  row=random.choice(pool);old=state['generated'].get(kind)
  if len(m.inventory())>=30:
   if old is None:raise ValueError('Randomized needs a free inventory slot; your items were retained')
   m.remove_generated(old);state['generated'].pop(kind,None);state.setdefault('owned',{}).pop(old,None);old=None
  result=m.give(row['code'])
  if not result.get('verified') or len(result.get('ids',[]))!=1:raise RuntimeError('Generated rare was not acknowledged; Randomized stopped')
  item_id=result['ids'][0]
  state.setdefault('owned',{})[item_id]=kind
  state['generated'][kind]=item_id
  if not m.equip_id(item_id):raise RuntimeError('The game refused to equip the generated rare; Randomized stopped')
  if old is not None:m.remove_generated(old);state['owned'].pop(old,None)
 state['cycles']+=1;state['due']=now+state['interval'];state['message']='Equipment randomized'
 if 'epoch' in state:new_epoch(m,state)


def configure(sid,ad,ctx,on,interval,categories,character_class,catalog):
 from .pso_gc_extras import Extras
 from .pso_controls import session_lock
 from .psoitems import CLASSES
 if not 5<=interval<=300:raise ValueError('Choose 5 to 300 seconds')
 if on and (not categories or len(set(categories))!=len(categories) or set(categories)-set(PREFIXES)):raise ValueError('Choose weapon, armor, shield and/or mag')
 if on and character_class not in CLASSES:raise ValueError('Choose your class before starting Randomized')
 m=Extras(ad);m.check()
 previous=_states.get(sid)
 if previous and previous.get('on'):
  if on:
   if character_class!=previous['character_class']:raise ValueError('Stop Randomized before changing class')
   for kind in categories:
    if not any(category(r)==kind and r.get('rare') and (not r.get('classes') or character_class in r['classes']) for r in catalog):
     raise ValueError('No class-compatible rare '+kind+' items in the owned disc catalog')
   cleanup(m,previous,set(previous['categories'])-set(categories))
   previous.update(interval=interval,categories=list(categories))
   previous['due']=time.monotonic()+interval
   return status(sid)
 if not on:
  if previous:
   previous['on']=False
   if not epoch_valid(m,previous):
    _states.pop(sid,None)
    return {'on':False,'verified':True,'message':'State load/reset detected. Mode stopped; the restored inventory was left intact.'}
   cleanup(m,previous)
   previous['message']='Randomized stopped; original equipment restored where still present'
  return status(sid)|{'on':False,'verified':True}
 if len(m.inventory())>=30:raise ValueError('Free one inventory slot before starting Randomized')
 for kind in categories:
  if not any(category(r)==kind and r.get('rare') and (not r.get('classes') or character_class in r['classes']) for r in catalog):
   raise ValueError('No class-compatible rare '+kind+' items in the owned disc catalog')
 if previous and previous.get('owned'):raise ValueError('Stop Randomized to clean up the previous generated gear before restarting')
 state={'on':True,'interval':interval,'categories':list(categories),'character_class':character_class,
        'original':{category(r):r['id'] for r in m.inventory() if r['equipped'] and category(r)},
        'generated':{},'owned':{},'catalog':catalog,'due':time.monotonic(),'cycles':0,'message':'Starting Randomized'}
 m.hook();new_epoch(m,state)
 _states[sid]=state
 def watch():
  from .tools import SESSIONS
  while sid in SESSIONS and state.get('on'):
   lock=session_lock(sid)
   if lock.acquire(blocking=False):
    try:
     from .models import Permission
     if Permission.MEMORY_WRITE not in ctx.config.granted_permissions:raise PermissionError('memory_write permission was removed')
     if time.monotonic()>=state['due'] and not getattr(ad,'paused_tids',None):
      if not getattr(ad,'dbg',None) or not ad.dbg.info().get('halted'):tick(m,state,time.monotonic())
    except Exception as error:state.update(on=False,message=str(error)[:250],error=True)
    finally:lock.release()
   time.sleep(.25)
  if sid not in SESSIONS:_states.pop(sid,None)
 threading.Thread(target=watch,name='pso-randomized-'+sid,daemon=True).start()
 return status(sid)|{'verified':True}
