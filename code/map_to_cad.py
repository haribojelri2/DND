# -*- coding: utf-8 -*-
"""MAP → CAD 역변환 — `.map` 의 NODE/LINK 를 레일 센터선 DXF(LINE/ARC)로 되돌린다.

`.map` 은 호의 **반지름·중심을 저장하지 않는다**. 저장된 것은 링크 타입(S/L/R/U/N),
양 끝 노드 좌표, 링크 길이뿐이다. 그래서 다음 규칙으로 형상을 되풀어낸다.

  S      직선. 두 노드를 잇는 LINE.
  L / R  호 하나. 현 길이 c 와 호 길이 La 로 `La = 2R·asin(c/2R)` 를 풀어 R 을 구한다.
         타입이 회전방향(L=CCW, R=CW)이라 중심이 어느 쪽인지도 정해진다.
  U      180° 되돌림(호-직-호). c 와 La 로 `r = (La-c)/(π-2)`, `mid = c-2r`.
         돌출 방향은 **시작점의 진행 접선**으로 결정한다(맵에 없는 정보를 이웃에서 얻는다).
  N      45°급 크로스오버(호-대각-호). 시작 접선 기준 종/횡 성분(u, w)과 표준 반지름으로
         호 스윕각 a 와 대각 길이 d 를 수치해로 구한다.

**입력은 `ori_*.map` 을 쓸 것.** 최종 맵은 clearance 노드가 호 끝을 접선 밖으로 밀어놓아
현·호길이가 한 원에 맞지 않는다(복원 반지름이 틀어진다).

복원되지 않는 것: 레이어·색·블록 구조·장비 외형·치수·텍스트. 레일 골격만 나온다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

Pt = Tuple[float, float]
Primitive = Tuple  # ("LINE", p1, p2) | ("ARC", center, r, start_deg, end_deg)

EPS = 1e-9


# ── .map 파싱 ────────────────────────────────────────────────────────────────

@dataclass
class MapLinkRec:
    id: str
    type: str
    start: str
    end: str
    length: float


@dataclass
class MapDoc:
    nodes: Dict[str, Pt] = field(default_factory=dict)
    node_types: Dict[str, str] = field(default_factory=dict)
    links: List[MapLinkRec] = field(default_factory=list)
    ports: List[Pt] = field(default_factory=list)
    header: Optional[str] = None


def load_map(path: str | Path) -> MapDoc:
    """`.map` 텍스트를 NODE/LINK/PORT 로 파싱. 필드 구분자는 '/'."""
    doc = MapDoc()
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line:
                continue
            if line.startswith("#"):
                if doc.header is None:
                    doc.header = line
                continue
            f_ = line.split("/")
            kind = f_[0]
            try:
                if kind == "NODE":
                    doc.nodes[f_[1]] = (float(f_[4]), float(f_[5]))
                    doc.node_types[f_[1]] = f_[2]
                elif kind == "LINK":
                    doc.links.append(MapLinkRec(f_[1], f_[2], f_[3], f_[4], float(f_[5])))
                elif kind == "PORT":
                    doc.ports.append((float(f_[4]), float(f_[5])))
            except (IndexError, ValueError):
                continue          # 형식이 어긋난 줄은 건너뛴다
    return doc


# ── 벡터 유틸 ────────────────────────────────────────────────────────────────

def _sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def _add(a: Pt, b: Pt) -> Pt:
    return (a[0] + b[0], a[1] + b[1])


def _mul(a: Pt, k: float) -> Pt:
    return (a[0] * k, a[1] * k)


def _norm(a: Pt) -> float:
    return math.hypot(a[0], a[1])


def _unit(a: Pt) -> Pt:
    n = _norm(a)
    return (0.0, 0.0) if n < EPS else (a[0] / n, a[1] / n)


def _dot(a: Pt, b: Pt) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Pt, b: Pt) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _perp_left(a: Pt) -> Pt:
    """진행방향 a 의 왼쪽 법선."""
    return (-a[1], a[0])


def _rot(a: Pt, rad: float) -> Pt:
    c, s = math.cos(rad), math.sin(rad)
    return (a[0] * c - a[1] * s, a[0] * s + a[1] * c)


def _deg(a: Pt) -> float:
    return math.degrees(math.atan2(a[1], a[0])) % 360.0


def _arc_prim(center: Pt, r: float, p_start: Pt, p_end: Pt) -> Primitive:
    """중심·양끝점으로 ARC 프리미티브. DXF ARC 는 CCW start→end 라 방향을 맞춘다.
    스윕이 180° 미만이라는 가정(그 이상은 호출 측에서 쪼개서 넘긴다)."""
    v0, v1 = _sub(p_start, center), _sub(p_end, center)
    if _cross(v0, v1) >= 0.0:                     # CCW
        return ("ARC", center, r, _deg(v0), _deg(v1))
    return ("ARC", center, r, _deg(v1), _deg(v0))  # CW → 뒤집어 기록


def _walk_arc(p: Pt, t: Pt, r: float, sweep: float, turn: int) -> Tuple[Pt, Pt, Pt]:
    """점 p 에서 접선 t 로 출발해 반지름 r, 스윕 sweep(rad) 만큼 turn(+1 좌/−1 우) 회전.
    반환: (중심, 끝점, 끝점 접선)"""
    n = _mul(_perp_left(t), float(turn))
    center = _add(p, _mul(n, r))
    ang = sweep * turn
    return center, _add(center, _rot(_sub(p, center), ang)), _rot(t, ang)


# ── 반지름 역산 ──────────────────────────────────────────────────────────────

def solve_radius(chord: float, arclen: float) -> Optional[float]:
    """`La = 2R·asin(c/2R)` 를 R 에 대해 이분법으로 푼다(스윕 <180° 가정)."""
    if chord <= EPS or arclen <= chord + 1e-6:
        return None
    lo, hi = chord / 2.0, chord * 1e4
    for _ in range(200):
        r = (lo + hi) / 2.0
        f = 2.0 * r * math.asin(min(1.0, chord / (2.0 * r)))
        if f > arclen:
            lo = r
        else:
            hi = r
    return (lo + hi) / 2.0


def _solve_n_full(u: float, w: float, arclen: float) -> Optional[Tuple[float, float, float]]:
    """N(호-대각-호)의 반지름까지 맵에서 직접 푼다 — 관측 3개(u, w, 호길이)로 미지수 3개(r, a, d).
        La = 2r·a + d
        u  = 2r·sin a + d·cos a
        w  = 2r(1−cos a) + d·sin a
    앞의 두 식에서 a 에 대해 r·d 를 소거하고, 세 번째 식의 잔차로 이분법.
    반환: (r, a, d)"""
    def rd(a: float) -> Optional[Tuple[float, float]]:
        ca, sa = math.cos(a), math.sin(a)
        den = 2.0 * sa - 2.0 * a * ca
        if abs(den) < 1e-12:
            return None
        r = (u - arclen * ca) / den
        if r <= 1e-6:
            return None
        d = arclen - 2.0 * r * a
        return r, d

    def resid(a: float) -> Optional[float]:
        got = rd(a)
        if got is None:
            return None
        r, d = got
        if d < -1.0:
            return None
        return 2.0 * r * (1.0 - math.cos(a)) + d * math.sin(a) - w

    N = 2000
    hi_a = math.pi / 2.0 - 1e-4
    prev_a, prev_f, bracket = None, None, None
    for i in range(N + 1):
        a = 1e-4 + (hi_a - 1e-4) * i / N
        f = resid(a)
        if f is None:
            prev_a, prev_f = None, None
            continue
        if abs(f) < 1e-9:
            bracket = (a, a)
            break
        if prev_f is not None and prev_f * f < 0:
            bracket = (prev_a, a)
            break
        prev_a, prev_f = a, f
    if bracket is None:
        return None
    lo, hi = bracket
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_lo, f_mid = resid(lo), resid(mid)
        if f_lo is None or f_mid is None:
            break
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo = mid
    a = (lo + hi) / 2.0
    got = rd(a)
    if got is None:
        return None
    r, d = got
    return r, a, max(0.0, d)


def _solve_n_sweep(u: float, w: float, r: float) -> Optional[Tuple[float, float]]:
    """N(호-대각-호): 종/횡 성분과 반지름으로 호 스윕각 a(rad)·대각 길이 d 를 구한다.
        u = 2r·sin a + d·cos a
        w = 2r(1−cos a) + d·sin a
    """
    def resid(a: float) -> Optional[float]:
        ca, sa = math.cos(a), math.sin(a)
        if ca < 1e-9:
            return None                      # a→90°: d 가 발산해 의미 없음
        d = (u - 2.0 * r * sa) / ca
        return 2.0 * r * (1.0 - ca) + d * sa - w

    # 부호가 바뀌는 구간을 격자로 먼저 찾는다.
    #  (상한을 90° 바로 앞에 두면 cos≈0 으로 발산해 브래킷이 깨지므로 격자 탐색이 안전하다)
    N = 2000
    hi_a = math.pi / 2.0 - 1e-4
    prev_a, prev_f = None, None
    bracket = None
    for i in range(N + 1):
        a = 1e-6 + (hi_a - 1e-6) * i / N
        f = resid(a)
        if f is None:
            break
        if abs(f) < 1e-9:
            prev_a, prev_f = a, f
            bracket = (a, a)
            break
        if prev_f is not None and prev_f * f < 0:
            bracket = (prev_a, a)
            break
        prev_a, prev_f = a, f
    if bracket is None:
        return None

    lo, hi = bracket
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_lo, f_mid = resid(lo), resid(mid)
        if f_lo is None or f_mid is None:
            break
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo = mid
    a = (lo + hi) / 2.0
    ca = math.cos(a)
    if ca < 1e-9:
        return None
    d = (u - 2.0 * r * math.sin(a)) / ca
    if d < -1.0:
        return None
    return a, max(0.0, d)


# ── 접선 추정 ────────────────────────────────────────────────────────────────

def _build_tangents(doc: MapDoc) -> Dict[str, Pt]:
    """노드별 '진행 접선' — U/N 의 돌출·횡단 방향을 정하는 데 필요하다.
    맵에는 없는 정보라 인접 **직선(S) 링크**에서 가져온다.
    들어오는 S 를 우선(진행방향과 같음), 없으면 나가는 S 를 쓴다(직선 통과 구간이면 동일)."""
    tan: Dict[str, Pt] = {}
    for lk in doc.links:
        if lk.type != "S":
            continue
        a, b = doc.nodes.get(lk.start), doc.nodes.get(lk.end)
        if a is None or b is None:
            continue
        d = _unit(_sub(b, a))
        if _norm(d) < EPS:
            continue
        tan.setdefault(lk.end, d)          # 들어오는 S: 끝 노드의 진행 접선
    for lk in doc.links:
        if lk.type != "S":
            continue
        a, b = doc.nodes.get(lk.start), doc.nodes.get(lk.end)
        if a is None or b is None:
            continue
        d = _unit(_sub(b, a))
        if _norm(d) < EPS:
            continue
        tan.setdefault(lk.start, d)        # 폴백: 나가는 S
    return tan


# ── 링크별 복원 ──────────────────────────────────────────────────────────────

def _rebuild_arc(p0: Pt, p1: Pt, arclen: float, ccw: bool,
                 r_std: float, r_tol: float) -> Tuple[List[Primitive], List[str]]:
    warn: List[str] = []
    chord = _norm(_sub(p1, p0))
    r = solve_radius(chord, arclen)
    if r is None:
        return [("LINE", p0, p1)], ["호 반지름 역산 실패 → 직선으로 대체"]
    if abs(r - r_std) <= r_tol:
        r = r_std                                    # 표준 반지름으로 정돈(길이 반올림 오차 흡수)
    else:
        warn.append(f"복원 반지름 {r:.1f} ≠ 설정 R {r_std:g} — 도면 기준을 확인하세요")
    theta = 2.0 * math.asin(min(1.0, chord / (2.0 * r)))
    if arclen > math.pi * r:                         # 열각(>180°)
        theta = 2.0 * math.pi - theta
    if theta >= math.pi - 1e-9:
        warn.append("스윕 180° 이상 — 두 조각으로 쪼갬")
    d_mid = r * math.cos(theta / 2.0)
    mid = _mul(_add(p0, p1), 0.5)
    n = _perp_left(_unit(_sub(p1, p0)))
    center = _add(mid, _mul(n, d_mid if ccw else -d_mid))
    if theta < math.pi - 1e-9:
        return [_arc_prim(center, r, p0, p1)], warn
    # 180° 이상은 중간점을 끼워 두 조각으로 (DXF 방향 판정이 모호해지는 것을 피한다)
    half = _add(center, _rot(_sub(p0, center), (theta / 2.0) * (1 if ccw else -1)))
    return [_arc_prim(center, r, p0, half), _arc_prim(center, r, half, p1)], warn


def _rebuild_u(p0: Pt, p1: Pt, arclen: float, t0: Optional[Pt],
               r_std: float, r_tol: float) -> Tuple[List[Primitive], List[str]]:
    warn: List[str] = []
    chord = _norm(_sub(p1, p0))
    if chord < EPS:
        return [], ["U 링크 양끝이 같은 점"]
    r = (arclen - chord) / (math.pi - 2.0)
    if abs(r - r_std) <= r_tol:
        r = r_std
    elif r > EPS:
        warn.append(f"복원 반지름 {r:.1f} ≠ 설정 R {r_std:g} — 도면 기준을 확인하세요")
    mid_len = chord - 2.0 * r
    if r <= EPS or mid_len < -r_tol:
        warn.append(f"U 분해 실패(r={r:.1f}, mid={mid_len:.1f}) → 호 하나로 대체")
        prims, w2 = _rebuild_arc(p0, p1, arclen, True, r_std, r_tol)
        return prims, warn + w2
    mid_len = max(0.0, mid_len)
    v = _unit(_sub(p1, p0))
    if t0 is None:
        t0 = _perp_left(v)                           # 이웃 직선이 없을 때: 임의로 왼쪽 돌출
        warn.append("시작 접선 없음 — 돌출 방향을 왼쪽으로 가정")
    t = _unit(_sub(t0, _mul(v, _dot(t0, v))))        # 현에 수직한 성분만 남긴다
    if _norm(t) < EPS:
        t = _perp_left(v)
        warn.append("접선이 현과 평행 — 돌출 방향을 왼쪽으로 가정")
    c1 = _add(p0, _mul(v, r))
    a1 = _add(c1, _mul(t, r))
    c2 = _sub(p1, _mul(v, r))
    a2 = _add(c2, _mul(t, r))
    prims: List[Primitive] = [_arc_prim(c1, r, p0, a1)]
    if mid_len > 1e-6:
        prims.append(("LINE", a1, a2))
    prims.append(_arc_prim(c2, r, a2, p1))
    return prims, warn


def _rebuild_n(p0: Pt, p1: Pt, arclen: float, t0: Optional[Pt],
               r_std: float, r_tol: float) -> Tuple[List[Primitive], List[str]]:
    warn: List[str] = []
    v = _sub(p1, p0)
    if t0 is None:
        warn.append("시작 접선 없음 → 직선으로 대체")
        return [("LINE", p0, p1)], warn
    t0 = _unit(t0)
    u, w_signed = _dot(v, t0), _cross(t0, v)
    turn = 1 if w_signed >= 0 else -1

    # 1순위: 반지름까지 맵에서 직접 푼다(설정 R 에 의존하지 않음)
    r = r_std
    full = _solve_n_full(u, abs(w_signed), arclen)
    if full is not None:
        r, a, d = full
        if abs(r - r_std) <= r_tol:
            r = r_std                        # 표준값으로 정돈
            re_solved = _solve_n_sweep(u, abs(w_signed), r)
            if re_solved is not None:
                a, d = re_solved
        else:
            warn.append(f"복원 반지름 {r:.1f} ≠ 설정 R {r_std:g} — 도면 기준을 확인하세요")
    else:
        sol = _solve_n_sweep(u, abs(w_signed), r_std)
        if sol is None:
            warn.append("N 분해 실패 → 직선으로 대체")
            return [("LINE", p0, p1)], warn
        a, d = sol

    c1, q1, t1 = _walk_arc(p0, t0, r, a, turn)
    q2 = _add(q1, _mul(t1, d))
    c2, q3, _ = _walk_arc(q2, t1, r, a, -turn)
    err = _norm(_sub(q3, p1))
    if err > max(2.0, r_tol):
        warn.append(f"N 복원 오차 {err:.1f}mm")
    prims: List[Primitive] = [_arc_prim(c1, r, p0, q1)]
    if d > 1e-6:
        prims.append(("LINE", q1, q2))
    prims.append(_arc_prim(c2, r, q2, p1))
    return prims, warn


def primitive_length(p: Primitive) -> float:
    """프리미티브의 실제 경로 길이 (LINE=현, ARC=호 길이)."""
    if p[0] == "LINE":
        return _norm(_sub(p[2], p[1]))
    _, _c, r, a0, a1 = p
    return math.radians((a1 - a0) % 360.0) * r


def reconstruct(doc: MapDoc, radius_mm: float = 480.0,
                radius_tol_mm: float = 5.0) -> Tuple[List[Primitive], List[str]]:
    """MAP 링크 전체를 LINE/ARC 프리미티브 목록으로 복원. (프리미티브, 경고문) 반환.

    복원 결과의 경로 길이를 MAP 에 적힌 길이와 대조해, 어긋나면 경고를 남긴다.
    (설정 R 이 도면 R 과 다르면 N 은 끝점을 맞추면서 길이가 틀어지는데 — 그걸 잡는다)
    """
    tan = _build_tangents(doc)
    prims: List[Primitive] = []
    warns: List[str] = []
    for lk in doc.links:
        p0, p1 = doc.nodes.get(lk.start), doc.nodes.get(lk.end)
        if p0 is None or p1 is None:
            warns.append(f"링크 {lk.id}: 노드 {lk.start}/{lk.end} 없음 — 건너뜀")
            continue
        t0 = tan.get(lk.start)
        if lk.type == "S":
            out, w = [("LINE", p0, p1)], []
        elif lk.type in ("L", "R"):
            out, w = _rebuild_arc(p0, p1, lk.length, lk.type == "L", radius_mm, radius_tol_mm)
        elif lk.type == "U":
            out, w = _rebuild_u(p0, p1, lk.length, t0, radius_mm, radius_tol_mm)
        elif lk.type == "N":
            out, w = _rebuild_n(p0, p1, lk.length, t0, radius_mm, radius_tol_mm)
        else:
            out, w = [("LINE", p0, p1)], [f"미지 타입 {lk.type} → 직선"]
        # 길이 대조 — 복원 형상이 맵에 적힌 길이와 맞는지
        got = sum(primitive_length(p) for p in out)
        lim = max(2.0, lk.length * 0.005)
        if out and abs(got - lk.length) > lim:
            w = list(w) + [f"길이 불일치: 복원 {got:.1f} vs 맵 {lk.length:.1f} "
                           f"(설정 R={radius_mm:g} 이 도면과 다를 수 있음)"]
        prims.extend(out)
        warns.extend(f"링크 {lk.id}({lk.type}): {m}" for m in w)
    return prims, warns


# ── DXF 출력 ─────────────────────────────────────────────────────────────────

def primitives_to_dxf(prims: List[Primitive], out_path: str | Path, *,
                      layer: str = "RAIL", ports: Optional[List[Pt]] = None,
                      port_layer: str = "RAIL_PORT", port_marker_r: float = 100.0) -> None:
    import ezdxf
    doc = ezdxf.new("R2010")
    for name in (layer, port_layer):
        if name not in doc.layers:
            doc.layers.add(name)
    msp = doc.modelspace()
    for p in prims:
        if p[0] == "LINE":
            msp.add_line(p[1], p[2], dxfattribs={"layer": layer})
        elif p[0] == "ARC":
            _, c, r, a0, a1 = p
            msp.add_arc(c, r, a0, a1, dxfattribs={"layer": layer})
    for pt in (ports or []):
        msp.add_circle(pt, port_marker_r, dxfattribs={"layer": port_layer})
    # 공장 좌표계는 x 70만·y 430만 대라 원점에서 아주 멀다. 뷰를 맞춰 저장하지 않으면
    # CAD 가 원점 근처를 비춰 **빈 화면으로 열린다**.
    # (헤더 $EXTMIN/$EXTMAX 는 ezdxf 가 저장할 때 항상 미설정값으로 되돌리므로 손대지 않는다.
    #  ZOOM EXTENTS 는 CAD 가 도형에서 다시 계산하니 문제되지 않는다.)
    try:
        import ezdxf.zoom
        ezdxf.zoom.extents(msp, factor=1.05)
    except Exception:
        pass
    # 격자·단위: ezdxf 새 문서는 활성 뷰포트의 격자가 꺼져 있고($INSUNITS 도 m=6) → CAD 에서 열면 격자가 안 보인다.
    #  원본 도면과 같게 격자 켬 + 좌표가 mm 이므로 단위 mm(4). 간격은 공장 규모(수십 m)에 맞춰 1000mm.
    try:
        doc.header["$INSUNITS"] = 4          # ($GRIDMODE/$GRIDUNIT 는 헤더 변수가 아님 — 격자는 VPORT 속성)
        for vp in doc.viewports.get_config("*Active"):
            vp.dxf.grid_on = 1
            vp.dxf.grid_spacing = (1000.0, 1000.0)
    except Exception:
        pass
    doc.saveas(str(out_path))


def map_to_dxf(map_path: str | Path, dxf_path: str | Path | None = None, *,
               radius_mm: float = 480.0, radius_tol_mm: float = 5.0,
               layer: str = "RAIL", draw_ports: bool = True,
               log: Callable[[str], None] = print) -> dict:
    """`.map` → 레일 센터선 DXF. 산출 경로와 통계를 dict 로 반환.

    `draw_ports=True` 면 PORT 레코드 위치마다 반지름 100 원을 `RAIL_PORT` 레이어에 그린다.
    레일 위에 동그라미로 보이므로, 필요 없으면 False 로 두거나 CAD 에서 그 레이어를 끄면 된다.
    """
    map_path = Path(map_path)
    if dxf_path is None:
        dxf_path = map_path.with_name(map_path.stem + "_fromMap.dxf")
    dxf_path = Path(dxf_path)

    doc = load_map(map_path)
    log(f"MAP 읽음: NODE {len(doc.nodes)}개, LINK {len(doc.links)}개, PORT {len(doc.ports)}개")
    if not doc.links:
        raise ValueError("LINK 레코드가 없습니다 — .map 파일이 맞는지 확인해주세요.")
    if map_path.name and not map_path.name.startswith("ori_"):
        log("[주의] 최종 맵은 대기(clearance) 노드가 호 끝을 밀어놓아 반지름 복원이 어긋납니다. "
            "ori_*.map 을 쓰는 것을 권합니다.")

    prims, warns = reconstruct(doc, radius_mm=radius_mm, radius_tol_mm=radius_tol_mm)
    n_line = sum(1 for p in prims if p[0] == "LINE")
    n_arc = len(prims) - n_line
    marks = doc.ports if draw_ports else []
    primitives_to_dxf(prims, dxf_path, layer=layer, ports=marks)

    for m in warns[:20]:
        log("  " + m)
    if len(warns) > 20:
        log(f"  ... 경고 {len(warns) - 20}건 더")
    log(f"DXF 저장: {dxf_path}  (LINE {n_line}개, ARC {n_arc}개, R={radius_mm:g})")
    if doc.ports:
        log(f"  포트 마커 {len(marks)}개"
            + (" → 레이어 RAIL_PORT 에 원(r=100)으로 표시" if marks
               else f" 생략 (PORT {len(doc.ports)}개는 그리지 않음)"))
    return {"dxf": str(dxf_path), "lines": n_line, "arcs": n_arc,
            "nodes": len(doc.nodes), "links": len(doc.links),
            "ports": len(marks), "warnings": warns}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="MAP → CAD (레일 센터선 DXF) 역변환")
    ap.add_argument("map_path")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("-r", "--radius", type=float, default=480.0)
    ap.add_argument("--no-ports", action="store_true",
                    help="PORT 위치의 원 마커를 그리지 않는다")
    a = ap.parse_args()
    map_to_dxf(a.map_path, a.out, radius_mm=a.radius, draw_ports=not a.no_ports)
