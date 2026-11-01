/* RE5 EBFFDB22 native inventory staging and replacement.
 * stage/discard use a private cItemManager; commit is the only live-inventory
 * transaction. The worker must serialize them with its flash controller and
 * validate process, player, slot and object identities before publication.
 * Offsets/functions come from EBFFDB22 Ghidra and checked-in native dispatch.
 */
typedef unsigned long U;typedef unsigned int W;typedef unsigned char B;
extern B INVENTORY_VT[],ITEM_VT[],S_ITEM[];
extern void INIT_INVENTORY(B*);
extern B *ADD_ITEM(B*,B*,W,int,int,int,int,int,B,B,B,B,B,B,B,B,B,B*,W,B*);
extern void EQUIP(B*,int);
extern U CONTAINS(B*,B*);
static int living(B*p,U gen){return *(U*)(p+0x1a00)==gen && *(short*)(p+0x1eb8)>1;}
static int allowed(W id){
 /* Catalogued weapons, including grenades/mines; not arbitrary item IDs. */
 return id>=0x101 && id<=0x136 && ((0x200007ff7fffffUL>>(id-0x101))&1);
}
__attribute__((noinline)) static void clear_slot(B*s){for(W i=8;i<0x38;i++)s[i]=0;*(W*)(s+0x1c)=13;}

__attribute__((noinline)) static B *insert(B*p,B*inventory,W id,B*u){
 W bone=*(W*)(p+(p[0x2701]?0x363c:0x3638));
 return ADD_ITEM(*(B**)S_ITEM,inventory,id,-2,-1,-1,-1,0,0,0,0,0,0,0,0,0,0,p,bone,u);
}
__attribute__((section(".text.stage")))
B *stage(B*player,U generation,B*scratch,W id){
 if(!living(player,generation)||!allowed(id))return 0;
 if(!*(U*)scratch)INIT_INVENTORY(scratch);
 if(*(U*)scratch!=(U)INVENTORY_VT)return 0;
 for(W i=0;i<24;i++)if(scratch[0x35+i*0x38])return 0;
 return insert(player,scratch,id,0);
}
/* Discard only the private staged item; never touches the live inventory. */
__attribute__((section(".text.discard")))
U discard(B*player,U generation,B*scratch,B*unit,U born){
 B*slot=scratch+8;B*items=*(B**)S_ITEM;
 if(*(U*)(player+0x1a00)!=generation || *(U*)scratch!=(U)INVENTORY_VT ||
    *(U*)slot!=(U)ITEM_VT || !slot[0x2d] || *(B**)(slot+0x30)!=unit ||
    !unit || *(U*)(unit+0x1a00)!=born || *(B**)(unit+0x1a10)!=player || !CONTAINS(items,unit))return 0;
 ((void(*)(B*,B*))(*(U*)(*(U*)items+0x70)))(items,unit);
 clear_slot(slot);return 1;
}
__attribute__((noinline,section(".text.validate")))
U validate(B*p,U gen,B*s,B*u,U born,B*old,B*old_unit,U old_born){
 if(*(U*)(p+0x1a00)!=gen || *(short*)(p+0x1eb8)<=1 ||
  p[0x1b4c] || *(int*)(p+0x1b48)!=-1 || p[0x3f2c] ||
  (p[0x8f8]!=0 && p[0x8f8]!=1 && p[0x8f8]!=7 && p[0x8f8]!=9 && p[0x8f8]!=10) ||
  *(U*)(p+0x30e8)!=(U)INVENTORY_VT || *(U*)s!=(U)INVENTORY_VT ||
  *(U*)(s+8)!=(U)ITEM_VT || !s[0x35] || *(B**)(s+0x38)!=u ||
  !u || *(U*)(u+0x1a00)!=born || *(B**)(u+0x1a10)!=p || !u[0x1b88] || u[0x1a71])return 0;
 W matches=0,free=0;
 for(W i=0;i<24;i++){
  B*r=p+0x30f0+56*i;if(*(U*)r!=(U)ITEM_VT)return 0;
  if(!r[0x2d]){free++;continue;}
  if(*(B**)(r+0x30)==u)return 0;
  if(*(W*)(r+0x1c)==0){matches++;if(r!=old || *(B**)(r+0x30)!=old_unit)return 0;}
 }
 if((!old && old_unit) || !free || matches!=(old!=0) || (old && old_unit && (*(U*)(old_unit+0x1a00)!=old_born || *(B**)(old_unit+0x1a10)!=p)))return 0;
 return CONTAINS(*(B**)S_ITEM,u) && (!old_unit || CONTAINS(*(B**)S_ITEM,old_unit));
}
__attribute__((section(".text.commit")))
U commit(B*p,U gen,B*s,B*u,U born,B*old,B*old_unit,U old_born){
 if(!validate(p,gen,s,u,born,old,old_unit,old_born))return 0;
 B*items=*(B**)S_ITEM;B*staged=s+8;
 B*r=insert(p,p+0x30e8,*(W*)(staged+8),u);
 if(!r)return 0;
 if(r<p+0x30f0 || r>=p+0x3630 || (U)(r-(p+0x30f0))%56 || r==old || !r[0x2d] || *(B**)(r+0x30)!=u)return 2;
 if(old)clear_slot(old);
 clear_slot(staged);EQUIP(p,0);
 if(old_unit)((void(*)(B*,B*))(*(U*)(*(U*)items+0x70)))(items,old_unit);
 return *(W*)(r+0x20)==1?1:2;
}
