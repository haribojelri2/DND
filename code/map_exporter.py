from __future__ import annotations
from core import *
# -*- coding: utf-8 -*-
"""
OHT/레일 맵 파일(.map) — NODE / LINK 한 줄 포맷 (기존 out.map 호환)

---------------------------------------------------------------------------
Basic Config (속성·리스트 구분자)
---------------------------------------------------------------------------
- **속성 구분자:** `/` — 한 줄에서 상위 필드(속성)를 나눈다.
- **Param(속성 블록) 안의 리스트 구분자:** `|` — Param은 하나의 속성으로 두고,
  그 안의 항목들만 `|` 로 구분한다. (NODE의 Disabled/Yield, LINK 끝의 CarrierType 등)

예시 (스펙 문서):
  LINK/100196/S/000106/000107/805///1000/3/5/F300_1||||
  → Length 뒤 `///` 는 Steer/Slope/Speed 빈칸, 이어서 수치·CPS 등 `/` 로 구분,
  → `F300_1||||` 처럼 마지막 구간에 `|` 가 섞이면 Param 리스트로 해석.

파싱 시: **먼저 `/` 로 split** 한 뒤, Param 전용 필드는 **필요하면 `|` 로 재분리**한다.

---------------------------------------------------------------------------
필드 의미 (NODE / LINK 정의표)
---------------------------------------------------------------------------
NODE
  ID(6자리), Type(G/T/L), Reality(R/V), X, Y(mm),
  ParentLinkID, RelativeDistance, LayerID(0~9), PIODeviceID, LiftTagID, ZoneID,
  Param: Disabled, YieldEnabled (기존 out.map 은 `/|/값/` 형태)

LINK
  ID, Type(S/L/R/U/N), StartNodeID, EndNodeID, Length,
  Steer(L/R/N/빈칸), Slope(U/D/빈칸), Speed,
  VehicleDetect(0~31), GeneralDetect(0~31), CPS1, CPS2,
  Param: CarrierType, GroupID, Disabled, Penalty, YieldDisabled, ReleaseDistance

Link.Type: S 직선, L 좌곡, R 우곡, U 180° 곡선, N N-way 분기
"""


import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Basic Config — 스프레드시트 "Basic Config" 와 동일
ATTR_SEP = "/"  # 속성(필드) 구분


# ---------------------------------------------------------------------------
# NODE
# ---------------------------------------------------------------------------


@dataclass
class MapNode:
    """out.map 한 줄: | 앞에 필드 5개 (ParentLinkID ~ PIODeviceID 전까지 구간에 LayerID 등 배치)."""

    id: str
    type: str  # G / T / L
    reality: str  # R / V
    x: Union[int, float, str]
    y: Union[int, float, str]
    parent_link_id: str = ""
    relative_distance: str = ""
    reserved: str = ""  # T 전용 등 스펙 여분 슬롯 (기존 파일은 빈칸)
    layer_id: str = "0"
    pio_device_id: str = ""
    param_disabled: str = ""
    param_yield_enabled: str = "0"


def format_node_line(n: MapNode) -> str:
    """out.map 1행과 동일: NODE/.../Y/parent/rel/res/layer/pio/|dis/yld/"""
    return (
        f"NODE/{n.id}/{n.type}/{n.reality}/{n.x}/{n.y}/"
        f"{n.parent_link_id}/{n.relative_distance}/{n.reserved}/{n.layer_id}/{n.pio_device_id}/|{n.param_disabled}/{n.param_yield_enabled}/"
    )


def parse_node_line(line: str) -> Optional[MapNode]:
    line = line.strip()
    if not line.startswith("NODE/"):
        return None
    parts = line.split("/")
    # ... pio, |, yield, trailing ''  → len 14
    if len(parts) < 14:
        return None
    if parts[11] != "|":
        return None
    # |/0/ 형태면 Disabled는 빈칸, Yield가 parts[12]
    return MapNode(
        id=parts[1],
        type=parts[2],
        reality=parts[3],
        x=parts[4],
        y=parts[5],
        parent_link_id=parts[6],
        relative_distance=parts[7],
        reserved=parts[8],
        layer_id=parts[9],
        pio_device_id=parts[10],
        param_disabled="",
        param_yield_enabled=parts[12] if len(parts) > 12 else "0",
    )


# ---------------------------------------------------------------------------
# LINK
# ---------------------------------------------------------------------------


@dataclass
class MapLink:
    id: str
    type: str  # S / L / R / U / N
    start_node_id: str
    end_node_id: str
    length: Union[int, str]
    steer: str = ""
    slope: str = ""
    speed: str = ""
    # CPS/검지 등은 기존 파일이 한 필드에 | 로 묶어 둠
    pipe_tail: str = "|||||1|0|0"  # out.map 기본값 (파서로 역추적한 문자열)
    param_a: str = "0"
    param_b: str = "0"


def _link_steer_slope_speed_pipe(steer: str, slope: str, speed: str, pipe_tail: str) -> str:
    """out.map 규칙: speed 가 비어 있으면 steer/slope/pipe 만 세 구간(6190///|||||1|0|0 — 길이 뒤 슬래시 3개)."""
    if speed == "":
        return ATTR_SEP.join([steer, slope, pipe_tail])
    return ATTR_SEP.join([steer, slope, speed, pipe_tail])


def format_link_line(l: MapLink) -> str:
    """LINK 한 줄: `/` 로 속성 연결. pipe_tail 에 `|` 가 들어갈 수 있음(Basic Config)."""
    mid = _link_steer_slope_speed_pipe(l.steer, l.slope, l.speed, l.pipe_tail)
    base = (
        f"LINK/{l.id}/{l.type}/{l.start_node_id}/{l.end_node_id}/{l.length}/{mid}/{l.param_a}"
    )
    if l.param_b:
        return base + f"/{l.param_b}/"
    return base + "/"


# ---------------------------------------------------------------------------
# 파일 입출력
# ---------------------------------------------------------------------------


def save_map(
    path: str,
    nodes: List[MapNode],
    links: List[MapLink],
    header: Optional[str] = None,
    ports: Optional[List[Any]] = None,
) -> None:
    lines: List[str] = []
    if header:
        lines.append(header.rstrip() + "\n")
    for n in nodes:
        lines.append(format_node_line(n) + "\n")
    for lk in links:
        lines.append(format_link_line(lk) + "\n")
    if ports:
        # 순환참조 방지를 위해 로컬 import
        from port_extractor import format_port_line
        for p in ports:
            lines.append(format_port_line(p) + "\n")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)






def minor_arc_sweep_deg(start_deg: float, end_deg: float) -> float:
    """호의 작은 쪽 중심각(도)."""
    ccw = (end_deg - start_deg) % 360.0
    return min(ccw, 360.0 - ccw)














def arc_link_type_from_arcseg(d: Any) -> str:
    """
    ArcSeg 기반으로 .map 링크 타입 결정.
    CAD에서 실제로 그려진(중간점 포함) 방향과 동일하게 L/R를 결정한다.
    """
    r = float(getattr(d, "r", 0.0) or 0.0)
    if r < 1e-12:
        return "S"
    cx = float(d.cx)
    cy = float(d.cy)
    ps = getattr(d, "p_start", None)
    pe = getattr(d, "p_end", None)
    if ps is None or pe is None:
        # fallback: 각도차로 결정(기존 동작)
        diff = float(d.end_deg) - float(d.start_deg)
        while diff > 180:
            diff -= 360
        while diff < -180:
            diff += 360
        if abs(diff) < 1e-6:
            return "S"
        return "L" if diff > 0 else "R"

    sx, sy = float(ps[0]), float(ps[1])
    ex, ey = float(pe[0]), float(pe[1])
    vx, vy = ex - sx, ey - sy
    if math.hypot(vx, vy) < 1e-9:
        return "S"

    # L/R is a property of the current link direction. Trust the actual CAD
    # geometry first: whichever side the arc center is on from start->end.
    center_side = vx * (cy - sy) - vy * (cx - sx)
    side_eps = max(1e-6, math.hypot(vx, vy) * max(abs(r), 1.0) * 1e-9)
    if abs(center_side) > side_eps:
        return "L" if center_side > 0 else "R"

    ts = math.degrees(math.atan2(sy - cy, sx - cx)) % 360.0
    te = math.degrees(math.atan2(ey - cy, ex - cx)) % 360.0
    L1 = ccw_delta_deg(ts, te)
    L2 = 360.0 - L1
    if min(L1, L2) < 1e-6:
        return "S"
    pm = arc_curve_midpoint(d, cx, cy, r)
    use_ccw = arc_should_use_ccw_sweep(ts, te, ccw_delta_deg(ts, te), 360.0 - ccw_delta_deg(ts, te), cx, cy, r, pm)
    return "L" if use_ccw else "R"


def arc_minor_sweep_deg_edge(edge: Any) -> float:
    """ARC 엣지의 작은 쪽 스윕 각도(도). LINE 등은 0."""
    if getattr(edge, "edge_type", None) != "ARC":
        return 0.0
    d = edge._data
    return minor_arc_sweep_deg(float(d.start_deg), float(d.end_deg))


def edge_path_length_mm(edge: Any) -> float:
    """asd.ipynb Edge: LINE은 직선 거리, ARC는 r * 라디안(작은 호).

    clearance 단계에서 호 끝점이 인접 직선(접선) 방향으로 밀려 **원 밖(off-circle)** 으로
    나간 경우, 단순 r·각도는 끝점 위치와 어긋난다(각도가 부풀어 길이가 왜곡; 심하면
    경로<현이 되어 불가능). 이때는 실제 경로 = 접선직선(start쪽) + 참호(r·turn) + 접선직선(end쪽)
    으로 보정한다. 끝점이 원 위(on-circle)면 기존 식 그대로라 ori(이격 전) 출력은 불변.
    """
    et = getattr(edge, "edge_type", None)
    if et == "LINE":
        return dist(edge.start, edge.end)
    if et == "ARC":
        d = edge._data
        r = float(d.r)
        if r < 1e-12:
            return 0.0
        cx, cy = float(d.cx), float(d.cy)
        s = edge.start
        e = edge.end
        d1 = math.hypot(float(s[0]) - cx, float(s[1]) - cy)
        d2 = math.hypot(float(e[0]) - cx, float(e[1]) - cy)
        on_circle_eps = 2.0  # mm
        if abs(d1 - r) <= on_circle_eps and abs(d2 - r) <= on_circle_eps:
            # 끝점이 원 위 → 기존 동작 그대로 (ori 출력 불변)
            th = math.radians(minor_arc_sweep_deg(float(d.start_deg), float(d.end_deg)))
            return r * th
        # off-circle: 접선직선 + 참호 + 접선직선
        tin = math.sqrt(max(0.0, d1 * d1 - r * r))
        tout = math.sqrt(max(0.0, d2 * d2 - r * r))
        sa = math.degrees(math.atan2(float(s[1]) - cy, float(s[0]) - cx))
        ea = math.degrees(math.atan2(float(e[1]) - cy, float(e[0]) - cx))
        # 회전방향(L=CCW / R=CW): 끝점이 원 밖이라 끝점 기반 판정(arc_link_type)은 뒤집힐 수 있으므로
        # corruption 에 영향받지 않는 출처를 우선한다 — ① clearance 전 기록한 _rot_link_type,
        # ② forced_link_type, ③ 호 중점 p_mid_curve, ④ (최후) 끝점 기반.
        lt = getattr(edge, "_rot_link_type", None) or getattr(edge, "forced_link_type", None)
        if lt not in ("L", "R"):
            pm = getattr(d, "p_mid_curve", None)
            if pm is not None:
                ma = math.degrees(math.atan2(float(pm[1]) - cy, float(pm[0]) - cx))
                lt = "L" if ((ma - sa) % 360.0) <= ((ea - sa) % 360.0) else "R"
            else:
                lt = arc_link_type_from_arcseg(d)
        if lt == "L":   # CCW
            directed = (ea - sa) % 360.0
        else:           # R / CW
            directed = (sa - ea) % 360.0
        phi1 = math.degrees(math.acos(max(-1.0, min(1.0, r / d1)))) if d1 > 1e-9 else 0.0
        phi2 = math.degrees(math.acos(max(-1.0, min(1.0, r / d2)))) if d2 > 1e-9 else 0.0
        true_sweep = directed - phi1 - phi2
        if true_sweep < 0.0:
            true_sweep = 0.0
        return tin + r * math.radians(true_sweep) + tout
    return 0.0


def edge_link_type(edge: Any) -> str:
    """LINE→S, ARC→L(반시계 스윕)/R(시계). U/N 병합 링크는 export 단계에서 별도 부여."""
    forced = getattr(edge, "forced_link_type", None)
    if forced is not None:
        return forced
    et = getattr(edge, "edge_type", None)
    if et != "ARC":
        return "S"
    d = edge._data
    return arc_link_type_from_arcseg(d)


def get_rotation_direction(start_angle: float, end_angle: float) -> str:
    """asd.ipynb get_rotation_direction 과 동일 (도 단위)."""
    diff = float(end_angle) - float(start_angle)
    if diff < -180:
        diff += 360
    elif diff > 180:
        diff -= 360
    if diff > 0:
        return "CCW (반시계)"
    if diff < 0:
        return "CW (시계)"
    return "직선/알수없음"


def arc_sweep_direction(edge: Any, enter_at_start: bool = True) -> str:
    if getattr(edge, "edge_type", None) != "ARC":
        return "직선/알수없음"
    d = edge._data
    if enter_at_start:
        return get_rotation_direction(d.start_deg, d.end_deg)
    return get_rotation_direction(d.end_deg, d.start_deg)


def find_next_edge(
    current_end_pt: Tuple[float, float],
    edges: List[Any],
    tol: float,
    exclude: Optional[List[int]] = None,
    *,
    prefer_arc: bool = False,
) -> Tuple[Optional[int], Any, Optional[bool]]:
    """
    같은 접점에 LINE 과 ARC 가 모두 있으면, U/N 병합에서는 prefer_arc=True 로
    ARC 를 우선(리스트 앞쪽 직선만 잡히는 문제 완화).
    """
    ex = set() if exclude is None else set(exclude)
    candidates: List[Tuple[int, Any, bool]] = []
    for j, e in enumerate(edges):
        if j in ex:
            continue
        if dist(e.start, current_end_pt) <= tol:
            candidates.append((j, e, False))
        elif dist(e.end, current_end_pt) <= tol:
            candidates.append((j, e, True))
    if not candidates:
        return None, None, None
    if prefer_arc:
        candidates.sort(
            key=lambda t: (0 if getattr(t[1], "edge_type", None) == "ARC" else 1, t[0])
        )
    j, e, fl = candidates[0]
    return j, e, fl


def line_length(edge: Any) -> float:
    if getattr(edge, "edge_type", None) != "LINE":
        return float("inf")
    return dist(edge.start, edge.end)


def line_sufficiently_diagonal(edge: Any, *, min_deg_from_axis: float = 5.0) -> bool:
    """
    N분기(호-직-호)에서 중간 직선이 '대각선'인지: 수평·수직(0°, 90°)에 너무 가깝지 않음.

    min_deg_from_axis: 축(0/90/180°)에서 떨어져야 하는 최소 각(도). 0이면 검사 생략과 동일.
    """
    if getattr(edge, "edge_type", None) != "LINE":
        return False
    mda = float(min_deg_from_axis)
    if mda <= 0:
        return True
    dx = float(edge.end[0]) - float(edge.start[0])
    dy = float(edge.end[1]) - float(edge.start[1])
    if abs(dx) + abs(dy) < 1e-12:
        return False
    theta = math.degrees(math.atan2(dy, dx)) % 180.0
    m = theta % 90.0
    dist_axis = min(m, 90.0 - m)
    return dist_axis >= mda


def other_endpoint(edge: Any, junction_pt: Tuple[float, float], tol: float) -> Optional[Tuple[float, float]]:
    if dist(edge.start, junction_pt) <= tol:
        return edge.end
    if dist(edge.end, junction_pt) <= tol:
        return edge.start
    return None


def arc_path_turn_sign(edge: Any, forward: bool) -> int:
    """
    경로 기준 arc의 좌/우 회전 판단
    +1: 좌회전(CCW)
    -1: 우회전(CW)
    0: 판별 불가
    """
    if getattr(edge, "edge_type", None) != "ARC":
        return 0

    d = edge._data

    if forward:
        ax, ay = float(edge.start[0]), float(edge.start[1])
        bx, by = float(edge.end[0]), float(edge.end[1])
        sa, ea = float(d.start_deg), float(d.end_deg)
    else:
        ax, ay = float(edge.end[0]), float(edge.end[1])
        bx, by = float(edge.start[0]), float(edge.start[1])
        sa, ea = float(d.end_deg), float(d.start_deg)

    cx, cy = float(d.cx), float(d.cy)
    r = float(getattr(d, "r", 0.0) or 0.0)
    if r > 1e-12:
        ts = math.degrees(math.atan2(ay - cy, ax - cx)) % 360.0
        te = math.degrees(math.atan2(by - cy, bx - cx)) % 360.0
        if min(ccw_delta_deg(ts, te), 360.0 - ccw_delta_deg(ts, te)) >= 1e-6:
            pm = arc_curve_midpoint(d, cx, cy, r)
            return 1 if arc_should_use_ccw_sweep(ts, te, ccw_delta_deg(ts, te), 360.0 - ccw_delta_deg(ts, te), cx, cy, r, pm) else -1

    diff = ea - sa
    while diff > 180:
        diff -= 360
    while diff < -180:
        diff += 360

    if abs(abs(diff) - 180.0) < 1e-6:
        return 1 if diff > 0 else -1

    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    if abs(cross) < 1e-9:
        return 1 if diff > 0 else -1

    return 1 if cross > 0 else -1


def un_branch_type_from_arcs(
    first: Any,
    second: Any,
    second_forward: bool,
) -> str:
    t1 = arc_path_turn_sign(first, True)
    t2 = arc_path_turn_sign(second, second_forward)

    if t1 != 0 and t2 != 0:
        return "N" if t1 != t2 else "U"

    d1 = first._data
    d2 = second._data

    diff1 = float(d1.end_deg) - float(d1.start_deg)
    if second_forward:
        diff2 = float(d2.end_deg) - float(d2.start_deg)
    else:
        diff2 = float(d2.start_deg) - float(d2.end_deg)

    return "N" if (diff1 * diff2 < 0) else "U"


def arc_radius(edge: Any) -> float:
    """ARC 엣지의 반지름(도면 단위). LINE 등은 0."""
    if getattr(edge, "edge_type", None) != "ARC":
        return 0.0
    return float(getattr(edge._data, "r", 0.0))


def u_branch_u_metric_mm(
    arc_a: Any,
    arc_b: Any,
    scale_to_mm: float,
    line_edge: Optional[Any] = None,
) -> float:
    """
    U분기 수치 검증용(mm, scale_to_mm 반영):
    - 호-호: 두 호 반지름 합
    - 호-직-호: 두 호 반지름 합 + 중간 직선 길이
    """
    r_sum = arc_radius(arc_a) + arc_radius(arc_b)
    extra = 0.0
    if line_edge is not None and getattr(line_edge, "edge_type", None) == "LINE":
        extra = line_length(line_edge)
    return (r_sum + extra) * float(scale_to_mm)


def line_edge_indices_at_point(
    pt: Tuple[float, float],
    edges: List[Any],
    tol: float,
    exclude: Optional[set[int]] = None,
) -> List[int]:
    """접점 pt에 연결된 LINE 엣지 인덱스."""
    ex = exclude or set()
    out: List[int] = []
    for idx, e in enumerate(edges):
        if idx in ex:
            continue
        if getattr(e, "edge_type", None) != "LINE":
            continue
        if dist(e.start, pt) <= tol or dist(e.end, pt) <= tol:
            out.append(idx)
    return out


def arc_line_arc_line_junction_centers(arc: Any, tol: float) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    직-호-직 판별용 호의 양 끝 접점.
    Edge.start/end만 쓰면 ArcSeg.p_start·p_end와 수 mm 어긋날 때 한쪽만 LINE이 잡히는 경우가 있어,
    네 점을 tol 버킷으로 묶은 뒤 서로 가장 먼 두 접점을 쓴다.
    """
    if getattr(arc, "edge_type", None) != "ARC":
        return None
    pts: List[Tuple[float, float]] = [
        (float(arc.start[0]), float(arc.start[1])),
        (float(arc.end[0]), float(arc.end[1])),
    ]
    d = getattr(arc, "_data", None)
    if d is not None:
        ps = getattr(d, "p_start", None)
        pe = getattr(d, "p_end", None)
        if ps is not None:
            pts.append((float(ps[0]), float(ps[1])))
        if pe is not None:
            pts.append((float(pe[0]), float(pe[1])))
    buckets: Dict[Tuple[float, float], List[Tuple[float, float]]] = {}
    for p in pts:
        k = coord_key(p, tol)
        buckets.setdefault(k, []).append(p)
    centers: List[Tuple[float, float]] = []
    for group in buckets.values():
        sx = sum(x for x, _ in group) / len(group)
        sy = sum(y for _, y in group) / len(group)
        centers.append((sx, sy))
    if len(centers) < 2:
        return None
    if len(centers) == 2:
        return (centers[0], centers[1])
    best_i, best_j = 0, 1
    best_d = -1.0
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            dd = dist(centers[i], centers[j])
            if dd > best_d:
                best_d = dd
                best_i, best_j = i, j
    return (centers[best_i], centers[best_j])


def arc_line_arc_line_u_ok(
    arc: Any,
    *,
    scale_to_mm: float,
    radius_target_mm: float,
    tol_mm: float,
    abs_sa_ea_tol_deg: float,
) -> bool:
    """
    직-호-직 U 판별: 가운데 호 반지름(mm)≈radius_target, 스윕각(작은 호)≈180.

    NOTE: DXF 각도는 0~360 wrap이 있고 start/end를 단순 abs 차로 보면 오판정이 날 수 있어
    `minor_arc_sweep_deg` 기반으로 180° 근접을 검사한다.
    """
    if getattr(arc, "edge_type", None) != "ARC":
        return False
    d = arc._data
    # asd.ipynb 파이프라인에서 glue/snap으로 p_start/p_end가 약간 움직이면
    # start_deg/end_deg가 깨질 수 있어, 원본 각도 스냅샷(dxf_*)이 있으면 우선 사용
    sa_raw = getattr(d, "dxf_start_deg", None)
    ea_raw = getattr(d, "dxf_end_deg", None)
    if sa_raw is None:
        sa_raw = getattr(d, "start_deg")
    if ea_raw is None:
        ea_raw = getattr(d, "end_deg")
    sa = float(sa_raw)
    ea = float(ea_raw)
    sweep = minor_arc_sweep_deg(sa, ea)
    if abs(float(sweep) - 180.0) > float(abs_sa_ea_tol_deg):
        return False
    r_mm = arc_radius(arc) * float(scale_to_mm)
    return abs(r_mm - float(radius_target_mm)) <= float(tol_mm)


def find_line_arc_line_u_branch_groups(
    edges: List[Any],
    tol: float,
    *,
    scale_to_mm: float = 1.0,
    radius_target_mm: float = 450.0,
    radius_tol_mm: float = 5.0,
    abs_sa_ea_tol_deg: float = 5.0,
) -> List[Tuple[Tuple[int, int, int], str]]:
    """
    직선 → 호 → 직선(가운데 호 하나) 구간을 **U분기로 판단**할 때 사용.

    조건: 호 양끝에 LINE이 붙고, 반지름(mm)≈`radius_target_mm`±`radius_tol_mm`,
    `abs(sa-ea)`≈180°(`abs_sa_ea_tol_deg`).

    `find_un_branch_merge_groups`에는 넣지 않음. `.map` U는 `emit_line_arc_line_u_links` 참고.

    접점은 `arc_line_arc_line_junction_centers`로 잡아 Edge·p_start/p_end 불일치로 한쪽만 인식되던 경우를 줄인다.
    """
    out: List[Tuple[Tuple[int, int, int], str]] = []
    for j_arc, mid_arc in enumerate(edges):
        if getattr(mid_arc, "edge_type", None) != "ARC":
            continue
        junc_pair = arc_line_arc_line_junction_centers(mid_arc, tol)
        if junc_pair is None:
            continue
        j0, j1 = junc_pair
        idxs_s = line_edge_indices_at_point(j0, edges, tol, exclude={j_arc})
        idxs_e = line_edge_indices_at_point(j1, edges, tol, exclude={j_arc})
        if not idxs_s or not idxs_e:
            continue
        if not arc_line_arc_line_u_ok(
            mid_arc,
            scale_to_mm=scale_to_mm,
            radius_target_mm=radius_target_mm,
            tol_mm=radius_tol_mm,
            abs_sa_ea_tol_deg=abs_sa_ea_tol_deg,
        ):
            continue
        for i_line_s in idxs_s:
            for i_line_e in idxs_e:
                if i_line_s == i_line_e:
                    continue
                out.append(((i_line_s, j_arc, i_line_e), "U"))
    return out


def line_arc_line_u_edge_indices_for_export(
    edges: List[Any],
    tol: float,
    *,
    scale_to_mm: float,
    radius_target_mm: float,
    radius_tol_mm: float,
    abs_sa_ea_tol_deg: float,
    exclude_edge_indices: set[int],
) -> set[int]:
    """
    직-호-직 U 조건을 만족하는 **가운데 호(ARC) 엣지 인덱스**.
    내보낼 때 **가운데 호만** Type U로 마킹한다. (양쪽 직선은 S 유지)
    """
    raw = find_line_arc_line_u_branch_groups(
        edges,
        tol,
        scale_to_mm=scale_to_mm,
        radius_target_mm=radius_target_mm,
        radius_tol_mm=radius_tol_mm,
        abs_sa_ea_tol_deg=abs_sa_ea_tol_deg,
    )
    seen_arc: set[int] = set()
    out: set[int] = set()
    for triple, _ in raw:
        a, b, c = triple[0], triple[1], triple[2]
        if b in seen_arc:
            continue
        if a in exclude_edge_indices or b in exclude_edge_indices or c in exclude_edge_indices:
            continue
        seen_arc.add(b)
        out.add(b)
    return out


def find_un_branch_merge_groups(
    edges: List[Any],
    tol: float,
    short_straight_threshold: float,
    *,
    n_branch_min_arc_sweep_deg: float = 90.0,
    n_branch_diagonal_axis_tol_deg: float = 5.0,
    u_branch_arc_sum_target_mm: float = 4000.0,
    u_x_threshold_mm: Optional[float] = None,
    scale_to_mm: float = 1.0,
) -> List[Tuple[Tuple[int, ...], str]]:
    """
    U/N 패턴에 해당하는 엣지 구간을 하나의 링크로 합칠 때 사용.

    `u_x_threshold_mm`이 주어지면 U는 추가로 끝점 X폭
    (dist(first_arc.start, last_arc.end)*scale_to_mm)이 임계값 미만일 때만 인정.
    (최종 맵의 X 기준과 동일하게 ori 맵을 맞추기 위한 게이트)

    - Option 1: 호 → 호 → (i, j)
      - **U**: 두 평행 직선 사이 rail 폭이 `u_branch_arc_sum_target_mm` 미만(scale_to_mm 반영).
    - Option 2: 호 → 직선 → 호 (호-직-호, 호 두 개) → (i, line_j, arc_k)
      - **U**: r1+r2+중간 직선 길이 합이 `u_branch_arc_sum_target_mm` 미만.
      - **N**: 직선 길이 무관. 두 호 스윕 각이 `n_branch_min_arc_sweep_deg` 이상이고,
        중간 직선이 대각선(수평·수직에서 `n_branch_diagonal_axis_tol_deg` 이상 떨어짐).

    직선 → 호 → 직선(호 하나)은 **이 함수에서 병합하지 않음**(호-호·호-직-호만).
    .map 직-호-직은 export 시 **호 start 직선·호·호 end 직선** 세 LINK Type U.

    N(Option 1)도 두 호의 스윕 각이 위 최소값 이상일 때만 병합.

    맵에는 첫 호의 start ~ 마지막 호의 end 로 한 줄 기록.
    겹치면 앞에서 잡힌 패턴이 유지됩니다.
    """
    groups: List[Tuple[Tuple[int, ...], str]] = []
    covered: set[int] = set()
    n_min = float(n_branch_min_arc_sweep_deg)

    def _n_arcs_sweep_ok(a: Any, b: Any) -> bool:
        return (
            arc_minor_sweep_deg_edge(a) >= n_min
            and arc_minor_sweep_deg_edge(b) >= n_min
        )

    for i, edge in enumerate(edges):
        if i in covered:
            continue
        if getattr(edge, "edge_type", None) != "ARC":
            continue
        next_j, next_e, next_flip = find_next_edge(
            edge.end, edges, tol=tol, exclude=[i], prefer_arc=True
        )
        if next_e is None:
            continue

        if getattr(next_e, "edge_type", None) == "ARC":
            if next_j in covered:
                continue
            branch = un_branch_type_from_arcs(edge, next_e, not bool(next_flip))
            if branch == "N" and not _n_arcs_sweep_ok(edge, next_e):
                continue
            if branch == "U" and u_branch_u_metric_mm(edge, next_e, scale_to_mm) > u_branch_arc_sum_target_mm + 5.0:
                continue
            if branch == "U" and u_x_threshold_mm is not None:
                far_end = next_e.start if next_flip else next_e.end
                if dist(edge.start, far_end) * float(scale_to_mm) >= u_x_threshold_mm:
                    continue
            groups.append(((i, next_j), branch))
            covered.add(i)
            covered.add(next_j)
        elif getattr(next_e, "edge_type", None) == "LINE":
            if next_j in covered:
                continue
            junc = edge.end
            other_pt = other_endpoint(next_e, junc, tol=tol)
            if other_pt is None:
                continue
            third_j, third_e, third_flip = find_next_edge(
                other_pt, edges, tol=tol, exclude=[i, next_j], prefer_arc=True
            )
            if third_e is None or getattr(third_e, "edge_type", None) != "ARC":
                continue
            if third_j in covered:
                continue
            branch = un_branch_type_from_arcs(edge, third_e, not bool(third_flip))
            if branch == "U":
                if third_flip:
                    continue
                if u_branch_u_metric_mm(edge, third_e, scale_to_mm, line_edge=next_e) > u_branch_arc_sum_target_mm + 5.0:
                    continue
                if u_x_threshold_mm is not None:
                    if dist(edge.start, third_e.end) * float(scale_to_mm) >= u_x_threshold_mm:
                        continue
            else:
                if not _n_arcs_sweep_ok(edge, third_e):
                    continue
                if not line_sufficiently_diagonal(
                    next_e, min_deg_from_axis=n_branch_diagonal_axis_tol_deg
                ):
                    continue
            groups.append(((i, next_j, third_j), branch))
            covered.add(i)
            covered.add(next_j)
            covered.add(third_j)

    return groups


def _arc_forward_tangent(arc_edge: Any, at_start: bool) -> Optional[Tuple[float, float]]:
    """Arc의 forward 진행방향 단위벡터. at_start=True: arc.start에서, False: arc.end에서."""
    if getattr(arc_edge, "edge_type", None) != "ARC":
        return None
    d = arc_edge._data
    r = float(getattr(d, "r", 0.0) or 0.0)
    if r < 1e-9:
        return None
    cx, cy = float(d.cx), float(d.cy)
    pt = arc_edge.start if at_start else arc_edge.end
    theta = math.atan2(float(pt[1]) - cy, float(pt[0]) - cx)
    lt = arc_link_type_from_arcseg(d)
    if lt == "L":  # CCW
        return (-math.sin(theta), math.cos(theta))
    else:  # CW ("R")
        return (math.sin(theta), -math.cos(theta))


def find_un_branch_merge_groups_by_x(
    edges: List[Any],
    tol: float,
    short_straight_threshold: float,
    *,
    u_x_threshold_mm: float = 4000.0,
    n_branch_min_arc_sweep_deg: float = 90.0,
    n_branch_diagonal_axis_tol_deg: float = 5.0,
    scale_to_mm: float = 1.0,
    exclude_indices: Optional[set] = None,
) -> List[Tuple[Tuple[int, ...], str]]:
    """find_un_branch_merge_groups의 X 기반 변형.
    U 판단 기준: dist(first_arc.start, last_arc.end) < u_x_threshold_mm (기본 1601mm).

    exclude_indices: U/N 후보에서 완전히 제외할 엣지 인덱스(복합분기로 이미 처리된 호 등).
      이 호들이 인접 U의 짝을 가로채(끝점 공유) 잘못된 쌍을 만들고, 그 쌍이 후처리에서
      통째로 버려져 진짜 U가 누락되는 것을 방지한다.
    """
    groups: List[Tuple[Tuple[int, ...], str]] = []
    covered: set[int] = set()
    _excl: set = set(exclude_indices) if exclude_indices else set()
    n_min = float(n_branch_min_arc_sweep_deg)

    def _n_arcs_sweep_ok(a: Any, b: Any) -> bool:
        return (
            arc_minor_sweep_deg_edge(a) >= n_min
            and arc_minor_sweep_deg_edge(b) >= n_min
        )

    for i, edge in enumerate(edges):
        if i in covered or i in _excl:
            continue
        if getattr(edge, "edge_type", None) != "ARC":
            continue
        next_j, next_e, next_flip = find_next_edge(
            edge.end, edges, tol=tol, exclude=[i] + list(_excl), prefer_arc=True
        )
        if next_e is None:
            continue

        if getattr(next_e, "edge_type", None) == "ARC":
            if next_j in covered or next_j in _excl:
                continue
            branch = un_branch_type_from_arcs(edge, next_e, not bool(next_flip))
            if branch == "N" and not _n_arcs_sweep_ok(edge, next_e):
                continue
            if branch == "U":
                far_end = next_e.start if next_flip else next_e.end
                X = dist(edge.start, far_end) * float(scale_to_mm)
                if X >= u_x_threshold_mm:
                    continue
            groups.append(((i, next_j), branch))
            covered.add(i)
            covered.add(next_j)
        elif getattr(next_e, "edge_type", None) == "LINE":
            if next_j in covered or next_j in _excl:
                continue
            junc = edge.end
            other_pt = other_endpoint(next_e, junc, tol=tol)
            if other_pt is None:
                continue
            third_j, third_e, third_flip = find_next_edge(
                other_pt, edges, tol=tol, exclude=[i, next_j] + list(_excl), prefer_arc=True
            )
            if third_e is None or getattr(third_e, "edge_type", None) != "ARC":
                continue
            if third_j in covered or third_j in _excl:
                continue
            branch = un_branch_type_from_arcs(edge, third_e, not bool(third_flip))
            if branch == "U":
                if third_flip:
                    third_e.reverse()
                far_end = third_e.end
                X = dist(edge.start, far_end) * float(scale_to_mm)
                if X >= u_x_threshold_mm:
                    continue
            else:
                if not _n_arcs_sweep_ok(edge, third_e):
                    continue
                if not line_sufficiently_diagonal(
                    next_e, min_deg_from_axis=n_branch_diagonal_axis_tol_deg
                ):
                    continue
            groups.append(((i, next_j, third_j), branch))
            covered.add(i)
            covered.add(next_j)
            covered.add(third_j)

    return groups


def export_map_from_unified_edges(
    edges: List[Any],
    path: Union[str, Path],
    *,
    tol: float = 10.0,
    scale_to_mm: float = 1.0,
    short_straight_threshold: float = 400.0,
    n_branch_min_arc_sweep_deg: float = 10.0,
    n_branch_diagonal_axis_tol_deg: float = 5.0,
    u_branch_arc_sum_target_mm: float = 4000.0,
    u_x_threshold_mm: Optional[float] = None,
    line_arc_line_u_radius_mm: float = 450.0,
    line_arc_line_u_radius_tol_mm: float = 5.0,
    line_arc_line_u_abs_sa_ea_tol_deg: float = 5.0,
    emit_line_arc_line_u_links: bool = True,
    merge_un_branches: bool = True,
    precomputed_merge_groups: Optional[List[Tuple[Tuple[int, ...], str]]] = None,
    header: Optional[str] = None,
) -> Tuple[List[MapNode], List[MapLink]]:
    """
    asd.ipynb 의 `unified_edges`(Edge 리스트)로 NODE/LINK를 만들어 .map 저장.

    - `merge_un_branches=False`: 엣지 1개당 LINK 1개(호-호·호-직-호 U/N **구간 병합 없음**).
      타입은 직선 S, 호 L/R, (옵션) 직-호-직 가운데 호만 U.
    - `merge_un_branches=True`(기본): 아래 U/N 병합·한 줄 LINK 규칙 적용.

    - 노드: **실제로 내보내는 각 LINK의 양끝**만 `tol` 그리드로 묶어 6자리 ID(000001~).
      U/N 병합 시 중간 접점(호-호 접점, 호-직-호 사이 등)은 노드에서 제외.
    - 좌표: 도면 단위에 scale_to_mm(기본 1)을 곱한 뒤 **소수점 6자리**로 기록.
    - LINK: U/N 패턴은 **한 줄**로 합침 — 첫 호의 start ~ 마지막 호의 end, Type U/N, 길이는 구간 합.
      U는 호-호는 두 호 **반지름 합**, 호-직-호(호 두 개)는 **반지름 합+중간 직선**이 target±tol.
      직선–호–직선(반원·450mm 등)은 병합하지 않음. 기본(`emit_line_arc_line_u_links=True`)이면
      **가운데 호(ARC)만** Type U. 끄면 S/L·R.
      U(호-직-호, 호 두 개)만 중간 직선 길이 상한 사용. N은 직선 길이 무관, 두 호 스윕 각·중간 직선이 대각선.
      그 외는 직선 S / 호 L·R.
    """

    if precomputed_merge_groups is not None:
        merge_groups = precomputed_merge_groups
    elif merge_un_branches:
        merge_groups = find_un_branch_merge_groups(
            edges,
            tol,
            short_straight_threshold,
            n_branch_min_arc_sweep_deg=n_branch_min_arc_sweep_deg,
            n_branch_diagonal_axis_tol_deg=n_branch_diagonal_axis_tol_deg,
            u_branch_arc_sum_target_mm=u_branch_arc_sum_target_mm,
            u_x_threshold_mm=u_x_threshold_mm,
            scale_to_mm=scale_to_mm,
        )
    else:
        merge_groups = []
    group_starts: Dict[int, Tuple[Tuple[int, ...], str]] = {}
    all_in_merge: set[int] = set()
    for indices, ut in merge_groups:
        group_starts[indices[0]] = (indices, ut)
        for x in indices:
            all_in_merge.add(x)

    line_arc_u_edge_idx: set[int] = set()
    if emit_line_arc_line_u_links:
        line_arc_u_edge_idx = line_arc_line_u_edge_indices_for_export(
            edges,
            tol,
            scale_to_mm=scale_to_mm,
            radius_target_mm=line_arc_line_u_radius_mm,
            radius_tol_mm=line_arc_line_u_radius_tol_mm,
            abs_sa_ea_tol_deg=line_arc_line_u_abs_sa_ea_tol_deg,
            exclude_edge_indices=all_in_merge,
        )

    def _pt_key(p: Tuple[float, float]) -> Tuple[float, float]:
        """실제 좌표를 키로 사용. tol 이내 근접점은 대표점으로 병합."""
        return (float(p[0]), float(p[1]))

    def _merge_pt_key(
        raw: Tuple[float, float],
        reps: List[Tuple[float, float]],
        buckets: Dict[Tuple[int, int], List[Tuple[float, float]]],
        merge_tol: float,
    ) -> Tuple[float, float]:
        """reps 중 merge_tol 이내 기존 대표점이 있으면 그걸 반환, 없으면 raw를 새 대표점으로 등록."""
        cell = max(merge_tol, 1.0)
        gx = int(math.floor(raw[0] / cell))
        gy = int(math.floor(raw[1] / cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for rep in buckets.get((gx + dx, gy + dy), []):
                    if dist(raw, rep) <= merge_tol:
                        return rep
        reps.append(raw)
        buckets.setdefault((gx, gy), []).append(raw)
        return raw

    # 1) 내보낼 LINK 스펙만 수집 → 병합 구간의 내부 점은 노드 후보에 넣지 않음
    _pt_reps: List[Tuple[float, float]] = []
    _pt_buckets: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}

    def _k(p: Tuple[float, float]) -> Tuple[float, float]:
        raw = (float(p[0]), float(p[1]))
        return _merge_pt_key(raw, _pt_reps, _pt_buckets, tol)

    link_specs: List[Tuple[Tuple[float, float], Tuple[float, float], str, int]] = []
    for e_idx in range(len(edges)):
        if e_idx in all_in_merge and e_idx not in group_starts:
            continue
        if e_idx in group_starts:
            indices, ut = group_starts[e_idx]
            first_e = edges[indices[0]]
            last_e = edges[indices[-1]]
            sk = _k(first_e.start)
            ek = _k(last_e.end)
            path_len = sum(edge_path_length_mm(edges[j]) for j in indices)
            ln = max(0, int(round(path_len * scale_to_mm)))
            if ln == 0 and dist(first_e.start, last_e.end) < tol * 0.01:
                continue
            link_specs.append((sk, ek, ut, ln))
            continue

        e = edges[e_idx]
        sk = _k(e.start)
        ek = _k(e.end)
        ln = max(0, int(round(edge_path_length_mm(e) * scale_to_mm)))
        if ln == 0 and dist(e.start, e.end) < tol * 0.01:
            continue
        lt = edge_link_type(e)
        if e_idx in line_arc_u_edge_idx:
            lt = "U"
        link_specs.append((sk, ek, lt, ln))

    required_keys: set[Tuple[float, float]] = set()
    for sk, ek, _, _ in link_specs:
        required_keys.add(sk)
        required_keys.add(ek)

    key_to_id = {k: str(i).zfill(6) for i, k in enumerate(required_keys, start=1)}

    def _fmt_coord(v: float) -> str:
        # .map에 소수점 6자리까지 유지
        return f"{float(v):.6f}"

    nodes: List[MapNode] = []
    for k in required_keys:
        nid = key_to_id[k]
        x_mm = float(k[0]) * float(scale_to_mm)
        y_mm = float(k[1]) * float(scale_to_mm)
        nodes.append(
            MapNode(
                id=nid,
                type="G",
                reality="R",
                x=_fmt_coord(x_mm),
                y=_fmt_coord(y_mm),
                layer_id="0",
                param_yield_enabled="0",
            )
        )

    links: List[MapLink] = []
    for li, (sk, ek, lt, ln) in enumerate(link_specs, start=1):
        links.append(
            MapLink(
                id=str(li),
                type=lt,
                start_node_id=key_to_id[sk],
                end_node_id=key_to_id[ek],
                length=str(ln),
            )
        )

    outp = Path(path)
    save_map(str(outp), nodes, links, header=header)
    return nodes, links
