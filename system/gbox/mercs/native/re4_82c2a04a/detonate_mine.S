// RE4 82C2A04A: request the real mine-dart explosion on the game thread.
// x0=mine, w1=mine generation, x2=player, w3=player generation.
// Returns 1 only after the exact owned mine enters its native explosion state.
    stp x29, x30, [sp, #-0x20]!
    stp x19, x20, [sp, #0x10]
    mov x19, x0
    adrp x8, #0x1131000
    ldr x8, [x8, #0xf0]
    cmp x2, x8
    b.eq .Lplayer
    adrp x8, #0x113b000
    ldr x8, [x8, #0x398]
    cmp x2, x8
    b.ne .Lrefuse
.Lplayer:
    cbz x2, .Lrefuse
    ldr w8, [x2, #0x110]
    cmp w3, w8
    b.ne .Lrefuse
    adrp x8, #0xb1a000
    ldr x8, [x8, #0xe08]
    ldr w9, [x8, #0x78]
    tbz w9, #30, .Lrefuse
    add x9, x8, #0x8000
    ldrb w9, [x9, #0x6ff]
    cbnz w9, .Lrefuse
    add x8, x8, #0x5000
    ldrh w8, [x8, #0x28]
    cbz w8, .Lrefuse
    adrp x8, #0xae6000
    add x8, x8, #0xef8
    ldr x9, [x8, #8]
    cbz x9, .Lrefuse
    ldr w10, [x8, #0x10]
    cmp w10, #512
    b.hi .Lrefuse
    cbz w10, .Lrefuse
    ldr w11, [x8, #0x14]
    mov w12, #0x10c8
    cmp w11, w12
    b.ne .Lrefuse
    subs x9, x19, x9
    b.lo .Lrefuse
    udiv x12, x9, x11
    cmp x12, x10
    b.hs .Lrefuse
    msub x9, x12, x11, x9
    cbnz x9, .Lrefuse
    ldr x8, [x19]
    adrp x9, #0xaed000
    add x9, x9, #0x720
    cmp x8, x9
    b.ne .Lrefuse
    ldr w8, [x19, #0x110]
    cmp w1, w8
    b.ne .Lrefuse
    ldr w8, [x19, #8]
    mov w9, #0x201
    and w8, w8, w9
    cmp w8, #1
    b.ne .Lrefuse
    ldrb w8, [x19, #0x118]
    cmp w8, #0x5f
    b.ne .Lrefuse
    ldrb w8, [x19, #0x119]
    cmp w8, #1
    b.hi .Lrefuse
    ldrb w8, [x19, #0x114]
    cmp w8, #1
    b.ne .Lrefuse
    ldrb w8, [x19, #0x115]
    cmp w8, #4
    b.hi .Lrefuse
    // Fresh game-thread positions: refuse self-blast inside native reach + 1m.
    // Return 2 before invoking the native routine; the fuse may safely retry.
    ldr s0, [x19, #0xa4]
    ldr s1, [x2, #0xa4]
    fsub s0, s0, s1
    fmul s0, s0, s0
    ldr s1, [x19, #0xa8]
    ldr s2, [x2, #0xa8]
    fsub s1, s1, s2
    fmadd s0, s1, s1, s0
    ldr s1, [x19, #0xac]
    ldr s2, [x2, #0xac]
    fsub s1, s1, s2
    fmadd s0, s1, s1, s0
    fmov w9, s0
    ubfx w9, w9, #23, #8
    cmp w9, #255
    b.eq .Lrefuse
    ldrb w8, [x19, #0x541]
    mov w9, #7000
    mov w10, #5000
    cmp w8, #1
    csel w9, w10, w9, eq
    mov w10, #3000
    cmp w8, #0
    csel w9, w10, w9, eq
    scvtf s1, w9
    fmul s1, s1, s1
    fcmp s0, s1
    b.ls .Lunsafe
    mov x0, x19
    bl #0x1b4d20
    ldrh w8, [x19, #0x114]
    cmp w8, #0x501             // wall-attached: native release (4 frames), then explosion
    b.eq .Laccepted
    cmp w8, #0x601
    cset w0, eq
    b .Lreturn
.Laccepted:
    mov w0, #1
    b .Lreturn
.Lrefuse:
    mov w0, #0
    b .Lreturn
.Lunsafe:
    mov w0, #2
.Lreturn:
    ldp x19, x20, [sp, #0x10]
    ldp x29, x30, [sp], #0x20
    ret
