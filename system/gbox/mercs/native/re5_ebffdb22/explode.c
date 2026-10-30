/* RE5 EBFFDB22: native flash callback, not the held weapon's bomb animation.
 * 806B80 consumes +24CC bit 0 only for a live thrown bomb (+27B9), then
 * publishes +28A0 and configures native hit volumes/effect/audio. 820E50
 * also advances the flash-specific filter. Never replay a completed bomb.
 */
typedef unsigned long U;typedef unsigned int W;typedef unsigned char B;
extern B FLASH_VT[];
extern void CONFIGURE(B*,U,W,unsigned short,W);
extern void FLASH_UPDATE(B*);
U explode(B *unit,U born,B *player,U player_born) {
    if (!unit || !player || *(U*)unit!=(U)FLASH_VT || *(U*)(unit+0x1a00)!=born ||
        *(B**)(unit+0x1a10)!=player || *(U*)(player+0x1a00)!=player_born ||
        *(short*)(player+0x1eb8)<=1 || *(U*)(player+0x1a10)!=0 ||
        unit[0x1b88]!=1 || unit[0x1a71] || unit[0x28a0] ||
        !*(U*)(unit+0x1fb8) || !*(U*)(unit+0x1d38) || !*(W*)(unit+0x1d5c))return 0;
    CONFIGURE(unit,1,0,0x108,1);
    unit[0x24cc]|=1;
    FLASH_UPDATE(unit);
    return 1; /* Caller still requires allocation + native exploded-flag readback. */
}
