#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
typedef uint64_t U;typedef unsigned W;typedef unsigned char B;
static U base=0x100000000ULL,gen=0x100000002;
static B player[0x5000],saved[0x5000],scratch[0x550],unit[0x3000],previous[0x3000];
static U items[32],item_vt[16];
static unsigned initialized,added,refuse,removed,equipped,registered,old_registered;
static B*old;
static void init(B*p){
 initialized++;memset(p,0,0x550);*(U*)p=base+0x1c78280;
 for(W i=0;i<24;i++){*(U*)(p+8+56*i)=base+0x1c782c0;*(W*)(p+0x24+56*i)=13;}
}
static U contains(B*m,B*u){assert(m==(B*)items);return u==unit?registered:u==previous?old_registered:0;}
static void remove_unit(B*m,B*u){
 assert(m==(B*)items);removed++;
 if(u==unit){assert(registered);registered=0;}
 else {assert(u==previous&&old_registered&&equipped&&!old[0x2d]);old_registered=0;}
}
static void equip(B*p,int grid){
 assert(p==player&&grid==0);equipped++;B*selected=0;
 for(W i=0;i<24;i++){
  B*r=p+0x30f0+56*i;
  if(r[0x2d]&&*(W*)(r+0x1c)==0){assert(!selected);selected=r;}
  *(W*)(r+0x20)=0;
 }
 assert(selected&&*(B**)(selected+0x30)==unit);*(W*)(selected+0x20)=1;
}
static B*add(B*manager,B*inventory,W id,int count,int capacity,int c,int d,int grid,
 B p9,B p10,B p11,B p12,B p13,B p14,B p15,B p16,B p17,B*owner,W bone,B*existing){
 assert(manager==(B*)items&&owner==player&&(inventory==scratch||inventory==player+0x30e8));
 assert(id==0x119||id==0x10f);assert(count==-2&&capacity==-1&&c==-1&&d==-1&&grid==0);
 assert(!p9&&!p10&&!p11&&!p12&&!p13&&!p14&&!p15&&!p16&&!p17);
 assert(bone==(player[0x2701]?76:75));added++;
 if(inventory!=scratch){assert(existing==unit&&old[0x2d]&&*(B**)(old+0x30)==previous);}
 else assert(!existing);
 if(refuse)return 0;
 B*r=0;for(W i=0;i<24;i++){if(!inventory[0x35+56*i]){r=inventory+8+56*i;break;}}
 assert(r);*(W*)(r+8)=id;*(W*)(r+0x1c)=0;*(U*)(r+0x30)=(U)unit;r[0x2d]=1;
 registered=1;*(U*)(unit+0x1a00)=77;*(U*)(unit+0x1a10)=(U)owner;unit[0x1b88]=1;
 return r;
}
static void bridge(U at,U fn){W j[]={0x58000050,0xd61f0200};memcpy((void*)(base+at),j,8);*(U*)(base+at+8)=fn;}
static void reset(void){
 memset(scratch,0,sizeof scratch);memset(player,0,sizeof player);memset(unit,0,sizeof unit);memset(previous,0,sizeof previous);
 init(player+0x30e8);*(W*)(player+0x3638)=75;*(W*)(player+0x363c)=76;
 *(U*)(player+0x1a00)=gen;*(short*)(player+0x1eb8)=900;*(int*)(player+0x1b48)=-1;
 /* UI grid0 deliberately lives at physical record15. */
 for(W i=0;i<16;i++){B*r=player+0x30f0+56*i;r[0x2d]=1;*(W*)(r+8)=0x102;*(W*)(r+0x1c)=i+1;}
 old=player+0x30f0+56*15;*(W*)(old+0x1c)=0;*(W*)(old+0x20)=1;*(U*)(old+0x30)=(U)previous;
 *(U*)(previous+0x1a00)=78;*(U*)(previous+0x1a10)=(U)player;
 memcpy(saved,player,sizeof saved);initialized=added=refuse=removed=equipped=registered=0;old_registered=1;
 items[0]=(U)item_vt;item_vt[14]=(U)remove_unit;
}
int main(int argc,char**argv){
 assert(argc==5);assert(mmap((void*)base,0x3000000,7,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void*)base);
 FILE*f=fopen(argv[1],"rb");assert(f);size_t n=fread((void*)(base+0x118eac8),1,0x538,f);assert(n>0&&n<=0x538);fclose(f);
 U entry[3];for(int i=0;i<3;i++)assert(sscanf(argv[i+2],"%lx",entry+i)==1);
 bridge(0x91faf0,(U)init);bridge(0x1c2ef0,(U)add);bridge(0x1c3d10,(U)contains);bridge(0x7ab380,(U)equip);*(U*)(base+0x1cf1408)=(U)items;
 __builtin___clear_cache((char*)base,(char*)base+0x3000000);
 B*(*stage)(B*,U,B*,W)=(void*)(base+entry[0]);
 U(*drop)(B*,U,B*,B*,U)=(void*)(base+entry[1]);
 U(*commit)(B*,U,B*,B*,U,B*,B*,U)=(void*)(base+entry[2]);
 #define STAGE() assert(stage(player,gen,scratch,0x119)==scratch+8)
 #define COMMIT() commit(player,gen,scratch,unit,77,old,previous,78)
 reset();STAGE();assert(initialized==1&&added==1&&!memcmp(saved,player,sizeof saved));
 assert(!stage(player,gen,scratch,0x119)&&added==1);
 assert(!drop(player,2,scratch,unit,77)&&!removed);assert(!drop(player,gen,scratch,unit,78)&&!removed);
 assert(drop(player,gen,scratch,unit,77)==1&&removed==1&&!scratch[0x35]&&!memcmp(saved,player,sizeof saved));
 assert(!drop(player,gen,scratch,unit,77)&&removed==1);
 reset();assert(!stage(player,2,scratch,0x119)&&!initialized&&!added);
 reset();assert(!stage(player,gen,scratch,0x118)&&!initialized&&!added);
 reset();assert(!stage(player,gen,scratch,0xffff)&&!initialized&&!added);
 reset();*(U*)scratch=17;assert(!stage(player,gen,scratch,0x119)&&!initialized&&!added);
 reset();init(scratch);scratch[0x35+23*56]=1;assert(!stage(player,gen,scratch,0x119)&&!added);
 reset();refuse=1;assert(!stage(player,gen,scratch,0x119)&&added==1&&!memcmp(saved,player,sizeof saved));
 reset();player[0x2701]=1;memcpy(saved,player,sizeof saved);assert(stage(player,gen,scratch,0x10f)==scratch+8&&!memcmp(saved,player,sizeof saved));
 reset();STAGE();assert(COMMIT()==1&&added==2&&equipped==1&&removed==1&&!old_registered&&registered);
 assert(!scratch[0x35]&&!old[0x2d]);B*new_slot=player+0x30f0+56*16;
 assert(*(U*)(new_slot+0x30)==(U)unit&&*(W*)(new_slot+0x20)==1&&*(W*)(new_slot+0x1c)==0);
 assert(!COMMIT()&&added==2&&removed==1); /* no replay */
 for(int failure=0;failure<15;failure++){
  reset();STAGE();
  switch(failure){
  case 0:*(U*)(player+0x1a00)=2;break;
  case 1:*(U*)(previous+0x1a00)=79;break;
  case 2:player[0x1b4c]=1;break;
  case 3:*(int*)(player+0x1b48)=0;break;
  case 4:*(short*)(player+0x1eb8)=1;break;
  case 5:player[0x8f8]=29;break;
  case 6:unit[0x1b88]=0;break;
  case 7:unit[0x1a71]=1;break;
  case 8:*(U*)(unit+0x1a10)=0;break;
  case 9:*(U*)(previous+0x1a10)=0;break;
  case 10:*(W*)(player+0x30f0+0x1c)=0;break;
  case 11:for(W i=0;i<24;i++)player[0x30f0+56*i+0x2d]=1;break;
  case 12:*(U*)(old+0x30)=0;break;
  case 13:refuse=1;break;
  case 14:player[0x3f2c]=1;break;
  }
  memcpy(saved,player,sizeof saved);assert(!COMMIT());
  assert(!memcmp(saved,player,sizeof saved)&&!removed&&!equipped&&old_registered&&scratch[0x35]);
 }
 reset();STAGE();assert(!commit(player,gen,scratch,unit,77,0,previous,78)&&!removed&&!equipped);
 puts("PASS: native staging/discard/replacement ABI, grid0 at record15, stage-first insertion, preservation on refusal, lifetime/idle/resource/capacity guards, no replay");
}
