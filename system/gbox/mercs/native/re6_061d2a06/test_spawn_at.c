#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
typedef uint64_t U;
static U base=0x100000000ULL, player, want_dti;
static unsigned step;
static unsigned char unit[0x4000], pl[0x6000];
static U manager_vt[16];
static int fail_create;
static const uint32_t X=0x44fa0000, Y=0x43480000, Z=0xc4bb8000;   /* 2000.0, 200.0, -1500.0 */
static U create(U sys,U dti,unsigned line,U a,unsigned b) {
    assert(sys==123 && dti==want_dti && line==13 && a==0 && b==0 && step++==0);
    if(fail_create) return 0;
    memset(unit,0,sizeof unit);
    *(U*)(unit+0x13a8)=(U)manager_vt;
    return (U)unit;
}
static void rotate(U obj, uint32_t *q) {
    assert(obj==(U)unit && q[0]==0 && q[1]==0 && q[2]==0 && q[3]==0x3f800000 && step++==1);
    assert(*(U*)(unit+0x1300)==player);
    assert(*(uint32_t*)(unit+0x60)==X && *(uint32_t*)(unit+0x64)==Y && *(uint32_t*)(unit+0x68)==Z);
    assert(*(uint32_t*)(unit+0x6c)==0);
}
static void request(U mgr,unsigned id,unsigned priority,U a,unsigned b,unsigned c) {
    assert(mgr==(U)unit+0x13a8 && id==7 && priority==0 && a==0 && b==0xffffffff && c==0 && step++==2);
    assert(*(U*)(unit+0x3920)==0x4116cbe4 && *(U*)(unit+0x3928)==0);
    assert(*(U*)(unit+0x3930)==0 && *(U*)(unit+0x3938)==0 && *(U*)(unit+0x388c)==0x100000001UL);
}
static void register_projectile(U sys,U owner,U projectile,U flags) {
    assert(sys==456 && owner==player && projectile==(U)unit && flags==0 && step++==3);
}
static void bridge(U off,U fn) {
    uint32_t jump[2]={0x58000050,0xd61f0200};
    memcpy((void*)(base+off),jump,8); *(U*)(base+off+8)=fn;
}
int main(int argc,char **argv) {
    assert(argc==3);
    unsigned size; assert(sscanf(argv[2],"%u",&size)==1);
    assert(mmap((void*)base,0x3000000,PROT_READ|PROT_WRITE|PROT_EXEC,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void*)base);
    FILE *f=fopen(argv[1],"rb"); assert(f);
    assert(fread((void*)(base+0x18f2ac0),1,0x500,f)==size); fclose(f);
    bridge(0x3bcf90,(U)create); bridge(0x125ccf0,(U)rotate); bridge(0x3a9e70,(U)register_projectile);
    *(U*)(base+0x28ea8e0)=123; *(U*)(base+0x28e9be0)=456;
    player=(U)pl; manager_vt[6]=(U)request;
    float pos[3]={10,20,30}; memcpy(pl+0x60,pos,12);
    __builtin___clear_cache((char*)base,(char*)base+0x3000000);
    U (*spawn_at)(U,U,U,U,U)=(void*)(base+0x18f2ac0);
    const U dtis[3]={base+0x2951490,base+0x29514c8,base+0x2951500};   /* uWp1091 hand, uWp1093 fire, uWp1095 flash */
    for(int i=0;i<3;i++) {
        step=0; fail_create=0; want_dti=dtis[i];
        /* upper register halves are junk-free from Python, but the W parameters must ignore them anyway */
        assert(spawn_at(player,want_dti,X|0xdead00000000ULL,Y,Z)==(U)unit && step==4);
        assert(memcmp(pl+0x60,pos,12)==0);                              /* the player is not moved */
    }
    step=0; fail_create=1; want_dti=dtis[0];
    assert(spawn_at(player,want_dti,X,Y,Z)==0 && step==1);
    const U refused[4]={base+0x2951538 /* uWp1097 remote bomb */, base+0x2951298 /* uWp1090 */, 0, base+0x2951501};
    for(int i=0;i<4;i++) { step=0; assert(spawn_at(player,refused[i],X,Y,Z)==0 && step==0); }
    puts("PASS: ring spawn for hand/incendiary/flash classes only, chosen position, ownership, zero velocity, refusal");
}
