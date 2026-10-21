/*
 * gbox_bridge.c - gBox's bot bridge for the GoldenEye 007 PC port (github.com/jkdansereau/goldeneye-pc-port).
 *
 * gBox's own code, not part of the upstream port. gbox/native_ports.py copies this file into port/src/ of a local
 * build (the port's CMake compiles every .c file in that folder) and adds two calls:
 *   - gboxBridgeTick()  once per frame on the game thread, in src/boss.c right after joyConsumeSamplesWrapper();
 *   - gboxBridgeSeat()  in port/src/input.c where every controller's buttons and stick are produced (input thread).
 * With GE_GBOX_BRIDGE unset both return at once and the build plays exactly like upstream.
 *
 * GE_GBOX_BRIDGE=<path> (Linux: a file, normally under /dev/shm) or <name> (Windows: a named file mapping such as
 * Local\gbox-ge007-1234) is a shared-memory block the port creates and gBox maps; gbox/ge007_bridge.py mirrors the
 * layout below field for field (GBX_VERSION must match).
 *
 *   The port writes, every frame: each player's position, yaw (vv_theta), pitch (vv_verta), health, armour, death
 *   flag, weapon, kills/deaths/points, the line-of-sight matrix between players, and each player's nearest directly
 *   walkable navigation node; every few frames the weapons lying in the level and the nearest guards (solo levels).
 *   Line of sight is the guards' own test (chrCanSeeBond): stanTestLineUnobstructed over the floor tiles, which
 *   must end on the target's tile.
 *
 *   Once per stage it writes a navigation graph. Multiplayer setups ship no waypoints (their path tables are
 *   empty), and the pads alone leave rooms unconnected, so the nodes are every pad and bound pad plus one floor
 *   tile midpoint per GBX_CELL-sized cell (stairs and corridors included), and two nodes are linked when the same
 *   floor-tile line test walks from one to the other with nothing in the way (stanTestLineUnobstructed again).
 *
 *   gBox writes buttons + stick per seat. A seat gBox enabled takes that input instead of the pad: seats 1-3 are
 *   the bots (GE_MPVIRT seats), seat 0 is player 1 when gBox drives it (streamed input, autoplay). A seat whose
 *   writer stops bumping `seq` for GBX_STALE_FRAMES frames is released (idle), so a crashed bot never runs into a
 *   wall forever.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#endif

#include "port_math.h"     /* the port's way to reach the system math.h past the game's include/math.h */
#include <ultra64.h>
#include <bondconstants.h>
#include <bondtypes.h>
#include "player.h"
#include "stan.h"

#define GBX_MAGIC        0x31584247u   /* "GBX1" little endian */
#define GBX_VERSION      1
#define GBX_PLAYERS      4
#define GBX_MAX_NODES    1024
#define GBX_MAX_EDGES    16384
#define GBX_MAX_DEGREE   16
#define GBX_MAX_ITEMS    64
#define GBX_MAX_CHRS     32
#define GBX_STALE_FRAMES 120           /* ~2 s at 60 fps */
#define GBX_EDGE_RANGE   3000.0f       /* longest straight walk tested between two pads (world units, ~cm) */
#define GBX_TILE_RANGE   1200.0f       /* ... when one end is a floor-tile node */
#define GBX_EDGE_DY      400.0f
#define GBX_CELL         300.0f        /* one floor-tile node per cell of this size (x, z; y in 150-unit floors) */
#define GBX_CELLS        8192          /* open-addressing table for the cells already taken */
#define GBX_NODES_PER_TICK 12          /* graph build spread over frames: no hitch at match start */
#define GBX_LOS_TYPES    (CDTYPE_OBJS | CDTYPE_DOORS | CDTYPE_PATHBLOCKER | CDTYPE_AIOPAQUE)
#define GBX_WALK_TYPES   (CDTYPE_OBJS | CDTYPE_PATHBLOCKER)
#define GBX_EYE          130.0f        /* line-of-sight test height above the floor (chrCanSeeBond: chrheight - 20) */
#define GBX_KNEE         40.0f         /* walk test height: low crates block a walk but not a look */

typedef struct {
    float   pos[3];       /*  0 prop->pos */
    float   theta;        /* 12 vv_theta, degrees */
    float   verta;        /* 16 vv_verta, degrees */
    float   health;       /* 20 bondhealth */
    float   armour;       /* 24 bondarmour */
    int32_t dead;         /* 28 bonddead */
    int32_t weapon;       /* 32 hands[0].weaponnum (ITEM_IDS) */
    int32_t room;         /* 36 prop->rooms[0], -1 none */
    int32_t near_node;    /* 40 nearest node reachable in a straight walk, -1 none */
    uint32_t visible;     /* 44 bit j: player j is in line of sight */
    int32_t kills;        /* 48 g_playerPlayerData[i].kill_count */
    int32_t deaths;       /* 52 player->deathcount */
    int32_t points;       /* 56 get_points_for_mp_player */
    uint32_t flags;       /* 60 bit0 present, bit1 on a floor tile */
    int32_t ammo;         /* 64 rounds for the weapon in hand (magazines + reserve), -1 = needs none */
    int32_t mag;          /* 68 rounds in the right hand's magazine */
    int32_t pad_[2];      /* 72 */
} GbxPlayer;              /* 80 */

typedef struct {
    uint32_t seq;         /*  0 bumped by gBox on every write */
    uint32_t enabled;     /*  4 1: gBox drives this seat */
    uint16_t buttons;     /*  8 N64 button mask (A 0x8000 B 0x4000 Z 0x2000 START 0x1000 ...) */
    int8_t   sx, sy;      /* 10 stick, -80..80 */
    uint32_t live;        /* 12 written by the port: 1 while it takes this seat's input */
} GbxSeat;                /* 16 */

typedef struct {
    float   pos[3];       /*  0 */
    int32_t first;        /* 12 first index into edges[] */
    int32_t count;        /* 16 */
    int32_t kind;         /* 20 0 pad, 1 bound pad, 2 floor tile */
} GbxNode;                /* 24 */

typedef struct {
    float   pos[3];
    int32_t item;         /* ITEM_IDS */
} GbxItem;                /* 16 */

typedef struct {
    float   pos[3];
    int32_t alive;
    uint32_t visible;     /* bit i: player i sees this guard */
    float   health;       /* 1 - damage / maxdamage */
    int32_t pad_[2];
} GbxChr;                 /* 32 */

typedef struct {
    uint32_t magic;       /*   0 */
    uint32_t version;     /*   4 */
    uint32_t size;        /*   8 */
    uint32_t frame;       /*  12 bumped at the end of every tick */
    int32_t  stage;       /*  16 lvlGetCurrentStageToLoad() */
    int32_t  nplayers;    /*  20 */
    int32_t  in_match;    /*  24 a stage (not the title) with players spawned */
    uint32_t nav_serial;  /*  28 bumped when a new graph is published (0: none yet) */
    int32_t  num_nodes;   /*  32 */
    int32_t  num_edges;   /*  36 */
    int32_t  num_items;   /*  40 */
    int32_t  num_chrs;    /*  44 */
    uint32_t pid;         /*  48 */
    uint32_t reserved[3]; /*  52 */
    GbxPlayer players[GBX_PLAYERS];   /*   64 */
    GbxSeat   seats[GBX_PLAYERS];     /*  384 */
    GbxItem   items[GBX_MAX_ITEMS];   /*  448 */
    GbxChr    chrs[GBX_MAX_CHRS];     /* 1472 */
    GbxNode   nodes[GBX_MAX_NODES];   /* 2496 */
    int32_t   edges[GBX_MAX_EDGES];   /* 27072 */
} GbxBridge;                          /* 92608 */

_Static_assert(sizeof(GbxPlayer) == 80, "GbxPlayer layout");
_Static_assert(sizeof(GbxSeat) == 16, "GbxSeat layout");
_Static_assert(sizeof(GbxNode) == 24, "GbxNode layout");
_Static_assert(sizeof(GbxChr) == 32, "GbxChr layout");
_Static_assert(offsetof(GbxBridge, players) == 64, "GbxBridge.players");
_Static_assert(offsetof(GbxBridge, seats) == 384, "GbxBridge.seats");
_Static_assert(offsetof(GbxBridge, items) == 448, "GbxBridge.items");
_Static_assert(offsetof(GbxBridge, chrs) == 1472, "GbxBridge.chrs");
_Static_assert(offsetof(GbxBridge, nodes) == 2496, "GbxBridge.nodes");
_Static_assert(offsetof(GbxBridge, edges) == 27072, "GbxBridge.edges");
_Static_assert(sizeof(GbxBridge) == 92608, "GbxBridge size");

/* Game state this file reads. All of it is touched on the game thread only (gboxBridgeTick). */
extern stagesetup g_CurrentSetup;
extern PropRecord *g_ActivePropsHead;
extern ChrRecord *g_ChrSlots;
extern s32 g_NumChrSlots;
extern s32 lvlGetCurrentStageToLoad(void);
extern s32 get_points_for_mp_player(s32 playernum);
extern s32 get_ammo_type_for_weapon(ITEM_IDS weapon);
struct StanPrefixRecord {                 /* as stan.c defines it (file-local there): same tag and members */
    s32 stanfile;
    StandTile *ptr_firstroom;
};
extern struct StanPrefixRecord *stan_prefix;
extern u8 list_of_tilesizes[];
extern bool stanTileHasZeroArea(StandTile *tile);
extern void getTileMidPoint(StandTile *tile, coord3d *out);

static volatile GbxBridge *g_gbx;      /* NULL: bridge off */
static int s_tried;

/* the graph is built here, then copied into the block in one go */
static float s_nodePos[GBX_MAX_NODES][3];
static StandTile *s_nodeStan[GBX_MAX_NODES];
static int32_t s_nodeKind[GBX_MAX_NODES];
static int32_t s_adj[GBX_MAX_NODES][GBX_MAX_DEGREE];
static float s_adjDist[GBX_MAX_NODES][GBX_MAX_DEGREE];
static int32_t s_adjCount[GBX_MAX_NODES];
static int s_numNodes, s_buildNext = -1, s_navStage = -1, s_stageFrames;

/* seat liveness: the port releases a seat whose writer stopped bumping seq */
static uint32_t s_seatSeq[GBX_PLAYERS], s_seatSeenFrame[GBX_PLAYERS];
static volatile int s_seatLive[GBX_PLAYERS];
static uint32_t s_frame;

static void *gbxMap(const char *where, size_t size)
{
#ifdef _WIN32
    HANDLE h = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0, (DWORD)size, where);
    if (!h) return NULL;
    return MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, size);   /* the mapping lives as long as the process */
#else
    int fd = open(where, O_RDWR | O_CREAT, 0600);
    if (fd < 0) return NULL;
    if (ftruncate(fd, (off_t)size) != 0) { close(fd); return NULL; }
    void *p = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    return p == MAP_FAILED ? NULL : p;
#endif
}

static int gbxOpen(void)
{
    if (g_gbx) return 1;
    if (s_tried) return 0;
    s_tried = 1;
    const char *where = getenv("GE_GBOX_BRIDGE");
    if (!where || !*where) return 0;
    GbxBridge *b = (GbxBridge *)gbxMap(where, sizeof(GbxBridge));
    if (!b) {
        osSyncPrintf("gbox bridge: cannot map %s\n", where);
        return 0;
    }
    memset(b, 0, sizeof(*b));
    b->version = GBX_VERSION;
    b->size = sizeof(GbxBridge);
#ifdef _WIN32
    b->pid = (uint32_t)GetCurrentProcessId();
#else
    b->pid = (uint32_t)getpid();
#endif
    for (int i = 0; i < GBX_PLAYERS; i++) b->players[i].near_node = -1;
    __sync_synchronize();
    b->magic = GBX_MAGIC;                  /* last: gBox waits for it */
    g_gbx = b;
    osSyncPrintf("gbox bridge: %s (%u bytes)\n", where, (unsigned)sizeof(GbxBridge));
    return 1;
}

static int gbxPresent(int i)
{
    return i < getPlayerCount() && g_playerPointers[i] && g_playerPointers[i]->prop;
}

/* The guards' straight-line test: walk the floor tiles from `from` (on tile *t) to `to`; true when nothing of
 * `types` is in the way and the walk ends on tile `want`. */
static int gbxLine(StandTile *t, const float *from, const float *to, StandTile *want, s32 types, f32 h)
{
    if (!t || !want) return 0;
    if (!stanTestLineUnobstructed(&t, from[0], from[2], to[0], to[2], types, h, h, 0.0f, 1.0f)) return 0;
    return t == want;
}

static void gbxNavReset(int stage)
{
    s_numNodes = 0;
    s_buildNext = -1;
    s_navStage = stage;
    s_stageFrames = 0;
}

/* One floor-tile midpoint per cell, walking the tile list the way the game's own nearest-tile search does
 * (stan.c sub_GAME_7F0AFB78: skip flagged and zero-area tiles, step by list_of_tilesizes). */
static void gbxNavTiles(void)
{
    static uint32_t cells[GBX_CELLS];
    if (!stan_prefix || !stan_prefix->ptr_firstroom) return;
    memset(cells, 0, sizeof(cells));
    StandTile *tile = stan_prefix->ptr_firstroom;
    int guard = 0;
    while (*(u32 *)tile && s_numNodes < GBX_MAX_NODES && guard++ < 65536) {
        if (((((u16 *)tile)[0] >> 15) & 1) != 1 && !stanTileHasZeroArea(tile)) {
            coord3d mid;
            getTileMidPoint(tile, &mid);
            int cx = (int)floorf(mid.x / GBX_CELL), cy = (int)floorf(mid.y / 150.0f), cz = (int)floorf(mid.z / GBX_CELL);
            uint32_t key = ((uint32_t)(cx & 0x3FF) << 20 | (uint32_t)(cy & 0x3FF) << 10 | (uint32_t)(cz & 0x3FF)) + 1u;
            uint32_t h = (key * 2654435761u) % GBX_CELLS;
            while (cells[h] && cells[h] != key) h = (h + 1) % GBX_CELLS;
            if (!cells[h]) {
                cells[h] = key;
                s_nodePos[s_numNodes][0] = mid.x;
                s_nodePos[s_numNodes][1] = mid.y;
                s_nodePos[s_numNodes][2] = mid.z;
                s_nodeStan[s_numNodes] = tile;
                s_nodeKind[s_numNodes] = 2;
                s_numNodes++;
            }
        }
        tile = (StandTile *)((u8 *)tile + list_of_tilesizes[(tile->tail.half >> 12) & 0xf]);
    }
}

static void gbxNavCollect(void)
{
    s_numNodes = 0;
    if (g_CurrentSetup.pads) {
        for (PadRecord *pad = g_CurrentSetup.pads; pad->plink && s_numNodes < GBX_MAX_NODES; pad++) {
            if (!pad->stan) continue;
            s_nodePos[s_numNodes][0] = pad->pos.x;
            s_nodePos[s_numNodes][1] = pad->pos.y;
            s_nodePos[s_numNodes][2] = pad->pos.z;
            s_nodeStan[s_numNodes] = pad->stan;
            s_nodeKind[s_numNodes] = 0;
            s_numNodes++;
        }
    }
    if (g_CurrentSetup.boundpads) {
        for (BoundPadRecord *pad = g_CurrentSetup.boundpads; pad->plink && s_numNodes < GBX_MAX_NODES; pad++) {
            if (!pad->stan) continue;
            s_nodePos[s_numNodes][0] = pad->pos.x;
            s_nodePos[s_numNodes][1] = pad->pos.y;
            s_nodePos[s_numNodes][2] = pad->pos.z;
            s_nodeStan[s_numNodes] = pad->stan;
            s_nodeKind[s_numNodes] = 1;
            s_numNodes++;
        }
    }
    gbxNavTiles();
    memset(s_adjCount, 0, sizeof(s_adjCount));
    s_buildNext = 0;
}

/* keep each node's GBX_MAX_DEGREE nearest straight-walk neighbours */
static void gbxNavAddEdge(int i, int j, float d)
{
    int n = s_adjCount[i];
    if (n == GBX_MAX_DEGREE && d >= s_adjDist[i][n - 1]) return;
    if (n < GBX_MAX_DEGREE) n++;
    int k = n - 1;
    while (k > 0 && s_adjDist[i][k - 1] > d) {
        s_adj[i][k] = s_adj[i][k - 1];
        s_adjDist[i][k] = s_adjDist[i][k - 1];
        k--;
    }
    s_adj[i][k] = j;
    s_adjDist[i][k] = d;
    s_adjCount[i] = n;
}

static void gbxNavBuildSome(void)
{
    int end = s_buildNext + GBX_NODES_PER_TICK;
    if (end > s_numNodes) end = s_numNodes;
    for (int i = s_buildNext; i < end; i++) {
        for (int j = 0; j < s_numNodes; j++) {
            if (j == i) continue;
            float dx = s_nodePos[j][0] - s_nodePos[i][0];
            float dy = s_nodePos[j][1] - s_nodePos[i][1];
            float dz = s_nodePos[j][2] - s_nodePos[i][2];
            float d = sqrtf(dx * dx + dz * dz);
            float range = (s_nodeKind[i] == 2 || s_nodeKind[j] == 2) ? GBX_TILE_RANGE : GBX_EDGE_RANGE;
            if (d > range || fabsf(dy) > GBX_EDGE_DY) continue;
            if (gbxLine(s_nodeStan[i], s_nodePos[i], s_nodePos[j], s_nodeStan[j], GBX_WALK_TYPES, GBX_KNEE))
                gbxNavAddEdge(i, j, sqrtf(d * d + dy * dy));
        }
    }
    s_buildNext = end;
}

static void gbxNavPublish(void)
{
    volatile GbxBridge *b = g_gbx;
    int e = 0;
    for (int i = 0; i < s_numNodes; i++) {
        volatile GbxNode *n = &b->nodes[i];
        n->pos[0] = s_nodePos[i][0];
        n->pos[1] = s_nodePos[i][1];
        n->pos[2] = s_nodePos[i][2];
        n->kind = s_nodeKind[i];
        n->first = e;
        int c = 0;
        for (int k = 0; k < s_adjCount[i] && e < GBX_MAX_EDGES; k++, c++) b->edges[e++] = s_adj[i][k];
        n->count = c;
    }
    b->num_nodes = s_numNodes;
    b->num_edges = e;
    __sync_synchronize();
    b->nav_serial++;
    s_buildNext = -1;
    osSyncPrintf("gbox bridge: stage %d nav graph %d nodes %d links\n", s_navStage, s_numNodes, e);
}

/* nearest node a player reaches by walking straight (tested nearest-first, at most 8 tests) */
static int gbxNearNode(PropRecord *prop)
{
    if (!prop->stan || s_buildNext >= 0 || !g_gbx->nav_serial) return -1;
    int best[8], nb = 0;
    float bestd[8];
    float p[3] = { prop->pos.x, prop->pos.y, prop->pos.z };
    for (int i = 0; i < s_numNodes; i++) {
        float dx = s_nodePos[i][0] - p[0], dy = s_nodePos[i][1] - p[1], dz = s_nodePos[i][2] - p[2];
        float d = dx * dx + dz * dz + 4.0f * dy * dy;     /* other floors count as far away */
        if (nb < 8) nb++;
        else if (d >= bestd[nb - 1]) continue;
        int k = nb - 1;
        while (k > 0 && bestd[k - 1] > d) { best[k] = best[k - 1]; bestd[k] = bestd[k - 1]; k--; }
        best[k] = i;
        bestd[k] = d;
    }
    for (int k = 0; k < nb; k++)
        if (gbxLine(prop->stan, p, s_nodePos[best[k]], s_nodeStan[best[k]], GBX_WALK_TYPES, GBX_KNEE)) return best[k];
    return nb ? best[0] : -1;    /* nothing straight: the nearest one (the bot steers and the stuck logic copes) */
}

static void gbxPlayers(void)
{
    volatile GbxBridge *b = g_gbx;
    for (int i = 0; i < GBX_PLAYERS; i++) {
        volatile GbxPlayer *o = &b->players[i];
        if (!gbxPresent(i)) {
            o->flags = 0;
            o->visible = 0;
            o->near_node = -1;
            continue;
        }
        struct player *pl = g_playerPointers[i];
        PropRecord *prop = pl->prop;
        o->pos[0] = prop->pos.x;
        o->pos[1] = prop->pos.y;
        o->pos[2] = prop->pos.z;
        o->theta = pl->vv_theta;
        o->verta = pl->vv_verta;
        o->health = pl->bondhealth;
        o->armour = pl->bondarmour;
        o->dead = pl->bonddead;
        o->weapon = pl->hands[0].weaponnum;
        o->room = prop->rooms[0] == 0xFF ? -1 : prop->rooms[0];
        o->kills = g_playerPlayerData[i].kill_count;
        o->deaths = pl->deathcount;
        o->points = getPlayerCount() > 1 ? get_points_for_mp_player(i) : 0;
        o->flags = 1u | (prop->stan ? 2u : 0u);
        {   /* as currentPlayerGetAmmoCount does for player 1: reserve of the weapon's ammo type + magazines */
            s32 type = get_ammo_type_for_weapon(pl->hands[0].weaponnum);
            o->mag = pl->hands[0].weapon_ammo_in_magazine;
            if (type <= AMMO_NONE || type >= 30) {
                o->ammo = -1;
            } else {
                s32 n = pl->ammoheldarr[type] + pl->hands[0].weapon_ammo_in_magazine;
                if (get_ammo_type_for_weapon(pl->hands[1].weaponnum) == type) n += pl->hands[1].weapon_ammo_in_magazine;
                o->ammo = n;
            }
        }
        if ((s_frame & 3) == (uint32_t)i) o->near_node = gbxNearNode(prop);
    }
    /* line of sight: the guards' test from i's tile to j's position, ending on j's tile */
    for (int i = 0; i < GBX_PLAYERS; i++) {
        uint32_t vis = 0;
        if (gbxPresent(i) && !g_playerPointers[i]->bonddead) {
            PropRecord *a = g_playerPointers[i]->prop;
            float from[3] = { a->pos.x, a->pos.y, a->pos.z };
            for (int j = 0; j < GBX_PLAYERS; j++) {
                if (j == i || !gbxPresent(j) || g_playerPointers[j]->bonddead) continue;
                PropRecord *t = g_playerPointers[j]->prop;
                float to[3] = { t->pos.x, t->pos.y, t->pos.z };
                if (gbxLine(a->stan, from, to, t->stan, GBX_LOS_TYPES, GBX_EYE)) vis |= 1u << j;
            }
        }
        b->players[i].visible = vis;
    }
}

/* GE_GBOX_DEBUG=1: every 2 s, the raw line tests between players (diagnostics only) */
static void gbxDebugLines(void)
{
    static int on = -1;
    if (on < 0) on = getenv("GE_GBOX_DEBUG") != NULL;
    if (!on || (s_frame % 120) != 0) return;
    for (int i = 0; i < GBX_PLAYERS; i++) {
        if (!gbxPresent(i)) continue;
        PropRecord *a = g_playerPointers[i]->prop;
        int nodesSeen = 0;
        for (int n = 0; n < s_numNodes && s_buildNext < 0; n++) {
            float from[3] = { a->pos.x, a->pos.y, a->pos.z };
            if (gbxLine(a->stan, from, s_nodePos[n], s_nodeStan[n], GBX_LOS_TYPES, GBX_EYE)) nodesSeen++;
        }
        for (int j = 0; j < GBX_PLAYERS; j++) {
            if (j == i || !gbxPresent(j)) continue;
            PropRecord *t = g_playerPointers[j]->prop;
            StandTile *tile = a->stan;
            s32 ret = tile ? stanTestLineUnobstructed(&tile, a->pos.x, a->pos.z, t->pos.x, t->pos.z, GBX_LOS_TYPES,
                                                      GBX_EYE, GBX_EYE, 0.0f, 1.0f) : -1;
            float dx = t->pos.x - a->pos.x, dz = t->pos.z - a->pos.z;
            osSyncPrintf("gbox bridge: los %d->%d d=%.0f ret=%d end=%p want=%p nodes_seen=%d\n", i, j,
                         sqrtf(dx * dx + dz * dz), (int)ret, (void *)tile, (void *)t->stan, nodesSeen);
        }
    }
}

static void gbxItems(void)
{
    volatile GbxBridge *b = g_gbx;
    int n = 0;
    for (PropRecord *p = g_ActivePropsHead; p && n < GBX_MAX_ITEMS; p = p->next) {
        if (p->type != PROP_TYPE_WEAPON || !p->weapon || p->parent) continue;
        b->items[n].pos[0] = p->pos.x;
        b->items[n].pos[1] = p->pos.y;
        b->items[n].pos[2] = p->pos.z;
        b->items[n].item = p->weapon->weaponnum;
        n++;
    }
    b->num_items = n;
}

/* solo levels: the guards nearest to player 1, with who can see them */
static void gbxChrs(void)
{
    volatile GbxBridge *b = g_gbx;
    int n = 0;
    if (g_ChrSlots && gbxPresent(0)) {
        for (int c = 0; c < g_NumChrSlots && n < GBX_MAX_CHRS; c++) {
            ChrRecord *chr = &g_ChrSlots[c];
            if (!chr->model || !chr->prop) continue;
            volatile GbxChr *o = &b->chrs[n];
            o->pos[0] = chr->prop->pos.x;
            o->pos[1] = chr->prop->pos.y;
            o->pos[2] = chr->prop->pos.z;
            o->alive = chr->actiontype != ACT_DIE && chr->actiontype != ACT_DEAD;
            o->health = chr->maxdamage > 0.0f ? 1.0f - chr->damage / chr->maxdamage : 1.0f;
            uint32_t vis = 0;
            for (int i = 0; i < GBX_PLAYERS; i++) {
                if (!gbxPresent(i)) continue;
                PropRecord *a = g_playerPointers[i]->prop;
                float from[3] = { a->pos.x, a->pos.y, a->pos.z };
                float to[3] = { chr->prop->pos.x, chr->prop->pos.y, chr->prop->pos.z };
                if (o->alive && gbxLine(a->stan, from, to, chr->prop->stan, GBX_LOS_TYPES, GBX_EYE)) vis |= 1u << i;
            }
            o->visible = vis;
            n++;
        }
    }
    b->num_chrs = n;
}

static void gbxSeats(void)
{
    volatile GbxBridge *b = g_gbx;
    for (int i = 0; i < GBX_PLAYERS; i++) {
        uint32_t seq = b->seats[i].seq;
        if (seq != s_seatSeq[i]) {
            s_seatSeq[i] = seq;
            s_seatSeenFrame[i] = s_frame;
        }
        int live = b->seats[i].enabled && (s_frame - s_seatSeenFrame[i]) < GBX_STALE_FRAMES;
        s_seatLive[i] = live;
        b->seats[i].live = (uint32_t)live;
    }
}

/* Game thread, once per frame (src/boss.c after joyConsumeSamplesWrapper). */
void gboxBridgeTick(void)
{
    if (!gbxOpen()) return;
    volatile GbxBridge *b = g_gbx;
    s_frame++;
    s32 stage = lvlGetCurrentStageToLoad();
    int inMatch = stage != LEVELID_TITLE && stage >= 0 && gbxPresent(0);
    b->stage = stage;
    b->nplayers = getPlayerCount();
    b->in_match = inMatch;
    if (stage != s_navStage) {
        gbxNavReset(stage);
        b->num_nodes = b->num_edges = 0;
    }
    gbxSeats();
    if (inMatch) {
        s_stageFrames++;
        if (s_buildNext < 0 && s_numNodes == 0 && s_stageFrames > 30) gbxNavCollect();
        if (s_buildNext >= 0) {
            gbxNavBuildSome();
            if (s_buildNext >= s_numNodes) gbxNavPublish();
        }
        gbxPlayers();
        gbxDebugLines();
        if ((s_frame % 10) == 0) gbxItems();
        if ((s_frame & 3) == 0) gbxChrs();
    } else {
        for (int i = 0; i < GBX_PLAYERS; i++) b->players[i].flags = 0;
    }
    __sync_synchronize();
    b->frame = s_frame;
}

/* Input thread (port/src/input.c), for every controller every poll: a seat gBox drives takes its buttons and stick.
 * Returns 1 when it replaced them. */
int gboxBridgeSeat(int idx, unsigned *button, int *sx, int *sy)
{
    volatile GbxBridge *b = g_gbx;
    if (!b || idx < 0 || idx >= GBX_PLAYERS || !s_seatLive[idx]) return 0;
    *button = b->seats[idx].buttons;
    *sx = b->seats[idx].sx;
    *sy = b->seats[idx].sy;
    return 1;
}
