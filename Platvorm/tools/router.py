#!/usr/bin/env python3
"""Grid A* router + via passes for the Platvorm 4-layer re-route.

Run under KiCad's bundled Python. Consumes analysis/helpers/pads_api.json.
"""
import pcbnew, json, math, heapq
from collections import deque

NM = 1000000
BOARD = "Platvorm.kicad_pcb"
HELP = "analysis/helpers"
F, B, IN1, IN2 = pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu

CLR = 0.20
TRK_SIG = 0.2  # fits 2.54-pitch THT fields with 0.2 clearance
VIA_D, VIA_DRILL = 0.6, 0.3
VIA_HALF = VIA_D / 2
MARGIN = 0.05
EDGE_KEEPIN = 0.95  # edge rule 0.3 + max track half 0.6 + margin
GRID = 0.05
VIA_COST = 6.0   # ~0.3 mm equivalent: vias nearly free, B layer is wide open

FAT_NETS = {
    "/Power Supply/VIN_BUCK": 1.2, "/Power Supply/SW": 1.2,
    "/Power Supply/VOUT_PRE": 1.2, "+5V": 1.0, "+12V": 1.0, "-12V": 1.0,
    "/Power Supply/+12V_RAW": 1.0, "/Power Supply/-12V_RAW": 1.0,
    "/Power Supply/+5V_EURO": 1.0, "VBUS": 0.5,
}
PLANES = {"GND": IN1, "+3V3": IN2}

ROUTE_ORDER = [
    "/USB & UART Bridge/USB_DM", "/USB & UART Bridge/USB_DP",
    "/Power Supply/VIN_BUCK", "/Power Supply/VOUT_PRE", "FB", "/Power Supply/SW",
    "/Power Supply/+12V_RAW", "/Power Supply/-12V_RAW", "/Power Supply/+5V_EURO",
    "+12V", "-12V", "+5V", "VBUS",
    "/USB & UART Bridge/CC1", "/USB & UART Bridge/CC2",
]


def V(x, y):
    return pcbnew.VECTOR2I(int(round(x * NM)), int(round(y * NM)))


def aabb_pad(p):
    w, h = p["w"], p["h"]
    rot = p["rot"] % 180
    if 45 < rot < 135:
        w, h = h, w
    return w, h


class Router:
    """0.1 mm grid A* over F.Cu/B.Cu with via transitions."""

    def __init__(self, pads):
        self.pads = pads
        x0, y0, x1, y1 = pads["bbox"]
        self.x0, self.y0 = x0 + EDGE_KEEPIN, y0 + EDGE_KEEPIN
        self.x1, self.y1 = x1 - EDGE_KEEPIN, y1 - EDGE_KEEPIN
        self.nx = int((self.x1 - self.x0) / GRID) + 1
        self.ny = int((self.y1 - self.y0) / GRID) + 1
        n = self.nx * self.ny
        self.INF = {  # obstacle inflation per width class
            "sig": CLR + TRK_SIG / 2 + MARGIN,      # tracks <= 0.25
            "fat12": CLR + 0.6 + MARGIN,            # tracks ~1.2
            "fat10": CLR + 0.5 + MARGIN,            # tracks ~1.0
            "fat08": CLR + 0.4 + MARGIN,            # tracks ~0.8
            "via": CLR + VIA_HALF + MARGIN,
        }
        self.g = [{k: bytearray(n) for k in self.INF} for _ in range(2)]
        self.net_cells = {}       # net -> set((i,j)) own copper (passable)
        self.vias = []            # (x, y, net)
        self.placed_tracks = []   # (layer_idx, x1,y1,x2,y2, width, net)
        self._pad_obstacles()

    # ---------- grid helpers ----------
    def cell(self, x, y):
        return int(round((x - self.x0) / GRID)), int(round((y - self.y0) / GRID))

    def xy(self, i, j):
        return self.x0 + i * GRID, self.y0 + j * GRID

    def inb(self, i, j):
        return 0 <= i < self.nx and 0 <= j < self.ny

    # ---------- obstacles ----------
    def _mark_rect(self, li, cls, cx, cy, hw, hh, clear=False):
        g = self.g[li][cls]
        i0, j0 = self.cell(cx - hw, cy - hh)
        i1, j1 = self.cell(cx + hw, cy + hh)
        for j in range(max(0, j0), min(self.ny, j1 + 1)):
            base = j * self.nx
            for i in range(max(0, i0), min(self.nx, i1 + 1)):
                x, y = self.xy(i, j)
                if abs(x - cx) <= hw and abs(y - cy) <= hh:
                    idx = base + i
                    g[idx] = max(0, g[idx] - 1) if clear else min(255, g[idx] + 1)

    def _mark_seg(self, li, cls, x1, y1, x2, y2, r, clear=False):
        g = self.g[li][cls]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        i0, j0 = self.cell(min(x1, x2) - r, min(y1, y2) - r)
        i1, j1 = self.cell(max(x1, x2) + r, max(y1, y2) + r)
        for j in range(max(0, j0), min(self.ny, j1 + 1)):
            base = j * self.nx
            for i in range(max(0, i0), min(self.nx, i1 + 1)):
                x, y = self.xy(i, j)
                t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
                px, py = x1 + t * dx, y1 + t * dy
                if (x - px) ** 2 + (y - py) ** 2 <= r * r:
                    idx = base + i
                    g[idx] = max(0, g[idx] - 1) if clear else min(255, g[idx] + 1)

    def _mark_all_cls(self, li, kind, args, width, clear=False):
        for cls in self.INF:
            inf = self.INF[cls]
            if kind == "seg":
                r = width / 2 + inf
                self._mark_seg(li, cls, args[0], args[1], args[2], args[3], r, clear)
            else:
                x, y = args
                if isinstance(width, tuple):
                    w, h = width
                    self._mark_rect(li, cls, x, y, w / 2 + inf, h / 2 + inf, clear)
                else:
                    self._mark_rect(li, cls, x, y, width / 2 + inf, width / 2 + inf, clear)

    def _pad_obstacles(self):
        for ref, fp in self.pads["footprints"].items():
            for p in fp["pads"]:
                # NB: unconnected pads are physical copper -> obstacles too
                w, h = aabb_pad(p)
                lays = (0, 1) if p["attr"] == 0 else (0 if fp["layer"] == "F.Cu" else 1,)
                for li in lays:
                    self._mark_all_cls(li, "rect", (p["x"], p["y"]), (w, h))

    def block_track(self, li, x1, y1, x2, y2, width, net):
        self._mark_all_cls(li, "seg", (x1, y1, x2, y2), width)
        cells = self.net_cells.setdefault(net, set())
        i0, j0 = self.cell(min(x1, x2) - width / 2, min(y1, y2) - width / 2)
        i1, j1 = self.cell(max(x1, x2) + width / 2, max(y1, y2) + width / 2)
        for j in range(max(0, j0), min(self.ny, j1 + 1)):
            for i in range(max(0, i0), min(self.nx, i1 + 1)):
                cells.add((i, j, li))  # layer-aware

    def block_via(self, x, y):
        for li in (0, 1):
            self._mark_all_cls(li, "rect", (x, y), (VIA_D, VIA_D))

    # ---------- own-net passability ----------
    def open_net(self, net):
        """Make own-net cells passable on both layers for chaining."""
        cells = self.net_cells.get(net)
        if not cells:
            return
        for li in range(2):
            for cls in self.INF:
                g = self.g[li][cls]
                for (i, j) in cells:
                    if 0 <= i < self.nx and 0 <= j < self.ny:
                        g[j * self.nx + i] = 0

    def close_net(self, net, li_pairs):
        """Re-block own-net cells except those just opened for endpoints."""
        # after routing we re-block every own cell: foreign nets must not pass
        # through our copper; own net re-opens at next route() call anyway.
        cells = self.net_cells.get(net)
        if not cells:
            return
        for li, cls in li_pairs:
            g = self.g[li][cls]
            for (i, j) in cells:
                if 0 <= i < self.nx and 0 <= j < self.ny:
                    g[j * self.nx + i] = 1

    # ---------- pads -> endpoint cells ----------
    def forget_net(self, net):
        """Permanently un-mark and drop all placed copper of a net (rip-up)."""
        keep_t = []
        for t in self.placed_tracks:
            if t[6] == net:
                self._mark_all_cls(t[0], "seg", (t[1], t[2], t[3], t[4]), t[5], clear=True)
            else:
                keep_t.append(t)
        self.placed_tracks = keep_t
        keep_v = []
        for v in self.vias:
            if v[2] == net:
                for li in (0, 1):
                    self._mark_all_cls(li, "rect", (v[0], v[1]), (VIA_D, VIA_D), clear=True)
            else:
                keep_v.append(v)
        self.vias = keep_v
        self.net_cells.pop(net, None)

    def pad_endpoints(self, pad, fp):
        w, h = aabb_pad(pad)
        lays = (0, 1) if pad["attr"] == 0 else (0 if fp["layer"] == "F.Cu" else 1,)
        out = {}
        for li in lays:
            i0, j0 = self.cell(pad["x"] - w / 2 - 0.05, pad["y"] - h / 2 - 0.05)
            i1, j1 = self.cell(pad["x"] + w / 2 + 0.05, pad["y"] + h / 2 + 0.05)
            out[li] = {(i, j) for i in range(max(0, i0), min(self.nx, i1 + 1))
                       for j in range(max(0, j0), min(self.ny, j1 + 1))}
        return out

    # ---------- A* ----------
    def build_avoid(self, x0, y0, x1, y1):
        """Soft-cost region: through-traffic discouraged (buck switching area)."""
        self.avoid = [bytearray(self.nx * self.ny), bytearray(self.nx * self.ny)]
        for li in (0, 1):
            i0, j0 = self.cell(x0, y0); i1, j1 = self.cell(x1, y1)
            for j in range(max(0, j0), min(self.ny, j1 + 1)):
                base = j * self.nx
                for i in range(max(0, i0), min(self.nx, i1 + 1)):
                    self.avoid[li][base + i] = 1

    def route(self, width, starts, goals, guide=None, bmult=1.0, avoid=False):
        if width <= TRK_SIG + 0.01:
            cls = "sig"
        elif width >= 1.1:
            cls = "fat12"
        elif width >= 0.9:
            cls = "fat10"
        else:
            cls = "fat08"
        gsig = (self.g[0][cls], self.g[1][cls])
        gvia = (self.g[0]["via"], self.g[1]["via"])
        start_set = {(i, j, li) for li, c in starts.items() for (i, j) in c}
        goal_states = {(i, j, li) for li, c in goals.items() for (i, j) in c}
        if not start_set or not goal_states:
            return None
        parent = {}
        dist = {}
        pq = []
        for s in sorted(start_set):
            dist[s] = 0.0
            heapq.heappush(pq, (0.0, 0.0, s))
        goal_state = None
        while pq:
            d, _, cur = heapq.heappop(pq)
            if d > dist.get(cur, 1e18) + 1e-9:
                continue
            i, j, li = cur
            if cur in goal_states:  # layer-aware: F-only goals must not match B cells
                goal_state = cur
                break
            nbrs = []
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not self.inb(ni, nj):
                    continue
                if gsig[li][nj * self.nx + ni]:
                    continue
                c = bmult if li == 1 else 1.0
                if guide is not None:
                    c += guide[li][nj * self.nx + ni]
                if avoid and self.avoid[li][nj * self.nx + ni]:
                    c += 3.0
                nbrs.append((ni, nj, li, c))
            # via transition
            oli = 1 - li
            if not gvia[li][j * self.nx + i] and not gvia[oli][j * self.nx + i]:
                nbrs.append((i, j, oli, VIA_COST))
            for (ni, nj, nli, c) in nbrs:
                nd = d + c
                st = (ni, nj, nli)
                if nd < dist.get(st, 1e18) - 1e-9:
                    dist[st] = nd
                    parent[st] = cur
                    gi = (ni - i) ** 2 + (nj - j) ** 2
                    heapq.heappush(pq, (nd, gi, st))
        if goal_state is None:
            return None
        path = [goal_state]
        while path[-1] in parent:
            path.append(parent[path[-1]])
        path.reverse()
        return path

    # ---------- emit copper ----------
    def emit(self, path, width, net, board, start_pad, goal_pad):
        pts = []
        for (i, j, li) in path:
            x, y = self.xy(i, j)
            if pts and pts[-1][2] != li:
                pts.append([x, y, pts[-1][2]])
            pts.append([x, y, li])
        for a, b in zip(pts, pts[1:]):
            if a[2] == b[2]:
                dx = abs(a[0] - b[0]); dy = abs(a[1] - b[1])
                if not (dx <= GRID + 1e-9 and dy <= GRID + 1e-9):
                    raise RuntimeError(f"PATH DISCONTINUITY in {net}")

        runs, run = [], [pts[0]]
        for p in pts[1:]:
            if p[2] != run[-1][2]:
                runs.append((run[0][2], run))
                run = [p]
            else:
                run.append(p)
        runs.append((run[0][2], run))

        def collinear_merge(r):
            res = [r[0]]
            for p in r[1:]:
                lp = res[-1]
                if p[0] == lp[0] and p[1] == lp[1]:
                    continue
                if len(res) >= 2:
                    pp = res[-2]
                    if (pp[0] == lp[0] == p[0]) or (pp[1] == lp[1] == p[1]):
                        res[-1] = p
                        continue
                res.append(p)
            return res

        def stair_merge(r):
            """DISABLED: merged diagonals cross unvalidated cells and short
            foreign copper (observed: 20mm diagonals through U1 pad column).
            Staircase routing is kept — correctness over cosmetics."""
            return r
            changed = True
            while changed and len(r) > 2:
                changed = False
                out = [r[0]]
                k = 1
                while k < len(r) - 1:
                    if k >= len(r) - 2 and len(r) > 2:
                        pass  # keep final two points intact (goal termination)
                    a, b, c = out[-1], r[k], r[k + 1]
                    ab = (b[0] - a[0], b[1] - a[1])
                    bc = (c[0] - b[0], c[1] - b[1])
                    one = GRID + 1e-9
                    if (abs(ab[0]) <= one and abs(ab[1]) <= one and
                            abs(bc[0]) <= one and abs(bc[1]) <= one and
                            ((ab[0] == 0) != (bc[0] == 0))):  # perpendicular unit steps
                        out.append(c)  # diagonal a->c
                        k += 2
                        changed = True
                    else:
                        out.append(r[k])
                        k += 1
                out.append(r[-1]) if out[-1] != r[-1] else None
                r = out
            return r

        # NB: no pad-center insertion. pad_core_cells guarantees the path's
        # first/last grid cells lie inside real pad copper, so the connection
        # is made by the grid path itself. Center insertion produced short
        # unvalidated diagonals that violated clearance at tight connectors.

        netcode = board.FindNet(net)
        placed = 0
        for li, rr in runs:
            lay = F if li == 0 else B
            poly = collinear_merge(rr)
            poly = stair_merge(poly)
            for a, b in zip(poly, poly[1:]):
                if a[0] == b[0] and a[1] == b[1]:
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(V(a[0], a[1])); t.SetEnd(V(b[0], b[1]))
                t.SetWidth(int(width * NM))
                t.SetLayer(lay)
                t.SetNet(netcode)
                board.Add(t)
                self.block_track(li, a[0], a[1], b[0], b[1], width, net)
                self.placed_tracks.append((li, a[0], a[1], b[0], b[1], width, net))
                placed += 1
        for (li_prev, r_prev) in runs[:-1]:
            x, y = r_prev[-1][0], r_prev[-1][1]
            v = pcbnew.PCB_VIA(board)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetPosition(V(x, y))
            v.SetWidth(int(VIA_D * NM)); v.SetDrill(int(VIA_DRILL * NM))
            v.SetNet(netcode)
            board.Add(v)
            self.block_via(x, y)
            self.vias.append((x, y, net))
            placed += 1
        return placed

    # ---------- guide field (diff pair coupling) ----------
    def dist_field(self, cells):
        """BFS distance (grid steps) from given cells, per layer, as float cost arrays."""
        fields = [bytearray(self.nx * self.ny) for _ in range(2)]
        for li in range(2):
            dq = deque()
            seen = bytearray(self.nx * self.ny)
            for (i, j) in cells:
                if self.inb(i, j):
                    idx = j * self.nx + i
                    if not seen[idx]:
                        seen[idx] = 1
                        dq.append((i, j, 0))
            while dq:
                i, j, d = dq.popleft()
                if d >= 255:
                    continue
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = i + di, j + dj
                    if self.inb(ni, nj):
                        idx = nj * self.nx + ni
                        if not seen[idx]:
                            seen[idx] = 1
                            fields[li][idx] = d + 1 if d + 1 < 255 else 255
                            dq.append((ni, nj, d + 1))
        return fields
