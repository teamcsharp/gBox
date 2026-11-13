// RE4 Switch (82C2A04A21D3E0B850F273D4149C9003) native dispatcher.
//
// Installed into the never-executed zero padding at main+0x655880 (scripts/verify_re4_caves.py proves it: 1920
// bytes on a fresh 64-byte line, no branch or literal into it). It is reached through DATA only: the controller
// clones the player object's vtable, points slot +0xA0 (the player per-frame virtual,
// called by the player update at main+0x311400) at this code, and stores the clone's address into player+0. The clone also carries
// the mailbox pointer at entry 32 (offset 0x100), so this code never hardcodes private storage.
//
// Mailbox (the proven .bss page; E3):
//   +0x00 u32 state      0 idle, 1 requested, 2 running, 3 done
//   +0x08 u64 target     the game function to call
//   +0x10 .. +0x40       7 arguments (x0..x6)
//   +0x48 u64 result     x0 on return
//   +0x50 u64 generation the controller's request generation (read back by the host; not used here)
//   +0x58 u64 ticks      incremented on every entry (E6's live proof that the slot fires every frame)
//
// Every entry tail-calls the original tick with the unit in x0, so the game keeps working while the harness
// is attached. A NULL mailbox pointer (or a request with no target) is safe: the original still runs.
    stp     x29, x30, [sp, #-0x40]!
    mov     x29, sp
    stp     x19, x20, [sp, #0x10]
    stp     x21, x22, [sp, #0x20]
    mov     x19, x0                       // the unit
    ldr     x20, [x19]                    // the vtable pointer (our clone)
    ldr     x20, [x20, #0x100]            // the clone's mailbox pointer (entry 32)
    cbz     x20, .Loriginal
    ldr     x9, [x20, #0x58]              // ticks++
    add     x9, x9, #1
    str     x9, [x20, #0x58]
    ldr     w9, [x20, #0x00]              // a request?
    cmp     w9, #1
    b.ne    .Loriginal
    mov     w9, #2                        // running
    str     w9, [x20, #0x00]
    ldr     x8, [x20, #0x08]              // target
    cbz     x8, .Ldone
    ldp     x0, x1, [x20, #0x10]          // args x0..x6
    ldp     x2, x3, [x20, #0x20]
    ldp     x4, x5, [x20, #0x30]
    ldp     x6, x7, [x20, #0x40]
    blr     x8
    str     x0, [x20, #0x48]              // result
.Ldone:
    mov     w9, #3                        // done
    str     w9, [x20, #0x00]
.Loriginal:
    mov     x0, x19
    mov     x1, x20
    bl      0x655920                     // passive firearm-rate guard, main+CAVE_AT+0xa0
    mov     x0, x19
    ldr     x9, [x19]                    // each character keeps its own original callback
    ldr     x9, [x9, #0x108]             // pinned original stored after the mailbox pointer
    ldp     x19, x20, [sp, #0x10]
    ldp     x21, x22, [sp, #0x20]
    ldp     x29, x30, [sp], #0x40
    br      x9
    ret                                   // the self-test target: a call here proves the mailbox path
