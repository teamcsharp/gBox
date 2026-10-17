/* Deterministic synthetic libretro core for proxy conformance tests. No game assets. */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
static unsigned char ram[2048];
static int16_t (*input)(unsigned,unsigned,unsigned,unsigned);
struct info {const char *name,*version,*extensions;bool fullpath,extract;};
API void retro_set_environment(void *f){}
API void retro_set_video_refresh(void *f){}
API void retro_set_audio_sample(void *f){}
API void retro_set_audio_sample_batch(void *f){}
API void retro_set_input_poll(void *f){}
API void retro_set_input_state(int16_t (*f)(unsigned,unsigned,unsigned,unsigned)){input=f;}
API void retro_init(void){}
API void retro_deinit(void){}
API unsigned retro_api_version(void){return 1;}
API void retro_get_system_info(struct info*i){i->name="Synthetic test core";i->version="1";i->extensions="bin";i->fullpath=false;i->extract=false;}
API void retro_get_system_av_info(void *i){}
API void retro_set_controller_port_device(unsigned p,unsigned d){}
API bool retro_load_game(void *g){memset(ram,0,2048);return true;}
API bool retro_load_game_special(unsigned t,void*g,size_t n){return false;}
API void retro_unload_game(void){}
API void retro_reset(void){memset(ram,0,2048);}
API void retro_run(void){
 int16_t a=input(0,1,0,256),b=input(1,1,0,8);
 uint32_t n;memcpy(&n,ram,4);n++;memcpy(ram,&n,4);
 for(unsigned i=4;i<2048;i++)ram[i]=(unsigned char)(ram[i]+a+b+i);
 ram[0x75f]=0;ram[0x75c]=(unsigned char)((n/250)%4);ram[0x770]=1;ram[0x772]=3;ram[0xe]=8;
}
API size_t retro_serialize_size(void){return 2048;}
API bool retro_serialize(void*d,size_t n){if(n!=2048)return false;memcpy(d,ram,n);return true;}
API bool retro_unserialize(const void*d,size_t n){if(n!=2048)return false;memcpy(ram,d,n);return true;}
API void retro_cheat_reset(void){}
API void retro_cheat_set(unsigned i,bool on,const char*c){}
API unsigned retro_get_region(void){return 0;}
API void *retro_get_memory_data(unsigned id){return id==2?ram:0;}
API size_t retro_get_memory_size(unsigned id){return id==2?2048:0;}
