#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
typedef uint64_t U;
static U base=0x100000000ULL;
static unsigned char player[0x5000],unit[0x3000],saved[0x5000];
static unsigned calls,rotations,refuse;
static U create(U manager,U dti,unsigned line,unsigned front,unsigned flags) {
    assert(manager==1234 && dti==base+0x1d71538 && line==10 && front==1 && flags==0);calls++;
    return refuse?0:(U)unit;
}
static void rotate(U ptr,float *v) {
    assert(ptr==(U)unit && v[0]==0 && v[1]==0 && v[2]==0 && v[3]==1);rotations++;
}
static void bridge(U off,U fn) {uint32_t jump[]={0x58000050,0xd61f0200};memcpy((void*)(base+off),jump,8);*(U*)(base+off+8)=fn;}
int main(int argc,char **argv) {
    assert(argc==2);assert(mmap((void*)base,0x3000000,7,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void*)base);
    FILE*f=fopen(argv[1],"rb");assert(f);size_t n=fread((void*)(base+0x118e840),1,0x1c0,f);assert(n>0 && n<0x1c0);fclose(f);
    bridge(0x1c21c0,(U)create);bridge(0xd22880,(U)rotate);*(U*)(base+0x1cf1408)=1234;
    __builtin___clear_cache((char*)base,(char*)base+0x3000000);
    U(*run)(void*,U)=(void*)(base+0x118e840);
    memset(player,0xab,sizeof player);*(U*)(player+0x1a00)=34;*(short*)(player+0x1eb8)=1000;
    memcpy(saved,player,sizeof player);
    assert(run(player,34)==(U)unit && calls==1 && rotations==1);
    assert(memcmp(saved,player,sizeof player)==0);
    assert(!memcmp(unit+0x60,player+0x60,12) && !memcmp(unit+0x2680,player+0x60,12));
    assert(*(U*)(unit+0x1a10)==(U)player && *(uint32_t*)(unit+0x6c)==0);
    assert(run(player,35)==0 && calls==1);
    *(short*)(player+0x1eb8)=0;assert(run(player,34)==0 && calls==1);
    *(short*)(player+0x1eb8)=1;refuse=1;assert(run(player,34)==0 && calls==2 && rotations==1);
    puts("PASS: native constructor ABI, life guards, player/inventory bytes preserved, position and attribution, refusal");
}
