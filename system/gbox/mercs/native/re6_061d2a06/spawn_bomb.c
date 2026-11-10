/* Pinned RE6 061D2A06: a remote bomb dropped at a chosen point, already lying placed - no throw, no animation, no
 * remote in his hand (operator 2026-11-10: "The remote mines should just fall onto the ground and be armed and ready
 * for detonation by the bot flipping the ram byte flag at will").
 *
 * The same native allocation as spawn.c with the placed remote bomb's class (uWp1097, BOMB_DTI), its owner set, then
 * its own placed action (cWpAction_wp_act_setting, action 24 of the weapon action table main+0x2825700) requested
 * through its action manager. The detonator's flag - bit 0x2000 of the owner's u32 +0x5A18, which the remote's throw
 * ORs in (main+0x108AB7C) - is set here on the game thread first: the setting action's move (main+0x112FF30) sets a
 * bomb off on the first frame it reads the flag clear. Clearing that bit later (re6_switch_mods.detonate) is the
 * detonation. Returns the unit, or 0 for an allocation refusal or a player who is not one.
 */
typedef unsigned long U;
typedef unsigned int W;
typedef unsigned char B;
extern B S_ITEM[], BOMB_DTI[], S_STATS[];
extern B *CREATE_ITEM(void*,void*,W,U,W);
extern void SET_ROTATION(void*,void*);
extern void REGISTER_PROJECTILE(void*,void*,void*,U);
__attribute__((section(".text.spawn_bomb")))
U spawn_bomb(B *player, W x, W y, W z) {
    if(!player) return 0;
    B *unit=CREATE_ITEM(*(void**)S_ITEM,BOMB_DTI,13,0,0);
    if(!unit) return 0;
    *(volatile W*)(player+0x5a18)|=0x2000;
    *(B**)(unit+0x1300)=player;
    *(W*)(unit+0x60)=x;
    *(W*)(unit+0x64)=y;
    *(W*)(unit+0x68)=z;
    *(W*)(unit+0x6c)=0;
    volatile W quat[4]; quat[0]=0; quat[1]=0; quat[2]=0; quat[3]=0x3f800000;
    SET_ROTATION(unit,(void*)quat);
    B *manager=unit+0x13a8;
    ((void(*)(void*,W,W,U,W,W))(*(U*)(*(U*)manager+0x30)))(manager,24,0,0,0xffffffff,0);
    REGISTER_PROJECTILE(*(void**)S_STATS,player,unit,0);
    return (U)unit;
}
