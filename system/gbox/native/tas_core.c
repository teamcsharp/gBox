/* gBox libretro capture/replay proxy. The core owns emulation; this records the
 * exact input callback results and successful state restores in execution order.
 * No libretro/RetroArch implementation code is included. Wire format: tas.py. */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#define API __declspec(dllexport)
#define SYM(name) GetProcAddress(lib, name)
static HMODULE lib;
#else
#include <dlfcn.h>
#define API __attribute__((visibility("default")))
#define SYM(name) dlsym(lib, name)
static void *lib;
#endif
typedef bool (*env_t)(unsigned, void*);
typedef void (*video_t)(const void*,unsigned,unsigned,size_t);
typedef void (*audio_t)(int16_t,int16_t);
typedef size_t (*batch_t)(const int16_t*,size_t);
typedef void (*poll_t)(void);
typedef int16_t (*input_t)(unsigned,unsigned,unsigned,unsigned);
struct game {const char *path;const void *data;size_t size;const char *meta;};
struct sysinfo {const char *name,*version,*extensions;bool fullpath,block_extract;};
struct geometry {unsigned base_width,base_height,max_width,max_height;float aspect;};
struct timing {double fps,sample_rate;};
struct avinfo {struct geometry geometry;struct timing timing;};
static void (*p_init)(void),(*p_deinit)(void),(*p_run)(void),(*p_reset)(void),(*p_unload)(void);
static unsigned (*p_api)(void),(*p_region)(void);
static void (*p_env)(env_t),(*p_video)(video_t),(*p_audio)(audio_t),(*p_batch)(batch_t),(*p_poll)(poll_t),(*p_input)(input_t);
static void (*p_info)(struct sysinfo*),(*p_av)(struct avinfo*),(*p_device)(unsigned,unsigned),(*p_cheat_reset)(void),(*p_cheat_set)(unsigned,bool,const char*);
static bool (*p_load)(const struct game*),(*p_special)(unsigned,const struct game*,size_t),(*p_unserialize)(const void*,size_t);
static size_t (*p_size)(void),(*p_memsize)(unsigned);
static bool (*p_serialize)(void*,size_t);
static void* (*p_mem)(unsigned);
static video_t frontend_video;static audio_t frontend_audio;static batch_t frontend_batch;static input_t frontend_input;
static FILE *tape;static bool playing,recording,failed,initial,preroll,looping,closed;
static uint64_t frame,start_frame,end_frame=UINT64_MAX,loops,max_bytes=536870912;
static uint32_t last_hash;static unsigned failures;static const char *status_path,*seal_path;
static unsigned char *previous_state;static size_t previous_size;
struct query {uint8_t port,device,index;uint16_t id;int16_t value;};
#define MAX_QUERIES 4096
static struct query queries[MAX_QUERIES];static unsigned query_count,query_at;
static unsigned char *payload;static uint32_t payload_size;
static bool library_ready,library_attempted;

static uint32_t u32(const unsigned char *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t u64(const unsigned char *p){return (uint64_t)u32(p)|(uint64_t)u32(p+4)<<32;}
static void put16(unsigned char*p,uint16_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);}
static void put32(unsigned char*p,uint32_t v){put16(p,(uint16_t)v);put16(p+2,(uint16_t)(v>>16));}
static void put64(unsigned char*p,uint64_t v){put32(p,(uint32_t)v);put32(p+4,(uint32_t)(v>>32));}
static uint64_t integer_env(const char *key,uint64_t fallback){const char*v=getenv(key);return v&&*v?strtoull(v,0,10):fallback;}
static uint32_t hash(const void *data,size_t n){const unsigned char*p=(const unsigned char*)data;uint32_t h=2166136261u;while(n--)h=(h^*p++)*16777619u;return h;}
static uint32_t ram_hash(void){void*p=p_mem(2);size_t n=p_memsize(2);return p&&n&&n<=1048576?hash(p,n):0;}
static void status(const char *state,const char *reason){
 if(!status_path)return;
 FILE*f=fopen(status_path,"wb");if(!f)return;
 fprintf(f,"{\"state\":\"%s\",\"reason\":\"%s\",\"frame\":%llu,\"loops\":%llu,\"mismatches\":%u}\n",state,reason,(unsigned long long)frame,(unsigned long long)loops,failures);fclose(f);
}
static void fault(const char *why){if(!failed){failed=true;failures++;status("failed",why);}}
static bool write_record(char tag,const void *data,uint32_t size){
 unsigned char head[5];head[0]=(unsigned char)tag;put32(head+1,size);
 if(!tape||fwrite(head,1,5,tape)!=5||(size&&fwrite(data,1,size,tape)!=size)){fault("recording write failed");return false;}
 return true;
}
static void finish(void){
 if(closed)return;closed=true;
 if(recording&&tape){unsigned char data[8];put64(data,frame);if(!failed)write_record('E',data,8);fflush(tape);}
 if(tape){fclose(tape);tape=0;}
 if(!failed)status(playing?"finished":"captured","");
 recording=false;
}
static bool read_record(char *tag){
 unsigned char head[5];if(!tape||fread(head,1,5,tape)!=5){fault("replay ended without a complete footer");return false;}
 uint32_t n=u32(head+1);if(n>33554432){fault("replay record too large");return false;}
 unsigned char *next=(unsigned char*)realloc(payload,n?n:1);if(!next){fault("replay allocation failed");return false;}payload=next;payload_size=n;
 if(n&&fread(payload,1,n,tape)!=n){fault("truncated replay record");return false;}*tag=(char)head[0];return true;
}
/* Zero/literal RLE over XOR deltas. Each snapshot is independently reconstructible
 * by the streaming indexer; replay keeps just the preceding snapshot in memory. */
static bool snapshot(unsigned reason,const void *provided,size_t size){
 unsigned char *state=0,*encoded=0;bool delta;size_t pos=0,out=14;
 if(!recording||failed)return false;
 if(!provided){size=p_size();if(!size||size>16777216)return false;state=(unsigned char*)calloc(size,1);if(!state||!p_serialize(state,size)){free(state);return false;}}
 else {if(!size||size>16777216){fault("state snapshot exceeds limit");return false;}state=(unsigned char*)malloc(size);if(!state){fault("state allocation failed");return false;}memcpy(state,provided,size);}
 delta=previous_state&&previous_size==size;
 encoded=(unsigned char*)malloc(size*2+32);if(!encoded){free(state);fault("state encoding allocation failed");return false;}
 put64(encoded,frame);encoded[8]=(unsigned char)reason;encoded[9]=(unsigned char)delta;put32(encoded+10,(uint32_t)size);
 while(pos<size){
  size_t count=0;bool zero=(state[pos]^(delta?previous_state[pos]:0))==0;size_t begin=pos;
  while(pos<size&&count<65535&&(((state[pos]^(delta?previous_state[pos]:0))==0)==zero)){pos++;count++;}
  /* Worst case alternating data uses 4 bytes per byte; fold tiny zero runs into a literal. */
  if(count<4){zero=false;pos=begin;count=0;while(pos<size&&count<65535){size_t z=0;while(pos+z<size&&z<4&&(state[pos+z]^(delta?previous_state[pos+z]:0))==0)z++;if(z>=4&&count)break;pos++;count++;}}
  put16(encoded+out,(uint16_t)count);encoded[out+2]=zero?0:1;out+=3;
  if(!zero){for(size_t i=0;i<count;i++)encoded[out++]=state[begin+i]^(delta?previous_state[begin+i]:0);}
 }
 bool ok=write_record('S',encoded,(uint32_t)out);free(encoded);free(previous_state);previous_state=state;previous_size=size;return ok;
}
static bool apply_snapshot(void){
 if(payload_size<14)return false;size_t size=u32(payload+10),out=0,pos=14;bool delta=payload[9]!=0;
 if(!size||size>16777216||(delta&&previous_size!=size))return false;
 unsigned char *state=(unsigned char*)calloc(size,1);if(!state)return false;
 while(pos<payload_size){if(pos+3>payload_size){free(state);return false;}unsigned n=payload[pos]|payload[pos+1]<<8;unsigned kind=payload[pos+2];pos+=3;
  if(!n||out+n>size||kind>1||(kind&&pos+n>payload_size)){free(state);return false;}
  for(unsigned i=0;i<n;i++)state[out+i]=(kind?payload[pos+i]:0)^(delta?previous_state[out+i]:0);
  if(kind)pos+=n;out+=n;
 }
 if(out!=size){free(state);return false;}
 bool restore=payload[8]!=2;bool ok=!restore||p_unserialize(state,size);
 free(previous_state);previous_state=state;previous_size=size;return ok;
}
static int16_t input(unsigned port,unsigned device,unsigned index,unsigned id){
 if(playing){
  if(query_at>=query_count){fault("core requested an unrecorded input");return 0;}struct query*q=&queries[query_at++];
  if(q->port!=port||q->device!=device||q->index!=index||q->id!=id){fault("core input callback sequence changed");return 0;}return q->value;
 }
 int16_t value=frontend_input?frontend_input(port,device,index,id):0;
 if(recording&&!failed){if(query_count>=MAX_QUERIES||port>255||device>255||index>255||id>65535)fault("input event exceeds capture limits");else {struct query*q=&queries[query_count++];q->port=(uint8_t)port;q->device=(uint8_t)device;q->index=(uint8_t)index;q->id=(uint16_t)id;q->value=value;}}
 return value;
}
static void video(const void *d,unsigned w,unsigned h,size_t pitch){if(!preroll&&frontend_video)frontend_video(d,w,h,pitch);}
static void audio(int16_t l,int16_t r){if(!preroll&&frontend_audio)frontend_audio(l,r);}
static size_t batch(const int16_t*d,size_t n){return !preroll&&frontend_batch?frontend_batch(d,n):n;}
static bool open_tape(void){
 const char*play=getenv("GBOX_TAS_PLAY"),*record=getenv("GBOX_TAS_RECORD");unsigned char header[16]={0};
 status_path=getenv("GBOX_TAS_STATUS");seal_path=getenv("GBOX_TAS_SEAL");playing=play&&*play;recording=!playing&&record&&*record;
 if(!playing&&!recording)return true;
 tape=fopen(playing?play:record,playing?"rb":"wb");if(!tape){fault("cannot open managed replay file");return false;}
 if(playing){if(fread(header,1,16,tape)!=16||memcmp(header,"GBTAS001",8)||u32(header+8)!=1){fault("unsupported replay header");return false;}}
 else {memcpy(header,"GBTAS001",8);put32(header+8,1);if(fwrite(header,1,16,tape)!=16){fault("cannot write replay header");return false;}}
 start_frame=integer_env("GBOX_TAS_FROM",0);end_frame=integer_env("GBOX_TAS_TO",UINT64_MAX);looping=integer_env("GBOX_TAS_LOOP",0)!=0;max_bytes=integer_env("GBOX_TAS_MAX_BYTES",max_bytes);
 status(playing?"playing":"recording","");return true;
}
static bool next_frame(void){
 for(;;){char tag;if(!read_record(&tag))return false;
  if(tag=='S'){if(!apply_snapshot()){fault("checkpoint restore failed");return false;}continue;}
  if(tag=='R'){p_reset();continue;}
  if(tag=='E')return false;
  if(tag!='F'||payload_size<28){fault("invalid replay frame");return false;}
  frame=u64(payload);query_count=payload[8]|payload[9]<<8;query_at=0;
  if(query_count>MAX_QUERIES||payload_size!=28+query_count*7){fault("invalid input frame size");return false;}
  for(unsigned i=0;i<query_count;i++){unsigned char *v=payload+28+7*i;queries[i].port=v[0];queries[i].device=v[1];queries[i].index=v[2];queries[i].id=v[3]|v[4]<<8;queries[i].value=(int16_t)(v[5]|v[6]<<8);}
  return true;
 }
}
static bool rewind_tape(void){
 if(fseek(tape,16,SEEK_SET)){fault("cannot loop replay");return false;}
 free(previous_state);previous_state=0;previous_size=0;frame=0;loops++;return true;
}
API void retro_run(void){
 if(recording&&seal_path&&frame%15==0){FILE*f=fopen(seal_path,"rb");if(f){fclose(f);finish();}}
 if(failed||closed){if(!playing)p_run();return;} /* capture failure must never stop human gameplay */
 if(playing){
  unsigned steps=0;
  do {
   if(frame>=end_frame){if(looping){if(!rewind_tape())return;}else{finish();return;}}
   if(!next_frame()){if(!failed&&looping){if(!rewind_tape()||!next_frame())return;}else {if(!failed)finish();return;}}
   if(frame>=end_frame){if(looping){if(!rewind_tape())return;continue;}finish();return;}
   uint32_t expected=u32(payload+12);preroll=frame<start_frame;p_run();preroll=false;
   if(query_at!=query_count){fault("core consumed fewer inputs than recorded");return;}
   if(ram_hash()!=expected){fault("emulated RAM diverged from the recorded frame");return;}
   frame++;if(frame%60==0)status("playing","");
  }while(frame<start_frame&&++steps<600);
  return;
 }
 if(recording){
  uint32_t before=ram_hash();
  if(!initial){if(!snapshot(0,0,0)){fault("core cannot serialize initial state");}initial=true;}
  else if(before!=last_hash){snapshot(3,0,0);}
  else if(frame%300==0){snapshot(2,0,0);}
  query_count=0;
 }
 p_run();
 if(recording&&!failed){
  unsigned char data[28+MAX_QUERIES*7];memset(data,0,28);put64(data,frame);put16(data+8,(uint16_t)query_count);last_hash=ram_hash();put32(data+12,last_hash);
  unsigned char *ram=(unsigned char*)p_mem(2);size_t n=p_memsize(2);
  if(ram&&n>=2048){unsigned offsets[8]={0x75f,0x75c,0x750,0x770,0x772,0xe,0x754,9};for(unsigned i=0;i<8;i++)data[20+i]=ram[offsets[i]];}
  for(unsigned i=0;i<query_count;i++){unsigned char*v=data+28+7*i;struct query*q=&queries[i];v[0]=q->port;v[1]=q->device;v[2]=q->index;put16(v+3,q->id);put16(v+5,(uint16_t)q->value);}
  write_record('F',data,28+7*query_count);frame++;
  if(frame%60==0){fflush(tape);status("recording","");long pos=ftell(tape);if(pos<0||(uint64_t)pos>=max_bytes){finish();status("budget_stop","complete captured prefix retained; game continues");}}
 }
}
static bool load_library(void){
 if(library_attempted)return library_ready;library_attempted=true;const char*path=getenv("GBOX_TAS_CORE");if(!path||!*path)return false;
#ifdef _WIN32
 lib=LoadLibraryA(path);
#else
 lib=dlopen(path,RTLD_NOW|RTLD_LOCAL);
#endif
 if(!lib)return false;
#define BIND(variable,name) do {*(void**)(&variable)=(void*)SYM(name);if(!variable)return false;}while(0)
 BIND(p_init,"retro_init");BIND(p_deinit,"retro_deinit");BIND(p_run,"retro_run");BIND(p_reset,"retro_reset");BIND(p_unload,"retro_unload_game");
 BIND(p_api,"retro_api_version");BIND(p_region,"retro_get_region");BIND(p_env,"retro_set_environment");BIND(p_video,"retro_set_video_refresh");BIND(p_audio,"retro_set_audio_sample");BIND(p_batch,"retro_set_audio_sample_batch");BIND(p_poll,"retro_set_input_poll");BIND(p_input,"retro_set_input_state");
 BIND(p_info,"retro_get_system_info");BIND(p_av,"retro_get_system_av_info");BIND(p_device,"retro_set_controller_port_device");BIND(p_cheat_reset,"retro_cheat_reset");BIND(p_cheat_set,"retro_cheat_set");BIND(p_load,"retro_load_game");BIND(p_special,"retro_load_game_special");BIND(p_size,"retro_serialize_size");BIND(p_serialize,"retro_serialize");BIND(p_unserialize,"retro_unserialize");BIND(p_mem,"retro_get_memory_data");BIND(p_memsize,"retro_get_memory_size");library_ready=true;return true;
}
API void retro_set_environment(env_t f){if(load_library())p_env(f);}
API void retro_set_video_refresh(video_t f){frontend_video=f;if(load_library())p_video(video);}
API void retro_set_audio_sample(audio_t f){frontend_audio=f;if(load_library())p_audio(audio);}
API void retro_set_audio_sample_batch(batch_t f){frontend_batch=f;if(load_library())p_batch(batch);}
API void retro_set_input_poll(poll_t f){if(load_library())p_poll(f);}
API void retro_set_input_state(input_t f){frontend_input=f;if(load_library())p_input(input);}
API unsigned retro_api_version(void){return load_library()?p_api():1;}
API void retro_init(void){if(load_library())p_init();}
API void retro_deinit(void){finish();if(library_ready)p_deinit();}
API void retro_get_system_info(struct sysinfo*i){memset(i,0,sizeof(*i));if(load_library())p_info(i);}
API void retro_get_system_av_info(struct avinfo*i){if(load_library())p_av(i);}
API void retro_set_controller_port_device(unsigned p,unsigned d){if(load_library())p_device(p,d);}
API bool retro_load_game(const struct game*g){if(!load_library()||!p_load(g))return false;open_tape();return true;}
API bool retro_load_game_special(unsigned t,const struct game*g,size_t n){return load_library()&&p_special(t,g,n);}
API void retro_unload_game(void){finish();if(library_ready)p_unload();}
API void retro_reset(void){if(playing)return;if(recording&&initial)write_record('R',0,0);if(library_ready)p_reset();}
API size_t retro_serialize_size(void){return library_ready?p_size():0;}
API bool retro_serialize(void*d,size_t n){return library_ready&&p_serialize(d,n);}
API bool retro_unserialize(const void*d,size_t n){if(playing)return false;bool ok=library_ready&&p_unserialize(d,n);if(ok&&recording&&initial){snapshot(1,d,n);last_hash=ram_hash();}return ok;}
API void retro_cheat_reset(void){if(library_ready&&!playing)p_cheat_reset();}
API void retro_cheat_set(unsigned i,bool e,const char*c){if(library_ready&&!playing)p_cheat_set(i,e,c);}
API unsigned retro_get_region(void){return library_ready?p_region():0;}
API void*retro_get_memory_data(unsigned i){return library_ready?p_mem(i):0;}
API size_t retro_get_memory_size(unsigned i){return library_ready?p_memsize(i):0;}
