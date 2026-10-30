/* Pinned RE6 061D2A06, ordinary throw's native allocation/initialization path.
 * Creates one owned flash projectile at the player. No inventory or input.
 * Detonation is a separate verified native action request after initialization.
 */
typedef unsigned long U;
typedef unsigned int W;
typedef unsigned char B;
extern B S_ITEM[], FLASH_DTI[], S_STATS[];
extern B *CREATE_ITEM(void*,void*,W,U,W);
extern void SET_ROTATION(void*,void*);
extern void REGISTER_PROJECTILE(void*,void*,void*,U);
__attribute__((section(".text.spawn")))
U spawn(B *player) {
    B *unit=CREATE_ITEM(*(void**)S_ITEM,FLASH_DTI,13,0,0);
    if(!unit) return 0;
    *(B**)(unit+0x1300)=player;
    *(U*)(unit+0x60)=*(U*)(player+0x60);
    *(W*)(unit+0x68)=*(W*)(player+0x68);
    *(W*)(unit+0x6c)=0;
    volatile W quat[4]; quat[0]=0; quat[1]=0; quat[2]=0; quat[3]=0x3f800000;
    SET_ROTATION(unit,(void*)quat);
    *(U*)(unit+0x3920)=0x4116cbe4;
    *(U*)(unit+0x3928)=0;
    *(U*)(unit+0x3930)=0;
    *(U*)(unit+0x3938)=0;
    *(U*)(unit+0x388c)=0x100000001UL;
    B *manager=unit+0x13a8;
    ((void(*)(void*,W,W,U,W,W))(*(U*)(*(U*)manager+0x30)))(manager,7,0,0,0xffffffff,0);
    REGISTER_PROJECTILE(*(void**)S_STATS,player,unit,0);
    return (U)unit;
}
