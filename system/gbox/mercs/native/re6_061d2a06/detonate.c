/* RE6 061D2A06: execute the native explosion transition on the game thread.
 * Only an initialized flash owned by this player/allocation may be consumed.
 * A receipt proves the native bomb action ran, not that every enemy was hit.
 */
typedef unsigned long U;
typedef unsigned int W;
typedef unsigned char B;
extern B FLASH_VT[], THROW_VT[], BOMB_VT[], MANAGER_VT[];
extern W REQUEST(void*,W,W,U,W,W);
extern void UPDATE(void*);
__attribute__((section(".text.detonate")))
U detonate(B *unit, B *player, W generation, W player_generation) {
    if (*(U*)unit != (U)FLASH_VT || *(U*)(unit+0x1300)!=(U)player ||
        *(W*)(unit+0x1308)!=generation || *(W*)(player+0x1308)!=player_generation)
        return 0;
    B *manager=unit+0x13a8;
    if (*(U*)manager!=(U)MANAGER_VT || *(U*)(manager+8)!=(U)unit)
        return 0;
    B *action=*(B**)(manager+0x48);
    if (!action || *(U*)action!=(U)THROW_VT) return 0;
    if (!REQUEST(manager,10,0,0,0xffffffff,0)) return 0;
    UPDATE(manager);
    action=*(B**)(manager+0x48);
    return action && *(U*)action==(U)BOMB_VT;
}
