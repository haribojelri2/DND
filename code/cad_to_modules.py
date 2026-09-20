# -*- coding: utf-8 -*-
"""도면의 선·호를 기본 모듈로 치환한다 (CAD → CAD).

    python cad_to_modules.py <입력.dxf> [출력.dxf] [--layer RAIL,0] [--tol 2] [--L 200]

일반 도면(선·호만 있는 도면)에서 모듈 형태를 찾아 플러그인 기본 모듈(RAILMOD_ 블록 + RAILPLUGIN XData)로 바꾼다.
찾는 형태는 모듈 형상(module_judge.build_local = 플러그인 ModuleGeom.Build 와 같은 것)과 같은 것만이다.

  호-(직선)-호, 두 호가 같은 쪽으로 180°        → 아치: 양 끝 레일이 지나가면 DOUBLE BRANCH,
                                                 한쪽만 지나가면 U BRANCH, 둘 다 끝나면 U
  호-(직선)-호, 두 호가 반대쪽으로 같은 각도      → 차선 이동: 양 끝이 지나가면 N, 한쪽이 끝나면 BY PASS,
                                                 둘 다 끝나면 S
  90° 호 하나, 한쪽 끝이 갈림점                  → BRANCH
  90° 호 하나, 양쪽 끝이 그냥 이어짐              → CURVE

모듈 하나가 덮는 직선 길이는 L 로 정해진다(다리·관통 직선). 붙어 있는 직선이 짧으면 L 을 줄여서 맞추고,
그래도 안 맞으면 그 자리는 바꾸지 않고 경고한다. 모듈이 덮지 않은 선·호는 그대로 남긴다.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ezdxf

import module_judge as mj
from module_testdxf import Lay

Pt = Tuple[float, float]

L_CANDIDATES = (200.0, 150.0, 120.0, 100.0, 80.0, 60.0, 50.0)


# ── 기본 계산 ────────────────────────────────────────────────────────────────
def sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def add(a: Pt, b: Pt) -> Pt:
    return (a[0] + b[0], a[1] + b[1])


def mul(a: Pt, k: float) -> Pt:
    return (a[0] * k, a[1] * k)


def dot(a: Pt, b: Pt) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Pt, b: Pt) -> float:
    return a[0] * b[1] - a[1] * b[0]


def norm(a: Pt) -> float:
    return math.hypot(a[0], a[1])


def unit(a: Pt) -> Pt:
    n = norm(a)
    return (a[0] / n, a[1] / n) if n > 1e-9 else (0.0, 0.0)


def dist(a: Pt, b: Pt) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def ang(c: Pt, p: Pt) -> float:
    return math.degrees(math.atan2(p[1] - c[1], p[0] - c[0])) % 360.0


# ── 도면 읽기 ────────────────────────────────────────────────────────────────
@dataclass
class Seg:
    kind: str                 # LINE / ARC
    p0: Pt
    p1: Pt
    c: Optional[Pt] = None    # 호 중심
    r: float = 0.0
    sweep: float = 0.0        # 0→1 로 갈 때의 부호 있는 각(+ 반시계)
    layer: str = "0"
    covered: List[Tuple[float, float]] = field(default_factory=list)   # 직선: 덮인 구간(0~길이)
    used: bool = False        # 호: 모듈이 가져감

    @property
    def length(self) -> float:
        if self.kind == "LINE":
            return dist(self.p0, self.p1)
        return abs(math.radians(self.sweep)) * self.r

    def dir(self) -> Pt:
        return unit(sub(self.p1, self.p0))

    def tangent_at(self, p: Pt) -> Pt:
        """p(끝점) 에서 세그먼트가 뻗어 나가는 방향."""
        if self.kind == "LINE":
            return self.dir() if dist(p, self.p0) < dist(p, self.p1) else unit(sub(self.p0, self.p1))
        sgn = 1.0 if self.sweep > 0 else -1.0
        if dist(p, self.p1) < dist(p, self.p0):
            sgn = -sgn
        rad = sub(p, self.c)
        return unit((-sgn * rad[1], sgn * rad[0]))


def read_segments(doc, layers: Optional[Sequence[str]]) -> List[Seg]:
    segs: List[Seg] = []
    lay = set(s.upper() for s in layers) if layers else None

    def take(e, ocs_owner=None):
        t = e.dxftype()
        if lay is not None and str(e.dxf.layer).upper() not in lay:
            return
        if t == "LINE":
            s, q = e.dxf.start, e.dxf.end
            segs.append(Seg("LINE", (s.x, s.y), (q.x, q.y), layer=str(e.dxf.layer)))
        elif t == "ARC":
            c = e.ocs().to_wcs(e.dxf.center)
            r = float(e.dxf.radius)
            a0, a1 = float(e.dxf.start_angle), float(e.dxf.end_angle)
            sweep = (a1 - a0) % 360.0
            p0 = (c.x + r * math.cos(math.radians(a0)), c.y + r * math.sin(math.radians(a0)))
            p1 = (c.x + r * math.cos(math.radians(a1)), c.y + r * math.sin(math.radians(a1)))
            if float(e.dxf.extrusion.z) < 0:       # 좌우 대칭 배치(OCS) → 월드로 뒤집기
                cx = c.x
                p0 = (2 * cx - p0[0], p0[1])
                p1 = (2 * cx - p1[0], p1[1])
                sweep = -sweep
            segs.append(Seg("ARC", p0, p1, (c.x, c.y), r, sweep, layer=str(e.dxf.layer)))

    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            for ve in e.virtual_entities():
                take(ve)
        else:
            take(e)
    return segs


# ── 연결 그래프 ──────────────────────────────────────────────────────────────
class Graph:
    def __init__(self, segs: List[Seg], tol: float):
        self.segs = segs
        self.tol = tol
        self.nodes: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
        for i, s in enumerate(segs):
            for e, p in ((0, s.p0), (1, s.p1)):
                self.nodes.setdefault(self.key(p), []).append((i, e))

    def key(self, p: Pt) -> Tuple[int, int]:
        return (int(round(p[0] / self.tol)), int(round(p[1] / self.tol)))

    def at(self, p: Pt) -> List[Tuple[int, int]]:
        return self.nodes.get(self.key(p), [])

    def deg(self, p: Pt) -> int:
        return len(self.at(p))

    def others(self, p: Pt, exclude: Sequence[int]) -> List[int]:
        return [i for i, _ in self.at(p) if i not in exclude]


# ── 모듈 후보 ────────────────────────────────────────────────────────────────
@dataclass
class Cand:
    name: str
    at: Pt                    # 모듈 로컬 anchor 가 놓일 월드 점
    anchor: Any               # 로컬 anchor (r,l,w,a,h 를 받아 계산)
    heading: float            # 로컬 +Y 가 향할 월드 방향(도)
    R: float
    W: float
    A: float
    segs: Tuple[int, ...]     # 이 후보가 가져가는 도면 세그먼트(호·중간 직선)
    note: str = ""


def turn_sign(s: Seg, from_pt: Pt) -> int:
    """from_pt 에서 출발해 호를 지날 때 왼쪽(+1)/오른쪽(-1) 어느 쪽으로 도는가."""
    sgn = 1 if s.sweep > 0 else -1
    if dist(from_pt, s.p1) < dist(from_pt, s.p0):
        sgn = -sgn
    return sgn


def _smooth(arrive: Pt, depart: Pt, ang_tol: float) -> bool:
    """이어지는 두 조각의 진행 방향이 같은가(첨점이 아닌가)."""
    return dot(arrive, depart) >= math.cos(math.radians(max(ang_tol, 2.0)))


def _chain_partner(g: Graph, i: int, ang_tol: float) -> List[Tuple[int, Optional[int], Pt, Pt]]:
    """호 i 와 (직선 하나를 사이에 두고) 진행 방향이 이어지는 다른 호들:
    (j, 중간직선, 바깥끝 i, 바깥끝 j)"""
    out = []
    segs = g.segs
    a = segs[i]
    for ea, pa in ((0, a.p0), (1, a.p1)):
        outer_a = a.p1 if ea == 0 else a.p0
        arrive = mul(a.tangent_at(pa), -1.0)          # pa 에 도착하는 진행 방향
        for j in g.others(pa, [i]):
            b = segs[j]
            if b.kind == "ARC":
                if not _smooth(arrive, b.tangent_at(pa), ang_tol):
                    continue
                outer_b = b.p1 if dist(b.p0, pa) < dist(b.p1, pa) else b.p0
                out.append((j, None, outer_a, outer_b))
            else:
                if not _smooth(arrive, b.tangent_at(pa), ang_tol):
                    continue
                far = b.p1 if dist(b.p0, pa) < dist(b.p1, pa) else b.p0
                arrive2 = mul(b.tangent_at(far), -1.0)
                for k in g.others(far, [j]):
                    c = segs[k]
                    if c.kind != "ARC" or k == i:
                        continue
                    if not _smooth(arrive2, c.tangent_at(far), ang_tol):
                        continue
                    outer_c = c.p1 if dist(c.p0, far) < dist(c.p1, far) else c.p0
                    out.append((k, j, outer_a, outer_c))
    return out


def find_candidates(g: Graph, tol: float, ang_tol: float) -> List[Cand]:
    segs = g.segs
    cands: List[Cand] = []
    taken: set = set()

    # 1) 호-(직선)-호
    for i, a in enumerate(segs):
        if a.kind != "ARC" or i in taken:
            continue
        for j, mid, Ja, Jb in _chain_partner(g, i, ang_tol):
            if j in taken or i in taken:
                continue
            b = segs[j]
            if abs(a.r - b.r) > tol:
                continue
            # 회전 방향은 '지나가는 방향' 기준 (Ja → a → … → b → Jb)
            turn_a = turn_sign(a, Ja)
            turn_b = -turn_sign(b, Jb)          # b 는 Jb 쪽으로 나가므로 반대에서 들어온다
            same_turn = turn_a == turn_b
            sw_a, sw_b = abs(a.sweep), abs(b.sweep)
            ua = a.tangent_at(Ja)          # 접합점에서 호가 뻗는 방향
            ub = b.tangent_at(Jb)
            lane_a = unit(mul(ua, -1.0))   # 모듈 다리(레일)가 뻗는 방향의 반대 = 로컬 +Y 후보
            chord = sub(Jb, Ja)
            if same_turn and abs(sw_a + sw_b - 180.0) <= ang_tol:
                # 아치: 두 접합점을 잇는 선은 레일과 직각, 아치는 레일 방향 쪽에 있다
                u = unit(mul(ua, 1.0))     # 접합점에서 호 쪽(= 아치 쪽) 이 로컬 +Y
                w = dist(Ja, Jb)
                if abs(dot(chord, u)) > tol:
                    continue
                left_first = cross(u, chord) > 0       # Ja 기준 Jb 가 왼쪽이면 Ja 가 로컬 x=w
                J0, J1 = (Jb, Ja) if left_first else (Ja, Jb)   # J0 = 로컬 x=0 (u 기준 왼쪽)
                d0, d1 = g.deg(J0), g.deg(J1)
                if d0 >= 3 and d1 >= 3:
                    name = "DOUBLE BRANCH"
                elif d0 >= 3:
                    name = "U BRANCH RIGHT"            # 관통 = 로컬 x=0
                elif d1 >= 3:
                    name = "U BRANCH LEFT"             # 관통 = 로컬 x=w
                else:
                    name = "U"
                cands.append(Cand(name, J0, lambda p: (0.0, p["l"]), math.degrees(math.atan2(u[1], u[0])),
                                  a.r, w, 45.0, tuple(x for x in (i, j, mid) if x is not None)))
                taken.update({i, j} | ({mid} if mid is not None else set()))
                break
            if (not same_turn) and abs(sw_a - sw_b) <= ang_tol:
                # 차선 이동: 진행 방향 = 접합점에서 호가 뻗는 방향. 아래 접합점(Ja) 이 로컬 높이 l.
                u_lane = ua
                low, high = Ja, Jb
                d_low, d_high = g.deg(low), g.deg(high)
                if d_low >= 3 and d_high >= 3:
                    kind = "N"
                elif d_low < 3 and d_high < 3:
                    kind = "S"
                else:
                    kind = "BY PASS"
                    if d_low >= 3:      # 끝나는 레일이 위쪽이면 반대 방향으로 놓는다
                        u_lane = mul(u_lane, -1.0)
                        low, high = high, low
                chord2 = sub(high, low)
                w = abs(cross(u_lane, chord2))
                left = cross(u_lane, chord2) > 0       # 이동이 진행 방향 왼쪽
                name = f"{kind} {'LEFT' if left else 'RIGHT'}"
                anchor = (lambda p: (p["w"], p["l"])) if left else (lambda p: (0.0, p["l"]))
                cands.append(Cand(name, low, anchor,
                                  math.degrees(math.atan2(u_lane[1], u_lane[0])),
                                  a.r, w, sw_a, tuple(x for x in (i, j, mid) if x is not None)))
                taken.update({i, j} | ({mid} if mid is not None else set()))
                break

    # 2) 호 하나 — BRANCH / CURVE
    for i, s in enumerate(segs):
        if s.kind != "ARC" or i in taken:
            continue
        if abs(abs(s.sweep) - 90.0) > ang_tol:
            continue
        for J, B in ((s.p0, s.p1), (s.p1, s.p0)):
            if g.deg(J) < 2:
                continue
            lane = [k for k in g.others(J, [i]) if segs[k].kind == "LINE"]
            if not lane:
                continue
            u = unit(sub(B, J))
            # 레일 방향: 접합점에 붙은 직선 중 호가 앞쪽이 되는 방향
            lane_dirs = [segs[k].tangent_at(J) for k in lane]
            best = max(lane_dirs, key=lambda d: dot(d, u))
            u_lane = mul(best, -1.0) if dot(best, u) < 0 else best
            # CURVE 는 호 뒤로 레일이 이어지지 않는다(차수 2), BRANCH 는 이어진다(차수 3)
            name_side = "LEFT" if cross(u_lane, sub(B, J)) > 0 else "RIGHT"
            base = "BRANCH" if g.deg(J) >= 3 else "CURVE"
            if base == "CURVE":
                # 코너: 레일이 접합점에서 꺾인다 → 들어오는 직선 방향이 로컬 +Y
                u_lane = mul(segs[lane[0]].tangent_at(J), -1.0)
                name_side = "LEFT" if cross(u_lane, sub(B, J)) > 0 else "RIGHT"
            name = f"{base} {name_side}"
            cands.append(Cand(name, J, lambda p: (0.0, p["l"]),
                              math.degrees(math.atan2(u_lane[1], u_lane[0])),
                              s.r, 900.0, 45.0, (i,)))
            taken.add(i)
            break
    return cands


# ── 모듈 형상 ↔ 도면 대조 ────────────────────────────────────────────────────
def place_pieces(name: str, at: Pt, anchor_fn, heading: float, r: float, l: float, w: float, a: float):
    idx = next(k for k, d in enumerate(mj.DEFS) if d[0] == name)
    r, l, w, a = mj.clamp(idx, r, l, w, a)
    pieces, _ = mj.build_local(idx, r, l, w, a)
    h = mj.cross_rise(r, w, a) if mj.DEFS[idx][2] else 0.0
    anc = anchor_fn({"r": r, "l": l, "w": w, "a": a, "h": h})
    rot = math.radians(heading - 90.0)
    cs, sn = math.cos(rot), math.sin(rot)

    def W(p: Pt) -> Pt:
        q = (p[0] * cs - p[1] * sn, p[0] * sn + p[1] * cs)
        return (at[0] + q[0] - (anc[0] * cs - anc[1] * sn), at[1] + q[1] - (anc[0] * sn + anc[1] * cs))

    out = []
    for p in pieces:
        if p.kind == "LINE":
            out.append(("LINE", W(p.a), W(p.b), None, 0.0))
        else:
            out.append(("ARC", W(p.a), W(p.b), W(p.c), p.r))
    return out, (idx, r, l, w, a)


def match_line(segs: List[Seg], p: Pt, q: Pt, tol: float):
    """모듈 직선 p→q 를 도면 직선(여러 개에 걸쳐도 됨)이 덮는지. 덮으면 [(도면직선, 구간)…]."""
    d = unit(sub(q, p))
    total = dist(p, q)
    if total < tol:
        return []
    n = (-d[1], d[0])
    parts, spans = [], []
    for i, s in enumerate(segs):
        if s.kind != "LINE":
            continue
        if abs(dot(sub(s.p0, p), n)) > tol or abs(dot(sub(s.p1, p), n)) > tol:
            continue
        t0, t1 = dot(sub(s.p0, p), d), dot(sub(s.p1, p), d)
        lo, hi = sorted((t0, t1))
        lo, hi = max(lo, 0.0), min(hi, total)
        if hi - lo <= tol:
            continue
        sd = s.dir()
        a0 = dot(sub(add(p, mul(d, lo)), s.p0), sd)
        a1 = dot(sub(add(p, mul(d, hi)), s.p0), sd)
        parts.append((i, min(a0, a1), max(a0, a1)))
        spans.append((lo, hi))
    if not spans:
        return None
    t = 0.0
    for lo, hi in sorted(spans):
        if lo > t + tol:
            return None
        t = max(t, hi)
    return parts if t >= total - tol else None


def match_arc(segs: List[Seg], p: Pt, q: Pt, c: Pt, r: float, tol: float):
    for i, s in enumerate(segs):
        if s.kind != "ARC" or s.used:
            continue
        if dist(s.c, c) > tol or abs(s.r - r) > tol:
            continue
        if (dist(s.p0, p) <= tol and dist(s.p1, q) <= tol) or (dist(s.p0, q) <= tol and dist(s.p1, p) <= tol):
            return i
    return None


def fit(cand: Cand, segs: List[Seg], tol: float, L_list=L_CANDIDATES):
    """L 을 줄여 가며 모듈 형상이 도면 안에 들어가는 첫 값을 찾는다."""
    for l in L_list:
        pieces, par = place_pieces(cand.name, cand.at, cand.anchor, cand.heading, cand.R, l, cand.W, cand.A)
        hits_line, hits_arc, ok = [], [], True
        for kind, p, q, c, r in pieces:
            if kind == "LINE":
                m = match_line(segs, p, q, tol)
                if m is None:
                    ok = False
                    break
                hits_line.extend(m)
            else:
                m = match_arc(segs, p, q, c, r, tol)
                if m is None:
                    ok = False
                    break
                hits_arc.append(m)
        if ok:
            return l, par, hits_line, hits_arc
    return None


# ── 본체 ────────────────────────────────────────────────────────────────────
def convert(in_path: str, out_path: str, layers, tol: float, l_max: float, log=print) -> Dict[str, Any]:
    doc = ezdxf.readfile(in_path)
    segs = read_segments(doc, layers)
    if not segs:
        raise SystemExit("선·호를 찾지 못했습니다 (레이어 지정을 확인하세요)")
    g = Graph(segs, tol)
    cands = find_candidates(g, tol, ang_tol=1.0)

    l_list = tuple(x for x in L_CANDIDATES if x <= l_max) or (l_max,)
    lay = Lay()
    placed, skipped = [], []
    for cd in cands:
        res = fit(cd, segs, tol, l_list)
        if res is None:
            skipped.append((cd, "형상이 도면과 맞지 않음(붙은 직선이 짧거나 치수가 다름)"))
            continue
        l, par, hits_line, hits_arc = res
        idx, r, l, w, a = par
        for i, lo, hi in hits_line:
            segs[i].covered.append((lo, hi))
        for i in hits_arc:
            segs[i].used = True
        anc = cd.anchor({"r": r, "l": l, "w": w, "a": a,
                         "h": mj.cross_rise(r, w, a) if mj.DEFS[idx][2] else 0.0})
        lay.place(cd.name, anc, cd.at, cd.heading, False, R=r, L=l, W=w, A=a)
        ref = list(lay.msp)[-1]                      # 모듈은 원래 선과 같은 레이어에 둔다
        ref.dxf.layer = segs[cd.segs[0]].layer
        placed.append((cd.name, r, l, w, a, cd.at))

    # 모듈이 덮지 않은 부분만 남긴다
    left_lines = left_arcs = 0
    for s in segs:
        if s.kind == "ARC":
            if not s.used:
                a0, a1 = ang(s.c, s.p0), ang(s.c, s.p1)
                if s.sweep < 0:
                    a0, a1 = a1, a0
                lay.msp.add_arc(s.c, s.r, a0, a1, dxfattribs={"layer": "RAIL"})
                left_arcs += 1
            continue
        d, L = s.dir(), s.length
        cov = sorted((max(0.0, lo), min(L, hi)) for lo, hi in s.covered)
        merged: List[List[float]] = []
        for lo, hi in cov:
            if merged and lo <= merged[-1][1] + tol:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        t = 0.0
        for lo, hi in merged + [[L, L]]:
            if lo - t > tol:
                lay.line(add(s.p0, mul(d, t)), add(s.p0, mul(d, lo)))
                left_lines += 1
            t = max(t, hi)

    lay.save(out_path)
    return {"modules": placed, "skipped": skipped, "left_lines": left_lines, "left_arcs": left_arcs,
            "segs": len(segs)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="도면의 선·호를 기본 모듈로 치환")
    ap.add_argument("input")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--layer", default="", help="레일 레이어(쉼표로 여러 개). 비우면 전부")
    ap.add_argument("--tol", type=float, default=8.0, help="형상 대조 허용 오차 mm")
    ap.add_argument("--L", type=float, default=200.0, help="모듈 다리 길이 최대값 mm")
    a = ap.parse_args(argv)
    out = a.output or (a.input.rsplit(".", 1)[0] + "_modules.dxf")
    layers = [s.strip() for s in a.layer.split(",") if s.strip()] or None
    res = convert(a.input, out, layers, a.tol, a.L)

    import collections
    cnt = collections.Counter(m[0] for m in res["modules"])
    print(f"입력 세그먼트 {res['segs']}개 → 모듈 {len(res['modules'])}개")
    for k, v in sorted(cnt.items()):
        print(f"   {k} {v}")
    print(f"남긴 직선 {res['left_lines']}개, 남긴 호 {res['left_arcs']}개")
    for cd, why in res["skipped"]:
        print(f"[주의] {cd.name} 자리 건너뜀 @({cd.at[0]:.0f},{cd.at[1]:.0f}) - {why}")
    print(f"저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
