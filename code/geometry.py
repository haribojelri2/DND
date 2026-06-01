from __future__ import annotations
import math
import copy
from typing import List, Tuple, Optional, Any, Dict, Set

import itertools
from collections import defaultdict
from core import *

def split_near_180_arcs(arcs: List["ArcSeg"], *, target_deg: float = 180.0, tol_deg: float = 1.0) -> List["ArcSeg"]:
    out = []
    for arc in arcs:
        r = float(arc.r)
        if r <= 1e-12:
            out.append(arc)
            continue
        sa_raw = getattr(arc, "dxf_start_deg", None)
        ea_raw = getattr(arc, "dxf_end_deg", None)
        if sa_raw is not None and ea_raw is not None:
            sweep = ccw_delta_deg(float(sa_raw), float(ea_raw))
        else:
            sweep = ccw_delta_deg(float(arc.start_deg), float(arc.end_deg))
        minor_sweep = min(sweep, 360.0 - sweep)
        if abs(minor_sweep - float(target_deg)) > float(tol_deg):
            out.append(arc)
            continue
        pm = arc_curve_midpoint(arc, float(arc.cx), float(arc.cy), r)
        if pm is None or dist(pm, arc.p_start) <= INTER_MERGE_TOL * 0.02 or dist(pm, arc.p_end) <= INTER_MERGE_TOL * 0.02:
            out.append(arc)
            continue
        first = arc_subsegment(arc, arc.p_start, pm)
        second = arc_subsegment(arc, pm, arc.p_end)
        out.append(first)
        out.append(second)
    return out

def split_edges_at_intersections(
    line_list: List[LineSeg],
    arc_list: List[ArcSeg],
    *,
    merge_tol: float = INTER_MERGE_TOL,
) -> Tuple[List[LineSeg], List[ArcSeg], List[Tuple[float, float]]]:
    """LINE 분할: (1) 다른 LINE과의 교차 (2) 원호와 직선의 실교차 (3) 호 끝점이 직선 위에 있을 때.\n
    이후 직선과 교차하는 호를 교차점에서 ArcSeg 여러 개로 나눈다."""
    intersection_vertices: List[Tuple[float, float]] = []

    # 교차점 수가 많아지면 O(N^2) 중복 검사로 누락/느려짐이 생길 수 있어,
    # merge_near_points와 같은 방식(격자 버킷 + 인접 8칸 탐색)으로 교차점 병합.
    v_buckets: dict[Tuple[int, int], List[Tuple[float, float]]] = defaultdict(list)

    def _vkey(p: Tuple[float, float]) -> Tuple[int, int]:
        cell = max(float(merge_tol), 1e-9)
        return (int(math.floor(float(p[0]) / cell)), int(math.floor(float(p[1]) / cell)))

    def register_vertex(pt: Tuple[float, float]) -> None:
        g = _vkey(pt)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for q in v_buckets.get((g[0] + dx, g[1] + dy), []):
                    if dist(pt, q) <= merge_tol:
                        return
        intersection_vertices.append(pt)
        v_buckets[g].append(pt)

    line_edges: List[LineSeg] = []

    for L in line_list:
        a, b = L.p1, L.p2
        cuts: List[Tuple[float, float]] = [a, b]

        for M in line_list:
            if M is L:
                continue
            c1, d1 = M.p1, M.p2
            for hit in seg_intersection(a, b, c1, d1):
                cuts.append(hit)
                register_vertex(hit)

        for arc in arc_list:
            if arc.r < 1e-12:
                continue

            for hit in line_seg_circle_hits(a, b, arc.cx, arc.cy, arc.r):
                if on_arc_circle(hit, arc, merge_tol):
                    cuts.append(hit)
                    register_vertex(hit)

            for ep in (arc.p_start, arc.p_end):
                if point_on_segment(ep, a, b, merge_tol):
                    cuts.append(ep)
                    register_vertex(ep)

        chain = sort_dedupe_on_segment(a, b, cuts, merge_tol)
        for k in range(len(chain) - 1):
            p, q = chain[k], chain[k + 1]
            if dist(p, q) > MIN_LINE_LENGTH:
                line_edges.append(LineSeg(p, q))

    new_arcs = split_arcs_at_line_intersections(arc_list, line_edges, merge_tol=merge_tol)
    return line_edges, new_arcs, intersection_vertices

def split_arcs_at_line_intersections(arcs, line_edges, *, merge_tol=INTER_MERGE_TOL):
    """호를 라인과의 교차점에서 분할.
    각 호에 대해 라인들과의 교차점을 찾고, 호 위 순서로 정렬한 뒤 서브 세그먼트로 나눈다.
    """
    result = []
    for arc in arcs:
        if arc.r < 1e-12:
            result.append(arc)
            continue

        cuts = []
        for line in line_edges:
            for hit in line_seg_circle_hits(line.p1, line.p2, arc.cx, arc.cy, arc.r):
                if not on_arc_circle(hit, arc, merge_tol):
                    continue
                # 호 끝점과 너무 가까우면 스킵 (끝점 자체는 이미 연결됨)
                if dist(hit, arc.p_start) <= merge_tol or dist(hit, arc.p_end) <= merge_tol:
                    continue
                cuts.append(hit)

        if not cuts:
            result.append(arc)
            continue

        # 호 위 경로 순서로 정렬 후 중복 제거
        cuts = sort_cuts_along_arc(arc, cuts, merge_tol)

        # p_start → cut₁ → cut₂ → ... → p_end 로 분할
        prev = arc.p_start
        for cut in cuts:
            if dist(prev, cut) > merge_tol:
                result.append(arc_subsegment(arc, prev, cut))
            prev = cut
        if dist(prev, arc.p_end) > merge_tol:
            result.append(arc_subsegment(arc, prev, arc.p_end))

    return result

def glue_arc_endpoints_to_lines(lines: List[LineSeg], arcs: List[ArcSeg], tol: float) -> None:
    """호 끝이 직선에 ‘거의’ 닿는데 끝점 스냅만으로는 안 붙는 경우:
    원 위에서 직선 쪽으로 끝을 옮기고, 해당 직선을 그 투영점에서 분할한다."""
    if tol <= 0:
        return
    min_seg = max(1e-6, tol * 0.02)
    for arc in arcs:
        if arc.r < 1e-12:
            continue
        for end_name in ("p_start", "p_end"):
            p = getattr(arc, end_name)
            best_q = None
            best_d = float("inf")
            best_idx = -1
            for i, seg in enumerate(lines):
                q = closest_point_on_segment(p, seg.p1, seg.p2)
                d = dist(p, q)
                if d < best_d:
                    best_d, best_q, best_idx = d, q, i
            if best_d > tol or best_idx < 0 or best_q is None:
                continue
            ang = math.atan2(best_q[1] - arc.cy, best_q[0] - arc.cx)
            px = arc.cx + arc.r * math.cos(ang)
            py = arc.cy + arc.r * math.sin(ang)
            setattr(arc, end_name, (px, py))
            arc.start_deg = math.degrees(math.atan2(arc.p_start[1] - arc.cy, arc.p_start[0] - arc.cx)) % 360.0
            arc.end_deg = math.degrees(math.atan2(arc.p_end[1] - arc.cy, arc.p_end[0] - arc.cx)) % 360.0
            arc.p_mid_curve = None
            seg = lines[best_idx]
            split_pt = closest_point_on_segment((px, py), seg.p1, seg.p2)
            if dist(seg.p1, split_pt) < min_seg or dist(seg.p2, split_pt) < min_seg:
                continue
            lines[best_idx : best_idx + 1] = [LineSeg(seg.p1, split_pt), LineSeg(split_pt, seg.p2)]

def snap_segments(split_lines: List[LineSeg], arcs: List[ArcSeg], tol: float) -> None:
    """세그먼트 좌표들을 tol 이내 대표점으로 in-place 치환."""
    if tol <= 0:
        return

    def _q(p: Tuple[float, float]) -> Tuple[float, float]:
        """좌표 양자화(정수/소수점). U/N 병합 안정화를 위해 스냅 전에 적용."""
        d = int(SNAP_DECIMALS)
        if d <= 0:
            return (float(int(round(float(p[0])))), float(int(round(float(p[1])))))
        return (round(float(p[0]), d), round(float(p[1]), d))

    pts: List[Tuple[float, float]] = []

    # ARC 끝점을 먼저 넣어, tol 이내 병합 시 대표 좌표를 호 쪽으로 둔다.
    # (직선 끝이 호 쪽으로 당겨지므로 reproject_arcs_to_circle 불필요하지만 안전망으로 유지.)
    for a in arcs:
        pts.append(_q(a.p_start))
        pts.append(_q(a.p_end))

    for s in split_lines:
        pts.append(_q(s.p1))
        pts.append(_q(s.p2))

    # 중심/중간점은 마지막에 넣어도 무방 (필요 시에만)
    for a in arcs:
        pts.append(_q((a.cx, a.cy)))
        if getattr(a, "p_mid_curve", None) is not None:
            pts.append(_q(a.p_mid_curve))

    mp = merge_near_points(pts, tol)

    for s in split_lines:
        s.p1 = mp.get(_q(s.p1), _q(s.p1))
        s.p2 = mp.get(_q(s.p2), _q(s.p2))

    for a in arcs:
        a.p_start = mp.get(_q(a.p_start), _q(a.p_start))
        a.p_end = mp.get(_q(a.p_end), _q(a.p_end))
        c = mp.get(_q((a.cx, a.cy)), _q((a.cx, a.cy)))
        a.cx, a.cy = float(c[0]), float(c[1])
        if getattr(a, "p_mid_curve", None) is not None:
            pm = mp.get(_q(a.p_mid_curve), _q(a.p_mid_curve))
            ang = math.atan2(pm[1] - a.cy, pm[0] - a.cx)
            rr = max(a.r, 1e-12)
            a.p_mid_curve = (a.cx + rr * math.cos(ang), a.cy + rr * math.sin(ang))

def merge_near_points(points: List[Tuple[float, float]], tol: float) -> dict:
    """points의 각 점을 tol 이내 대표점으로 매핑."""
    if tol <= 0 or not points:
        return {p: p for p in points}

    cell = float(tol)
    buckets: dict[Tuple[int, int], List[Tuple[float, float]]] = defaultdict(list)
    reps: List[Tuple[float, float]] = []
    mapping: dict[Tuple[float, float], Tuple[float, float]] = {}

    for p in points:
        g = grid_key(p, cell)
        best_rep = None
        best_d = None
        
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for r in buckets.get((g[0] + dx, g[1] + dy), []):
                    d = dist(p, r)
                    if d <= tol and (best_d is None or d < best_d):
                        best_rep, best_d = r, d

        if best_rep is None:
            reps.append(p)
            buckets[g].append(p)
            mapping[p] = p
        else:
            mapping[p] = best_rep

    return mapping

def sort_dedupe_on_segment(
    a: Tuple[float, float],
    b: Tuple[float, float],
    pts: List[Tuple[float, float]],
    merge_tol: float,
) -> List[Tuple[float, float]]:
    items = []
    for p in pts:
        t = seg_param_t(a, b, p)
        if -1e-6 <= t <= 1 + 1e-6:
            t = max(0.0, min(1.0, t))
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            items.append((t, q))
    items.sort(key=lambda x: x[0])
    out: List[Tuple[float, float]] = []
    for _, q in items:
        if not out or dist(out[-1], q) > merge_tol:
            out.append(q)
    return out

def line_seg_circle_hits(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    cx: float,
    cy: float,
    r: float,
) -> List[Tuple[float, float]]:
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    fx, fy = p1[0] - cx, p1[1] - cy
    a = dx * dx + dy * dy
    if a < EPS:
        return []
    b = 2 * (fx * dx + fy * dy)
    c0 = fx * fx + fy * fy - r * r
    disc = b * b - 4 * a * c0
    if disc < -1e-12:
        return []
    disc = max(0.0, disc)
    sqrt_d = math.sqrt(disc)
    out = []
    for sign in (-1.0, 1.0):
        t = (-b + sign * sqrt_d) / (2 * a)
        if -1e-9 <= t <= 1 + 1e-9:
            t = max(0.0, min(1.0, t))
            out.append((p1[0] + t * dx, p1[1] + t * dy))
    if len(out) == 2 and dist(out[0], out[1]) < INTER_MERGE_TOL:
        return [out[0]]
    return out

def point_on_segment(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float], tol: float) -> bool:
    t = seg_param_t(a, b, p)
    if not (-1e-9 <= t <= 1 + 1e-9):
        return False
    t = max(0.0, min(1.0, t))
    q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return dist(p, q) <= tol

def closest_point_on_segment(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
    """선분 AB 위에서 p에 가장 가까운 점(구간으로 클램프)."""
    t = seg_param_t(a, b, p)
    t = max(0.0, min(1.0, t))
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

def on_arc_circle(pt: Tuple[float, float], arc: ArcSeg, tol: float) -> bool:
    """원 위 점이 실제로 그려진 호 위에 있는지."""
    r = arc.r
    if r < 1e-12:
        return False
    d = abs(dist((arc.cx, arc.cy), pt) - r)
    tol_r = max(tol, 1e-9 * max(r, 1.0))
    if d > tol_r:
        return False
    ts, te = arc_endpoint_degrees(arc)
    tp = math.degrees(math.atan2(pt[1] - arc.cy, pt[0] - arc.cx)) % 360.0
    eps_deg = 1e-3 + math.degrees(math.atan2(tol_r, max(r, 1e-12)))
    L1 = ccw_delta_deg(ts, te)
    L2 = 360.0 - L1
    if L1 < 1e-9 or L2 < 1e-9:
        return dist(pt, arc.p_start) <= tol_r or dist(pt, arc.p_end) <= tol_r
    pm = getattr(arc, "p_mid_curve", None)
    if abs(L1 - L2) < 1e-6 and pm is not None:
        use_ccw = arc_should_use_ccw_sweep(ts, te, L1, L2, arc.cx, arc.cy, arc.r, pm)
        if use_ccw:
            return ccw_delta_deg(ts, tp) <= L1 + eps_deg and ccw_delta_deg(tp, te) <= L1 + eps_deg
        return ccw_delta_deg(te, tp) <= L2 + eps_deg and ccw_delta_deg(tp, ts) <= L2 + eps_deg
    if abs(L1 - L2) < 1e-6:
        ok_a = ccw_delta_deg(ts, tp) <= L1 + eps_deg and ccw_delta_deg(tp, te) <= L1 + eps_deg
        ok_b = ccw_delta_deg(te, tp) <= L1 + eps_deg and ccw_delta_deg(tp, ts) <= L1 + eps_deg
        return ok_a or ok_b
    if L1 <= L2:
        return ccw_delta_deg(ts, tp) <= L1 + eps_deg and ccw_delta_deg(tp, te) <= L1 + eps_deg
    return ccw_delta_deg(te, tp) <= L2 + eps_deg and ccw_delta_deg(tp, ts) <= L2 + eps_deg

def arc_sample_points_along_drawn(arc: ArcSeg, n: int = 64) -> List[Tuple[float, float]]:
    """실제로 그려진 호를 따라 start→end 순서 샘플 점 (_arc_xy_polyline과 동일 기준)."""
    cx, cy, r = float(arc.cx), float(arc.cy), float(arc.r)
    if r < 1e-12:
        return [arc.p_start, arc.p_end]
    ta = math.degrees(math.atan2(arc.p_start[1] - cy, arc.p_start[0] - cx)) % 360.0
    tb = math.degrees(math.atan2(arc.p_end[1] - cy, arc.p_end[0] - cx)) % 360.0
    L1 = ccw_delta_deg(ta, tb)
    L2 = 360.0 - L1
    pm = getattr(arc, "p_mid_curve", None)
    use_ccw = arc_should_use_ccw_sweep(ta, tb, L1, L2, cx, cy, r, pm)
    out: List[Tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        if use_ccw:
            end_ccw = dxf_ccw_unwrap_end_deg(ta, tb)
            ang_deg = ta + t * (end_ccw - ta)
        else:
            ang_deg = ta - t * L2
        ang = math.radians(ang_deg)
        out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return out

def sort_cuts_along_arc(arc: ArcSeg, cuts: List[Tuple[float, float]], merge_tol: float) -> List[Tuple[float, float]]:
    """교차점을 호 위 순서(start→end)로 정렬."""
    if not cuts:
        return []
    samples = arc_sample_points_along_drawn(arc, n=96)
    scored: List[Tuple[float, int, float, Tuple[float, float]]] = []
    for p in cuts:
        best_i = 0
        best_d = float("inf")
        for i, q in enumerate(samples):
            d = dist(p, q)
            if d < best_d:
                best_d, best_i = d, i
        scored.append((best_i, best_d, float(p[0]), p))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [t[3] for t in scored]

def arc_subsegment(arc: ArcSeg, pa: Tuple[float, float], pb: Tuple[float, float]) -> ArcSeg:
    """부분 호: 끝점만 맞추고 p_mid_curve는 항상 설정 (L/R 판단 정확도를 위해).
    원본 호의 p_mid_curve를 기반으로 CCW/CW 방향을 판단해 서브 호의 중간점을 세팅한다."""
    cx, cy, r = float(arc.cx), float(arc.cy), float(arc.r)
    sa = math.degrees(math.atan2(pa[1] - cy, pa[0] - cx)) % 360.0
    ea = math.degrees(math.atan2(pb[1] - cy, pb[0] - cx)) % 360.0
    L1 = ccw_delta_deg(sa, ea)
    L2 = 360.0 - L1
    # 원본 호의 방향(CCW/CW) 계산
    orig_ta = math.degrees(math.atan2(arc.p_start[1] - cy, arc.p_start[0] - cx)) % 360.0
    orig_tb = math.degrees(math.atan2(arc.p_end[1] - cy, arc.p_end[0] - cx)) % 360.0
    orig_L1 = ccw_delta_deg(orig_ta, orig_tb)
    orig_L2 = 360.0 - orig_L1
    orig_pm = getattr(arc, "p_mid_curve", None)
    orig_use_ccw = arc_should_use_ccw_sweep(orig_ta, orig_tb, orig_L1, orig_L2, cx, cy, r, orig_pm)
    # 서브 호도 같은 방향(CCW/CW)으로 중간점 계산 — p_mid_curve 항상 설정
    if orig_use_ccw:
        end_unwrap = sa + L1  # CCW
        mid_deg = (sa + 0.5 * L1) % 360.0
    else:
        mid_deg = (sa - 0.5 * L2) % 360.0
    mr = math.radians(mid_deg)
    pm_sub = (cx + r * math.cos(mr), cy + r * math.sin(mr))
    return ArcSeg(
        cx=cx,
        cy=cy,
        r=r,
        start_deg=sa,
        end_deg=ea,
        p_start=pa,
        p_end=pb,
        p_mid_curve=pm_sub,
        dxf_start_deg=sa,
        dxf_end_deg=ea,
    )

def reproject_arcs_to_circle(arcs: List[ArcSeg]) -> None:
    """snap/glue 이후 스윕각 계산이 깨지는 문제를 방지.
    기존에는 p_start/p_end를 원 위로 재투영했는데,
    그 과정에서 '라인 끝점과 이미 병합된 접점'이 다시 어긋나는 문제가 생길 수 있다.
    여기서는 **끝점 좌표는 유지**하고, 각도(start/end_deg)만 현재 끝점 기준으로 재계산한다.
    """
    for a in arcs:
        if a.r < 1e-12:
            continue
        def _deg(p: Tuple[float, float]) -> float:
            return math.degrees(math.atan2(p[1] - a.cy, p[0] - a.cx)) % 360.0
        a.start_deg = _deg(a.p_start)
        a.end_deg = _deg(a.p_end)
        # 180° 모호성 해소용 중간점은 원 위에 두는 편이 안정적이라 투영 유지
        if getattr(a, "p_mid_curve", None) is not None:
            rr = float(max(a.r, 1e-12))
            pm = a.p_mid_curve
            ang = math.atan2(pm[1] - a.cy, pm[0] - a.cx)
            a.p_mid_curve = (a.cx + rr * math.cos(ang), a.cy + rr * math.sin(ang))


def merge_line_segments_at_degree2_nodes(
    split_lines: List[LineSeg],
    arcs: List[ArcSeg],
    tol: float = SNAP_TOL,
) -> List[LineSeg]:
    """Degree-2 노드에서 LINE 세그먼트 병합.

    snap 완료 후 적용: ARC 연결이 전혀 없고 정확히 두 개의 LineSeg만 연결된 노드는
    실질적으로 불필요한 중간 분할점이므로 제거하고, 양쪽 LineSeg를 하나로 합친다.

    규칙:
      - ARC 끝점(p_start/p_end)에 해당하는 노드는 절대 제거하지 않는다.
      - degree 3 이상(분기점)도 제거하지 않는다.
      - 체인은 양방향으로 확장하여 non-removable 끝점을 찾아 새 LineSeg(끝1, 끝2) 생성.
      - removable 노드로만 이루어진 고립 루프는 결과에서 제외한다.
    """
    if tol is None or tol <= 0:
        tol = 1e-9

    def pkey(p: Tuple[float, float]) -> Tuple[float, float]:
        return (round(float(p[0]) / tol) * tol, round(float(p[1]) / tol) * tol)

    # 1) ARC 끝점 노드 집합
    arc_nodes: Set[Tuple[float, float]] = set()
    for a in arcs:
        arc_nodes.add(pkey(a.p_start))
        arc_nodes.add(pkey(a.p_end))

    # 2) 노드 → 연결된 LineSeg 인덱스 (양쪽 끝)
    node_to_lines: Dict[Tuple[float, float], List[int]] = defaultdict(list)
    for i, seg in enumerate(split_lines):
        k1 = pkey(seg.p1)
        k2 = pkey(seg.p2)
        node_to_lines[k1].append(i)
        # self-loop(같은 키) 방지: 같은 세그먼트가 한 노드에 두 번 등록되더라도 degree 카운트 의미 보존
        if k2 != k1:
            node_to_lines[k2].append(i)
        else:
            # p1==p2 인 degenerate 세그먼트는 degree에 한 번만 기여
            pass

    def is_removable(node_key: Tuple[float, float]) -> bool:
        if node_key in arc_nodes:
            return False
        return len(node_to_lines.get(node_key, [])) == 2

    # 3) 체인 병합
    used: Set[int] = set()
    result: List[LineSeg] = []

    def other_endpoint(seg_idx: int, node_key: Tuple[float, float]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """seg의 두 끝점 중 node_key가 아닌 쪽의 (실좌표, 키)를 반환."""
        seg = split_lines[seg_idx]
        k1 = pkey(seg.p1)
        k2 = pkey(seg.p2)
        if k1 == node_key:
            return seg.p2, k2
        return seg.p1, k1

    def neighbor_line(seg_idx: int, node_key: Tuple[float, float]) -> Optional[int]:
        """node_key에서 seg_idx가 아닌 다른 LineSeg 인덱스 (degree-2 전제)."""
        lines_here = node_to_lines.get(node_key, [])
        for j in lines_here:
            if j != seg_idx:
                return j
        return None

    for start_idx in range(len(split_lines)):
        if start_idx in used:
            continue
        seg = split_lines[start_idx]
        k1 = pkey(seg.p1)
        k2 = pkey(seg.p2)

        # 이 체인에 포함되는 세그먼트 인덱스들 (확장 중 중복 방지용 로컬)
        chain_local: Set[int] = {start_idx}

        # 한쪽(p1) 방향 확장
        end1_pt = seg.p1
        end1_key = k1
        cur_idx = start_idx
        cur_node = k1
        while is_removable(cur_node):
            nxt = neighbor_line(cur_idx, cur_node)
            if nxt is None or nxt in chain_local or nxt in used:
                break
            chain_local.add(nxt)
            end1_pt, end1_key = other_endpoint(nxt, cur_node)
            cur_idx = nxt
            cur_node = end1_key

        # 반대(p2) 방향 확장
        end2_pt = seg.p2
        end2_key = k2
        cur_idx = start_idx
        cur_node = k2
        while is_removable(cur_node):
            nxt = neighbor_line(cur_idx, cur_node)
            if nxt is None or nxt in chain_local or nxt in used:
                break
            chain_local.add(nxt)
            end2_pt, end2_key = other_endpoint(nxt, cur_node)
            cur_idx = nxt
            cur_node = end2_key

        used |= chain_local

        # removable 노드로만 이루어진 고립 루프 스킵 (양 끝이 같은 removable 노드)
        if end1_key == end2_key and is_removable(end1_key):
            continue

        if len(chain_local) == 1:
            # 병합 없이 원본 유지
            result.append(split_lines[start_idx])
        else:
            result.append(LineSeg(end1_pt, end2_pt))

    return result

