#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
typedef uint64_t U;
typedef void (*Tick)(U,U,U,U,U,U,U,U,double,double,double,double,double,double,double,double);
static unsigned calls, allocations, updates;
static int fail_alloc;
static U manager;
static void *allocate(void *a, U size, unsigned align) {
    assert(size==1024 && align==16); allocations++;
    return fail_alloc ? NULL : aligned_alloc(16, size);
}
static U sum(U a,U b,U c,U d,U e,U f,U g,U h) { calls++; return a+b+c+d+e+f+g+h; }
static void original(U a,U b,U c,U d,U e,U f,U g,U h,
                     double q0,double q1,double q2,double q3,double q4,double q5,double q6,double q7) {
    assert(a==manager && b==2 && c==3 && d==4 && e==5 && f==6 && g==7 && h==8);
    assert(q0==.5 && q1==1.5 && q2==2.5 && q3==3.5 && q4==4.5 && q5==5.5 && q6==6.5 && q7==7.5);
    updates++;
}
static void tick(U fn) { ((Tick)fn)(manager,2,3,4,5,6,7,8,.5,1.5,2.5,3.5,4.5,5.5,6.5,7.5); }
int main(int argc,char **argv) {
    assert(argc==2);
    U base=0x100000000ULL;
    void *map=mmap((void*)base,0x3000000,PROT_READ|PROT_WRITE|PROT_EXEC,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    assert(map==(void*)base);
    FILE *f=fopen(argv[1],"rb"); assert(f);
    assert(fread((void*)(base+0x18f2640),1,0x9c0,f)>0); fclose(f);
    // Branch islands to ordinary C functions preserve argument registers.
    uint32_t jump[2]={0x58000050,0xd61f0200};
    memcpy((void*)(base+0xf8ce10),jump,8);
    *(U*)(base+0xf8ce18)=(U)original;
    __builtin___clear_cache((char*)map,(char*)map+0x3000000);
    U original_vt=base+0x2858318, temp_vt=base+0x25a3100;
    U *vt=(U*)original_vt;
    for(int i=0;i<11;i++) vt[i]=0xaaaa0000+i;
    vt[9]=base+0xf8ce10;
    memcpy((void*)temp_vt,vt,88); ((U*)temp_vt)[9]=base+0x18f2640;
    manager=base+0x2b10000;
    U player=base+0x2b20000;
    ((U*)manager)[1]=player;
    *(uint32_t*)(player+0x1308)=33;
    U alloc_vt[16]={0}, allocator[1]={(U)alloc_vt};
    alloc_vt[7]=(U)allocate;
    *(uint32_t*)(base+0x2a51b78)=3U<<23;
    *(U*)(base+0x296cc48+3*8)=(U)allocator;
    *(U*)manager=temp_vt;
    tick(base+0x18f2640);
    U heap=*(U*)manager;
    assert(heap!=temp_vt && heap!=original_vt && allocations==1 && updates==1);
    for(int i=0;i<11;i++) assert(((U*)heap)[i] == (i==9 ? base+0x18f2780 : vt[i]));
    assert(*(U*)(heap+0x80)==original_vt && *(U*)(heap+0x90)==player);
    assert(*(uint32_t*)(heap+0x98)==33);
    assert(memcmp((void*)(heap+0xa0),"GBXNC001",8)==0);
    *(U*)(heap+0xc0)=(U)sum;
    for(int i=0;i<8;i++) *(U*)(heap+0xc8+i*8)=i+1;
    *(uint32_t*)(heap+0xa8)=1;
    tick(base+0x18f2780);
    assert(*(uint32_t*)(heap+0xa8)==3 && *(U*)(heap+0xb8)==36 && calls==1 && updates==2);
    tick(base+0x18f2780);
    assert(calls==1 && updates==3);
    *(uint32_t*)(heap+0xa8)=1;
    *(uint32_t*)(player+0x1308)=34;
    tick(base+0x18f2780);
    assert(calls==1 && updates==4 && *(uint32_t*)(heap+0xa8)==1);
    *(uint32_t*)(player+0x1308)=33;
    ((U*)manager)[1]=base+0x2b30000;
    tick(base+0x18f2780);
    assert(calls==1 && updates==5);
    ((U*)manager)[1]=player;
    *(U*)manager=original_vt;
    tick(base+0x18f2640);
    assert(allocations==1 && updates==6);
    fail_alloc=1; *(U*)manager=temp_vt;
    tick(base+0x18f2640);
    assert(*(U*)manager==original_vt && allocations==2 && updates==7);
    free((void*)heap); munmap(map,0x3000000);
    puts("PASS: allocator ABI, vtable ownership, integer/FP ABI, exactly one call, generation/owner guards, allocation refusal");
}
