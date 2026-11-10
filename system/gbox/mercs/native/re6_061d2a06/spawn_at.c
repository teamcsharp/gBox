/* Pinned RE6 061D2A06: the verified flash spawn (spawn.c) for the grenade ring.
 * Same native allocation/initialization/registration path, for one of the three
 * thrown grenade classes (uWp1091 hand, uWp1093 incendiary, uWp1095 flash) and a
 * caller-chosen world position (raw f32 bits). Any other DTI is refused before
 * allocation. No inventory, input or weapon change. Detonation is detonate_at.c.
 */
typedef unsigned long U;
typedef unsigned int W;
typedef unsigned char B;
extern B S_ITEM[], HAND_DTI[], FIRE_DTI[], FLASH_DTI[], S_STATS[];
extern B *CREATE_ITEM(void*,void*,W,U,W);
extern void SET_ROTATION(void*,void*);
extern void REGISTER_PROJECTILE(void*,void*,void*,U);
__attribute__((section(".text.spawn_at")))
U spawn_at(B *player, B *dti, W x, W y, W z) {
    if (dti != HAND_DTI && dti != FIRE_DTI && dti != FLASH_DTI) return 0;
    B *unit=CREATE_ITEM(*(void**)S_ITEM,dti,13,0,0);
    if(!unit) return 0;
    *(B**)(unit+0x1300)=player;
    *(volatile W*)(unit+0x60)=x;
    *(volatile W*)(unit+0x64)=y;
    *(volatile W*)(unit+0x68)=z;
    *(volatile W*)(unit+0x6c)=0;
    volatile W quat[4]; quat[0]=0; quat[1]=0; quat[2]=0; quat[3]=0x3f800000;
    SET_ROTATION(unit,(void*)quat);
    *(volatile U*)(unit+0x3920)=0x4116cbe4;
    *(volatile U*)(unit+0x3928)=0;
    *(volatile U*)(unit+0x3930)=0;
    *(volatile U*)(unit+0x3938)=0;
    *(volatile U*)(unit+0x388c)=0x100000001UL;
    B *manager=unit+0x13a8;
    ((void(*)(void*,W,W,U,W,W))(*(U*)(*(U*)manager+0x30)))(manager,7,0,0,0xffffffff,0);
    REGISTER_PROJECTILE(*(void**)S_STATS,player,unit,0);
    return (U)unit;
}
