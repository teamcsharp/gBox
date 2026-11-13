// Passive firearm animation rate at the end of each owned player update.
// x0 player, x1 private mailbox. Caller-saved registers only; no game calls.
// This runs after the routine dispatcher, before its next frame. A transition
// out of the firearm routine restores our speed before that new routine runs.
// It never changes routine numbers, health, position, or a game-owned rate.
// Mailbox append-only fields: 60 desired,64 player id,68 ownership bits,
// 6c applied float,70 object,78 object id,7c lease frames,
// 80 scaled frames,84 restorations,88 routine,8c class,90 sequence,94 item.
    cbz x1, .Lret
    ldr w8, [x1, #0x90]
    add w8, w8, #1
    str w8, [x1, #0x90]             // odd: observation being updated
    ldr w9, [x0, #0x110]
    ldr w10, [x1, #0x64]
    cmp w9, w10
    b.ne .Labandon                   // recycled player: no write to either actor
    ldr w9, [x0, #0x114]
    str w9, [x1, #0x88]
    adrp x12, 0x1279000
    ldrb w10, [x12, #0x36c]          // native equipped weapon class
    str w10, [x1, #0x8c]
    adrp x13, 0x124d000
    ldrh w11, [x13, #0x930]          // equipped item id, diagnostic only
    str w11, [x1, #0x94]
    ldr w11, [x1, #0x7c]
    cbz w11, .Lrestore
    sub w11, w11, #1
    str w11, [x1, #0x7c]
    ldrh w11, [x12, #0x360]          // dead player cannot acquire a rate
    cbz w11, .Lrestore
    ldr w2, [x1, #0x60]
    mov w3, #0x3f800000              // baseline 1.0, only rate we may acquire
    cmp w2, w3
    b.ls .Lrestore
    mov w4, #0x41a00000              // firearms bounded to requested 20x
    cmp w2, w4
    b.hi .Lrestore
    and w11, w9, #0xffff
    cmp w11, #0x600                  // living player in weapon routine only
    b.ne .Lrestore
    ubfx w11, w9, #16, #8
    cmp w11, #3                     // draw, aim, fire, holster; no reload/use
    b.hi .Lrestore
    cmp w10, #0x2e
    b.hi .Lrestore
    // Known firearm classes; no knife, bow, egg, grenade or healing item.
    movz x11, #0xfffe
    movk x11, #0x0002, lsl #16
    movk x11, #0x4002, lsl #32
    lsr x11, x11, x10
    tbz w11, #0, .Lrestore
    ldr w4, [x1, #0x68]
    ldr w5, [x1, #0x6c]
    ldr w6, [x0, #0x304]
    tbz w4, #0, .Lplayer_new
    cmp w6, w5
    b.eq .Lplayer_write
.Lplayer_new:
    cmp w6, w3
    b.ne .Lrestore                  // slow motion or another writer owns it
.Lplayer_write:
    str w2, [x0, #0x304]
    orr w4, w4, #1
    ldr w11, [x1, #0x80]
    add w11, w11, #1
    str w11, [x1, #0x80]
    ldr x12, [x0, #0x938]
    lsr x13, x12, #24
    cbz x13, .Lobject_drop
    lsr x13, x12, #40
    cbnz x13, .Lobject_drop
    ldr x12, [x12, #0x38]
    lsr x13, x12, #24
    cbz x13, .Lobject_drop
    lsr x13, x12, #40
    cbnz x13, .Lobject_drop
    ldr w13, [x12, #0x110]
    ldr x14, [x1, #0x70]
    cmp x12, x14
    b.ne .Lobject_new
    ldr w14, [x1, #0x78]
    cmp w13, w14
    b.ne .Lobject_new
    ldr w6, [x12, #0x304]
    tbz w4, #1, .Lobject_baseline
    cmp w6, w5
    b.eq .Lobject_write
    b .Lobject_baseline
.Lobject_new:
    bic w4, w4, #2
    str x12, [x1, #0x70]
    str w13, [x1, #0x78]
    ldr w6, [x12, #0x304]
.Lobject_baseline:
    cmp w6, w3
    b.ne .Lobject_drop
.Lobject_write:
    str w2, [x12, #0x304]
    orr w4, w4, #2
    b .Lapplied
.Lobject_drop:
    bic w4, w4, #2
.Lapplied:
    str w4, [x1, #0x68]
    str w2, [x1, #0x6c]
    b .Lfinish
.Lrestore:
    ldr w4, [x1, #0x68]
    cbz w4, .Lfinish
    mov w3, #0x3f800000
    ldr w5, [x1, #0x6c]
    tbz w4, #0, .Lrestore_object
    ldr w6, [x0, #0x304]
    cmp w6, w5
    b.ne .Lrestore_object
    str w3, [x0, #0x304]
    ldr w11, [x1, #0x84]
    add w11, w11, #1
    str w11, [x1, #0x84]
.Lrestore_object:
    tbz w4, #1, .Labandon
    ldr x12, [x0, #0x938]
    lsr x13, x12, #24
    cbz x13, .Labandon
    lsr x13, x12, #40
    cbnz x13, .Labandon
    ldr x12, [x12, #0x38]
    ldr x13, [x1, #0x70]
    cmp x12, x13
    b.ne .Labandon
    cbz x12, .Labandon
    ldr w13, [x12, #0x110]
    ldr w14, [x1, #0x78]
    cmp w13, w14
    b.ne .Labandon
    ldr w6, [x12, #0x304]
    cmp w6, w5
    b.ne .Labandon
    str w3, [x12, #0x304]
.Labandon:
    str wzr, [x1, #0x68]
    str xzr, [x1, #0x70]
.Lfinish:
    ldr w8, [x1, #0x90]
    add w8, w8, #1
    str w8, [x1, #0x90]             // even: coherent observation published
.Lret:
    ret
