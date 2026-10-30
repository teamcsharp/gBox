#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
typedef uint64_t U;
static U base=0x100000000ULL;
static unsigned char unit[0x4000], player[0x6000], action[128];
static unsigned requests, updates, refuse;
static unsigned request(U mgr,unsigned id,unsigned priority,U a,unsigned b,unsigned c) {
    assert(mgr==(U)unit+0x13a8 && id==10 && priority==0 && a==0 && b==0xffffffff && c==0);
    ++requests; return !refuse;
}
static void update(U mgr) {
    assert(mgr==(U)unit+0x13a8 && requests==1); ++updates;
    *(U*)action=base+0x288c868;
}
static void bridge(U off,U fn) {
    uint32_t jump[2]={0x58000050,0xd61f0200};
    memcpy((void*)(base+off),jump,8); *(U*)(base+off+8)=fn;
}
static void reset(void) {
    requests=updates=refuse=0;
    *(U*)unit=base+0x284aeb8; *(U*)(unit+0x1300)=(U)player;
    *(uint32_t*)(unit+0x1308)=47; *(uint32_t*)(player+0x1308)=34;
    *(U*)(unit+0x13a8)=base+0x2858318; *(U*)(unit+0x13b0)=(U)unit;
    *(U*)(unit+0x13f0)=(U)action; *(U*)action=base+0x288c9a0;
}
int main(int argc,char **argv) {
    assert(argc==2);
    assert(mmap((void*)base,0x3000000,7,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void*)base);
    FILE *f=fopen(argv[1],"rb"); assert(f);
    assert(fread((void*)(base+0x18f29c0),1,0x500,f)==232); fclose(f);
    bridge(0xf8c7c0,(U)request); bridge(0xf8ce10,(U)update);
    __builtin___clear_cache((char*)base,(char*)base+0x3000000);
    U (*run)(void*,void*,unsigned,unsigned)=(void*)(base+0x18f29c0);
    reset(); assert(run(unit,player,47,34)==1 && requests==1 && updates==1);
    assert(run(unit,player,47,34)==0 && requests==1 && updates==1);
    reset(); refuse=1; assert(run(unit,player,47,34)==0 && requests==1 && updates==0);
    reset(); assert(run(unit,player,48,34)==0 && requests==0);
    reset(); assert(run(unit,player,47,35)==0 && requests==0);
    reset(); *(U*)(unit+0x13b0)=0; assert(run(unit,player,47,34)==0 && requests==0);
    reset(); *(U*)(unit+0x1300)=0; assert(run(unit,player,47,34)==0 && requests==0);
    reset(); *(U*)unit=0; assert(run(unit,player,47,34)==0 && requests==0);
    reset(); *(U*)(unit+0x13f0)=0; assert(run(unit,player,47,34)==0 && requests==0);
    puts("PASS: guarded native explosion transition, no replay, allocation/owner/action rejection");
}
