/* RE6 061D2A06 shell-only research probe. Not a verified intervention.
 * See docs/research/re6-native-shell-ring.md. No bomb initializer/action fields.
 * Position, history and origin follow F6B500; velocities follow F59F30.
 * The probe initializes one stationary shell at the requested safe world point.
 */
typedef unsigned long U;
typedef unsigned int W;
typedef unsigned char B;
typedef short H;
extern B S_ITEM[], SHELL2_DTI[], SHELL3_DTI[], SHELL4_DTI[];
extern B SHELL2_VT[], SHELL3_VT[], SHELL4_VT[], MANAGER_VT[], SHELL_EXPLODE_VT[];
extern B *CREATE_ITEM(void *, void *, W, U, W);
extern void DETACH(void *, void *, W);

struct Packet { W pos[4]; B *unit; W stage; };

__attribute__((section(".text.spawn_shell")))
U spawn_shell(B *player, W player_generation, B *dti, struct Packet *packet) {
    U vt;
    if (dti == SHELL2_DTI) vt = (U)SHELL2_VT;
    else if (dti == SHELL3_DTI) vt = (U)SHELL3_VT;
    else if (dti == SHELL4_DTI) vt = (U)SHELL4_VT;
    else return 0;
    if (*(W *)(player + 0x1308) != player_generation || *(H *)(player + 0x1368) <= 0)
        return 0;
    B *unit = CREATE_ITEM(*(void **)S_ITEM, dti, 14, 0, 0);
    packet->unit = unit;
    packet->stage = unit ? 1 : 0;
    if (!unit || *(U *)unit != vt) return 0;
    DETACH(unit, 0, 0xffffffff);
    *(W *)(unit + 0x14) &= 0xffffd7ff;
    *(B **)(unit + 0x1300) = player;
    for (W i = 0; i < 3; i++) {
        *(W *)(unit + 0x60 + 4 * i) = packet->pos[i];
        *(W *)(unit + 0x3890 + 4 * i) = packet->pos[i];
        *(W *)(unit + 0x38d0 + 4 * i) = packet->pos[i];
        *(W *)(unit + 0x3870 + 4 * i) = 0;
        *(W *)(unit + 0x3880 + 4 * i) = 0;
    }
    *(W *)(unit + 0x6c) = 0;
    *(W *)(unit + 0x389c) = 0;
    *(W *)(unit + 0x38dc) = 0;
    *(B *)(unit + 0x38a0) = 1;
    packet->stage = 2;
    return (U)unit;
}

/* Arm the native forced-collision branch F45AB0 consumes on the next update.
 * F6B500 uses this same +3954 bit when a launch's native raycast hits geometry.
 * Return 1 means requested; it is never an explosion or damage receipt.
 */
__attribute__((section(".text.arm_shell")))
U arm_shell(B *unit, B *player, W generation, W player_generation, U vt) {
    if ((vt != (U)SHELL2_VT && vt != (U)SHELL3_VT && vt != (U)SHELL4_VT) ||
        *(U *)unit != vt || *(B **)(unit + 0x1300) != player ||
        *(W *)(unit + 0x1308) != generation ||
        *(W *)(player + 0x1308) != player_generation || *(H *)(player + 0x1368) <= 0)
        return 0;
    B *manager = unit + 0x13a8;
    if (*(U *)manager != (U)MANAGER_VT || *(B **)(manager + 8) != unit ||
        *(W *)(manager + 0x18) <= 19 || !*(U *)(manager + 0x28)) return 0;
    B *action = (*(B ***)(manager + 0x28))[19];
    if (!action || *(U *)action != (U)SHELL_EXPLODE_VT || *(B **)(action + 0x10) != unit)
        return 0;
    if ((*(W *)(unit + 0xc) & 0xffffff) != 0x201 || (*(W *)(unit + 0x2c18) & 1))
        return 0;
    *(W *)(unit + 0x3954) |= 4;
    return 1;
}
