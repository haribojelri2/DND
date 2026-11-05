# -*- coding: utf-8 -*-
"""모듈 도면 → MODULE FORMAT MAP (LayoutEditor 형식, NODE_모듈정보_기재가이드.md / MODULE FORMAT 제안서.pptx).

모듈이 있는 도면은 MAP 하나만 만든다(원본·이격 이원화 없음).

  NODE        이격 기준. 모듈 NODE = 슬롯 CAD 점에서 바깥으로 M1(관통 위쪽 슬롯은 M2) 밀어낸 점.
              뒤에 ModuleID / SlotID 필드가 붙는다(모듈과 무관한 NODE 는 공란).
  LINK        모듈 안: 슬롯 NODE 끼리(직선 S, 90° 곡선 L/R, 아치 U, S자 N) - 길이 = 경로 + 양 끝 마진.
              모듈 사이: 마주보는 슬롯 NODE 를 직선 S 로(길이 = 간격 g − 양쪽 마진).
              마진이 겹치면(g < 두 마진 합) 그 두 슬롯 NODE 는 만들지 않고 두 곡선을 U/N 링크 하나로 잇는다.
  MODULE      ID/Type/Angle/X/Y/Slot1/Slot2/… - X,Y = 슬롯① CAD 좌표, Angle = 0/90/180/270(시계 방향,
              가이드 예시 3 기준), SlotN = 직선으로 이어진 다른 모듈 슬롯 "ID-번호".
  MODULEPARAM R/L/W1/W2/A/M1/M2 (파일당 1개)

모듈 형상은 제안서 기준이다: 분기류(BL·BR·DB·UBL·UBR)의 관통 위쪽 팔 = L + 180(through_extra_mm).
플러그인 블록도 같은 형상(ModuleGeom.ThroughExtra)이다.
U·DB·UBL·UBR 은 W 를 쓰지 않는다 - 아치 = 반지름 R 의 반원(폭 2R). W1/W2 는 특수 분기(N·BY PASS·S) 폭만.
예전 플러그인이 폭 W 로 그린 넓은 아치 블록은 그 형상대로 읽되 규격 밖이라고 경고한다.
"""
from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import module_judge as mj

Pt = Tuple[float, float]

DEFAULTS = {
    "enabled": True,
    "through_extra_mm": 180.0,
    "slot_tol_mm": 20.0,
    "geom_tol_mm": "auto",
}

# 플러그인 모듈 이름 → 제안서 약어 후보(좌우는 형상으로 다시 가린다)
FAMILY = {
    "CURVE LEFT": ["C"], "CURVE RIGHT": ["C"],
    "BRANCH LEFT": ["BL", "BR"], "BRANCH RIGHT": ["BL", "BR"],
    "U": ["U"], "DOUBLE BRANCH": ["DB"],
    "U BRANCH LEFT": ["UBL", "UBR"], "U BRANCH RIGHT": ["UBL", "UBR"],
    "N LEFT": ["NL", "NR"], "N RIGHT": ["NL", "NR"],
    "BY PASS LEFT": ["BPL", "BPR"], "BY PASS RIGHT": ["BPL", "BPR"],
    "S LEFT": ["SL", "SR"], "S RIGHT": ["SL", "SR"],
    "Y": ["Y"],
}
USES_W = {"NL", "NR", "BPL", "BPR", "SL", "SR"}      # W 를 쓰는 모듈 = 특수 분기(N·BY PASS·S)만
ARCH_TYPES = {"U", "DB", "UBL", "UBR"}                  # U 계열: W 없음, 아치 = 반지름 R 의 반원(폭 2R)
# 마진이 겹칠 때 U/N 한 링크로 합칠 수 있는 슬롯(90° 곡선 끝) - 가이드 5장
MERGEABLE = {"C": {1, 2}, "Y": {2, 3}, "BL": {2}, "BR": {2}}


# 플러그인이 도면(NOD)에 저장하는 파라미터 XRecord - Real(40) 7개 R/L/W1/W2/A/M1/M2
PARAM_KEY = "RAILPLUGIN_MODULEPARAM"

# 마지막 build 에서 찾은 "합칠 수 없는 마진 겹침" 위치 — CAD 플러그인 [마진 검사] 가 도면에 표시한다
LAST_ISSUES: List[dict] = []


def read_drawing_param(doc) -> Optional[Tuple[float, ...]]:
    """도면에 저장된 모듈 파라미터 (R, L, W1, W2, A, M1, M2). 없거나 값이 모자라면 None."""
    try:
        xr = doc.rootdict.get(PARAM_KEY)
    except Exception:
        return None
    if xr is None or xr.dxftype() != "XRECORD":
        return None
    v = [float(t.value) for t in xr.tags if t.code == 40]
    return tuple(v[:7]) if len(v) >= 7 else None


def enabled(cfg: Optional[dict]) -> bool:
    v = cfg_of(cfg).get("enabled", True)
    return str(v).strip().lower() not in ("false", "0", "off", "no", "0.0")


def cfg_of(cfg: Optional[dict]) -> dict:
    out = dict(DEFAULTS)
    if cfg and isinstance(cfg.get("module_map"), dict):
        out.update(cfg["module_map"])
    return out


# ── 기하 ────────────────────────────────────────────────────────────────
def add(a, b): return (a[0] + b[0], a[1] + b[1])
def sub(a, b): return (a[0] - b[0], a[1] - b[1])
def mul(a, k): return (a[0] * k, a[1] * k)
def dot(a, b): return a[0] * b[0] + a[1] * b[1]
def cross(a, b): return a[0] * b[1] - a[1] * b[0]
def dist(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(a):
    n = math.hypot(a[0], a[1])
    return (a[0] / n, a[1] / n) if n > 1e-12 else (0.0, 0.0)


def rot_cw(p: Pt, deg: float) -> Pt:
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    return (p[0] * c + p[1] * s, -p[0] * s + p[1] * c)


# ── 제안서 템플릿 (Angle 0, 슬롯① = 원점) ────────────────────────────────
@dataclass
class TSlot:
    pos: Pt
    out: Pt
    m2: bool = False           # 관통 위쪽 슬롯(M2)


@dataclass
class TPath:
    a: int                     # 슬롯 번호(1부터)
    b: int
    kind: str                  # line / curve / arch / cross
    length: float
    probe: Pt                  # 이 경로만 지나는 점
    tan: Pt                    # probe 에서 a→b 진행 방향


def _mirror(slots, paths):
    ms = [TSlot((-s.pos[0], s.pos[1]), (-s.out[0], s.out[1]), s.m2) for s in slots]
    mp = [TPath(p.a, p.b, p.kind, p.length, (-p.probe[0], p.probe[1]), (-p.tan[0], p.tan[1])) for p in paths]
    return ms, mp


def template(t: str, R: float, L: float, W: float, A: float, E: float):
    c45, s45 = math.cos(math.pi / 4), math.sin(math.pi / 4)
    curve_len = 2 * L + math.pi * R / 2
    corner = (-(R + L), L + R)
    left_curve = TPath(1, 2, "curve", curve_len, (-R + R * c45, L + R * s45), (-s45, c45))
    top = R + 2 * L + E
    if t in ("C", "BL", "BR", "Y"):
        slots = [TSlot((0.0, 0.0), (0.0, -1.0)), TSlot(corner, (-1.0, 0.0))]
        paths = [left_curve]
        if t == "Y":
            slots.append(TSlot((R + L, L + R), (1.0, 0.0)))
            paths.append(TPath(1, 3, "curve", curve_len, (R - R * c45, L + R * s45), (s45, c45)))
            return slots, paths
        if t in ("BL", "BR"):
            slots.append(TSlot((0.0, top), (0.0, 1.0), True))
            paths.append(TPath(1, 3, "line", top, (0.0, L + R), (0.0, 1.0)))
            if t == "BR":
                return _mirror(slots, paths)
        return slots, paths
    arch_len = 2 * L + math.pi * R + max(W - 2 * R, 0.0)
    arch = TPath(1, 2, "arch", arch_len, (-W / 2, L + R), (-1.0, 0.0))
    if t == "U":
        return [TSlot((0.0, 0.0), (0.0, -1.0)), TSlot((-W, 0.0), (0.0, -1.0))], [arch]
    if t == "DB":
        slots = [TSlot((0.0, 0.0), (0.0, -1.0)), TSlot((-W, 0.0), (0.0, -1.0)),
                 TSlot((0.0, top), (0.0, 1.0), True), TSlot((-W, top), (0.0, 1.0), True)]
        paths = [arch, TPath(1, 3, "line", top, (0.0, L + R), (0.0, 1.0)),
                 TPath(2, 4, "line", top, (-W, L + R), (0.0, 1.0))]
        return slots, paths
    if t in ("UBL", "UBR"):
        slots = [TSlot((0.0, 0.0), (0.0, -1.0)), TSlot((-W, 0.0), (0.0, -1.0)),
                 TSlot((0.0, top), (0.0, 1.0), True)]
        paths = [arch, TPath(1, 3, "line", top, (0.0, L + R), (0.0, 1.0))]
        return (slots, paths) if t == "UBL" else _mirror(slots, paths)
    # S자 계열(NL/NR/BPL/BPR/SL/SR) - 참고 슬라이드: D = [W − 2R(1 − cosA)]/sinA
    ar = math.radians(A)
    D = (W - 2 * R * (1 - math.cos(ar))) / math.sin(ar)
    h = 2 * R * math.sin(ar) + D * math.cos(ar)
    H = 2 * L + h
    p1 = (-R + R * math.cos(ar), L + R * math.sin(ar))
    dvec = (-math.sin(ar), math.cos(ar))
    # probe = 대각선의 1/4 지점. 가운데(1/2)는 N 의 두 대각선(NL·NR 거울상)이 만나는 X 교차점이라 둘을 못 가린다
    #  (끝점 4개도 직사각형이라 같음) → N RIGHT 블록이 NL 로 판정돼 N 링크가 반대 차선끼리 이어졌다.
    cross_p = TPath(1, 2, "cross", 2 * L + 2 * R * ar + D, add(p1, mul(dvec, max(D, 0.0) / 4)), dvec)
    if t in ("NL", "NR"):
        slots = [TSlot((0.0, 0.0), (0.0, -1.0)), TSlot((-W, H), (0.0, 1.0)),
                 TSlot((0.0, H), (0.0, 1.0)), TSlot((-W, 0.0), (0.0, -1.0))]
        paths = [cross_p, TPath(1, 3, "line", H, (0.0, L + h / 2), (0.0, 1.0)),
                 TPath(4, 2, "line", H, (-W, L + h / 2), (0.0, 1.0))]
    elif t in ("BPL", "BPR"):
        slots = [TSlot((0.0, 0.0), (0.0, -1.0)), TSlot((-W, H), (0.0, 1.0)), TSlot((0.0, H), (0.0, 1.0))]
        paths = [cross_p, TPath(1, 3, "line", H, (0.0, L + h / 2), (0.0, 1.0))]
    else:  # SL/SR
        slots = [TSlot((0.0, 0.0), (0.0, -1.0)), TSlot((-W, H), (0.0, 1.0))]
        paths = [cross_p]
    return (slots, paths) if t.endswith("L") else _mirror(slots, paths)


# ── 도면 모듈 → 제안서 모듈 ───────────────────────────────────────────────
@dataclass
class SMod:
    no: int
    inst: Any
    type: str
    angle: int
    ref: Pt
    slots: List[TSlot]                 # 월드(제안서 위치)
    paths: List[TPath]                 # 월드 probe/tan
    plugin_ends: List[Pt]              # 슬롯별 플러그인 블록 끝점(형상 제거용)
    id: str = ""
    links: List[str] = field(default_factory=list)   # 슬롯별 연결 "ID-번호"


def _free_ends(inst, tol) -> List[Tuple[Pt, Pt]]:
    """플러그인 블록 조각의 열린 끝점과 그 끝의 바깥 방향."""
    #  열린 끝 = 그 점에서 바깥쪽으로 이어지는 조각이 없는 끝. 다른 조각이 닿아 있어도 모두 모듈 안쪽으로 가면
    #  열린 끝이다 — L = 0 이면 BRANCH 관통선 시작점(슬롯①)에서 곡선도 바로 시작해, '닿으면 내부'로 보면 슬롯이 사라진다.
    #  길이 0 조각(L = 0 의 다리)은 무시한다.
    pcs = [q for q in inst.pieces if q.kind != "LINE" or dist(q.a, q.b) > tol]

    def outward(p, pt, other):
        """조각 p 의 끝 pt 에서 조각 몸통 반대쪽(바깥) 방향."""
        if p.kind == "LINE":
            return unit(sub(pt, other))
        rad = unit(sub(pt, p.c))
        tan = (-rad[1], rad[0])
        return tan if dot(tan, sub(pt, other)) > 0 else mul(tan, -1)

    ends = []
    for i, p in enumerate(pcs):
        for pt, other in ((p.a, p.b), (p.b, p.a)):
            out = outward(p, pt, other)
            cont = False                     # pt 에서 바깥쪽으로 이어지는 다른 조각이 있나
            for j, q in enumerate(pcs):
                if j == i:
                    continue
                if q.kind == "LINE":
                    d = unit(sub(q.b, q.a))
                    t = dot(sub(pt, q.a), d)
                    if abs(cross(d, sub(pt, q.a))) > tol or not (-tol <= t <= dist(q.a, q.b) + tol):
                        continue
                    if tol < t < dist(q.a, q.b) - tol:          # 직선 중간을 지나감 → 양쪽으로 이어짐
                        cont = True
                    else:
                        far = q.b if t <= tol else q.a
                        cont = dot(unit(sub(far, pt)), out) > 0.5
                elif dist(pt, q.a) <= tol or dist(pt, q.b) <= tol:
                    qo = outward(q, *((q.a, q.b) if dist(pt, q.a) <= tol else (q.b, q.a)))
                    cont = dot(mul(qo, -1.0), out) > 0.5            # q 몸통이 바깥쪽으로 뻗음
                if cont:
                    break
            if cont:
                continue
            if any(dist(pt, e) <= tol and dot(o, out) > 0.9 for e, o in ends):
                continue                                             # 같은 슬롯(관통선·곡선이 함께 시작)
            ends.append((pt, out))
    return ends


def _on_pieces(inst, p: Pt, tol: float) -> bool:
    """점 p 가 플러그인 블록 조각(직선·호) 위에 있나."""
    for q in inst.pieces:
        if q.kind == "LINE":
            d = sub(q.b, q.a)
            n = dot(d, d)
            t = 0.0 if n == 0 else max(0.0, min(1.0, dot(sub(p, q.a), d) / n))
            if dist(p, add(q.a, mul(d, t))) <= tol:
                return True
        else:
            if abs(dist(p, q.c) - q.r) > tol:
                continue
            ang = lambda x: math.atan2(x[1] - q.c[1], x[0] - q.c[0])
            a0, am, a1, ap = ang(q.a), ang(q.m), ang(q.b), ang(p)
            span = (a1 - a0) % (2 * math.pi)
            if (am - a0) % (2 * math.pi) > span:          # a→b 가 시계 방향
                a0, span = a1, (a0 - a1) % (2 * math.pi)
            if (ap - a0) % (2 * math.pi) <= span + tol / max(q.r, 1.0):
                return True
    return False


def match_module(inst, mc: dict, log) -> Optional[SMod]:
    tol = float(mc["slot_tol_mm"])
    E = float(mc["through_extra_mm"])
    ends = _free_ends(inst, 0.5)
    R, L, W, A = inst.R, inst.L, inst.W, inst.A
    for t, Em in ((t, E) for t in FAMILY.get(inst.name, [])):   # 플러그인 블록 = 제안서 형상(관통 위 팔 L+180)
        tslots0, _ = template(t, R, L, W, A, Em)
        if len(tslots0) != len(ends):
            continue
        for ang in (0, 90, 180, 270):
            for ref, _ in ends:
                used, order = set(), []
                for s in tslots0:
                    wp = add(ref, rot_cw(s.pos, ang))
                    wo = rot_cw(s.out, ang)
                    # 위치 + 바깥 방향까지 맞아야 한다(곡선은 두 끝 위치만으론 ①② 를 못 가린다)
                    k = next((i for i, (q, o) in enumerate(ends)
                              if i not in used and dist(q, wp) <= tol and dot(o, wo) > 0.9), None)
                    if k is None:
                        break
                    used.add(k)
                    order.append(k)
                if len(order) != len(tslots0):
                    continue
                # 끝점만으론 대칭 형상(DB 등)의 위·아래를 못 가린다 → 경로 probe 가 블록 형상 위에 있어야 함
                _, tp0 = template(t, R, L, W, A, Em)
                if not all(_on_pieces(inst, add(ref, rot_cw(p.probe, ang)), tol) for p in tp0):
                    continue
                tslots, tpaths = template(t, R, L, W, A, E)
                slots = [TSlot(add(ref, rot_cw(s.pos, ang)), rot_cw(s.out, ang), s.m2) for s in tslots]
                paths = [TPath(p.a, p.b, p.kind, p.length, add(ref, rot_cw(p.probe, ang)), rot_cw(p.tan, ang))
                         for p in tpaths]
                return SMod(inst.no, inst, t, ang, ref, slots, paths, [ends[k][0] for k in order])
    log(f"[경고] 모듈 {inst.name} @({inst.insert[0]:.0f},{inst.insert[1]:.0f}) 을 제안서 형식에 맞추지 못함 - 일반 형상으로 처리")
    return None


# ── 엣지 도우미 ─────────────────────────────────────────────────────────
def _is_arc(e):
    return e.edge_type == "ARC"


def _center(e):
    return (e._data.cx, e._data.cy)


def _arc_ccw(e) -> bool:
    c = _center(e)
    return cross(sub(e.start, c), sub(e.end, c)) > 0


def _edge_tangent_at(e, p) -> Pt:
    if not _is_arc(e):
        return unit(sub(e.end, e.start))
    rad = unit(sub(p, _center(e)))
    return (-rad[1], rad[0]) if _arc_ccw(e) else (rad[1], -rad[0])


def _edge_dist(e, p) -> float:
    if not _is_arc(e):
        d = sub(e.end, e.start)
        n = dot(d, d)
        t = 0.0 if n == 0 else max(0.0, min(1.0, dot(sub(p, e.start), d) / n))
        return dist(p, add(e.start, mul(d, t)))
    c = _center(e)
    r = e._data.r
    a0 = math.atan2(e.start[1] - c[1], e.start[0] - c[0])
    a1 = math.atan2(e.end[1] - c[1], e.end[0] - c[0])
    ap = math.atan2(p[1] - c[1], p[0] - c[0])
    if not _arc_ccw(e):
        a0, a1 = a1, a0
    span = (a1 - a0) % (2 * math.pi)
    if (ap - a0) % (2 * math.pi) <= span + 1e-9:
        return abs(dist(p, c) - r)
    return min(dist(p, e.start), dist(p, e.end))


def _arc_len(e) -> float:
    c = _center(e)
    r = e._data.r
    a = math.atan2(cross(sub(e.start, c), sub(e.end, c)), dot(sub(e.start, c), sub(e.end, c)))
    return abs(a) * r


# ── 본체 ────────────────────────────────────────────────────────────────
@dataclass
class Result:
    nodes: list
    links: list
    modules: List[SMod]
    param: Tuple[float, ...]
    warnings: List[str]


def build(modules, unified_edges, cfg: dict, margins: Tuple[float, float], log=print) -> Result:
    LAST_ISSUES.clear()
    """margins = (M1, M2): CAD 도면에 저장된 값만 쓴다(CAD 모듈 형상에는 반영 안 하고 MAP 에만 반영)."""
    from map_exporter import MapNode, MapLink

    mc = cfg_of(cfg)
    tol = float(mc["slot_tol_mm"])
    M1, M2 = float(margins[0]), float(margins[1])
    warns: List[str] = []

    def warn(s):
        warns.append(s)
        log(s)

    smods = [m for m in (match_module(i, mc, warn) for i in modules) if m]
    for k, m in enumerate(smods, 1):
        m.id = f"{k:06d}"
        m.links = [""] * len(m.slots)

    # MODULEPARAM (파일당 1개)
    def common(vals):
        # 묶기는 소수 1자리(맵 왕복 도면의 미세 오차 900.016 등은 같은 값으로), 기록 값은 그 묶음에서 가장 많은
        # 원래 값(505.555556 같은 도면 값을 505.6 으로 바꾸면 역변환 형상이 mm 단위로 어긋난다)
        groups = collections.defaultdict(list)
        for v in vals:
            groups[round(v, 1)].append(round(v, 6))
        c = collections.Counter({k: len(g) for k, g in groups.items()})
        return [(collections.Counter(groups[k]).most_common(1)[0][0], n) for k, n in c.most_common()]

    rc, lc = common(m.inst.R for m in smods), common(m.inst.L for m in smods)
    ac = common(m.inst.A for m in smods if m.type in ("NL", "NR", "BPL", "BPR", "SL", "SR"))
    wc = common(m.inst.W for m in smods if m.type in USES_W)
    R0 = rc[0][0] if rc else 0.0
    L0 = lc[0][0] if lc else 0.0
    A0 = ac[0][0] if ac else 45.0
    ws = sorted(w for w, _ in wc[:2])
    W1 = ws[0] if ws else 0.0
    W2 = ws[1] if len(ws) > 1 else W1
    if len(rc) > 1 or len(lc) > 1:
        warn(f"[경고] 모듈마다 R·L 이 다름(R {[v for v, _ in rc]}, L {[v for v, _ in lc]}) - MODULEPARAM 은 {R0}/{L0} 로 기록")
    if len(ac) > 1:
        warn(f"[경고] 모듈마다 A 가 다름 {[v for v, _ in ac]} - MODULEPARAM A={A0}")
    _wide = [m for m in smods if m.type in ARCH_TYPES and abs(m.inst.W - 2 * m.inst.R) > 1.0]
    if _wide:
        warn(f"[경고] U 계열 모듈 {len(_wide)}개가 반원(폭 2R)이 아님 - 폭 "
             f"{sorted({round(m.inst.W) for m in _wide})} (규격: U·DOUBLE BRANCH·U BRANCH 는 W 없이 반원). "
             f"도면의 형상대로 변환했지만 LayoutEditor·역변환에서는 반원으로 재현됨")
    if len(wc) > 2:
        warn(f"[경고] 폭 종류가 {len(wc)}개 {[v for v, _ in wc]} - W1/W2 는 가장 많은 두 폭 {W1}/{W2}, 나머지 폭 모듈은 LayoutEditor 에서 재현 안 됨")

    def margin(s: TSlot) -> float:
        return M2 if s.m2 else M1

    # 1) 도면 엣지에서 모듈이 차지한 부분 빼기
    cover_lines, cover_arcs = [], []
    for m in smods:
        for p in m.inst.pieces:
            (cover_lines if p.kind == "LINE" else cover_arcs).append(p)

    # 속도: 엣지마다 모든 피스를 보지 않고 근처 피스만 본다(호 = 중심 격자, 직선 = 경계상자 격자). 원래 순서 유지 → 결과 동일
    _gc = max(tol, 1.0) * 4.0
    _gk = lambda p: (math.floor(p[0] / _gc), math.floor(p[1] / _gc))
    _arc_cells = collections.defaultdict(list)
    for k, q in enumerate(cover_arcs):
        _arc_cells[_gk(q.c)].append(k)
    _LC = 2000.0
    _line_cells = collections.defaultdict(list)
    for k, q in enumerate(cover_lines):
        x0, x1 = sorted((q.a[0], q.b[0]))
        y0, y1 = sorted((q.a[1], q.b[1]))
        for gx in range(math.floor((x0 - tol) / _LC), math.floor((x1 + tol) / _LC) + 1):
            for gy in range(math.floor((y0 - tol) / _LC), math.floor((y1 + tol) / _LC) + 1):
                _line_cells[(gx, gy)].append(k)

    def _arcs_near(c):
        gx, gy = _gk(c)
        ks = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                ks.update(_arc_cells.get((gx + dx, gy + dy), ()))
        return [cover_arcs[k] for k in sorted(ks)]

    def _lines_near(a, b):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        ks = set()
        for gx in range(math.floor((x0 - tol) / _LC), math.floor((x1 + tol) / _LC) + 1):
            for gy in range(math.floor((y0 - tol) / _LC), math.floor((y1 + tol) / _LC) + 1):
                ks.update(_line_cells.get((gx, gy), ()))
        return [cover_lines[k] for k in sorted(ks)]

    plain = []   # (kind, a, b, edge)  a→b = 진행 방향
    for e in unified_edges:
        if _is_arc(e):
            c, r = _center(e), e._data.r
            if any(dist(c, q.c) <= tol and abs(r - q.r) <= tol and
                   min(dist(e.start, q.a), dist(e.start, q.b)) <= tol and
                   min(dist(e.end, q.a), dist(e.end, q.b)) <= tol for q in _arcs_near(c)):
                continue
            plain.append(("ARC", e.start, e.end, e))
            continue
        d = unit(sub(e.end, e.start))
        Ltot = dist(e.start, e.end)
        cov = []
        for q in _lines_near(e.start, e.end):
            qd = sub(q.b, q.a)
            if abs(cross(d, sub(q.a, e.start))) > tol or abs(cross(d, sub(q.b, e.start))) > tol:
                continue
            t0, t1 = sorted((dot(sub(q.a, e.start), d), dot(sub(q.b, e.start), d)))
            t0, t1 = max(t0, 0.0), min(t1, Ltot)
            if t1 - t0 > tol:
                cov.append([t0, t1])
        cov.sort()
        t = 0.0
        for lo, hi in cov + [[Ltot, Ltot]]:
            if lo - t > tol:
                plain.append(("LINE", add(e.start, mul(d, t)), add(e.start, mul(d, lo)), e))
            t = max(t, hi)

    # 2) 슬롯 끝점 색인
    slot_at = []   # (pos, m, idx)
    for m in smods:
        for i, s in enumerate(m.slots):
            slot_at.append((s.pos, m, i))

    _sc = max(tol, 1.0)
    _slot_cells = collections.defaultdict(list)
    for k, (q, _m, _i) in enumerate(slot_at):
        _slot_cells[(math.floor(q[0] / _sc), math.floor(q[1] / _sc))].append(k)

    def slot_near(p):
        gx, gy = math.floor(p[0] / _sc), math.floor(p[1] / _sc)
        ks = sorted(k for dx in (-1, 0, 1) for dy in (-1, 0, 1) for k in _slot_cells.get((gx + dx, gy + dy), ()))
        return next(((slot_at[k][1], slot_at[k][2]) for k in ks if dist(slot_at[k][0], p) <= tol), None)

    # 3) 모듈 사이 직선 연결: 슬롯에서 시작하는 직선 사슬 → 반대편 슬롯
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))
    _cells = collections.defaultdict(list)
    for k, pc in enumerate(plain):
        _cells[key(pc[1])].append((k, pc[1]))
        _cells[key(pc[2])].append((k, pc[2]))

    class _Near:
        """점 p 에서 tol 안에 끝점이 있는 조각들. 격자 칸 경계(예: 좌표/tol = x.5)에 걸린 점이 옆 칸으로
        빠지지 않도록 주변 칸까지 거리로 찾는다 (칸 하나만 보면 같은 점의 조각을 놓쳐 슬롯 연결이 빠진다)."""
        def __getitem__(self, kp):
            p = kp
            cx, cy = key(p)
            out = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for k, q in _cells.get((cx + dx, cy + dy), ()):
                        if dist(q, p) <= tol:
                            out.append(k)
            return out

    at_pt = _Near()

    used_piece = set()
    conns = []   # (mA, iA, mB, iB, g, pieces[], forward(a→b 진행))
    for m in smods:
        for i, s in enumerate(m.slots):
            ks = [k for k in at_pt[s.pos] if plain[k][0] == "LINE" and k not in used_piece]
            for k in ks:
                chain, cur, g = [k], s.pos, 0.0
                ok = True
                while True:
                    kind, a, b, e = plain[chain[-1]]
                    nxt = b if dist(a, cur) <= tol else a
                    if abs(cross(unit(sub(nxt, cur)), s.out)) > 1e-3:
                        ok = False
                        break
                    g += dist(cur, nxt)
                    cur = nxt
                    hit = slot_near(cur)
                    if hit and hit[0] is not m:
                        break
                    cont = [q for q in at_pt[cur] if q not in chain and plain[q][0] == "LINE"]
                    if len(at_pt[cur]) != 2 or len(cont) != 1:
                        ok = False
                        break
                    chain.append(cont[0])
                if not ok:
                    continue
                mB, iB = hit
                if any(c[0] is mB and c[1] == iB and c[2] is m and c[3] == i for c in conns):
                    continue
                kind, a, b, e = plain[chain[0]]
                forward = dist(a, s.pos) <= tol       # 슬롯 A 에서 나가는 방향으로 흐르나
                conns.append((m, i, mB, iB, g, chain, forward))
                used_piece.update(chain)
    # 사이 직선 없이 마주 보는 슬롯: 맞닿음(g = 0) 또는 제안서 형상(관통 +180)으로 서로 지나침(g < 0)
    reach = 2.0 * max(M1, M2) + float(mc["through_extra_mm"]) * 2
    # 속도: 짝이 되려면 두 슬롯 거리가 reach + tol 안 → 그 크기 격자에서 이웃 칸만(번호순 유지 → 결과 동일)
    _fc = reach + 2.0 * tol + 1.0
    _face_cells = collections.defaultdict(list)
    for k, (q, _m, _i) in enumerate(slot_at):
        _face_cells[(math.floor(q[0] / _fc), math.floor(q[1] / _fc))].append(k)

    def _face_cands(x):
        q = slot_at[x][0]
        gx, gy = math.floor(q[0] / _fc), math.floor(q[1] / _fc)
        return sorted(k for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                      for k in _face_cells.get((gx + dx, gy + dy), ()) if k > x)

    for x in range(len(slot_at)):
        for y in _face_cands(x):
            pa, ma, ia = slot_at[x]
            pb, mb, ib = slot_at[y]
            if ma is mb:
                continue
            oa = ma.slots[ia].out
            if dot(oa, mb.slots[ib].out) > -0.9:
                continue
            g = dot(sub(pb, pa), oa)                       # 슬롯 A 바깥쪽으로 B 까지의 거리(겹치면 음수)
            if abs(cross(oa, sub(pb, pa))) > tol or not (-reach < g <= tol):
                continue
            if any((c[0] is ma and c[1] == ia) or (c[2] is ma and c[3] == ia) or
                   (c[0] is mb and c[1] == ib) or (c[2] is mb and c[3] == ib) for c in conns):
                continue
            conns.append((ma, ia, mb, ib, g, [], None))

    for mA, iA, mB, iB, g, chain, fw in conns:
        mA.links[iA] = f"{mB.id}-{iB + 1}"
        mB.links[iB] = f"{mA.id}-{iA + 1}"

    # 4) 경로 진행 방향(모듈 안) - probe 위치의 도면 엣지 방향
    # 속도: probe 에서 50 mm 안에 들 수 있는 엣지(경계상자 + 50 이 probe 를 품는 것)만 본다. 원래 순서 유지 → 결과 동일
    _ebox = [(min(e.start[0], e.end[0]), min(e.start[1], e.end[1]), max(e.start[0], e.end[0]), max(e.start[1], e.end[1]))
             if not _is_arc(e) else
             (_center(e)[0] - e._data.r, _center(e)[1] - e._data.r, _center(e)[0] + e._data.r, _center(e)[1] + e._data.r)
             for e in unified_edges]

    def path_forward(p: TPath) -> Optional[bool]:
        x, y = p.probe
        near = [e for e, b in zip(unified_edges, _ebox)
                if b[0] - 51.0 <= x <= b[2] + 51.0 and b[1] - 51.0 <= y <= b[3] + 51.0]
        best = min(near, key=lambda e: _edge_dist(e, p.probe), default=None)
        if best is None or _edge_dist(best, p.probe) > 50.0:
            return None
        return dot(_edge_tangent_at(best, p.probe), p.tan) > 0

    # 5) 겹침(마진 합보다 가까운 곡선 끝) → 슬롯 NODE 생략 + 두 곡선 한 링크
    suppressed = set()     # (module id, slot idx)
    merged = []            # (mA, pathA, mB, pathB, g)
    plain_conn = []
    same_point = {}        # 마진이 꼭 맞아 두 슬롯 NODE 가 한 점에 놓이는 쌍: (모듈 id, 슬롯) ↔ (모듈 id, 슬롯)
    EQ_TOL = 1.0
    for c in conns:
        mA, iA, mB, iB, g, chain, fw = c
        need = margin(mA.slots[iA]) + margin(mB.slots[iB])
        if abs(g - need) <= EQ_TOL:
            # 간격 = 마진 합: 두 NODE 가 같은 점 → NODE 하나로 쓰고 사이 링크(길이 0)는 만들지 않는다
            same_point[(mA.id, iA)] = (mB.id, iB)
            same_point[(mB.id, iB)] = (mA.id, iA)
            continue
        if g >= need - 1e-6:
            plain_conn.append(c)
            continue
        okA = (iA + 1) in MERGEABLE.get(mA.type, set())
        okB = (iB + 1) in MERGEABLE.get(mB.type, set())
        if not (okA and okB):
            p = mA.slots[iA].pos
            q = mB.slots[iB].pos
            LAST_ISSUES.append({"x": (p[0] + q[0]) / 2, "y": (p[1] + q[1]) / 2, "gap": round(g), "need": round(need),
                                "ha": str(getattr(mA.inst, "handle", "") or ""), "hb": str(getattr(mB.inst, "handle", "") or ""),
                                "text": f"마진 겹침 {mA.type}{iA + 1}-{mB.type}{iB + 1} 간격 {g:.0f} < 마진 합 {need:.0f}"})
            warn(f"[확인 필요] 마진 겹침 ({p[0]:.0f}, {p[1]:.0f}): 모듈 {mA.id}({mA.type}) 슬롯{iA + 1} ↔ "
                 f"모듈 {mB.id}({mB.type}) 슬롯{iB + 1} 간격 {g:.0f} mm 가 마진 합 {need:.0f} mm 보다 짧음 - "
                 f"NODE 하나로 합침. 마진(M1·M2) 설정 또는 도면의 두 모듈 간격을 확인하세요")
            # 사이 직선 길이가 0 이하가 되므로 길이 0 링크를 만들지 않고 두 슬롯이 NODE 하나를 함께 쓴다
            same_point[(mA.id, iA)] = (mB.id, iB)
            same_point[(mB.id, iB)] = (mA.id, iA)
            continue
        pA = next(p for p in mA.paths if iA + 1 in (p.a, p.b))
        pB = next(p for p in mB.paths if iB + 1 in (p.a, p.b))
        suppressed.update({(mA.id, iA), (mB.id, iB)})
        merged.append((mA, iA, pA, mB, iB, pB, g))

    # 6) NODE
    nodes: List[MapNode] = []
    nid = {}

    c1 = _param_str     # 좌표도 반올림 안 함(1자리로 자르면 MAP→CAD 직선이 0.1mm 기울어진다), 딱 떨어지면 '850.0'

    def new_node(p, mod_id="", slot=""):
        n = MapNode(id=f"{len(nodes) + 1:06d}", type="G", reality="R", x=c1(p[0]), y=c1(p[1]),
                    relative_distance="0", layer_id="0", param_yield_enabled="")
        n.module_id, n.slot_id = mod_id, slot
        n.v2 = True
        nodes.append(n)
        return n.id

    for m in smods:
        for i, s in enumerate(m.slots):
            if (m.id, i) in suppressed:
                continue
            other = same_point.get((m.id, i))
            if other is not None and other in nid:
                nid[(m.id, i)] = nid[other]          # 같은 점의 NODE 를 함께 쓴다
                continue
            nid[(m.id, i)] = new_node(add(s.pos, mul(s.out, margin(s))), m.id, str(i + 1))

    links: List[MapLink] = []

    away = []      # 링크별 (시작 NODE 에서 링크가 뻗는 방향, 끝 NODE 에서 링크가 뻗는 방향) — 방향 정리용

    def new_link(t, a, b, length, va=None, vb=None):
        links.append(MapLink(id=f"{len(links) + 1:06d}", type=t, start_node_id=a, end_node_id=b,
                             length=int(round(length))))
        away.append((va, vb))

    # 모듈 안 링크
    merged_paths = {(id(x[0]), id(x[2])) for x in merged} | {(id(x[3]), id(x[5])) for x in merged}
    for m in smods:
        for p in m.paths:
            if (id(m), id(p)) in merged_paths:
                continue
            fw = path_forward(p)
            if fw is None:
                warn(f"[경고] 모듈 {m.id} 슬롯{p.a}-{p.b} 경로의 진행 방향을 도면에서 찾지 못함 - 슬롯 번호 순으로 기록")
                fw = True
            a, b = (p.a - 1, p.b - 1) if fw else (p.b - 1, p.a - 1)
            sa, sb = m.slots[a], m.slots[b]
            ln = p.length + margin(sa) + margin(sb)
            t = p.kind
            if t == "curve":
                ein = mul(sa.out, -1.0)          # 슬롯 a 로 들어오며 진행하는 방향
                eout = sb.out                     # 슬롯 b 에서 나가는 방향
                typ = "L" if cross(ein, eout) > 0 else "R"
            else:
                typ = {"line": "S", "arch": "U", "cross": "N"}[t]
            new_link(typ, nid[(m.id, a)], nid[(m.id, b)], ln, mul(sa.out, -1.0), mul(sb.out, -1.0))

    # 합쳐진 곡선 링크
    for mA, iA, pA, mB, iB, pB, g in merged:
        oA = (pA.b if pA.a == iA + 1 else pA.a) - 1
        oB = (pB.b if pB.a == iB + 1 else pB.a) - 1
        fwA = path_forward(pA)
        # pA 가 oA → iA 로 흐르면 병합 링크는 oA → oB
        a_to_slot = (fwA if pA.a == oA + 1 else (not fwA)) if fwA is not None else True
        src, dst = ((mA, oA), (mB, oB)) if a_to_slot else ((mB, oB), (mA, oA))
        ln = pA.length + pB.length + g + margin(mA.slots[oA]) + margin(mB.slots[oB])
        ein = mul(src[0].slots[src[1]].out, -1.0)
        eout = dst[0].slots[dst[1]].out
        typ = "U" if dot(ein, eout) < -0.5 else "N"
        new_link(typ, nid[(src[0].id, src[1])], nid[(dst[0].id, dst[1])], ln,
                 mul(src[0].slots[src[1]].out, -1.0), mul(dst[0].slots[dst[1]].out, -1.0))

    # 모듈 사이 직선
    def exits_at(m, i) -> Optional[bool]:
        """모듈 m 안의 흐름이 슬롯 i 로 나가나(True) / 들어오나(False)."""
        for p in m.paths:
            if i + 1 in (p.a, p.b):
                f = path_forward(p)
                if f is not None:
                    return (p.b == i + 1) == f
        return None

    for mA, iA, mB, iB, g, chain, fw in plain_conn:
        ln = g - margin(mA.slots[iA]) - margin(mB.slots[iB])
        a, b = (mA, iA), (mB, iB)
        if ln <= 0:
            # 마진이 겹친(규칙 미정) 연결은 사이 직선이 모듈 안으로 들어가 있어 방향이 불확실 → 모듈 흐름 우선
            ex = exits_at(mA, iA)
            if ex is None and exits_at(mB, iB) is not None:
                ex = not exits_at(mB, iB)
            if ex is not None:
                fw = ex
        if fw is None:                                   # 사이 직선이 없음 → 모듈 흐름으로 방향
            ex = exits_at(mA, iA)
            fw = ex if ex is not None else (not exits_at(mB, iB) if exits_at(mB, iB) is not None else True)
        if fw is False:
            a, b = b, a
        new_link("S", nid[(a[0].id, a[1])], nid[(b[0].id, b[1])], max(ln, 0.0),
                 a[0].slots[a[1]].out, b[0].slots[b[1]].out)

    # 7) 모듈과 무관한 형상(모듈 사이 직선 연결에 쓰이지 않은 조각)
    pnode = {}
    overshoot = {}     # 슬롯 NODE 에 흡수된 끝점 → 이미 지나간 이격 길이

    def plain_node(p):
        hit = slot_near(p)
        if hit and (hit[0].id, hit[1]) in nid:
            return nid[(hit[0].id, hit[1])], margin(hit[0].slots[hit[1]])
        k = key(p)
        if k in overshoot:
            return pnode[k], overshoot[k]
        if k not in pnode:
            pnode[k] = new_node(p)
            inside = next((m for m in smods if _on_pieces(m.inst, p, tol)), None)
            if inside is not None:
                warn(f"[경고] 모듈 {inside.id}({inside.type}) 안쪽 ({p[0]:.0f},{p[1]:.0f}) 에 슬롯이 아닌 선이 붙음 - "
                     f"모듈 종류 확인(예: 양쪽 레일이 지나가면 N)")
        return pnode[k], 0.0

    # 슬롯 이격이 붙은 직선보다 길면(다음 형상까지 닿음) 그 끝점을 슬롯 NODE 로 합친다
    for k, (kind, a, b, e) in enumerate(plain):
        if k in used_piece or kind != "LINE":
            continue
        for s_end, far in ((a, b), (b, a)):
            hit = slot_near(s_end)
            if not hit or (hit[0].id, hit[1]) not in nid:
                continue
            m_ = margin(hit[0].slots[hit[1]])
            ln = dist(a, b)
            if ln <= m_ + 1e-6 and not slot_near(far):
                pnode[key(far)] = nid[(hit[0].id, hit[1])]
                overshoot[key(far)] = m_ - ln
                used_piece.add(k)
                warn(f"[경고] 모듈 {hit[0].id} 슬롯{hit[1] + 1} 이격 {m_:.0f} 이 붙은 직선({ln:.0f})보다 김 - "
                     f"슬롯 NODE 를 다음 형상 시작점으로 합치고 남은 {m_ - ln:.0f} 은 다음 링크에서 뺌")
                break

    for k, (kind, a, b, e) in enumerate(plain):
        if k in used_piece:
            continue
        na, ma_ = plain_node(a)
        nb, mb_ = plain_node(b)
        if kind == "LINE":
            new_link("S", na, nb, dist(a, b) - ma_ - mb_, unit(sub(b, a)), unit(sub(a, b)))
        else:
            new_link("L" if _arc_ccw(e) else "R", na, nb, _arc_len(e) - ma_ - mb_,
                     _arc_away(e, a, b), _arc_away(e, b, a))

    nflip, nconf = orient_links(links, away)
    if nflip:
        log(f"진행 방향 정리: 링크 {nflip}개 방향을 바로잡음(분기점·직진 연속 규칙)")
    # 전체 회전 방향을 사용자가 고른 진행 방향(config io.direction, CCW/CW)에 맞춘다. 첫 방향 잡기(가장 바깥 NODE 부터
    #  탐색)는 허용 오차가 조금만 달라도 시작점이 바뀌어 반대 방향으로 잡힐 수 있고, 위의 정리는 "덜 뒤집는 쪽"을 골라
    #  그대로 둔다. 모든 링크를 함께 뒤집으므로 끊김 수는 그대로다.
    _want = str(((cfg or {}).get("io") or {}).get("direction", "CCW")).upper()
    _rot = _rotation(nodes, links) if links else 0.0
    if (_want == "CW" and _rot > 0) or (_want != "CW" and _rot < 0):
        for l in links:
            l.start_node_id, l.end_node_id = l.end_node_id, l.start_node_id
            l.type = {"L": "R", "R": "L"}.get(l.type, l.type)
        log(f"진행 방향 정리: 전체 회전이 설정({_want})과 반대로 잡혀 전체를 뒤집음")
    if nflip and nconf:
        _pos = {n.id: (float(n.x), float(n.y)) for n in nodes}
        _where = ", ".join(f"({_pos[c][0]:.0f},{_pos[c][1]:.0f})" for c in nconf[:5] if c in _pos)
        warn(f"[확인 필요] 진행 방향 규칙이 서로 맞지 않는 곳 {len(nconf)}군데 {_where} - 도면의 분기 배치를 확인하세요")
    # 연결 끊긴 슬롯: 모듈 슬롯 NODE 인데 모듈 밖(다른 모듈·일반 선)으로 이어진 링크가 하나도 없다. 대개 두 모듈이
    #  같은 레일 조각을 나눠 써 슬롯 짝이 안 잡힌 자리(분기 옆에 바로 차선 이동)이거나 도면이 실제로 끊긴 자리
    _nmod = {n.id: n.module_id for n in nodes}
    _ext = set()
    for l in links:
        a, b = l.start_node_id, l.end_node_id
        if not _nmod.get(a) or _nmod.get(a) != _nmod.get(b):
            _ext.update((a, b))
    _mby = {m.id: m for m in smods}
    for n in nodes:
        if not n.module_id or n.id in _ext:
            continue
        m = _mby.get(n.module_id)
        mt = m.type if m else "?"
        x, y = float(n.x), float(n.y)
        LAST_ISSUES.append({"x": x, "y": y, "gap": 0, "need": 0,
                            "ha": str(getattr(m.inst, "handle", "") or "") if m else "", "hb": "",
                            "text": f"연결 끊긴 슬롯 {mt}{n.slot_id}"})
        warn(f"[확인 필요] 연결 끊긴 슬롯 ({x:.0f}, {y:.0f}): 모듈 {n.module_id}({mt}) 슬롯{n.slot_id} - 이웃 모듈·선과 "
             f"이어지지 않음. 모듈 겹침(분기 옆에 바로 차선 이동 등) 또는 도면 끊김을 확인하세요")
    return Result(nodes, links, smods, (R0, L0, W1, W2, A0, M1, M2), warns)


def _rotation(nodes, links) -> float:
    """MAP 전체의 회전 방향: 중심에 대한 링크 외적 합. 양수 = 반시계(CCW). 바깥 순환 루프가 합을 좌우한다."""
    pos = {n.id: (float(n.x), float(n.y)) for n in nodes}
    pts = [pos[i] for l in links for i in (l.start_node_id, l.end_node_id) if i in pos]
    if not pts:
        return 0.0
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    s = 0.0
    for l in links:
        a, b = pos.get(l.start_node_id), pos.get(l.end_node_id)
        if a and b:
            s += (a[0] - cx) * (b[1] - cy) - (a[1] - cy) * (b[0] - cx)
    return s


def _arc_away(e, p, other) -> Pt:
    """호 e 의 끝 p 에서 호 몸통 쪽(다른 끝 other 방향)으로 뻗는 접선."""
    c = _center(e)
    rad = unit(sub(p, c))
    tan = (-rad[1], rad[0])
    return tan if dot(tan, sub(other, p)) > 0 else mul(tan, -1.0)


def orient_links(links, away) -> Tuple[int, list]:
    """링크 진행 방향을 노드 규칙에 맞게 정리한다. 반환 (뒤집은 링크 수, 규칙이 충돌한 NODE id 목록).

    노드마다 붙은 링크를 '뻗는 방향'으로 두 쪽으로 나눈다(첫 링크와 90° 안쪽 = 같은 쪽). 한 쪽은 모두 들어오고
    다른 쪽은 모두 나가야 한다 - 직진 노드는 한쪽으로 들어와 반대쪽으로 나가고, 분기점은 같은 쪽으로 갈라지는
    두 링크(직진·곡선)가 함께 나가거나 함께 들어온다. 링크(뒤집을지)와 노드(어느 쪽이 나가는 쪽인지)를 ±1 변수로
    두고 부호 있는 union-find 로 풀며, 연결된 묶음마다 지금 방향을 덜 뒤집는 쪽을 고른다. L/R 은 뒤집으면 바뀐다."""
    parent, par = {}, {}

    def find(x):
        if parent.setdefault(x, x) == x:
            par.setdefault(x, 1)
            return x, 1
        r, p = find(parent[x])
        parent[x], par[x] = r, par[x] * p
        return r, par[x]

    conflicts = []

    def union(a, b, p):          # 값(a) = p * 값(b)
        ra, pa = find(a)
        rb, pb = find(b)
        if ra == rb:
            if pa * pb != p:
                conflicts.append(b[1])
            return
        parent[ra] = rb
        par[ra] = pa * p * pb

    inc = {}
    for i, (l, (va, vb)) in enumerate(zip(links, away)):
        if va is None or vb is None:
            continue
        inc.setdefault(l.start_node_id, []).append((i, 1, va))
        inc.setdefault(l.end_node_id, []).append((i, -1, vb))
    for n, lst in inc.items():
        if len(lst) < 2:
            continue
        v0 = lst[0][2]
        sides = [1 if dot(v, v0) > 0 else -1 for _, _, v in lst]
        if all(sd == 1 for sd in sides):
            continue                                  # 모두 같은 쪽 - 규칙을 세울 수 없음
        for (i, s, v), sd in zip(lst, sides):
            union(("L", i), ("N", n), sd * s)         # 뒤집기 x_i = σ_n · 쪽 · (지금 이 노드에서 나가나)
    comp = {}
    for i in range(len(links)):
        if ("L", i) not in parent:
            continue
        r, p = find(("L", i))
        comp.setdefault(r, []).append((i, p))
    flips = set()
    for r, members in comp.items():
        stay = sum(1 for _, p in members if p == 1)
        root = 1 if stay >= len(members) - stay else -1
        flips.update(i for i, p in members if root * p == -1)

    def breaks(flipped):
        """들어오는 링크나 나가는 링크가 없는 NODE 수(막다른 끝 제외)."""
        ins, outs = {}, {}
        for i, l in enumerate(links):
            s, e = (l.end_node_id, l.start_node_id) if i in flipped else (l.start_node_id, l.end_node_id)
            outs[s] = outs.get(s, 0) + 1
            ins[e] = ins.get(e, 0) + 1
        nodes_ = set(ins) | set(outs)
        return sum(1 for n in nodes_ if (ins.get(n, 0) == 0) != (outs.get(n, 0) == 0)
                   and ins.get(n, 0) + outs.get(n, 0) > 1)

    def violations(flipped):
        """쪽 규칙을 어긴 NODE 수: 한 쪽에 들어오는 링크와 나가는 링크가 섞였거나, 두 쪽이 같은 방향(둘 다 들어옴/나감).
        들어오고 나가는 링크가 모두 있어 끊김으로는 안 세지지만 갈래에서 갈래로 꺾어 가는 길이 되는 곳
        (예: Y 의 두 곡선이 ③→①→② 로 이어짐)을 잡는다."""
        bad = 0
        for n, lst in inc.items():
            if len(lst) < 2:
                continue
            v0 = lst[0][2]
            sides = [1 if dot(v, v0) > 0 else -1 for _, _, v in lst]
            if all(sd == 1 for sd in sides):
                continue
            outs_by_side = {1: set(), -1: set()}
            for (i, sgn, _v), sd in zip(lst, sides):
                out = (sgn == 1) != (i in flipped)          # 이 노드에서 나가는가
                outs_by_side[sd].add(out)
            a, b = outs_by_side[1], outs_by_side[-1]
            if len(a) > 1 or len(b) > 1 or (a and b and a == b):
                bad += 1
        return bad

    # 안전장치: 끊김과 쪽 규칙 위반이 둘 다 나빠지지 않고 하나라도 줄 때만 적용한다(어떤 도면도 나빠지지 않게)
    b0, b1 = breaks(set()), breaks(flips) if flips else None
    v0_, v1_ = violations(set()), violations(flips) if flips else None
    if not flips or b1 > b0 or v1_ > v0_ or (b1 == b0 and v1_ == v0_):
        return 0, conflicts
    for i in flips:
        l = links[i]
        l.start_node_id, l.end_node_id = l.end_node_id, l.start_node_id
        l.type = {"L": "R", "R": "L"}.get(l.type, l.type)
    return len(flips), conflicts


def module_lines(res: Result) -> List[str]:
    out = []
    for m in res.modules:
        # 가이드 예시와 같게: Y 뒤에 슬롯 필드를 '/' 로 잇고 끝에 '/' 를 더 붙이지 않는다
        rx, ry = _param_str(m.ref[0]), _param_str(m.ref[1])
        out.append(f"MODULE/{m.id}/{m.type}/{m.angle}/{rx}/{ry}/" + "/".join(m.links))
    out.append("MODULEPARAM/" + "/".join(_param_str(v) for v in res.param))
    return out


def _param_str(v: float) -> str:
    """MODULEPARAM 값: 소수 1자리로 딱 떨어지면 가이드처럼 '450.0', 아니면 반올림하지 않는다
    (예: W1 505.555556, A 33.75). 1자리로 자르면 역변환에서 N·BY PASS 형상이 mm 단위로 어긋난다."""
    v = round(float(v), 6)                # 계산 잡음(1234.0000001)은 6자리에서 정리
    if abs(v - round(v, 1)) < 1e-9:
        s = f"{v:.1f}"
    else:
        s = f"{v:.6f}".rstrip("0")
    return "0.0" if s == "-0.0" else s
