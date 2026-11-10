/* RE6 061D2A06: the verified explosion transition (detonate.c) for the grenade ring.
 * Only an initialized grenade of the expected class (hand / incendiary / flash),
 * owned by this player and allocation generation, may be consumed. Its x/z are
 * set to the ring point on the game thread just before the request (y, the
 * floor, is kept). Returns 1 when this call's native bomb action ran, 2 when the
 * grenade's own fuse/contact check already started it (no request made), 0 when
 * refused. A receipt proves the native bomb action ran, not that enemies were hit.
 */
typedef unsigned long U;
typedef unsigned int W;
typedef unsigned char B;
extern B HAND_VT[], FIRE_VT[], FLASH_VT[], THROW_VT[], BOMB_VT[], MANAGER_VT[];
extern W REQUEST(void*,W,W,U,W,W);
extern void UPDATE(void*);
__attribute__((section(".text.detonate_at")))
U detonate_at(B *unit, B *player, W generation, W player_generation, U vt, W x, W z) {
    if (vt != (U)HAND_VT && vt != (U)FIRE_VT && vt != (U)FLASH_VT) return 0;
    if (*(U*)unit != vt || *(U*)(unit+0x1300)!=(U)player ||
        *(W*)(unit+0x1308)!=generation || *(W*)(player+0x1308)!=player_generation)
        return 0;
    B *manager=unit+0x13a8;
    if (*(U*)manager!=(U)MANAGER_VT || *(U*)(manager+8)!=(U)unit)
        return 0;
    B *action=*(B**)(manager+0x48);
    if (action && *(U*)action==(U)BOMB_VT) return 2;
    if (!action || *(U*)action!=(U)THROW_VT) return 0;
    *(volatile W*)(unit+0x60)=x;
    *(volatile W*)(unit+0x68)=z;
    if (!REQUEST(manager,10,0,0,0xffffffff,0)) return 0;
    UPDATE(manager);
    action=*(B**)(manager+0x48);
    return action && *(U*)action==(U)BOMB_VT;
}
