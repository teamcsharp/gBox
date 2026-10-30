// Pinned RE6 Switch 061D2A06, linked at main+18f2640; live-validated 2026-10-30.
// A bootstrap allocates private storage using the game's allocator. No borrowed
// writable fields or guessed heap addresses. Native calls execute during the
// selected player's action-manager update, with the incoming ABI preserved.
.text
.global bootstrap, dispatcher
.extern ORIGINAL_VT, TEMP_VT, ORIGINAL_UPDATE, ALLOC_FLAGS, ALLOC_TABLE
.macro address reg, value
    adrp \reg, \value
    add \reg, \reg, :lo12:\value
.endm
.macro save
    sub sp, sp, #0x110
    stp x0,x1,[sp,#0]
    stp x2,x3,[sp,#16]
    stp x4,x5,[sp,#32]
    stp x6,x7,[sp,#48]
    stp x8,x19,[sp,#64]
    stp x20,x21,[sp,#80]
    stp x22,x30,[sp,#96]
    stp q0,q1,[sp,#112]
    stp q2,q3,[sp,#144]
    stp q4,q5,[sp,#176]
    stp q6,q7,[sp,#208]
.endm
.macro finish
    ldp q0,q1,[sp,#112]
    ldp q2,q3,[sp,#144]
    ldp q4,q5,[sp,#176]
    ldp q6,q7,[sp,#208]
    ldp x0,x1,[sp,#0]
    ldp x2,x3,[sp,#16]
    ldp x4,x5,[sp,#32]
    ldp x6,x7,[sp,#48]
    ldp x8,x19,[sp,#64]
    ldp x20,x21,[sp,#80]
    ldp x22,x30,[sp,#96]
    add sp,sp,#0x110
    address x16, ORIGINAL_UPDATE
    br x16
.endm
bootstrap:
    save
    mov x20,x0
    address x21,ORIGINAL_VT
    address x10,TEMP_VT
1:  ldaxr x9,[x20]
    cmp x9,x10
    b.ne 9f
    stlxr w11,x21,[x20]
    cbnz w11,1b
    address x9,ALLOC_FLAGS
    ldr w9,[x9]
    ubfx w9,w9,#23,#6
    address x10,ALLOC_TABLE
    ldr x0,[x10,x9,lsl #3]
    ldr x10,[x0]
    ldr x10,[x10,#0x38]
    mov x1,#0x400
    mov w2,#16
    blr x10
    cbz x0,9f
    mov x19,x0
    mov x9,#0
2:  add x10,x19,x9
    stp xzr,xzr,[x10]
    add x9,x9,#16
    cmp x9,#0x400
    b.lo 2b
    mov x9,#0
3:  ldr x10,[x21,x9]
    str x10,[x19,x9]
    add x9,x9,#8
    cmp x9,#0x58
    b.lo 3b
    adr x10,dispatcher
    str x10,[x19,#0x48]
    str x21,[x19,#0x80]
    address x10,ORIGINAL_UPDATE
    str x10,[x19,#0x88]
    ldr x10,[x20,#8]
    str x10,[x19,#0x90]
    ldr w11,[x10,#0x1308]
    str w11,[x19,#0x98]
    mov x10,#0x4247
    movk x10,#0x4e58,lsl #16
    movk x10,#0x3043,lsl #32
    movk x10,#0x3130,lsl #48
    str x10,[x19,#0xa0]
    stlr x19,[x20]
9:  clrex
    finish
.balign 16
dispatcher:
    save
    mov x20,x0
    ldr x19,[x20]
    ldr x10,[x20,#8]
    ldr x11,[x19,#0x90]
    cmp x10,x11
    b.ne 8f
    ldr w10,[x10,#0x1308]
    ldr w11,[x19,#0x98]
    cmp w10,w11
    b.ne 8f
    add x21,x19,#0xa8
4:  ldaxr w10,[x21]
    cmp w10,#1
    b.ne 8f
    mov w11,#2
    stlxr w12,w11,[x21]
    cbnz w12,4b
    ldr x16,[x19,#0xc0]
    ldp x0,x1,[x19,#0xc8]
    ldp x2,x3,[x19,#0xd8]
    ldp x4,x5,[x19,#0xe8]
    ldp x6,x7,[x19,#0xf8]
    blr x16
    str x0,[x19,#0xb8]
    mov w10,#3
    stlr w10,[x21]
8:  clrex
    finish
