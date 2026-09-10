# -*- coding: utf-8 -*-
"""모듈 정보 기반 분기 판정 — CAD 에 배치된 플러그인 기본 모듈을 읽어 판정한다.

플러그인(RailPlugin「Module」탭)이 그린 기본 모듈 15종은 블록 참조마다
XData(RAILPLUGIN) 에 **모듈 종류와 R/L/W/A** 를 새겨 둔다. 이 파일은 그 값을 그대로 읽어
맵의 분기 판정을 정한다. 선·호의 모양으로 U/N/복합분기를 **추정하지 않는다**.

  XData 순서: [Real L, Int16 모듈번호, Int16 kind(=7), Real W, Int16 lanes, Real R, Real A]
  블록 이름  : RAILMOD_<모듈>_R450_L1000[_W900][_A45]  (XData 가 없을 때의 대체 수단 + 교차 확인)

판정 규칙 (규칙 자체는 기존 node.pptx 스펙 그대로, 입력만 모듈 값으로)
---------------------------------------------------------------
  CURVE LEFT/RIGHT           단순 통과 곡선 — 양 끝 350 이격.
  BRANCH LEFT/RIGHT          일반 L/R 분기 — 분기·합류는 진행방향으로 결정(호가 접합점에서 시작=분기).
  U / DOUBLE BRANCH /        아치(호[+상부 직선]+호). W < 1601 이면 U분기(한 링크 U, 양 끝 J1 350).
    U BRANCH LEFT/RIGHT      W ≥ 1601 이면 U 가 아니다 — 접합점에 붙은 호는 일반 분기, 나머지는 단순 통과 곡선.
                             원본(ori) 맵은 W ≤ 2R+50(반원)만 U 로 병합한다(기존 ori/최종 기준 차이 유지).
  N / BY PASS / S L·R        크로스(호+대각+호) — 한 링크 N, N분기 규칙(J1 350, J2 = 대각 ≥750 ? 1500 : 1560).
  Y                          두 갈래 — 대기 노드 스펙 없음. 호는 L/R 링크로만 낸다.

L/R(좌·우)은 모듈 이름에서 정하지 않는다. 맵의 L/R 은 실제 진행방향 기준이라 같은 BRANCH LEFT 도
반대로 지나가면 R 이 된다 → 방향 통일 뒤 호 자체의 회전으로 정한다(기존 코드와 동일).

모듈 ↔ 엣지 대응은 모듈 형상(파이썬으로 옮긴 ModuleGeom.Build)을 월드좌표로 옮겨
같은 중심·반지름·각 범위의 호, 같은 선분 위의 직선을 찾는 것이다(모양 추정이 아니라 위치 대조).
"""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

Pt = Tuple[float, float]

APP = "RAILPLUGIN"
KIND_MODULE = 7
EPS = 1e-6

# ModuleGeom.Defs 와 같은 순서 (XData 의 모듈 번호 = 이 인덱스)
#   (이름, W 사용, A 사용)
DEFS: Tuple[Tuple[str, bool, bool], ...] = (
    ("CURVE LEFT", False, False),
    ("CURVE RIGHT", False, False),
    ("BRANCH LEFT", False, False),
    ("BRANCH RIGHT", False, False),
    ("U", True, False),
    ("DOUBLE BRANCH", True, False),
    ("U BRANCH LEFT", True, False),
    ("U BRANCH RIGHT", True, False),
    ("N LEFT", True, True),
    ("N RIGHT", True, True),
    ("BY PASS LEFT", True, True),
    ("BY PASS RIGHT", True, True),
    ("S LEFT", True, True),
    ("S RIGHT", True, True),
    ("Y", False, False),
)
DEF_R, DEF_L, DEF_W, DEF_A = 450.0, 1000.0, 900.0, 45.0

# 보고용 부분 이름 (Piece.role → 도면 용어)
ROLE_KO = {"through": "관통 직선", "stub": "접속 직선", "leg": "다리 직선",
           "arc": "호", "top": "상부 직선", "diag": "대각 직선"}

# 판정 기준 기본값 (config.json > module_judgment 로 덮어쓴다)
DEFAULTS = {
    "mode": "auto",                 # auto: 모듈이 있으면 모듈 판정 / on: 항상 / off: 기존 형상 판정
    "u_width_max_mm": 1601.0,       # 아치 폭 W 가 이 값 미만이면 U분기 (node.pptx 슬라이드 9, 코드 1601)
    "ori_u_extra_mm": 50.0,         # 원본 맵 U = W ≤ 2R + 이 값 (반원만)
    "match_center_tol_mm": 100.0,   # 호 중심 대조 허용 (좌표 스냅 SNAP_TOL 만큼 움직일 수 있다)
    "match_radius_tol_mm": 10.0,    # 호 반지름 대조 허용
    "match_point_tol_mm": 110.0,    # 끝점·선분 대조 허용
    "angle_margin_deg": 25.0,       # 호 각 범위 대조 여유 (이격 후 끝점이 접선 밖으로 밀린 만큼)
}


def module_config(cfg: Optional[dict]) -> dict:
    out = dict(DEFAULTS)
    out.update((cfg or {}).get("module_judgment", {}) or {})
    return out


def decide_modules(doc, cfg: Optional[dict]) -> Tuple[Optional[List["ModuleInstance"]], str]:
    """판정 방식 결정. 반환 (모듈 목록 또는 None, 로그 문구). None = 기존 형상 분기 판정.
      mode=auto : 도면에 기본 모듈이 하나라도 있으면 모듈 판정, 없으면 기존 판정
      mode=on   : 항상 모듈 판정(모듈이 없으면 분기 판정 자체가 없음)
      mode=off  : 항상 기존 형상 판정"""
    mode = str(module_config(cfg).get("mode", "auto")).strip().lower()
    if mode == "off":
        return None, "분기 판정: 기존 형상 판정 (config module_judgment.mode=off)"
    modules = read_modules(doc)
    if modules or mode == "on":
        return modules, (f"분기 판정: CAD 모듈 정보 사용 — 기본 모듈 {len(modules)}개 읽음 "
                         f"(형상으로 분기를 추정하지 않음)")
    return None, "분기 판정: 도면에 기본 모듈이 없어 기존 형상 판정 사용"


# ─────────────────────────────────────────────────────────────────────
# 모듈 형상 (RailPlugin/ModuleGeom.cs 의 Build 를 그대로 옮김 + 부분별 역할 표시)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Piece:
    kind: str                     # "LINE" | "ARC"
    role: str                     # through / stub / leg / arc / top / diag
    a: Pt                         # LINE 시작 / ARC 시작(로컬 CCW 기준)
    b: Pt                         # LINE 끝   / ARC 끝
    c: Optional[Pt] = None        # ARC 중심
    r: float = 0.0                # ARC 반지름
    m: Optional[Pt] = None        # ARC 위의 가운데 점


@dataclass
class Feature:
    kind: str                     # corner | branch | arch | cross | y
    pieces: List[int]             # Piece 인덱스 — 공간 순서(한쪽 끝 → 다른 끝)
    junctions: List[Pt]           # 본선에 붙는 접합점
    width: float = 0.0            # 아치·크로스의 W
    diag: float = 0.0             # 크로스 대각 직선 길이 d
    # 바인딩 결과 (엣지 객체)
    edges: List[Any] = field(default_factory=list)
    missing: List[int] = field(default_factory=list)   # 대응 엣지를 못 찾은 Piece


def clamp(idx: int, r: float, l: float, w: float, a: float) -> Tuple[float, float, float, float]:
    """ModuleGeom.Clamp — 물리적으로 불가능한 값 방어(플러그인과 같은 형상이 나오게)."""
    if r < 1.0:
        r = 1.0
    if l < 0.0:
        l = 0.0
    _, uses_w, uses_a = DEFS[idx]
    if uses_a:
        a = min(max(a, 1.0), 89.0)
        wmin = 2.0 * r * (1.0 - math.cos(math.radians(a)))
        if w < wmin:
            w = wmin
    elif uses_w:
        if w < 2.0 * r:
            w = 2.0 * r
    return r, l, w, a


def cross_run(r: float, w: float, a: float) -> float:
    """S자 대각 직선 길이 d = (W − 2R(1−cosA)) / sinA."""
    ar = math.radians(a)
    return (w - 2.0 * r * (1.0 - math.cos(ar))) / math.sin(ar)


def cross_rise(r: float, w: float, a: float) -> float:
    """S자 세로 점유 = 2R·sinA + d·cosA."""
    ar = math.radians(a)
    return 2.0 * r * math.sin(ar) + cross_run(r, w, a) * math.cos(ar)


def _ln(x1, y1, x2, y2, role) -> Piece:
    return Piece("LINE", role, (x1, y1), (x2, y2))


def _ar(cx, cy, r, a0, a1, role="arc") -> Piece:
    while a1 <= a0:
        a1 += 360.0
    t0, t1, tm = math.radians(a0), math.radians(a1), math.radians((a0 + a1) * 0.5)
    return Piece("ARC", role,
                 (cx + r * math.cos(t0), cy + r * math.sin(t0)),
                 (cx + r * math.cos(t1), cy + r * math.sin(t1)),
                 c=(cx, cy), r=r,
                 m=(cx + r * math.cos(tm), cy + r * math.sin(tm)))


def build_local(idx: int, r: float, l: float, w: float, a: float) -> Tuple[List[Piece], List[Feature]]:
    """모듈 로컬 형상과 판정 단위(Feature). 좌표계·치수는 ModuleGeom.Build 와 동일."""
    r, l, w, a = clamp(idx, r, l, w, a)
    name = DEFS[idx][0]
    P: List[Piece] = []
    F: List[Feature] = []

    def add(p: Piece) -> int:
        P.append(p)
        return len(P) - 1

    def arch(junctions: List[Pt]):
        # 상부 아치: (0,l) ↔ (w,l). 공간 순서 = 좌 호 → [상부 직선] → 우 호
        i0 = add(_ar(r, l, r, 90, 180))
        ids = [i0]
        if w - 2.0 * r > EPS:
            ids.append(add(_ln(r, l + r, w - r, l + r, "top")))
        ids.append(add(_ar(w - r, l, r, 0, 90)))
        F.append(Feature("arch", ids, junctions, width=w))

    def cross(left: bool, junctions: List[Pt]):
        ar_ = math.radians(a)
        ca, sa = math.cos(ar_), math.sin(ar_)
        d = cross_run(r, w, a)
        if left:   # (w,l) → (0,l+rise)
            ids = [add(_ar(w - r, l, r, 0, a))]
            p1 = (w - r + r * ca, l + r * sa)
            p2 = (p1[0] - d * sa, p1[1] + d * ca)
            if d > EPS:
                ids.append(add(_ln(p1[0], p1[1], p2[0], p2[1], "diag")))
            ids.append(add(_ar(p2[0] + r * ca, p2[1] + r * sa, r, 180, 180 + a)))
        else:      # (0,l) → (w,l+rise)
            ids = [add(_ar(r, l, r, 180 - a, 180))]
            p1 = (r - r * ca, l + r * sa)
            p2 = (p1[0] + d * sa, p1[1] + d * ca)
            if d > EPS:
                ids.append(add(_ln(p1[0], p1[1], p2[0], p2[1], "diag")))
            ids.append(add(_ar(p2[0] - r * ca, p2[1] + r * sa, r, 360 - a, 360)))
        F.append(Feature("cross", ids, junctions, width=w, diag=max(d, 0.0)))

    if name in ("CURVE LEFT", "CURVE RIGHT"):
        add(_ln(0, 0, 0, l, "stub"))
        if name == "CURVE LEFT":
            i = add(_ar(-r, l, r, 0, 90))
            add(_ln(-r, l + r, -r - l, l + r, "stub"))
        else:
            i = add(_ar(r, l, r, 90, 180))
            add(_ln(r, l + r, r + l, l + r, "stub"))
        F.append(Feature("corner", [i], []))
    elif name in ("BRANCH LEFT", "BRANCH RIGHT"):
        add(_ln(0, 0, 0, 2 * l + r, "through"))
        if name == "BRANCH LEFT":
            i = add(_ar(-r, l, r, 0, 90))
            add(_ln(-r, l + r, -r - l, l + r, "stub"))
        else:
            i = add(_ar(r, l, r, 90, 180))
            add(_ln(r, l + r, r + l, l + r, "stub"))
        F.append(Feature("branch", [i], [(0.0, l)]))
    elif name == "U":
        add(_ln(0, 0, 0, l, "leg"))
        add(_ln(w, 0, w, l, "leg"))
        arch([])
    elif name == "DOUBLE BRANCH":
        add(_ln(0, 0, 0, 2 * l + r, "through"))
        add(_ln(w, 0, w, 2 * l + r, "through"))
        arch([(0.0, l), (w, l)])
    elif name == "U BRANCH LEFT":
        add(_ln(w, 0, w, 2 * l + r, "through"))
        add(_ln(0, 0, 0, l, "leg"))
        arch([(w, l)])
    elif name == "U BRANCH RIGHT":
        add(_ln(0, 0, 0, 2 * l + r, "through"))
        add(_ln(w, 0, w, l, "leg"))
        arch([(0.0, l)])
    elif name in ("N LEFT", "N RIGHT", "BY PASS LEFT", "BY PASS RIGHT", "S LEFT", "S RIGHT"):
        h = cross_rise(r, w, a)
        left = name.endswith("LEFT")
        if name.startswith("N "):
            add(_ln(0, 0, 0, 2 * l + h, "through"))
            add(_ln(w, 0, w, 2 * l + h, "through"))
            cross(left, [(w, l), (0.0, l + h)] if left else [(0.0, l), (w, l + h)])
        elif name.startswith("BY PASS"):
            if left:     # 좌측 레일 관통, 우측 레일이 접합부에서 끝남
                add(_ln(0, 0, 0, 2 * l + h, "through"))
                add(_ln(w, 0, w, l, "leg"))
                cross(True, [(0.0, l + h)])
            else:
                add(_ln(w, 0, w, 2 * l + h, "through"))
                add(_ln(0, 0, 0, l, "leg"))
                cross(False, [(w, l + h)])
        else:            # S: 레일 한 줄이 W 만큼 옆으로 이동 — 접합점 없음
            if left:
                add(_ln(w, 0, w, l, "leg"))
                cross(True, [])
                add(_ln(0, l + h, 0, 2 * l + h, "leg"))
            else:
                add(_ln(0, 0, 0, l, "leg"))
                cross(False, [])
                add(_ln(w, l + h, w, 2 * l + h, "leg"))
    elif name == "Y":
        add(_ln(0, 0, 0, l, "stub"))
        i1 = add(_ar(-r, l, r, 0, 90))
        add(_ln(-r, l + r, -r - l, l + r, "stub"))
        i2 = add(_ar(r, l, r, 90, 180))
        add(_ln(r, l + r, r + l, l + r, "stub"))
        F.append(Feature("y", [i1, i2], [(0.0, l)]))
    return P, F


# ─────────────────────────────────────────────────────────────────────
# CAD 에서 모듈 읽기
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ModuleInstance:
    no: int
    idx: int
    name: str
    R: float
    L: float
    W: float
    A: float
    handle: str
    layer: str
    block: str
    insert: Pt
    rotation: float
    mirrored: bool
    source: str                               # "XData" | "블록이름"
    pieces: List[Piece] = field(default_factory=list)       # 월드 좌표
    features: List[Feature] = field(default_factory=list)   # 월드 좌표
    notes: List[str] = field(default_factory=list)
    judged: List[str] = field(default_factory=list)          # 판정 결과(보고용)


_NUM = r"(m?[0-9]+(?:p[0-9]+)?)"
_BLOCK_RE = re.compile(r"^RAILMOD_(.+?)_R" + _NUM + r"_L" + _NUM + r"(?:_W" + _NUM + r")?(?:_A" + _NUM + r")?$",
                       re.IGNORECASE)


def _num(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    return float(s.replace("p", ".").replace("m", "-"))


def parse_block_name(name: str) -> Optional[Tuple[int, float, float, Optional[float], Optional[float]]]:
    """RAILMOD_<모듈>_R.._L..[_W..][_A..] → (모듈번호, R, L, W, A). 모듈명의 공백은 '-' 로 들어 있다."""
    m = _BLOCK_RE.match(name or "")
    if not m:
        return None
    mod = m.group(1).replace("-", " ").upper()
    idx = next((i for i, d in enumerate(DEFS) if d[0] == mod), -1)
    if idx < 0:
        return None
    return idx, _num(m.group(2)), _num(m.group(3)), _num(m.group(4)), _num(m.group(5))


def _xdata_module(ins) -> Optional[Tuple[int, float, float, float, float]]:
    """RAILPLUGIN XData 가 kind 7(기본 모듈)이면 (모듈번호, R, L, W, A)."""
    try:
        if not ins.has_xdata(APP):
            return None
        tags = ins.get_xdata(APP)
    except Exception:
        return None
    reals = [float(t.value) for t in tags if t.code == 1040]
    ints = [int(t.value) for t in tags if t.code == 1070]
    kind = ints[1] if len(ints) >= 2 else 2          # 구버전(kind 없음) = 2차선 레일
    if kind != KIND_MODULE or not ints:
        return None
    idx = ints[0]
    if not (0 <= idx < len(DEFS)):
        return None
    L = reals[0] if len(reals) > 0 else DEF_L
    W = reals[1] if len(reals) > 1 else DEF_W
    R = reals[2] if len(reals) > 2 else DEF_R
    A = reals[3] if len(reals) > 3 else DEF_A
    return idx, R, L, W, A


def is_module_insert(ins) -> bool:
    if _xdata_module(ins) is not None:
        return True
    return parse_block_name(str(getattr(ins.dxf, "name", "") or "")) is not None


def _to_world(m, p: Pt) -> Pt:
    v = m.transform((p[0], p[1], 0.0))
    return (float(v[0]), float(v[1]))


def _instance(no: int, ins, m) -> Optional[ModuleInstance]:
    bname = str(getattr(ins.dxf, "name", "") or "")
    xd = _xdata_module(ins)
    bn = parse_block_name(bname)
    notes: List[str] = []
    if xd is not None:
        idx, R, L, W, A = xd
        src = "XData"
        if bn is not None and bn[0] != idx:
            notes.append(f"블록 이름({DEFS[bn[0]][0]})과 XData({DEFS[idx][0]}) 종류가 다름 — XData 사용")
    elif bn is not None:
        idx, R, L, W, A = bn
        W = W if W is not None else DEF_W
        A = A if A is not None else DEF_A
        src = "블록이름"
        notes.append("XData 없음 — 블록 이름으로 판정")
    else:
        return None
    R, L, W, A = clamp(idx, R, L, W, A)

    ux = m.transform_direction((1.0, 0.0, 0.0))
    uy = m.transform_direction((0.0, 1.0, 0.0))
    sx, sy = math.hypot(ux[0], ux[1]), math.hypot(uy[0], uy[1])
    det = ux[0] * uy[1] - ux[1] * uy[0]
    if abs(sx - sy) > 1e-6 * max(sx, sy, 1.0):
        notes.append(f"축척이 가로·세로 다름({sx:g}×{sy:g}) — 호가 원이 아니므로 평균 축척 사용")
    scale = 0.5 * (sx + sy)

    loc_p, loc_f = build_local(idx, R, L, W, A)
    world_p: List[Piece] = []
    for p in loc_p:
        if p.kind == "LINE":
            world_p.append(Piece("LINE", p.role, _to_world(m, p.a), _to_world(m, p.b)))
        else:
            world_p.append(Piece("ARC", p.role, _to_world(m, p.a), _to_world(m, p.b),
                                 c=_to_world(m, p.c), r=p.r * scale, m=_to_world(m, p.m)))
    world_f = [Feature(f.kind, list(f.pieces), [_to_world(m, j) for j in f.junctions],
                       width=f.width * scale, diag=f.diag * scale) for f in loc_f]
    ip = _to_world(m, (0.0, 0.0))
    return ModuleInstance(
        no=no, idx=idx, name=DEFS[idx][0], R=R * scale, L=L * scale, W=W * scale, A=A,
        handle=str(getattr(ins.dxf, "handle", "") or ""),
        layer=str(getattr(ins.dxf, "layer", "0") or "0"),
        block=bname, insert=ip,
        rotation=(math.degrees(math.atan2(ux[1], ux[0])) % 360.0),
        mirrored=det < 0.0, source=src,
        pieces=world_p, features=world_f, notes=notes,
    )


def read_modules(doc, *, max_depth: int = 8) -> List[ModuleInstance]:
    """모델공간(+중첩 블록)의 기본 모듈 참조를 모두 읽는다."""
    out: List[ModuleInstance] = []

    def walk(entities, depth: int):
        for e in entities:
            if e.dxftype() != "INSERT":
                continue
            if is_module_insert(e):
                inst = _instance(len(out) + 1, e, e.matrix44())
                if inst is not None:
                    out.append(inst)
                continue
            if depth >= max_depth:
                continue
            try:
                # virtual_entities 는 중첩 INSERT 를 WCS 로 옮긴 사본을 준다(XData 포함)
                walk([ve for ve in e.virtual_entities() if ve.dxftype() == "INSERT"], depth + 1)
            except Exception:
                pass

    walk(doc.modelspace(), 0)
    return out


# ─────────────────────────────────────────────────────────────────────
# 모듈 ↔ 엣지 대응 (위치 대조)
# ─────────────────────────────────────────────────────────────────────

def _d(p: Pt, q: Pt) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _ang(c: Pt, p: Pt) -> float:
    return math.atan2(p[1] - c[1], p[0] - c[0])


def _wrap(t: float) -> float:
    """(-π, π] 로."""
    return (t + math.pi) % (2.0 * math.pi) - math.pi


def _edge_arc_mid_angle(e, c: Pt) -> float:
    """엣지 호의 각 범위 가운데(작은 쪽 호 기준). 끝점이 원 밖으로 밀려 있어도 방향만 쓴다."""
    ts, te = _ang(c, e.start), _ang(c, e.end)
    return ts + _wrap(te - ts) * 0.5


def _piece_span(p: Piece) -> Tuple[float, float]:
    """피스 호의 (가운데 각, 반폭)."""
    tm = _ang(p.c, p.m)
    ta = _ang(p.c, p.a)
    return tm, abs(_wrap(ta - tm))


def _line_match(e, p: Piece, tol: float) -> bool:
    """엣지 직선이 피스 선분 위(같은 직선 + 구간 겹침)에 있는가."""
    ax, ay = p.a
    bx, by = p.b
    L = math.hypot(bx - ax, by - ay)
    if L < EPS:
        return False
    ux, uy = (bx - ax) / L, (by - ay) / L
    for q in (e.start, e.end):
        if abs((q[0] - ax) * uy - (q[1] - ay) * ux) > tol:
            return False
    mx, my = (e.start[0] + e.end[0]) * 0.5, (e.start[1] + e.end[1]) * 0.5
    t = (mx - ax) * ux + (my - ay) * uy
    return -tol <= t <= L + tol


def bind_modules(edges: Sequence[Any], modules: List[ModuleInstance], mcfg: dict) -> Dict[str, Any]:
    """판정 단위(Feature)마다 해당 엣지 객체를 찾아 붙인다. 반환: 통계."""
    tc = float(mcfg["match_center_tol_mm"])
    tr = float(mcfg["match_radius_tol_mm"])
    tp = float(mcfg["match_point_tol_mm"])
    margin = math.radians(float(mcfg["angle_margin_deg"]))
    arcs = [e for e in edges if getattr(e, "edge_type", None) == "ARC"]
    lines = [e for e in edges if getattr(e, "edge_type", None) == "LINE"]
    claimed: Dict[int, Tuple[int, int]] = {}      # id(edge) → (모듈 no, feature 번호)
    conflicts = 0

    for mod in modules:
        for fi, f in enumerate(mod.features):
            f.edges, f.missing = [], []
            for pi in f.pieces:
                p = mod.pieces[pi]
                hit = []
                if p.kind == "ARC":
                    tm, half = _piece_span(p)
                    for e in arcs:
                        d = e._data
                        c = (float(d.cx), float(d.cy))
                        if _d(c, p.c) > tc or abs(float(d.r) - p.r) > tr:
                            continue
                        if abs(_wrap(_edge_arc_mid_angle(e, c) - tm)) > half + margin:
                            continue
                        hit.append(e)
                else:
                    for e in lines:
                        if _line_match(e, p, tp):
                            hit.append(e)
                if not hit:
                    f.missing.append(pi)
                for e in hit:
                    key = id(e)
                    if key in claimed and claimed[key] != (mod.no, fi):
                        conflicts += 1
                        continue
                    claimed[key] = (mod.no, fi)
                    if e not in f.edges:
                        f.edges.append(e)
    module_arc_ids = {k for k in claimed}
    free_arcs = [e for e in arcs if id(e) not in module_arc_ids]
    return {"free_arcs": free_arcs, "conflicts": conflicts}


def _chain(edge_objs: Sequence[Any], tol: float) -> Optional[List[Any]]:
    """엣지들을 진행 순서(끝→시작 연결)로 늘어놓는다. 한 줄로 이어지지 않으면 None."""
    objs = list(edge_objs)
    if not objs:
        return None
    if len(objs) == 1:
        return objs
    heads = [e for e in objs if not any(o is not e and _d(o.end, e.start) <= tol for o in objs)]
    if len(heads) != 1:
        return None
    order = [heads[0]]
    rest = [e for e in objs if e is not heads[0]]
    while rest:
        nxt = [e for e in rest if _d(order[-1].end, e.start) <= tol]
        if len(nxt) != 1:
            return None
        order.append(nxt[0])
        rest.remove(nxt[0])
    return order


def _indices(edges: Sequence[Any], objs: Sequence[Any]) -> Optional[Tuple[int, ...]]:
    pos = {id(e): i for i, e in enumerate(edges)}
    out = []
    for o in objs:
        if id(o) not in pos:
            return None
        out.append(pos[id(o)])
    return tuple(out)


def _present(edges: Sequence[Any], objs: Sequence[Any]) -> List[Any]:
    ids = {id(e) for e in edges}
    return [o for o in objs if id(o) in ids]


# ─────────────────────────────────────────────────────────────────────
# 판정
# ─────────────────────────────────────────────────────────────────────

class ModuleJudge:
    """모듈 목록 + 판정 기준. 파이프라인 단계마다 엣지 인덱스로 된 판정 입력을 만든다."""

    def __init__(self, modules: List[ModuleInstance], cfg: Optional[dict] = None, *, tol: float = 100.0):
        self.modules = modules
        self.mcfg = module_config(cfg)
        self.tol = float(tol)
        self.u_max = float(self.mcfg["u_width_max_mm"])
        self.free_arc_count = 0
        self.conflicts = 0
        self.spacing_warnings: List[str] = []

    # ── 준비 ──
    def bind(self, edges: Sequence[Any]) -> None:
        """방향 통일 직후(이격 전) 엣지에 모듈을 붙인다. 이후 단계는 같은 엣지 객체를 따라간다."""
        st = bind_modules(edges, self.modules, self.mcfg)
        self.free_arc_count = len(st["free_arcs"])
        self.conflicts = st["conflicts"]
        self._free_arc_pts = [(round(e.start[0]), round(e.start[1])) for e in st["free_arcs"]]
        for mod in self.modules:
            for f in mod.features:
                if f.missing:
                    roles = ", ".join(ROLE_KO.get(mod.pieces[i].role, mod.pieces[i].role) for i in f.missing)
                    mod.notes.append(f"도면에서 못 찾은 부분: {roles} — 색·레이어 필터 또는 형상 수정 여부 확인")

    def _arch_is_u(self, f: Feature, *, ori: bool, mod: ModuleInstance) -> bool:
        if ori:
            return f.width <= 2.0 * mod.R + float(self.mcfg["ori_u_extra_mm"])
        return f.width < self.u_max

    def _chained(self, edges, f: Feature, mod: ModuleInstance, label: str) -> Optional[Tuple[int, ...]]:
        order = _chain(_present(edges, f.edges), self.tol)
        if order is None:
            mod.notes.append(f"{label}: 엣지가 한 방향으로 이어지지 않음(진행방향 불일치) — 병합 안 함")
            return None
        return _indices(edges, order)

    # ── 원본(ori) 맵 병합 ──
    def ori_merge_groups(self, edges: Sequence[Any]) -> List[Tuple[Tuple[int, ...], str]]:
        groups = []
        for mod in self.modules:
            for f in mod.features:
                if f.missing:
                    continue
                if f.kind == "arch" and self._arch_is_u(f, ori=True, mod=mod):
                    g = self._chained(edges, f, mod, "원본 U")
                    if g and len(g) > 1:
                        groups.append((g, "U"))
                elif f.kind == "cross":
                    g = self._chained(edges, f, mod, "원본 N")
                    if g and len(g) > 1:
                        groups.append((g, "N"))
        return _dedup(groups)

    # ── 대기 노드(이격) 입력 ──
    def clearance_inputs(self, edges: Sequence[Any]) -> Dict[str, Any]:
        """insert_clearance_nodes(module_judgment=...) 입력. 인덱스는 이 edges 기준."""
        u_pairs, n_pairs, lr_arcs, corner_arcs = [], [], [], []
        for mod in self.modules:
            mod.judged = []
            for f in mod.features:
                if f.missing:
                    mod.judged.append("판정 불가(형상 누락)")
                    continue
                if f.kind == "corner":
                    for e in _present(edges, f.edges):
                        corner_arcs.append(_indices(edges, [e])[0])
                    mod.judged.append("곡선(양 끝 350 이격)")
                elif f.kind == "branch":
                    roles = self._lr_roles(edges, f, mod, lr_arcs)
                    mod.judged.append("일반 분기(" + "/".join(roles) + ")")
                elif f.kind == "arch":
                    if self._arch_is_u(f, ori=False, mod=mod):
                        g = self._chained(edges, f, mod, "U")
                        if g:
                            u_pairs.append(g)
                            mod.judged.append(f"U분기(W {f.width:.0f} < {self.u_max:.0f})")
                        else:
                            mod.judged.append("U분기 — 방향 불일치로 제외")
                    else:
                        # W ≥ 1601: U 아님. 접합점에 붙은 호 = 일반 분기, 나머지 호 = 단순 통과 곡선
                        roles = []
                        for e in _present(edges, f.edges):
                            if e.edge_type != "ARC":
                                continue
                            i = _indices(edges, [e])[0]
                            j = _near_junction(e, f.junctions, self.tol)
                            if j is None:
                                corner_arcs.append(i)
                                roles.append("곡선")
                            elif _d(e.start, j) <= self.tol:
                                lr_arcs.append((i, "diverge"))
                                roles.append("분기")
                            else:
                                lr_arcs.append((i, "merge"))
                                roles.append("합류")
                        mod.judged.append(f"U 아님(W {f.width:.0f} ≥ {self.u_max:.0f}): " + "/".join(roles))
                elif f.kind == "cross":
                    g = self._chained(edges, f, mod, "N")
                    if g:
                        n_pairs.append(g)
                        mod.judged.append(f"N분기(대각 {f.diag:.0f})")
                    else:
                        mod.judged.append("N분기 — 방향 불일치로 제외")
                elif f.kind == "y":
                    mod.judged.append("Y — 대기 노드 스펙 없음(호는 L/R 링크)")
        self._spacing_check(edges, u_pairs, n_pairs, lr_arcs, corner_arcs)
        return {"u_pairs": u_pairs, "n_pairs": n_pairs, "lr_arcs": lr_arcs, "corner_arcs": corner_arcs}

    def _spacing_check(self, edges, u_pairs, n_pairs, lr_arcs, corner_arcs, take: float = 350.0) -> None:
        """대기 이격(350mm 이동)이 한 직선의 양 끝에서 동시에 일어날 때 직선이 모자라는지 본다.
        모자라면 배치 규칙이 이격을 건너뛰거나 두 노드가 한 점으로 겹친다 → 경고만 남긴다(판정은 그대로)."""
        tol = self.tol
        lines = [e for e in edges if e.edge_type == "LINE"]

        def at_start(pt):   # pt 에서 시작하는 직선
            return [e for e in lines if _d(e.start, pt) <= tol]

        def at_end(pt):     # pt 에서 끝나는 직선
            return [e for e in lines if _d(e.end, pt) <= tol]

        need: Dict[int, float] = {}
        where: Dict[int, Any] = {}

        def add(ls):
            for e in ls:
                need[id(e)] = need.get(id(e), 0.0) + take
                where[id(e)] = e

        for i, role in lr_arcs:              # J1(접합점 이동) + J3(호 반대쪽 끝 이동)
            a = edges[i]
            add(at_end(a.start) if role == "diverge" else at_start(a.end))
            add(at_start(a.end) if role == "diverge" else at_end(a.start))
        for i in corner_arcs:                # 단순 통과 곡선 양 끝
            a = edges[i]
            add(at_end(a.start))
            add(at_start(a.end))
        for g in list(u_pairs) + list(n_pairs):   # U·N 양 끝 J1
            add(at_end(edges[g[0]].start))
            add(at_start(edges[g[-1]].end))
        self.spacing_warnings = []
        for k, v in need.items():
            e = where[k]
            L = _d(e.start, e.end)
            if L - v < tol:
                mx, my = (e.start[0] + e.end[0]) * 0.5, (e.start[1] + e.end[1]) * 0.5
                self.spacing_warnings.append(
                    f"직선 {L:.0f}mm 에 대기 이격 {v:.0f}mm 필요(남는 길이 {max(L - v, 0.0):.0f}mm) "
                    f"— 이격 생략 또는 노드 겹침 @({mx:.0f},{my:.0f})")

    def _lr_roles(self, edges, f: Feature, mod: ModuleInstance, lr_arcs: list) -> List[str]:
        roles = []
        for e in _present(edges, f.edges):
            if e.edge_type != "ARC":
                continue
            j = _near_junction(e, f.junctions, self.tol)
            if j is None:
                mod.notes.append("분기 호가 접합점에 닿지 않음 — 분기 규칙 미적용")
                continue
            if _d(e.start, j) <= self.tol:
                lr_arcs.append((_indices(edges, [e])[0], "diverge"))
                roles.append("분기")
            else:
                lr_arcs.append((_indices(edges, [e])[0], "merge"))
                roles.append("합류")
        return roles

    # ── 최종 맵 병합 (이격 후) ──
    def final_merge_groups(self, edges: Sequence[Any]) -> List[Tuple[Tuple[int, ...], str]]:
        """이격 후 엣지로 U/N 병합. 이격 때 호 객체는 유지되고 가운데 직선만 새로 쪼개질 수 있어
        없어진 엣지는 두 호 사이를 그래프로 이어 채운다."""
        groups = []
        for mod in self.modules:
            for f in mod.features:
                if f.missing:
                    continue
                if f.kind == "arch" and self._arch_is_u(f, ori=False, mod=mod):
                    g = self._final_group(edges, f, mod, "최종 U")
                    if g:
                        groups.append((g, "U"))
                elif f.kind == "cross":
                    g = self._final_group(edges, f, mod, "최종 N")
                    if g:
                        groups.append((g, "N"))
        return _dedup(groups)

    def _final_group(self, edges, f: Feature, mod: ModuleInstance, label: str) -> Optional[Tuple[int, ...]]:
        present = _present(edges, f.edges)
        arcs_ = [e for e in present if e.edge_type == "ARC"]
        if len(arcs_) < 2:
            mod.notes.append(f"{label}: 이격 후 호를 찾지 못함 — 병합 안 함")
            return None
        order = _chain(present, self.tol)
        if order is None:
            # 가운데 직선이 쪼개졌거나 사라진 경우 — 첫 호 끝에서 다음 호 시작까지 그래프로 잇는다
            order = _bridge(edges, arcs_, self.tol)
        if order is None:
            mod.notes.append(f"{label}: 엣지가 한 방향으로 이어지지 않음 — 병합 안 함")
            return None
        return _indices(edges, order)

    # ── 보고 ──
    def summary_lines(self) -> List[str]:
        from collections import Counter
        c = Counter(m.name for m in self.modules)
        lines = [f"모듈 {len(self.modules)}개: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items()))]
        if self.free_arc_count:
            lines.append(f"[주의] 모듈에 속하지 않은 호 {self.free_arc_count}개 — 분기 판정 없이 L/R 링크로만 출력")
        if self.conflicts:
            lines.append(f"[주의] 두 모듈에 겹쳐 대응된 엣지 {self.conflicts}개 — 먼저 대응된 모듈 기준")
        n_notes = sum(1 for m in self.modules if m.notes)
        if n_notes:
            lines.append(f"[주의] 확인 필요한 모듈 {n_notes}개 — _modules.csv 의 비고 참고")
        for w in self.spacing_warnings:
            lines.append("[주의] " + w)
        return lines

    def save_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["번호", "모듈", "R", "L", "W", "A", "삽입X", "삽입Y", "회전", "대칭",
                        "판정", "읽은 곳", "레이어", "블록", "핸들", "비고"])
            for m in self.modules:
                _, uses_w, uses_a = DEFS[m.idx]
                w.writerow([m.no, m.name, f"{m.R:g}", f"{m.L:g}",
                            f"{m.W:g}" if uses_w else "", f"{m.A:g}" if uses_a else "",
                            f"{m.insert[0]:.3f}", f"{m.insert[1]:.3f}", f"{m.rotation:.1f}",
                            "Y" if m.mirrored else "", " | ".join(m.judged), m.source, m.layer,
                            m.block, m.handle, " | ".join(dict.fromkeys(m.notes))])
            if self.free_arc_count:
                w.writerow([])
                w.writerow(["모듈 밖 호", self.free_arc_count, "", "", "", "", "", "", "", "",
                            "분기 판정 없음(L/R 링크)", "", "", "", "",
                            "시작점: " + " ".join(f"({x},{y})" for x, y in self._free_arc_pts[:50])])
            if self.spacing_warnings:
                w.writerow([])
                for s in self.spacing_warnings:
                    w.writerow(["간격 경고", "", "", "", "", "", "", "", "", "", "", "", "", "", "", s])


def _near_junction(e, junctions: List[Pt], tol: float) -> Optional[Pt]:
    for j in junctions:
        if _d(e.start, j) <= tol or _d(e.end, j) <= tol:
            return j
    return None


def _bridge(edges: Sequence[Any], arcs_: List[Any], tol: float) -> Optional[List[Any]]:
    """두 호 사이를 끝→시작 연결(직선만)로 잇는 가장 짧은 엣지 경로. 호 순서도 연결로 정한다."""
    best = None
    for first in arcs_:
        for last in arcs_:
            if first is last:
                continue
            path = [first]
            cur = first
            seen = {id(first)}
            ok = False
            for _ in range(8):
                if _d(cur.end, last.start) <= tol:
                    path.append(last)
                    ok = True
                    break
                nxt = [e for e in edges if id(e) not in seen and e.edge_type == "LINE"
                       and _d(cur.end, e.start) <= tol]
                if len(nxt) != 1:
                    break
                cur = nxt[0]
                seen.add(id(cur))
                path.append(cur)
            if ok and (best is None or len(path) < len(best)):
                best = path
    return best


def _dedup(groups: List[Tuple[Tuple[int, ...], str]]) -> List[Tuple[Tuple[int, ...], str]]:
    seen, out = set(), []
    for g, t in groups:
        if any(i in seen for i in g):
            continue
        seen.update(g)
        out.append((g, t))
    return out
