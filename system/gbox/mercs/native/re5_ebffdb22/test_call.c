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
    assert(size==4096 && align==16); allocations++;
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
    assert(fread((void*)(base+0x118e600),1,0x9c0,f)>0); fclose(f);
    // Branch islands to ordinary C functions preserve argument registers.
    uint32_t jump[2]={0x58000050,0xd61f0200};
    memcpy((void*)(base+0x799210),jump,8);
    *(U*)(base+0x799218)=(U)original;
    __builtin___clear_cache((char*)map,(char*)map+0x3000000);
    U original_vt=base+0x1c290c8, temp_vt=base+0x1a91900;
    U *vt=(U*)original_vt;
    for(int i=0;i<149;i++) vt[i]=0xaaaa0000+i;
    vt[12]=base+0x799210;
    memcpy((void*)temp_vt,vt,1192); ((U*)temp_vt)[12]=base+0x118e600;
    *(U*)(temp_vt+0x4a8)=original_vt;
    manager=base+0x2b10000;
    U player=manager;
    *(U*)(player+0x1a00)=33;
    U alloc_vt[16]={0}, allocator[1]={(U)alloc_vt};
    alloc_vt[7]=(U)allocate;
    *(uint32_t*)(base+0x1e739a8)=3U<<23;
    *(U*)(base+0x1d8ac98+3*8)=(U)allocator;
    *(U*)manager=temp_vt;
    tick(base+0x118e600);
    U heap=*(U*)manager;
    assert(heap!=temp_vt && heap!=original_vt && allocations==1 && updates==1);
    for(int i=0;i<149;i++) assert(((U*)heap)[i] == (i==12 ? base+DISPATCH_OFFSET : vt[i]));
    assert(*(U*)(heap+0x680)==original_vt && *(U*)(heap+0x690)==player);
    assert(*(U*)(heap+0x698)==33);
    assert(memcmp((void*)(heap+0x6a0),"GBXNC502",8)==0);
    *(U*)(heap+0x6c0)=(U)sum;
    for(int i=0;i<8;i++) *(U*)(heap+0x6c8+i*8)=i+1;
    *(uint32_t*)(heap+0x6a8)=1;
    tick(base+DISPATCH_OFFSET);
    assert(*(uint32_t*)(heap+0x6a8)==3 && *(U*)(heap+0x6b8)==36 && calls==1 && updates==2);
    tick(base+DISPATCH_OFFSET);
    assert(calls==1 && updates==3);
    *(uint32_t*)(heap+0x6a8)=1;
    *(U*)(player+0x1a00)=34;
    tick(base+DISPATCH_OFFSET);
    assert(calls==1 && updates==4 && *(uint32_t*)(heap+0x6a8)==1);
    *(U*)(player+0x1a00)=33;
    *(U*)(heap+0x690)=base+0x2b30000;
    tick(base+DISPATCH_OFFSET);
    assert(calls==1 && updates==5);
    *(U*)(heap+0x690)=player;
    *(U*)manager=original_vt;
    tick(base+0x118e600);
    assert(allocations==1 && updates==6);
    fail_alloc=1; *(U*)manager=temp_vt;
    tick(base+0x118e600);
    assert(*(U*)manager==original_vt && allocations==2 && updates==7);
    free((void*)heap); munmap(map,0x3000000);
    puts("PASS: allocator ABI, vtable ownership, integer/FP ABI, exactly one call, generation/owner guards, allocation refusal");
}


