from __future__ import annotations
import math
import copy
from typing import List, Tuple, Optional, Any, Dict, Set
from dataclasses import dataclass
EPS = 1e-9
MIN_LINE_LENGTH = 0.0
SNAP_DECIMALS = 6
SNAP_TOL = 200.0
INTER_MERGE_TOL = 100.0     # 기하/토폴로지 병합 허용 오차 (mm)
CLEAN_TOL = 100.0           # DXF 파싱 단계 중복·영세그먼트 정리 오차 (mm)
SHORT_STRAIGHT_THRESHOLD = 900.0
@dataclass
class LineSeg:
    p1: Tuple[float, float]
    p2: Tuple[float, float]

@dataclass
class ArcSeg:
    cx: float
    cy: float
    r: float
    start_deg: float
    end_deg: float
    # 월드 XY에서 호의 시작·끝 (로컬 각도 점을 transform)
    p_start: Tuple[float, float] = (0.0, 0.0)
    p_end: Tuple[float, float] = (0.0, 0.0)
    # DXF 호의 실제 중간점 — 180°일 때 두 반원 중 어느 쪽인지 구분 (끝점 각만으로는 불가)
    p_mid_curve: Optional[Tuple[float, float]] = None
    # 원본 DXF(또는 분할 직후) 각도 스냅샷: glue/snap으로 끝점이 조금 움직여도 U 판별에 사용
    dxf_start_deg: Optional[float] = None
    dxf_end_deg: Optional[float] = None

class Edge:
    def __init__(self, seg_data):
        if isinstance(seg_data, LineSeg):
            self.edge_type = 'LINE'
            self.start = seg_data.p1
            self.end = seg_data.p2
            self._data = seg_data
        elif isinstance(seg_data, ArcSeg):
            self.edge_type = 'ARC'
            self.start = seg_data.p_start
            self.end = seg_data.p_end
            self._data = seg_data
        else:
            raise ValueError("지원되지 않는 세그먼트 타입")
    
    def reverse(self):
        """엣지 방향 뒤집기"""
        self.start, self.end = self.end, self.start
        if isinstance(self._data, LineSeg):
            self._data.p1, self._data.p2 = self._data.p2, self._data.p1
        elif isinstance(self._data, ArcSeg):
            self._data.p_start, self._data.p_end = self._data.p_end, self._data.p_start
            self._data.start_deg, self._data.end_deg = self._data.end_deg, self._data.start_deg
    
    def chord_midpoint(self):
        """아크의 현(chord) 중점 — 방향 규칙에 사용"""
        if self.edge_type == 'ARC':
            return ((self.start[0] + self.end[0]) / 2, (self.start[1] + self.end[1]) / 2)
        return None
    
    def __repr__(self):
        return f"Edge({self.edge_type}, S={self.start}, E={self.end})"

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def ccw_delta_deg(a, b):
    """a에서 b까지 반시계 각도차 (0~360)."""
    return (b - a) % 360.0

def grid_key(p: Tuple[float, float], cell: float) -> Tuple[int, int]:
    """공간 해싱용 정수 셀 인덱스 (geometry 내부 버킷 탐색용)."""
    if cell <= 0:
        return (0, 0)
    return (int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)))

def coord_key(p: Tuple[float, float], tol: float) -> Tuple[float, float]:
    """노드 병합·좌표 출력용 스냅 좌표 (real_map_format._grid_key 동일 로직)."""
    if tol <= 0:
        tol = 1e-9
    return (round(p[0] / tol) * tol, round(p[1] / tol) * tol)

def seg_param_t(a: Tuple[float, float], b: Tuple[float, float], p: Tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 < EPS:
        return 0.0
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2

def seg_intersection(p1, p2, p3, p4):
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4

    den = (x1-x2)*(y3-y4) - (y1-y2)*(x3-x4)
    if abs(den) < EPS:
        return []

    t = ((x1-x3)*(y3-y4) - (y1-y3)*(x3-x4)) / den
    u = -((x1-x2)*(y1-y3) - (y1-y2)*(x1-x3)) / den

    if -1e-8 <= t <= 1+1e-8 and -1e-8 <= u <= 1+1e-8:
        return [(x1 + t*(x2-x1), y1 + t*(y2-y1))]
    return []

def arc_point_at_deg(cx: float, cy: float, r: float, deg: float) -> Tuple[float, float]:
    a = math.radians(float(deg))
    return (float(cx) + float(r) * math.cos(a), float(cy) + float(r) * math.sin(a))

def arc_curve_midpoint(arc: "ArcSeg", cx: float, cy: float, r: float) -> Optional[Tuple[float, float]]:
    pm = getattr(arc, "p_mid_curve", None)
    if pm is not None:
        return (float(pm[0]), float(pm[1]))
    return arc_midpoint_from_dxf_angles(arc, cx, cy, r)

def arc_midpoint_from_dxf_angles(arc: "ArcSeg", cx: float, cy: float, r: float) -> Optional[Tuple[float, float]]:
    sa = getattr(arc, "dxf_start_deg", None)
    ea = getattr(arc, "dxf_end_deg", None)
    if sa is None or ea is None or r <= 1e-12:
        return None
    sweep = ccw_delta_deg(float(sa), float(ea))
    if sweep <= 1e-9:
        return None
    return arc_point_at_deg(cx, cy, r, float(sa) + 0.5 * sweep)

def dxf_ccw_unwrap_end_deg(ta: float, tb: float) -> float:
    """CCW로 ta→tb일 때 선형 보간용 끝 각(도). ta+Δ로 unwrap (예: 350°→10°면 370°)."""
    return float(ta) + ccw_delta_deg(ta, tb)

def arc_endpoint_degrees(arc: ArcSeg) -> Tuple[float, float]:
    ps, pe = arc.p_start, arc.p_end
    ts = math.degrees(math.atan2(ps[1] - arc.cy, ps[0] - arc.cx)) % 360.0
    te = math.degrees(math.atan2(pe[1] - arc.cy, pe[0] - arc.cx)) % 360.0
    return ts, te

def arc_should_use_ccw_sweep(
    ts: float,
    te: float,
    L1: float,
    L2: float,
    cx: float,
    cy: float,
    r: float,
    pm: Optional[Tuple[float, float]],
) -> bool:
    """start→end로 그릴 때 CCW 스윕(L1)을 쓸지, CW(L2)를 쓸지.
    p_mid_curve가 있으면 각도 구간으로 어느 호에 속하는지 먼저 판별(중점 거리보다 안정적).
    없으면 두 끝 사이 짧은 호(L1<=L2면 CCW 방향이 짧음)."""
    if pm is not None:
        tp = math.degrees(math.atan2(pm[1] - cy, pm[0] - cx)) % 360.0
        eps = max(0.05, math.degrees(math.atan2(1e-6, max(r, 1e-12))))
        on_ccw = ccw_delta_deg(ts, tp) <= L1 + eps and ccw_delta_deg(tp, te) <= L1 + eps
        on_cw = ccw_delta_deg(te, tp) <= L2 + eps and ccw_delta_deg(tp, ts) <= L2 + eps
        if on_ccw and not on_cw:
            return True
        if on_cw and not on_ccw:
            return False
        mid_ccw_deg = (ts + 0.5 * L1) % 360.0
        mid_cw_deg = (ts - 0.5 * L2) % 360.0

        def _pt(deg: float) -> Tuple[float, float]:
            a = math.radians(deg)
            return (cx + r * math.cos(a), cy + r * math.sin(a))

        return dist(_pt(mid_ccw_deg), pm) <= dist(_pt(mid_cw_deg), pm)
    return L1 <= L2

