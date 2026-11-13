// RE4 82C2A04A: checked first-aid use on the game thread.
// x0=item manager, x1=real item slot, x2=expected player, w3=unit id, x4=game object.
// Result 1 means the native item-use function consumed a spray; 0 means no use.
// No health writes: main+0x297AB0 owns healing and consumption. Keep at least one spray.
    stp x29, x30, [sp, #-0x30]!
    stp x19, x20, [sp, #0x10]
    stp x21, x22, [sp, #0x20]
    mov x19, x0
    mov x20, x1
    adrp x8, #0x124d000
    add x8, x8, #0x918
    cmp x19, x8
    b.ne .Lrefuse
    adrp x8, #0xb1a000
    ldr x8, [x8, #0xe08]
    cmp x4, x8
    b.ne .Lrefuse
    adrp x8, #0x1131000
    ldr x8, [x8, #0xf0]
    cmp x2, x8
    b.eq .Lplayer
    adrp x8, #0x113b000
    ldr x8, [x8, #0x398]
    cmp x2, x8
    b.ne .Lrefuse
.Lplayer:
    ldr w8, [x2, #0x110]
    cmp w3, w8
    b.ne .Lrefuse
    ldr w8, [x4, #0x78]
    tbz w8, #30, .Lrefuse
    add x8, x4, #0x8000
    ldrb w8, [x8, #0x6ff]
    cbnz w8, .Lrefuse
    add x8, x4, #0x5000
    ldrh w9, [x8, #0x28]
    cbz w9, .Lrefuse
    ldrh w10, [x8, #0x2a]
    cmp w9, w10
    b.hs .Lrefuse
    ldr w8, [x19, #0x30]
    cmp w8, #384
    b.ne .Lrefuse
    ldr x8, [x19, #0x20]
    cbz x8, .Lrefuse
    subs x9, x20, x8
    b.lo .Lrefuse
    mov x10, #14
    udiv x11, x9, x10
    cmp x11, #384
    b.hs .Lrefuse
    msub x9, x11, x10, x9
    cbnz x9, .Lrefuse
    ldrh w8, [x20]
    cmp w8, #5
    b.ne .Lrefuse
    ldrb w8, [x20, #4]
    tbz w8, #0, .Lrefuse
    ldrb w8, [x20, #5]
    cbnz w8, .Lrefuse
    ldrh w8, [x20, #2]
    cbz w8, .Lrefuse
    cmp w8, #2
    b.hs .Luse
    mov w8, #2
    strh w8, [x20, #2]
.Luse:
    ldrb w21, [x19, #0x1a]
    strb wzr, [x19, #0x1a]
    mov x0, x19
    mov x1, x20
    bl #0x297ab0
    strb w21, [x19, #0x1a]
    b .Lreturn
.Lrefuse:
    mov x0, #0
.Lreturn:
    ldp x19, x20, [sp, #0x10]
    ldp x21, x22, [sp, #0x20]
    ldp x29, x30, [sp], #0x30
    ret
