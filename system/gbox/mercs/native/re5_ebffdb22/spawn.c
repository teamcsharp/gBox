/* RE5 EBFFDB22 research: create one flash unit without touching inventory.
 * The native sItem factory registers and initializes the object normally.
 * Actor attribution uses the same +1A10 owner field as the clone-throw path.
 */
typedef unsigned long U;
typedef unsigned int W;
typedef unsigned char B;
extern B S_ITEM[],FLASH_DTI[];
extern B *CREATE_ITEM(void*,void*,W,W,W);
extern void SET_ROTATION(void*,const float*);
B *spawn(B *player,U generation) {
    if (*(U*)(player+0x1a00)!=generation || *(short*)(player+0x1eb8)<=0)return (B*)0;
    B *unit=CREATE_ITEM(*(void**)S_ITEM,FLASH_DTI,10,1,0);
    if(!unit)return unit;
    for(W i=0;i<3;i++) {
        *(W*)(unit+0x60+4*i)=*(W*)(player+0x60+4*i);
        *(W*)(unit+0x2680+4*i)=*(W*)(player+0x60+4*i);
    }
    *(W*)(unit+0x6c)=0;
    *(U*)(unit+0x1a10)=(U)player;
    static const float rotation[4]={0,0,0,1};
    SET_ROTATION(unit,rotation);
    return unit;
}
