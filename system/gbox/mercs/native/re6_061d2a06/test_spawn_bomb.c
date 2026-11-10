#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
typedef uint64_t U;
static U base=0x100000000ULL, player;
static unsigned step;
static unsigned char unit[0x4000], pl[0x6000];
static U manager_vt[16];
static int fail_create;
static U create(U sys,U dti,unsigned line,U a,unsigned b) {
    assert(sys==123 && dti==base+0x2951538 && line==13 && a==0 && b==0 && step++==0);
    if(fail_create) return 0;
    memset(unit,0,sizeof unit);
    *(U*)(unit+0x13a8)=(U)manager_vt;
    return (U)unit;
}
static void rotate(U obj, uint32_t *q) {
    assert(obj==(U)unit && q[0]==0 && q[1]==0 && q[2]==0 && q[3]==0x3f800000 && step++==1);
    assert(*(U*)(unit+0x1300)==player);
    float want[3]={1.5f,-2.0f,300.25f};
    assert(memcmp(unit+0x60,want,12)==0 && *(uint32_t*)(unit+0x6c)==0);
    assert(*(uint32_t*)(pl+0x5a18)==(0x41u|0x2000u));                 /* armed before the placed action runs */
}
static void request(U mgr,unsigned id,unsigned priority,U a,unsigned b,unsigned c) {
    assert(mgr==(U)unit+0x13a8 && id==24 && priority==0 && a==0 && b==0xffffffff && c==0 && step++==2);
}
static void register_projectile(U sys,U owner,U projectile,U flags) {
    assert(sys==456 && owner==player && projectile==(U)unit && flags==0 && step++==3);
}
static void bridge(U off,U fn) {
    uint32_t jump[2]={0x58000050,0xd61f0200};
    memcpy((void*)(base+off),jump,8); *(U*)(base+off+8)=fn;
}
int main(int argc,char **argv) {
    assert(argc==2);
    assert(mmap((void*)base,0x3000000,PROT_READ|PROT_WRITE|PROT_EXEC,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void*)base);
    FILE *f=fopen(argv[1],"rb"); assert(f);
    size_t n=fread((void*)(base+0x18f2ac0),1,0x540,f); fclose(f);
    assert(n>0 && n<=0x140);
    bridge(0x3bcf90,(U)create); bridge(0x125ccf0,(U)rotate); bridge(0x3a9e70,(U)register_projectile);
    *(U*)(base+0x28ea8e0)=123; *(U*)(base+0x28e9be0)=456;
    player=(U)pl; manager_vt[6]=(U)request;
    *(uint32_t*)(pl+0x5a18)=0x41;
    float x=1.5f,y=-2.0f,z=300.25f; uint32_t xb,yb,zb; memcpy(&xb,&x,4); memcpy(&yb,&y,4); memcpy(&zb,&z,4);
    __builtin___clear_cache((char*)base,(char*)base+0x3000000);
    U (*spawn_bomb)(U,unsigned,unsigned,unsigned)=(void*)(base+0x18f2ac0);
    assert(spawn_bomb(player,xb,yb,zb)==(U)unit && step==4);
    fail_create=1; step=0; *(uint32_t*)(pl+0x5a18)=0x41;
    assert(spawn_bomb(player,xb,yb,zb)==0 && step==1 && *(uint32_t*)(pl+0x5a18)==0x41);   /* refused: not armed */
    step=0;
    assert(spawn_bomb(0,xb,yb,zb)==0 && step==0);
    puts("PASS: the placed remote bomb's allocation, owner, point, the armed flag first, action 24, refusals");
}
