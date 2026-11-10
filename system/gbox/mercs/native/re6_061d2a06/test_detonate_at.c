#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
typedef uint64_t U;
static U base=0x100000000ULL;
static unsigned char unit[0x4000], player[0x6000], action[128];
static unsigned requests, updates, refuse;
static const uint32_t X=0x44fa0000, Z=0xc4bb8000, OLDY=0x42c80000;   /* 2000.0, -1500.0; the floor 100.0 */
static unsigned request(U mgr,unsigned id,unsigned priority,U a,unsigned b,unsigned c) {
    assert(mgr==(U)unit+0x13a8 && id==10 && priority==0 && a==0 && b==0xffffffff && c==0);
    assert(*(uint32_t*)(unit+0x60)==X && *(uint32_t*)(unit+0x64)==OLDY && *(uint32_t*)(unit+0x68)==Z);
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
static void reset(U vt) {
    requests=updates=refuse=0;
    *(U*)unit=vt; *(U*)(unit+0x1300)=(U)player;
    *(uint32_t*)(unit+0x1308)=47; *(uint32_t*)(player+0x1308)=34;
    *(uint32_t*)(unit+0x60)=0; *(uint32_t*)(unit+0x64)=OLDY; *(uint32_t*)(unit+0x68)=0;
    *(U*)(unit+0x13a8)=base+0x2858318; *(U*)(unit+0x13b0)=(U)unit;
    *(U*)(unit+0x13f0)=(U)action; *(U*)action=base+0x288c9a0;
}
int main(int argc,char **argv) {
    assert(argc==3);
    unsigned size; assert(sscanf(argv[2],"%u",&size)==1);
    assert(mmap((void*)base,0x3000000,7,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void*)base);
    FILE *f=fopen(argv[1],"rb"); assert(f);
    assert(fread((void*)(base+0x18f2c00),1,0x400,f)==size); fclose(f);
    bridge(0xf8c7c0,(U)request); bridge(0xf8ce10,(U)update);
    __builtin___clear_cache((char*)base,(char*)base+0x3000000);
    U (*run)(void*,void*,U,U,U,U,U)=(void*)(base+0x18f2c00);
    const U vts[3]={base+0x284b788,base+0x284b328,base+0x284aeb8};   /* uWp1091 hand, uWp1093 fire, uWp1095 flash */
    for(int i=0;i<3;i++) {
        U vt=vts[i];
        reset(vt); assert(run(unit,player,47,34,vt,X,Z)==1 && requests==1 && updates==1);
        assert(*(uint32_t*)(unit+0x64)==OLDY);                          /* the floor height is kept */
        /* already exploding: reported (2), never requested again */
        assert(run(unit,player,47,34,vt,X,Z)==2 && requests==1 && updates==1);
        reset(vt); refuse=1; assert(run(unit,player,47,34,vt,X,Z)==0 && requests==1 && updates==0);
        reset(vt); assert(run(unit,player,48,34,vt,X,Z)==0 && requests==0);
        reset(vt); assert(run(unit,player,47,35,vt,X,Z)==0 && requests==0);
        reset(vt); *(U*)(unit+0x13b0)=0; assert(run(unit,player,47,34,vt,X,Z)==0 && requests==0);
        reset(vt); *(U*)(unit+0x13a8)=0; assert(run(unit,player,47,34,vt,X,Z)==0 && requests==0);
        reset(vt); *(U*)(unit+0x1300)=0; assert(run(unit,player,47,34,vt,X,Z)==0 && requests==0);
        reset(vt); *(U*)(unit+0x13f0)=0; assert(run(unit,player,47,34,vt,X,Z)==0 && requests==0);
        reset(vt); *(U*)action=0; assert(run(unit,player,47,34,vt,X,Z)==0 && requests==0);
        /* the class must match the one the caller expects */
        reset(vt); assert(run(unit,player,47,34,vts[(i+1)%3],X,Z)==0 && requests==0);
        assert(*(uint32_t*)(unit+0x60)==0 && *(uint32_t*)(unit+0x68)==0); /* refused: never moved */
    }
    /* any other expected class (the remote bomb uWp1097, zero, a guess) is refused even if the unit matches it */
    const U refused[3]={base+0x284aa58,0,base+0x284aeb0};
    for(int i=0;i<3;i++) { reset(refused[i]); assert(run(unit,player,47,34,refused[i],X,Z)==0 && requests==0); }
    puts("PASS: ring explosion for hand/incendiary/flash only, x/z on the ring, already-exploding report, no replay, rejection");
}
