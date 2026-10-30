#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
typedef uint64_t U;
static U base=0x100000000ULL;
static unsigned char player[0x5000],unit[0x3000],saved[0x5000];static unsigned configured,updated;
static void configure(U ptr,U from_player,unsigned pickup,unsigned short id,unsigned count) {
 assert(ptr==(U)unit && from_player==1 && pickup==0 && id==0x108 && count==1);configured++;unit[0x27b9]=1;
}
static void update(U ptr) {assert(ptr==(U)unit && configured==1 && unit[0x24cc]==0x81 && unit[0x27b9]);updated++;unit[0x28a0]=1;}
static void reset(void) {
 memset(player,0,sizeof player);memset(unit,0,sizeof unit);configured=updated=0;
 *(U*)unit=base+0x1c5ef58;*(U*)(unit+0x1a00)=81;*(U*)(unit+0x1a10)=(U)player;
 *(U*)(player+0x1a00)=1;*(short*)(player+0x1eb8)=1000;unit[0x1b88]=1;unit[0x24cc]=0x80;
 *(U*)(unit+0x1fb8)=1;*(U*)(unit+0x1d38)=2;*(unsigned*)(unit+0x1d5c)=3;memcpy(saved,player,sizeof player);
}
static void bridge(U off,U fn) {uint32_t jump[]={0x58000050,0xd61f0200};memcpy((void*)(base+off),jump,8);*(U*)(base+off+8)=fn;}
int main(int argc,char **argv) {
 assert(argc==2);assert(mmap((void*)base,0x3000000,7,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void*)base);
 FILE*f=fopen(argv[1],"rb");assert(f);size_t n=fread((void*)(base+0x118eb00),1,0x400,f);assert(n>0 && n<0x400);fclose(f);
 bridge(0x60d6d0,(U)configure);bridge(0x820e50,(U)update);
 __builtin___clear_cache((char*)base,(char*)base+0x3000000);U(*run)(void*,U,void*,U)=(void*)(base+0x118eb00);
 #define RUN() run(unit,81,player,1)
 reset();assert(RUN()==1 && configured==1 && updated==1 && unit[0x28a0]==1 && !memcmp(saved,player,sizeof player));
 assert(RUN()==0 && configured==1 && updated==1); /* no replay */
 reset();assert(run(0,81,player,1)==0 && !configured);
 reset();assert(run(unit,81,0,1)==0 && !configured);
 reset();*(U*)unit=0;assert(RUN()==0 && !configured);
 reset();*(U*)(unit+0x1a00)=82;assert(RUN()==0 && !configured);
 reset();*(U*)(unit+0x1a10)=0;assert(RUN()==0 && !configured);
 reset();*(U*)(player+0x1a00)=2;assert(RUN()==0 && !configured);
 reset();*(short*)(player+0x1eb8)=1;assert(RUN()==0 && !configured);
 reset();*(U*)(player+0x1a10)=(U)unit;assert(RUN()==0 && !configured); /* reject attribution cycle */
 reset();unit[0x1b88]=0;assert(RUN()==0 && !configured);
 reset();unit[0x1a71]=1;assert(RUN()==0 && !configured);
 reset();*(U*)(unit+0x1fb8)=0;assert(RUN()==0 && !configured);
 reset();*(U*)(unit+0x1d38)=0;assert(RUN()==0 && !configured);
 reset();*(unsigned*)(unit+0x1d5c)=0;assert(RUN()==0 && !configured);
 puts("PASS: native flash callback ABI, life/resource/owner guards, no replay or player writes");
}
