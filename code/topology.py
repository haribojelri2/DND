from __future__ import annotations
import math
import copy
from typing import List, Tuple, Optional, Any, Dict, Set

from core import *
from geometry import *

def unify_edge_directions(segments, tolerance=INTER_MERGE_TOL, start_direction="CCW"):
    edges = [Edge(seg) for seg in segments]
    if not edges:
        return []

    all_pts = []
    for i, edge in enumerate(edges):
        all_pts.append((edge.start, i))
        all_pts.append((edge.end, i))

    cx_c = sum(p[0] for p, _ in all_pts) / len(all_pts)
    cy_c = sum(p[1] for p, _ in all_pts) / len(all_pts)

    # 1단계: 최외곽점 찾기
    best = max(
        ((dist(p, (cx_c, cy_c)), -i, p[0], p[1], p, i) for p, i in all_pts),
        key=lambda t: (t[0], t[1], t[2], t[3]),
    )
    outer_point = best[4]

    wants_ccw = (start_direction.upper() == "CCW")
    rx = outer_point[0] - cx_c
    ry = outer_point[1] - cy_c
    t_ccw = (-ry, rx) if wants_ccw else (ry, -rx)

    # 2단계: outer_point에 붙은 엣지 중 CCW 방향에 맞는 시작 엣지 선택 (가상 계산, 실제 reverse 없음)
    best_start_idx = None
    max_dot = -float('inf')

    for i, edge in enumerate(edges):
        s_near = dist(edge.start, outer_point) <= tolerance
        e_near = dist(edge.end,   outer_point) <= tolerance
        if not s_near and not e_near:
            continue
        if s_near:
            dx = edge.end[0] - edge.start[0]
            dy = edge.end[1] - edge.start[1]
        else:
            dx = edge.start[0] - edge.end[0]
            dy = edge.start[1] - edge.end[1]
        dot = dx * t_ccw[0] + dy * t_ccw[1]
        if dot > max_dot:
            max_dot = dot
            best_start_idx = i

    start_idx = best_start_idx if best_start_idx is not None else 0
    e0 = edges[start_idx]
    if dist(e0.start, outer_point) > dist(e0.end, outer_point):
        e0.reverse()

    visited = set([start_idx])
    dfs_order = [start_idx]
    stack = [start_idx]

    def correct_and_push(current_edge, j, next_edge, start_near, end_near):
        """방향 보정 후 push. 규칙: 라인-라인/아크-아크 = 꼬리물기, 라인->아크 = arc rule, 아크->라인 = arc exit tangent"""
        if current_edge.edge_type == 'LINE' and next_edge.edge_type == 'LINE':
            # 라인->라인: 꼬리물기
            if end_near and not start_near:
                next_edge.reverse()

        elif current_edge.edge_type == 'ARC' and next_edge.edge_type == 'ARC':
            # 아크->아크: 꼬리물기
            if end_near and not start_near:
                next_edge.reverse()

        elif current_edge.edge_type == 'LINE' and next_edge.edge_type == 'ARC':
            # 라인->아크: 회원님 규칙 (현의 중점 기준)
            apply_arc_direction_rule(next_edge, current_edge, tolerance)

        elif current_edge.edge_type == 'ARC' and next_edge.edge_type == 'LINE':
            # 아크->라인: 아크 exit tangent 기준
            junc = current_edge.end
            T = arc_unit_tangent_outward(current_edge, junc, tolerance)
            if T is not None:
                # 라인이 junc에서 출발하는 방향 벡터
                if start_near:
                    wx = next_edge.end[0] - next_edge.start[0]
                    wy = next_edge.end[1] - next_edge.start[1]
                else:
                    wx = next_edge.start[0] - next_edge.end[0]
                    wy = next_edge.start[1] - next_edge.end[1]
                # tangent와 선의 방향이 일치하면 start가 junc에 붙어야 함
                dot = wx * T[0] + wy * T[1]
                if dot >= 0:
                    # 라인이 tangent 방향으로 나감 → start가 junc
                    if end_near and not start_near:
                        next_edge.reverse()
                else:
                    # 라인이 tangent 반대 방향 → end가 junc
                    if start_near and not end_near:
                        next_edge.reverse()
            else:
                # fallback: 꼬리물기
                if end_near and not start_near:
                    next_edge.reverse()

        visited.add(j)
        dfs_order.append(j)
        stack.append(j)

    while stack:
        current_idx = stack.pop()
        current_edge = edges[current_idx]
        cur_end = current_edge.end

        for j, next_edge in enumerate(edges):
            if j in visited:
                continue
            start_near = dist(next_edge.start, cur_end) <= tolerance
            end_near   = dist(next_edge.end,   cur_end) <= tolerance
            if not start_near and not end_near:
                continue
            correct_and_push(current_edge, j, next_edge, start_near, end_near)

    # 미연결 잔여 엣지 처리
    while len(visited) < len(edges):
        for i in range(len(edges)):
            if i not in visited:
                start_idx = i
                break
        visited.add(start_idx)
        dfs_order.append(start_idx)
        stack = [start_idx]

        while stack:
            current_idx = stack.pop()
            current_edge = edges[current_idx]
            cur_end = current_edge.end

            for j, next_edge in enumerate(edges):
                if j in visited:
                    continue
                start_near = dist(next_edge.start, cur_end) <= tolerance
                end_near   = dist(next_edge.end,   cur_end) <= tolerance
                if not start_near and not end_near:
                    continue
                correct_and_push(current_edge, j, next_edge, start_near, end_near)

    return [edges[idx] for idx in dfs_order]

def apply_line_direction_rule(edge, prev_edge_end, tolerance=INTER_MERGE_TOL):
    """
    규칙 1: 라인 방향 통일
    이전 엣지와 만나는 점이 끝점이면 시작점이어야 하고, 시작점이면 끝점이어야 함
    """
    if edge.edge_type != 'LINE':
        return
    start_connects = dist(edge.start, prev_edge_end) <= tolerance
    end_connects = dist(edge.end, prev_edge_end) <= tolerance
    if end_connects and not start_connects:
        edge.reverse()

def apply_arc_direction_rule(edge, prev_edge, tolerance=INTER_MERGE_TOL):
    """
    라인->아크 방향 결정 규칙:
    - 현의 중점(chord midpoint)과 라인 끝점의 상대 위치로 판단
    - dot >= 0 (현의 중점이 진행방향 쪽): arc START가 라인 끝점과 만남
    - dot <  0 (현의 중점이 반대방향 쪽): arc END가 라인 끝점과 만남
    아크->아크: 이전 흐름 꼬리물기
    """
    if edge.edge_type != 'ARC':
        return

    prev_end = prev_edge.end
    start_near = dist(edge.start, prev_end) <= tolerance
    end_near   = dist(edge.end,   prev_end) <= tolerance

    # 아크->아크: 이전 아크의 흐름 그대로
    if prev_edge.edge_type == 'ARC':
        if end_near and not start_near:
            edge.reverse()
        return

    # 라인->아크: 현의 중점으로 방향 결정
    # 현의 중점 = arc의 시작점과 끝점의 단순 중간점 (orientation 무관하게 동일)
    chord_mid_x = (edge.start[0] + edge.end[0]) / 2
    chord_mid_y = (edge.start[1] + edge.end[1]) / 2

    # 라인 방향 벡터
    ldx = prev_edge.end[0] - prev_edge.start[0]
    ldy = prev_edge.end[1] - prev_edge.start[1]

    # 라인 끝점 -> 현의 중점 벡터
    cdx = chord_mid_x - prev_end[0]
    cdy = chord_mid_y - prev_end[1]

    dot = ldx * cdx + ldy * cdy

    if dot >= 0:
        # 현의 중점이 진행방향 쪽 -> arc START가 라인 끝점에 붙어야 함
        if end_near and not start_near:
            edge.reverse()
    else:
        # 현의 중점이 반대방향 쪽 -> arc END가 라인 끝점에 붙어야 함
        if start_near and not end_near:
            edge.reverse()

def arc_tangent_unit_at_end_forward(arc_edge):
    """ARC start→end로 따라갈 때 끝점에서 나가는 단위 접선."""
    d = arc_edge._data
    px, py = float(arc_edge.end[0]), float(arc_edge.end[1])
    cx, cy = float(d.cx), float(d.cy)
    rx, ry = px - cx, py - cy
    ta = math.degrees(math.atan2(arc_edge.start[1] - cy, arc_edge.start[0] - cx)) % 360.0
    tb = math.degrees(math.atan2(arc_edge.end[1] - cy, arc_edge.end[0] - cx)) % 360.0
    L1 = ccw_delta_deg(ta, tb)
    L2 = 360.0 - L1
    pm = getattr(d, "p_mid_curve", None)
    ccw = arc_should_use_ccw_sweep(ta, tb, L1, L2, cx, cy, d.r, pm)
    if ccw:
        tx, ty = -ry, rx
    else:
        tx, ty = ry, -rx
    mag = math.hypot(tx, ty)
    if mag < 1e-12:
        return (1.0, 0.0)
    return (tx / mag, ty / mag)

def arc_tangent_unit_at_start_forward(arc_edge):
    """ARC start→end 진행 시 시작점에서의 단위 접선."""
    d = arc_edge._data
    px, py = float(arc_edge.start[0]), float(arc_edge.start[1])
    cx, cy = float(d.cx), float(d.cy)
    rx, ry = px - cx, py - cy
    ta = math.degrees(math.atan2(arc_edge.start[1] - cy, arc_edge.start[0] - cx)) % 360.0
    tb = math.degrees(math.atan2(arc_edge.end[1] - cy, arc_edge.end[0] - cx)) % 360.0
    L1 = ccw_delta_deg(ta, tb)
    L2 = 360.0 - L1
    pm = getattr(d, "p_mid_curve", None)
    ccw = arc_should_use_ccw_sweep(ta, tb, L1, L2, cx, cy, d.r, pm)
    if ccw:
        tx, ty = -ry, rx
    else:
        tx, ty = ry, -rx
    mag = math.hypot(tx, ty)
    if mag < 1e-12:
        return (1.0, 0.0)
    return (tx / mag, ty / mag)

def arc_unit_tangent_outward(arc_edge, junction_pt, tolerance=INTER_MERGE_TOL):
    """접점에서 호를 따라 나온 뒤 다음 세그먼트로 이어질 때 단위 접선(호 밖 방향)."""
    if arc_edge.edge_type != 'ARC':
        return None
    d_end = dist(arc_edge.end, junction_pt)
    d_start = dist(arc_edge.start, junction_pt)
    if d_end <= tolerance and d_start > tolerance:
        return arc_tangent_unit_at_end_forward(arc_edge)
    if d_start <= tolerance and d_end > tolerance:
        tx, ty = arc_tangent_unit_at_start_forward(arc_edge)
        return (-tx, -ty)
    if d_start <= tolerance and d_end <= tolerance:
        return arc_tangent_unit_at_end_forward(arc_edge)
    return None

def apply_line_direction_rule_from_arc(line, arc_edge, junction_pt, tolerance=INTER_MERGE_TOL):
    """
    호 출구 접점 J에서 직선: 화살표(시작→끝)가 호 접선 T와 같은 방향 쪽이 되도록 둔다.
    후보는 (start=J, end=먼점) → 벡터 w 와 (start=먼점, end=J) → 벡터 -w 중,
    w·T 와 (-w)·T 중 더 큰 쪽을 택한다. 180°로 갈라진 두 직선도 둘 다 T와 '같은 방향'으로 맞출 수 있다.
    """
    if line.edge_type != 'LINE':
        return
    T = arc_unit_tangent_outward(arc_edge, junction_pt, tolerance)
    if T is None:
        apply_line_direction_rule(line, junction_pt, tolerance)
        return
    ds = dist(line.start, junction_pt)
    de = dist(line.end, junction_pt)
    if ds <= tolerance and de > tolerance:
        far = line.end
    elif de <= tolerance and ds > tolerance:
        far = line.start
    else:
        apply_line_direction_rule(line, junction_pt, tolerance)
        return
    wx = float(far[0]) - float(junction_pt[0])
    wy = float(far[1]) - float(junction_pt[1])
    if math.hypot(wx, wy) < 1e-12:
        return
    w_dot = wx * T[0] + wy * T[1]
    neg_w_dot = -w_dot
    if w_dot >= neg_w_dot:
        if not (ds <= tolerance and de > tolerance):
            line.reverse()
    else:
        if not (de <= tolerance and ds > tolerance):
            line.reverse()

def apply_arc_exit_tangent_to_incident_lines(edges, tolerance=INTER_MERGE_TOL):
    """
    각 호의 끝점(출구)에서 만나는 모든 직선에 접선 규칙 적용.
    DFS 순서·호→호 연결 여부와 무관(후처리).
    """
    for arc_edge in edges:
        if arc_edge.edge_type != 'ARC':
            continue
        junc = arc_edge.end
        for line_edge in edges:
            if line_edge.edge_type != 'LINE':
                continue
            if dist(line_edge.start, junc) > tolerance and dist(line_edge.end, junc) > tolerance:
                continue
            apply_line_direction_rule_from_arc(line_edge, arc_edge, junc, tolerance)


def insert_clearance_nodes(unified_edges, tol=1.0, *, n_arc_indices=None, u_arc_indices=None, cfg=None):
    """
    AGV 대기 노드 삽입 — PPT (슬라이드 1~9) 규칙 적용.

    Naming rule (Slide 1):
      - J1 (*1): 다른 분기와 맞닿은 포인트 → 분기 기준점으로부터 350mm **downstream** (outgoing LINE)
      - J2 (*2): 직선 구간을 통과하는 포인트 → 분기 기준점으로부터 upstream (incoming LINE)
      - J3 (*3): 곡선(ARC) 구간을 통과하는 포인트 → ARC 시작/끝에서 350mm 떨어진 ARC 위의 점

    규칙:
      - 일반 L/R 분기:
          X = Max(860+40, 525) = 900
          Diverge(arc.start가 junction):
            in_edges[j] = LINE 1, out_edges[j] = LINE 1 + ARC 1
            J1 = outgoing LINE에서 junction→downstream 350mm
            J2 = incoming LINE에서 junction으로부터 upstream 900mm
            J3 = ARC에서 arc.start로부터 arc-length 350mm
          Merge(arc.end가 junction):
            in_edges[j] = LINE 1 + ARC 1, out_edges[j] = LINE 1
            J1 = outgoing LINE에서 junction→downstream 350mm
            J2 = incoming LINE에서 junction으로부터 upstream 900mm
            J3 = ARC에서 arc.end로부터 역방향 arc-length 350mm
      - N분기 (arc_pair):
          Y = 중간 직선 길이 (arc→LINE→arc 인 경우)
            Y >= 750 → J2_dist = 1500 (1400 + 100 safety)
            Y <  750 → J2_dist = 1560 (1460 + 100 safety)
          J1 = 350 downstream, J2 = J2_dist upstream. J3 없음. 양쪽 junction 모두 적용.
      - 복합분기 (arc_pair):
          X = dist(first_arc.start, last_arc.end)
            X < 1600  → J1=350, J2=800 upstream (U로 판단 및 복합분기 규칙 적용 )
            X >= 1600 → J1=350, J2=900 upstream (복합분기)
          J3 없음.
    """
    from collections import defaultdict
    from core import dist, LineSeg, Edge

    # 회전방향(L/R) 스냅샷: 아래 clearance 로직이 호 끝점을 인접 직선(접선) 방향으로 밀어
    # **원 밖(off-circle)** 으로 보내면, 끝점 기반 회전판정(arc_link_type_from_arcseg)이 뒤집힐 수
    # 있다. 아직 모든 호가 on-circle 인 지금 올바른 회전을 전용 속성에 기록해 두면,
    # map_exporter.edge_path_length_mm 의 off-circle 길이 보정이 신뢰 가능한 회전을 쓴다.
    try:
        from map_exporter import arc_link_type_from_arcseg as _altfa_rot
        for _re in unified_edges:
            if getattr(_re, "edge_type", None) == "ARC" and getattr(_re, "_rot_link_type", None) is None:
                try:
                    _re._rot_link_type = _altfa_rot(_re._data)
                except Exception:
                    pass
    except Exception:
        pass

    # --- PPT 상수 (config 우선, 없으면 기본값) ---
    _cn = (cfg or {}).get("clearance_nodes", {})
    _dn = (cfg or {}).get("driving_nodes", {})
    J1_DOWNSTREAM        = _cn.get("j1_downstream", 350.0)
    J3_ARC_LEN           = _cn.get("j3_arc_len", 350.0)
    LR_J2_UPSTREAM       = _cn.get("lr_j2_upstream", 900.0)
    N_LONG_J2            = _cn.get("n_long_j2", 1500.0)
    N_SHORT_J2           = _cn.get("n_short_j2", 1560.0)
    N_STRAIGHT_THRESHOLD = _cn.get("n_straight_threshold", 750.0)
    DRIVING_NODE_MIN_LEN = _dn.get("min_length", 4000.0)
    DRIVING_NODE_MIN_SEG = _dn.get("min_segment", 2000.0)

    _n_pairs = [p for p in (n_arc_indices or [])]
    _u_pairs_all = [p for p in (u_arc_indices or [])]

    def _snap(v):
        d = int(SNAP_DECIMALS)
        if d <= 0:
            return float(int(round(float(v))))
        return round(float(v), d)

    def _v(p):
        cell = max(float(tol), 0.1)
        return (int(math.floor(float(p[0]) / cell)), int(math.floor(float(p[1]) / cell)))

    # --- 인접 그래프 ---
    in_edges = defaultdict(list)
    out_edges = defaultdict(list)
    for i, e in enumerate(unified_edges):
        in_edges[_v(e.end)].append((i, e))
        out_edges[_v(e.start)].append((i, e))

    # --- [1단계] 복합분기(L/R 쌍) 탐지 — 가장 먼저 수행 ---
    # 조건:
    #   1) diverge junction at arc.start (inLINE=1, inARC=0, outLINE=1, outARC=1)
    #   2) outgoing LINE 끝이 merge junction (inLINE=1, inARC=1, outLINE=1, outARC=0)
    #   3) div_arc.end → (BFS, top_line 제외) → mer_arc.start 경로 존재
    # 탐지된 arc에는 플래그(_complex_lr_flat)를 부여, 이후 모든 탐색에서 제외

    def _collect_arm_edge_path(start_vkey, target_vkey, exclude_edge_idx, exclude_set=None):
        """BFS로 start_vkey → target_vkey 경로 (edge index 순서 리스트) 반환 (top LINE 및 exclude_set 제외)."""
        from collections import deque
        _excl = exclude_set or set()
        visited = {start_vkey}
        q = deque([(start_vkey, [])])
        while q:
            cur, path = q.popleft()
            for ei, ee in out_edges.get(cur, []):
                if ei == exclude_edge_idx or ei in _excl:
                    continue
                nv = _v(ee.end)
                new_path = path + [ei]
                if nv == target_vkey:
                    return new_path
                if nv not in visited:
                    visited.add(nv)
                    q.append((nv, new_path))
        return []

    def _find_shortest_undirected_path(start_v, end_v, exclude_edges):
        from collections import deque
        q = deque([(start_v, [])])
        visited = {start_v}
        while q:
            cur, path = q.popleft()
            if cur == end_v:
                return path
            for ei, ee in out_edges.get(cur, []):
                if ei in exclude_edges:
                    continue
                nv = _v(ee.end)
                if nv not in visited:
                    visited.add(nv)
                    q.append((nv, path + [ei]))
            for ei, ee in in_edges.get(cur, []):
                if ei in exclude_edges:
                    continue
                nv = _v(ee.start)
                if nv not in visited:
                    visited.add(nv)
                    q.append((nv, path + [ei]))
        return None

    _complex_lr_pairs = []        # (diverge_arc_idx, merge_arc_idx, top_line_idx, arm_path) — X>=1601
    _small_x_complex_lr_pairs = []  # 같은 구조인데 X<1601 — U 노드 규칙 적용
    _u_arm_pairs = []             # arm이 단일 U(분할된 두 호)인 복합분기. arm은 U분기로 유지(흡수X)
    _small_x_no_arm_pairs = []    # arm=[] X<1601 — U가 처리하되 흡수는 여기서
    _u_no_arm_pairs = []          # same-direction no-arm X<1601 — 순수 U분기(단일 U링크 유지, plain_arc 제외)
    _plain_no_arm_pairs = []      # arm=[] X>=1601 — 일반 호직호(복합 아님). plain_arc로 처리
    _complex_lr_flat = set()  # 복합분기 arc 인덱스 플래그
    _intra_arm_u_idx = set()  # arm 내부 U 아크 (개별 U/L/R 처리 없음 — 복합분기가 전체 담당)
    _already_paired = set()

    # [사전] 그래프에서 X <= 1600 U 아크 인덱스 미리 수집 — 복합분기 탐지 전에 확보
    _U_X_PRE = 1601.0
    _pre_u_idx = set(idx for pair in (u_arc_indices or []) for idx in pair)
    for _i, _arc in enumerate(unified_edges):
        if _arc.edge_type != "ARC" or _i in _pre_u_idx:
            continue
        _ve = _v(_arc.end)
        for _j, _ne in out_edges.get(_ve, []):
            if _j in _pre_u_idx:
                continue
            if _ne.edge_type == "ARC":
                if dist(_arc.start, _ne.end) < _U_X_PRE:
                    _pre_u_idx.add(_i)
                    _pre_u_idx.add(_j)
                break
            elif _ne.edge_type == "LINE":
                _vm = _v(_ne.end)
                for _k, _te in out_edges.get(_vm, []):
                    if _k in _pre_u_idx or _k == _i:
                        continue
                    if _te.edge_type == "ARC":
                        if dist(_arc.start, _te.end) < _U_X_PRE:
                            _pre_u_idx.add(_i)
                            _pre_u_idx.add(_j)
                            _pre_u_idx.add(_k)
                    break
                break

    _nu_branch_idx = _pre_u_idx | set(idx for pair in (n_arc_indices or []) for idx in pair)
    _n_arc_idx_set = set(idx for pair in (n_arc_indices or []) for idx in pair)

    def _is_u_arc(idx):
        """아크가 X<1600 U 쌍에 속하는지 양방향 전수 확인 (pre-scan 누락 보완)."""
        ae = unified_edges[idx]
        if ae.edge_type != "ARC":
            return False
        # arc1 역할: forward — ae.end 이후 모든 이웃 검사
        ve = _v(ae.end)
        for _bj, _be in out_edges.get(ve, []):
            if _be.edge_type == "ARC":
                if dist(ae.start, _be.end) < _U_X_PRE:
                    return True
                # X >= 1600이어도 break 없이 다음 이웃 계속 검사
            elif _be.edge_type == "LINE":
                _vm = _v(_be.end)
                for _ck, _ce in out_edges.get(_vm, []):
                    if _ce.edge_type == "ARC":
                        if dist(ae.start, _ce.end) < _U_X_PRE:
                            return True
                        break  # LINE 뒤 첫 ARC만 검사
                    break
        # arc2 역할: backward — ae.start 이전 모든 이웃 검사
        vs = _v(ae.start)
        for _bj, _be in in_edges.get(vs, []):
            if _be.edge_type == "ARC":
                if dist(_be.start, ae.end) < _U_X_PRE:
                    return True
            elif _be.edge_type == "LINE":
                _vm = _v(_be.start)
                for _ck, _ce in in_edges.get(_vm, []):
                    if _ce.edge_type == "ARC":
                        if dist(_ce.start, ae.end) < _U_X_PRE:
                            return True
                        break
                    break
        return False

    for i, arc in enumerate(unified_edges):
        if arc.edge_type != "ARC" or i in _already_paired:
            continue
        if i in _n_arc_idx_set:
            continue  # N 분기 아크를 div arc 후보에서 제외
        js = _v(arc.start)
        in_js  = in_edges.get(js, [])
        out_js = out_edges.get(js, [])
        if not (sum(1 for _, e in in_js  if e.edge_type == "LINE") == 1 and
                sum(1 for _, e in in_js  if e.edge_type == "ARC")  == 0 and
                sum(1 for _, e in out_js if e.edge_type == "LINE") == 1 and
                sum(1 for _, e in out_js if e.edge_type == "ARC")  == 1):
            continue  # diverge junction 아님
        out_lines = [(oi, oe) for oi, oe in out_js if oe.edge_type == "LINE"]
        if not out_lines:
            continue
        top_line_idx, top_line_e = out_lines[0]
        vb = _v(top_line_e.end)
        in_vb  = in_edges.get(vb, [])
        out_vb = out_edges.get(vb, [])
        if not (sum(1 for _, e in in_vb  if e.edge_type == "LINE") == 1 and
                sum(1 for _, e in in_vb  if e.edge_type == "ARC")  == 1 and
                sum(1 for _, e in out_vb if e.edge_type == "LINE") == 1 and
                sum(1 for _, e in out_vb if e.edge_type == "ARC")  == 0):
            continue  # top LINE 끝이 merge junction 아님
        merge_arcs = [(mi, me) for mi, me in in_vb if me.edge_type == "ARC"]
        if not merge_arcs:
            continue
        merge_arc_idx = merge_arcs[0][0]
        if merge_arc_idx in _already_paired:
            continue
        if merge_arc_idx in _n_arc_idx_set:
            continue  # N 분기 아크를 merge arc 후보에서 제외
        # 방향 검사: div_arc와 mer_arc의 원 중심이 top_LINE 기준 같은 쪽이어야 복합분기
        # 반대쪽이면 S-커브 호직호 → plain/small_no_arm 처리
        _mer_arc_e = merge_arcs[0][1]
        _tl_dx = top_line_e.end[0] - top_line_e.start[0]
        _tl_dy = top_line_e.end[1] - top_line_e.start[1]
        _div_side = _tl_dx * (arc._data.cy - top_line_e.start[1]) - _tl_dy * (arc._data.cx - top_line_e.start[0])
        _mer_side = _tl_dx * (_mer_arc_e._data.cy - top_line_e.start[1]) - _tl_dy * (_mer_arc_e._data.cx - top_line_e.start[0])
        if _div_side * _mer_side < -1e-6:
            # 반대 방향 → 호직호
            _pX = dist(arc.start, _mer_arc_e.end)
            if _pX < 1601.0:
                _small_x_no_arm_pairs.append((i, merge_arcs[0][0], top_line_idx))
            else:
                _plain_no_arm_pairs.append((i, merge_arcs[0][0], top_line_idx))
            _already_paired.add(i)
            _already_paired.add(merge_arcs[0][0])
            continue

        # 내부 arm 연결 확인: div_arc.end → mer_arc.start (top LINE 제외)
        div_arc_end_v = _v(arc.end)
        mer_arc_start_v = _v(merge_arcs[0][1].start)
        _pair_X_pre = dist(arc.start, merge_arcs[0][1].end)
        arm_path = _collect_arm_edge_path(div_arc_end_v, mer_arc_start_v, exclude_edge_idx=top_line_idx, exclude_set=_nu_branch_idx)
        arm_indices = set(arm_path)

        _pair_X = dist(arc.start, merge_arcs[0][1].end)
        _arm_u_idx = {ai for ai in arm_indices if _is_u_arc(ai) or ai in _pre_u_idx}

        # arm 내부 arc 쌍(mer_arc2, div_arc2) 추출
        _arm_arc_list = [(ai, unified_edges[ai]) for ai in arm_path
                         if unified_edges[ai].edge_type == "ARC"]

        # directed BFS가 arc 2개짜리 arm을 못 찾으면 5-hop 직접 탐색
        if len(_arm_arc_list) != 2:
            arm_path = []
            arm_indices = set()
            _arm_u_idx = set()
            _arm_arc_list = []
            _excl = {top_line_idx, i, merge_arc_idx}
            for _l1i, _l1e in (list(out_edges.get(div_arc_end_v, [])) + list(in_edges.get(div_arc_end_v, []))):
                if _l1e.edge_type != "LINE" or _l1i in _excl: continue
                _v1a = _v(_l1e.end) if _v(_l1e.start) == div_arc_end_v else _v(_l1e.start)
                for _a1i, _a1e in (list(out_edges.get(_v1a, [])) + list(in_edges.get(_v1a, []))):
                    if _a1e.edge_type != "ARC" or _a1i in _excl: continue
                    _v2 = _v(_a1e.end) if _v(_a1e.start) == _v1a else _v(_a1e.start)
                    for _l2i, _l2e in (list(out_edges.get(_v2, [])) + list(in_edges.get(_v2, []))):
                        if _l2e.edge_type != "LINE" or _l2i in _excl or _l2i == _l1i: continue
                        _v3 = _v(_l2e.end) if _v(_l2e.start) == _v2 else _v(_l2e.start)
                        for _a2i, _a2e in (list(out_edges.get(_v3, [])) + list(in_edges.get(_v3, []))):
                            if _a2e.edge_type != "ARC" or _a2i in _excl or _a2i == _a1i: continue
                            _v4 = _v(_a2e.end) if _v(_a2e.start) == _v3 else _v(_a2e.start)
                            for _l3i, _l3e in (list(out_edges.get(_v4, [])) + list(in_edges.get(_v4, []))):
                                if _l3e.edge_type != "LINE" or _l3i in _excl or _l3i in {_l1i, _l2i}: continue
                                _v5 = _v(_l3e.end) if _v(_l3e.start) == _v4 else _v(_l3e.start)
                                if _v5 == mer_arc_start_v:
                                    arm_path = [_l1i, _a1i, _l2i, _a2i, _l3i]
                                    break
                            if arm_path: break
                        if arm_path: break
                    if arm_path: break
                if arm_path: break
            if arm_path:
                arm_indices = set(arm_path)
                _arm_u_idx = {ai for ai in arm_indices if _is_u_arc(ai) or ai in _pre_u_idx}
                _arm_arc_list = [(ai, unified_edges[ai]) for ai in arm_path
                                 if unified_edges[ai].edge_type == "ARC"]

        # 5-hop 실패 시 rigid 4-hop [LINE, ARC, ARC, LINE] 탐색
        # (단일 U 호가 180° 분할로 두 호가 된 복합분기 arm. div_end→LINE→ARC→ARC→LINE→mer_start)
        if len(_arm_arc_list) != 2:
            _excl4 = {top_line_idx, i, merge_arc_idx}
            _found4 = None
            for _l1i, _l1e in (list(out_edges.get(div_arc_end_v, [])) + list(in_edges.get(div_arc_end_v, []))):
                if _l1e.edge_type != "LINE" or _l1i in _excl4: continue
                _v1a = _v(_l1e.end) if _v(_l1e.start) == div_arc_end_v else _v(_l1e.start)
                for _a1i, _a1e in (list(out_edges.get(_v1a, [])) + list(in_edges.get(_v1a, []))):
                    if _a1e.edge_type != "ARC" or _a1i in _excl4 or _a1i in _n_arc_idx_set: continue
                    _v2 = _v(_a1e.end) if _v(_a1e.start) == _v1a else _v(_a1e.start)
                    for _a2i, _a2e in (list(out_edges.get(_v2, [])) + list(in_edges.get(_v2, []))):
                        if _a2e.edge_type != "ARC" or _a2i in _excl4 or _a2i == _a1i or _a2i in _n_arc_idx_set: continue
                        _v3 = _v(_a2e.end) if _v(_a2e.start) == _v2 else _v(_a2e.start)
                        for _l2i, _l2e in (list(out_edges.get(_v3, [])) + list(in_edges.get(_v3, []))):
                            if _l2e.edge_type != "LINE" or _l2i in _excl4 or _l2i == _l1i: continue
                            _v4 = _v(_l2e.end) if _v(_l2e.start) == _v3 else _v(_l2e.start)
                            if _v4 == mer_arc_start_v:
                                _found4 = [_l1i, _a1i, _a2i, _l2i]
                                break
                        if _found4: break
                    if _found4: break
                if _found4: break
            if _found4:
                # 단일 U arm(분할된 두 호): X = dist(div_arc.end, mer_arc.start)
                _Xu = dist(arc.end, merge_arcs[0][1].start)
                if _Xu < _pair_X:
                    # _found4 = [_l1i, _a1i, _a2i, _l2i] — 두 ARC가 분할된 U
                    _arm_u_arcs = tuple(ai for ai in _found4
                                        if unified_edges[ai].edge_type == "ARC")
                    # div/mer는 복합분기 타입, arm U는 U분기로 보존(흡수·제외 안함)
                    _complex_lr_flat.add(i)
                    _complex_lr_flat.add(merge_arc_idx)
                    _u_arm_pairs.append((i, merge_arc_idx, top_line_idx, _found4, _arm_u_arcs))
                    _already_paired.add(i)
                    _already_paired.add(merge_arc_idx)
                    continue

        # 내부 호가 first-pass U 탐지(ori 기하 기반)에 속하면 진짜 U분기
        _inner_arcs = [ai for ai in arm_path if unified_edges[ai].edge_type == "ARC"]
        _inner_is_u = any((ai in _pre_u_idx) or _is_u_arc(ai) for ai in _inner_arcs)

        if len(_arm_arc_list) < 2:
            # arm 없음: div/mer가 first-pass U면 U, 아니면 호직호
            if _pair_X < 1601.0 and ((i in _pre_u_idx) or _is_u_arc(i)):
                _u_no_arm_pairs.append((i, merge_arc_idx, top_line_idx))
            elif _pair_X < 1601.0:
                _small_x_no_arm_pairs.append((i, merge_arc_idx, top_line_idx))
            else:
                _plain_no_arm_pairs.append((i, merge_arc_idx, top_line_idx))
            _already_paired.add(i)
            _already_paired.add(merge_arc_idx)
            continue

        # X = dist(div_arc2.start, mer_arc2.end) — arm_path 순서: mer_arc2 먼저, div_arc2 다음
        _mer_arc2_e = _arm_arc_list[0][1]
        _div_arc2_e = _arm_arc_list[1][1]
        _X = dist(_div_arc2_e.start, _mer_arc2_e.end)

        # 복합분기 유효성: pair_X > X 이어야 함 (X >= pair_X는 복합분기 아님 → U/호직호 처리)
        if _X >= _pair_X:
            if _pair_X < 1601.0 and _inner_is_u:
                # pair_X<1601 + 내부 호가 진짜 U → 순수 U분기(단일 U링크 유지)
                _u_no_arm_pairs.append((i, merge_arc_idx, top_line_idx))
            elif _pair_X < 1601.0:
                # U 아님 → 호직호로 보존(R-S-R 분리 렌더)
                _small_x_no_arm_pairs.append((i, merge_arc_idx, top_line_idx))
            else:
                _plain_no_arm_pairs.append((i, merge_arc_idx, top_line_idx))
            _already_paired.add(i)
            _already_paired.add(merge_arc_idx)
            continue

        if _X < 1601.0:
            if _pair_X < 1601.0 and _inner_is_u:
                # pair_X<1601 + 진짜 U → U 파이프라인에 위임
                _already_paired.add(i)
                _already_paired.add(merge_arc_idx)
                continue
            if _pair_X < 1601.0:
                # U 아님 → 호직호로 보존
                _small_x_no_arm_pairs.append((i, merge_arc_idx, top_line_idx))
                _already_paired.add(i)
                _already_paired.add(merge_arc_idx)
                continue
            _small_x_complex_lr_pairs.append((i, merge_arc_idx, top_line_idx, arm_path))
            _complex_lr_flat.add(i)
            _complex_lr_flat.add(merge_arc_idx)
            if _inner_is_u:
                # 바깥 pair_X>=1601(복합)이지만 arm이 진짜 U(호-직-호, X<1601)이면
                # arm U를 흡수하지 않고 단일 U로 보존한다. inner 호·선을 제외셋
                # (complex_lr_flat·intra_arm_u_idx)에 넣지 않아, clearance 이후
                # by_x 재탐지가 arc-line-arc 를 단일 U 링크로 병합하게 둔다.
                # 바깥 div/mer만 복합으로 처리. (arm geometry는 위 흡수 단계에서 불변)
                pass
            else:
                _complex_lr_flat.update(arm_indices - _arm_u_idx)
                _intra_arm_u_idx.update(_arm_u_idx)
            _already_paired.add(i)
            _already_paired.add(merge_arc_idx)
            continue

        # X >= 1601 → 진짜 복합분기
        _complex_lr_pairs.append((i, merge_arc_idx, top_line_idx, arm_path))
        _complex_lr_flat.add(i)
        _complex_lr_flat.add(merge_arc_idx)
        _complex_lr_flat.update(arm_indices - _arm_u_idx)
        _intra_arm_u_idx.update(_arm_u_idx)
        _already_paired.add(i)
        _already_paired.add(merge_arc_idx)

    # --- [2단계] U/N 분기 분류 (X <= 1600 → U, X > 1600 → 복합분기) ---
    U_X_THRESHOLD = 1601.0
    _u_pairs = []
    _complex_pairs = []
    for p in _u_pairs_all:
        if any(idx in _complex_lr_flat for idx in p):
            continue
        fa = unified_edges[p[0]]
        la = unified_edges[p[-1]]
        if fa.edge_type == "ARC" and la.edge_type == "ARC":
            X = dist(fa.start, la.end)
            if X < U_X_THRESHOLD:
                _u_pairs.append(p)
            else:
                _complex_pairs.append(p)
        else:
            _u_pairs.append(p)

    # 단순 분기/전환선 (파란색, 대형 및 소형 모두)도 U 분기로 간주하여 대칭 clearance 및 병합 처리
    for div_idx, mer_idx, top_line_idx in _plain_no_arm_pairs:
        _u_pairs.append((div_idx, mer_idx))
    for div_idx, mer_idx, top_line_idx in _small_x_no_arm_pairs:
        _u_pairs.append((div_idx, mer_idx))
    # 순수 U분기(same-dir no-arm): U쌍 등록 → second-pass가 단일 U링크로 그룹핑
    for div_idx, mer_idx, top_line_idx in _u_no_arm_pairs:
        _u_pairs.append((div_idx, mer_idx))
    # U-arm 복합분기: arm의 두 분할 U 호를 U 쌍으로 등록 → 단일 U 링크로 보존(350mm J1)
    for _ua in _u_arm_pairs:
        _u_pairs.append(_ua[4])



    # 그래프에서 직접 X < 1600 U쌍 추가 탐지 (전달받은 u_arc_indices 누락분 보완)

    _u_pairs_len_before_scan = len(_u_pairs)
    _u_covered = set(idx for pair in _u_pairs for idx in pair)
    _u_covered |= set(idx for pair in _complex_pairs for idx in pair)
    _u_covered |= _complex_lr_flat
    _u_covered |= set(idx for pair in _n_pairs for idx in pair)
    for i, arc in enumerate(unified_edges):
        if arc.edge_type != "ARC" or i in _u_covered:
            continue
            
        d = arc._data
        sa = float(getattr(d, "dxf_start_deg", getattr(d, "start_deg", 0)))
        ea = float(getattr(d, "dxf_end_deg", getattr(d, "end_deg", 0)))
        ccw = (ea - sa) % 360.0
        sweep = min(ccw, 360.0 - ccw)
        if abs(sweep - 180.0) <= 5.0:
            _u_pairs.append((i,))
            _u_covered.add(i)
            continue
        v_end = _v(arc.end)
        for j, next_e in out_edges.get(v_end, []):
            if j in _u_covered:
                continue
            if next_e.edge_type == "ARC":
                X = dist(arc.start, next_e.end)
                if X < U_X_THRESHOLD:
                    _u_pairs.append((i, j))
                    _u_covered.add(i)
                    _u_covered.add(j)
                    break
            elif next_e.edge_type == "LINE":
                v_mid = _v(next_e.end)
                found = False
                for k, third_e in out_edges.get(v_mid, []):
                    if k in _u_covered or k == i:
                        continue
                    if third_e.edge_type == "ARC":
                        X = dist(arc.start, third_e.end)
                        if X < U_X_THRESHOLD:
                            _u_pairs.append((i, j, k))
                            _u_covered.add(i)
                            _u_covered.add(j)
                            _u_covered.add(k)
                            found = True
                    break
                if not found:
                    for k, third_e in in_edges.get(v_mid, []):
                        if k in _u_covered or k == i or k == j:
                            continue
                        if third_e.edge_type == "ARC":
                            X = dist(arc.start, third_e.start)
                            if X < U_X_THRESHOLD:
                                _u_pairs.append((i, j, k))
                                _u_covered.add(i)
                                _u_covered.add(j)
                                _u_covered.add(k)
                        break

    # 그래프 스캔으로 새로 찾은 U 쌍만 객체로 저장 (post-clearance 인덱스 변환용)
    _graph_scan_u_pair_objs = [
        tuple(unified_edges[idx] for idx in pair)
        for pair in _u_pairs[_u_pairs_len_before_scan:]
    ]

    # _un_flat: 복합분기 전체(div/merge arc + arm arcs) + U분기 + N분기 — L/R 탐색 제외
    # _complex_pairs(X>1600 U후보)는 그냥 diverge 호직호 → L/R 루프가 J1+J2+J3 처리하도록 제외 안함
    _un_flat = (_complex_lr_flat
                | _intra_arm_u_idx
                | set(idx for pair in _u_pairs for idx in pair)
                | set(idx for pair in _n_pairs for idx in pair))

    # 분할 누적 버킷
    line_splits = defaultdict(list)   # edge_idx → [point, ...]
    arc_splits = defaultdict(list)    # edge_idx → [arc_length_from_start, ...]
    _absorbed_line_indices = set()    # arm의 첫/마지막 LINE이 arc에 흡수되면 여기 등록 → 재구성 시 제거
    _absorbed_arc_indices = set()     # LINE을 흡수한 ARC 인덱스 → 이격 처리 대상

    # ------------------ 보조 함수 ------------------
    def _add_line_split(line_idx, line_edge, pt):
        """pt가 line_edge 내부일 때만 분할점 추가."""
        if line_edge.edge_type != "LINE":
            return
        le = dist(line_edge.start, line_edge.end)
        if le < 1e-6:
            return
        if dist(line_edge.start, pt) + dist(pt, line_edge.end) < le + 1.0:
            line_splits[line_idx].append(pt)

    def _split_downstream_on_outgoing_line(junction_pt, dist_mm):
        """junction에서 나가는 LINE 상에서 junction→downstream dist_mm 지점 분할 (J1)."""
        v_j = _v(junction_pt)
        for out_i, out_e in out_edges.get(v_j, []):
            if out_e.edge_type != "LINE":
                continue
            dx = out_e.end[0] - out_e.start[0]
            dy = out_e.end[1] - out_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < dist_mm:
                continue
            ox, oy = dx / mag, dy / mag
            raw_pt = (junction_pt[0] + ox * dist_mm, junction_pt[1] + oy * dist_mm)
            tgt = (_snap(raw_pt[0]), _snap(raw_pt[1]))
            _add_line_split(out_i, out_e, tgt)

    def _split_upstream_on_incoming_line(junction_pt, dist_mm):
        """junction으로 들어오는 LINE 상에서 junction으로부터 upstream dist_mm 지점 분할 (J2)."""
        v_j = _v(junction_pt)
        for in_i, in_e in in_edges.get(v_j, []):
            if in_e.edge_type != "LINE":
                continue
            dx = in_e.end[0] - in_e.start[0]
            dy = in_e.end[1] - in_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < dist_mm:
                continue
            ox, oy = dx / mag, dy / mag
            raw_pt = (junction_pt[0] - ox * dist_mm, junction_pt[1] - oy * dist_mm)
            tgt = (_snap(raw_pt[0]), _snap(raw_pt[1]))
            _add_line_split(in_i, in_e, tgt)

    def _update_arc_deg(e, new_pt, is_start):
        """ARC 엣지의 start 또는 end가 new_pt로 바뀔 때 해당 각도를 재계산."""
        d = e._data
        cx, cy = float(d.cx), float(d.cy)
        new_deg = math.degrees(math.atan2(float(new_pt[1]) - cy, float(new_pt[0]) - cx)) % 360.0
        if is_start:
            d.start_deg = new_deg
        else:
            d.end_deg = new_deg

    def _move_junction_upstream(junction_pt, arc_edge, line_edge, dist_mm):
        """junction_pt를 incoming LINE 방향으로 dist_mm upstream 이동.
        junction에 연결된 모든 엣지의 해당 끝점과 ARC 각도를 같이 이동."""
        dx = line_edge.end[0] - line_edge.start[0]
        dy = line_edge.end[1] - line_edge.start[1]
        mag = math.hypot(dx, dy)
        if mag < dist_mm:
            return
        ox, oy = dx / mag, dy / mag
        new_pt = (_snap(junction_pt[0] - ox * dist_mm), _snap(junction_pt[1] - oy * dist_mm))
        v_j = _v(junction_pt)
        for _, e in in_edges.get(v_j, []):
            e.end = new_pt
            if e.edge_type == "LINE":
                e._data.p2 = new_pt
            elif e.edge_type == "ARC":
                e._data.p_end = new_pt
                _update_arc_deg(e, new_pt, is_start=False)
        for _, e in out_edges.get(v_j, []):
            e.start = new_pt
            if e.edge_type == "LINE":
                e._data.p1 = new_pt
            elif e.edge_type == "ARC":
                e._data.p_start = new_pt
                _update_arc_deg(e, new_pt, is_start=True)

    def _move_junction_downstream(junction_pt, arc_edge, line_edge, dist_mm):
        """junction_pt를 outgoing LINE 방향으로 dist_mm downstream 이동.
        junction에 연결된 모든 엣지의 해당 끝점과 ARC 각도를 같이 이동."""
        dx = line_edge.end[0] - line_edge.start[0]
        dy = line_edge.end[1] - line_edge.start[1]
        mag = math.hypot(dx, dy)
        if mag < dist_mm:
            return
        ox, oy = dx / mag, dy / mag
        new_pt = (_snap(junction_pt[0] + ox * dist_mm), _snap(junction_pt[1] + oy * dist_mm))
        v_j = _v(junction_pt)
        for _, e in in_edges.get(v_j, []):
            e.end = new_pt
            if e.edge_type == "LINE":
                e._data.p2 = new_pt
            elif e.edge_type == "ARC":
                e._data.p_end = new_pt
                _update_arc_deg(e, new_pt, is_start=False)
        for _, e in out_edges.get(v_j, []):
            e.start = new_pt
            if e.edge_type == "LINE":
                e._data.p1 = new_pt
            elif e.edge_type == "ARC":
                e._data.p_start = new_pt
                _update_arc_deg(e, new_pt, is_start=True)

    def _arc_geometry(arc_edge):
        """ARC의 (cx, cy, r, ta, tb, L1, L2, ccw, sweep_deg, total_len) 반환."""
        d = arc_edge._data
        cx = float(d.cx)
        cy = float(d.cy)
        r = float(d.r)
        ta = math.degrees(math.atan2(arc_edge.start[1] - cy, arc_edge.start[0] - cx)) % 360.0
        tb = math.degrees(math.atan2(arc_edge.end[1] - cy, arc_edge.end[0] - cx)) % 360.0
        L1 = ccw_delta_deg(ta, tb)
        L2 = 360.0 - L1
        pm = getattr(d, "p_mid_curve", None)
        ccw = arc_should_use_ccw_sweep(ta, tb, L1, L2, cx, cy, r, pm)
        sweep_deg = L1 if ccw else L2
        total_len = r * math.radians(sweep_deg)
        return cx, cy, r, ta, tb, L1, L2, ccw, sweep_deg, total_len

    def _compute_virtual_P(arc_edge, orig_start=None, orig_end=None):
        """Virtual intersection P of tangent lines at arc.start and arc.end.
        orig_start/orig_end: J1 이동 전 원래 좌표 (그래프 조회용). None이면 arc_edge.start/end 사용.
        Returns (px, py) or None if undetermined."""
        arc_s = orig_start if orig_start is not None else arc_edge.start
        arc_e = orig_end if orig_end is not None else arc_edge.end
        vs = _v(arc_s)
        ve = _v(arc_e)

        in_lines_s = [(ii, ie) for ii, ie in in_edges.get(vs, []) if ie.edge_type == "LINE"]
        out_lines_e = [(oi, oe) for oi, oe in out_edges.get(ve, []) if oe.edge_type == "LINE"]

        if not in_lines_s or not out_lines_e:
            return None

        in_e = in_lines_s[0][1]
        out_e = out_lines_e[0][1]

        dx1 = in_e.end[0] - in_e.start[0]
        dy1 = in_e.end[1] - in_e.start[1]
        mag1 = math.hypot(dx1, dy1)
        if mag1 < 1e-9:
            return None
        d1 = (dx1 / mag1, dy1 / mag1)  # forward direction into arc.start

        dx2 = out_e.end[0] - out_e.start[0]
        dy2 = out_e.end[1] - out_e.start[1]
        mag2 = math.hypot(dx2, dy2)
        if mag2 < 1e-9:
            return None
        d2 = (-dx2 / mag2, -dy2 / mag2)  # backward direction toward arc.end

        # Solve: arc.start + t*d1 = arc.end + s*d2
        ax, ay = arc_s
        bx, by = arc_e
        det = d1[0] * (-d2[1]) - d1[1] * (-d2[0])
        if abs(det) < 1e-9:
            return None  # parallel tangents
        rhs_x = bx - ax
        rhs_y = by - ay
        t = (rhs_x * (-d2[1]) - rhs_y * (-d2[0])) / det
        return (ax + t * d1[0], ay + t * d1[1])

    def _split_j2_via_virtual_P(junction_pt, arc_edge, dist_mm, orig_arc_start=None, orig_arc_end=None):
        """Place J2 dist_mm upstream from virtual intersection P on incoming LINE at junction."""
        P = _compute_virtual_P(arc_edge, orig_start=orig_arc_start, orig_end=orig_arc_end)
        v_j = _v(junction_pt)
        for in_i, in_e in in_edges.get(v_j, []):
            if in_e.edge_type != "LINE":
                continue
            dx = in_e.end[0] - in_e.start[0]
            dy = in_e.end[1] - in_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < 1e-9:
                continue
            ox, oy = dx / mag, dy / mag
            if P is not None:
                raw_pt = (P[0] - ox * dist_mm, P[1] - oy * dist_mm)
            else:
                raw_pt = (in_e.end[0] - ox * dist_mm, in_e.end[1] - oy * dist_mm)
            tgt = (_snap(raw_pt[0]), _snap(raw_pt[1]))
            _add_line_split(in_i, in_e, tgt)

    def _split_j3_diverge(arc_edge, dist_mm):
        """J3 (분기): arc.end에 연결된 outgoing LINE에서 350mm downstream."""
        ve = _v(arc_edge.end)
        arc_end_pt = arc_edge.end
        for out_i, out_e in out_edges.get(ve, []):
            if out_e.edge_type != "LINE":
                continue
            dx = out_e.end[0] - out_e.start[0]
            dy = out_e.end[1] - out_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < 1e-6:
                continue
            ox, oy = dx / mag, dy / mag
            raw_pt = (arc_end_pt[0] + ox * dist_mm, arc_end_pt[1] + oy * dist_mm)
            _add_line_split(out_i, out_e, (_snap(raw_pt[0]), _snap(raw_pt[1])))

    def _split_j3_merge(arc_edge, dist_mm):
        """J3 (합류): arc.start에 연결된 incoming LINE에서 350mm upstream."""
        vs = _v(arc_edge.start)
        arc_start_pt = arc_edge.start
        for in_i, in_e in in_edges.get(vs, []):
            if in_e.edge_type != "LINE":
                continue
            dx = in_e.end[0] - in_e.start[0]
            dy = in_e.end[1] - in_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < 1e-6:
                continue
            ox, oy = dx / mag, dy / mag
            raw_pt = (arc_start_pt[0] - ox * dist_mm, arc_start_pt[1] - oy * dist_mm)
            _add_line_split(in_i, in_e, (_snap(raw_pt[0]), _snap(raw_pt[1])))

    def _split_j2_diverge_via_virtual_P(junction_pt, arc_edge, dist_mm, orig_arc_start=None, orig_arc_end=None):
        """Place J2 dist_mm downstream from virtual intersection P on outgoing LINE at junction."""
        P = _compute_virtual_P(arc_edge, orig_start=orig_arc_start, orig_end=orig_arc_end)
        v_j = _v(junction_pt)
        for out_i, out_e in out_edges.get(v_j, []):
            if out_e.edge_type != "LINE":
                continue
            dx = out_e.end[0] - out_e.start[0]
            dy = out_e.end[1] - out_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < 1e-9:
                continue
            ox, oy = dx / mag, dy / mag
            if P is not None:
                raw_pt = (P[0] + ox * dist_mm, P[1] + oy * dist_mm)
            else:
                raw_pt = (out_e.start[0] + ox * dist_mm, out_e.start[1] + oy * dist_mm)
            tgt = (_snap(raw_pt[0]), _snap(raw_pt[1]))
            _add_line_split(out_i, out_e, tgt)

    def _absorb_line_into_arc(arc_idx, arc_edge, line_idx, is_head):
        """arm 첫(is_head=True) 또는 마지막(is_head=False) LINE을 arc에 흡수.
        arc_edge의 end(is_head) 또는 start(!is_head)를 LINE의 반대 끝으로 확장."""
        from geometry import arc_subsegment
        from map_exporter import arc_link_type_from_arcseg
        line_e = unified_edges[line_idx]
        if line_e.edge_type != "LINE":
            return
        # 흡수 전 타입 저장
        if not hasattr(arc_edge, 'forced_link_type') or arc_edge.forced_link_type is None:
            arc_edge.forced_link_type = arc_link_type_from_arcseg(arc_edge._data)
        # 흡수 가드: 새 끝점이 arc 원에서 1000mm 이상 벗어나면 흡수 건너뜀.
        # 진짜 복합분기 arm connector: off_circle≈556mm → 통과.
        # 가짜(주 경로 직선): off_circle≈2311mm → 차단, 왜곡 방지.
        _d_g = arc_edge._data
        _new_pt_g = line_e.end if is_head else line_e.start
        _off_g = abs(dist(_new_pt_g, (float(_d_g.cx), float(_d_g.cy))) - float(_d_g.r))

        if _off_g > 1000.0:
            return
        if is_head:
            new_end = line_e.end
            new_arc_data = arc_subsegment(arc_edge._data, arc_edge.start, new_end)
            arc_edge._data = new_arc_data
            arc_edge.end = new_end
        else:
            new_start = line_e.start
            new_arc_data = arc_subsegment(arc_edge._data, new_start, arc_edge.end)
            arc_edge._data = new_arc_data
            arc_edge.start = new_start
        _absorbed_line_indices.add(line_idx)
        _absorbed_arc_indices.add(arc_idx)

    def _absorb_outer_line_into_arc(arc_idx, arc_edge, line_idx):
        """arc 바깥쪽(앞/뒤)에 붙은 LINE을 arc에 흡수.
        arc.start 앞에 LINE이 있으면 arc.start를 line.start로 확장,
        arc.end 뒤에 LINE이 있으면 arc.end를 line.end로 확장."""
        from geometry import arc_subsegment
        from map_exporter import arc_link_type_from_arcseg
        line_e = unified_edges[line_idx]
        if line_e.edge_type != "LINE":
            return
        if not hasattr(arc_edge, 'forced_link_type') or arc_edge.forced_link_type is None:
            arc_edge.forced_link_type = arc_link_type_from_arcseg(arc_edge._data)
        # line.end == arc.start → arc.start를 line.start로 확장
        if dist(line_e.end, arc_edge.start) < SNAP_TOL:
            new_start = line_e.start
            new_arc_data = arc_subsegment(arc_edge._data, new_start, arc_edge.end)
            arc_edge._data = new_arc_data
            arc_edge.start = new_start
        # line.start == arc.end → arc.end를 line.end로 확장
        elif dist(line_e.start, arc_edge.end) < SNAP_TOL:
            new_end = line_e.end
            new_arc_data = arc_subsegment(arc_edge._data, arc_edge.start, new_end)
            arc_edge._data = new_arc_data
            arc_edge.end = new_end
        _absorbed_line_indices.add(line_idx)

    def _add_arc_split_at_length(arc_idx, arc_edge, length_from_start):
        """ARC에서 start로부터 arc-length length_from_start 위치를 split 목록에 추가."""
        if arc_edge.edge_type != "ARC":
            return
        cx, cy, r, ta, tb, L1, L2, ccw, sweep_deg, total_len = _arc_geometry(arc_edge)
        if total_len < 1e-6:
            return
        if length_from_start <= 1.0 or length_from_start >= total_len - 1.0:
            return
        arc_splits[arc_idx].append(length_from_start)

    # --- [복합분기 흡수 — U 병합 전] arm 첫/마지막 LINE → div/mer arc 흡수 ---
    # U-arm 복합분기도 div/mer가 arm 첫/마지막 LINE 흡수(하나로 병합). arm U 호는 _u_pairs로 별도 유지
    _all_lr_pairs = (
        [(d, m, t, a) for d, m, t, a in _complex_lr_pairs] +
        [(d, m, t, a) for d, m, t, a in _small_x_complex_lr_pairs] +
        [(ua[0], ua[1], ua[2], ua[3]) for ua in _u_arm_pairs]
    )
    for div_idx, mer_idx, top_line_idx, arm_path in _all_lr_pairs:
        div_arc = unified_edges[div_idx]
        mer_arc = unified_edges[mer_idx]
        if arm_path:
            first_arm_idx = arm_path[0]
            last_arm_idx = arm_path[-1]
            if unified_edges[first_arm_idx].edge_type == "LINE":
                _absorb_line_into_arc(div_idx, div_arc, first_arm_idx, is_head=True)
            if unified_edges[last_arm_idx].edge_type == "LINE" and last_arm_idx != first_arm_idx:
                _absorb_line_into_arc(mer_idx, mer_arc, last_arm_idx, is_head=False)
        else:
            ve_div = _v(div_arc.end)
            for out_i, out_e in out_edges.get(ve_div, []):
                if out_e.edge_type == "LINE":
                    _absorb_line_into_arc(div_idx, div_arc, out_i, is_head=True)
                    break
            vs_mer = _v(mer_arc.start)
            for in_i, in_e in in_edges.get(vs_mer, []):
                if in_e.edge_type == "LINE":
                    _absorb_line_into_arc(mer_idx, mer_arc, in_i, is_head=False)
                    break

    # ------------------ [U 분기] ------------------
    U_J1 = _cn.get("u_j1", 350.0)
    for arc_pair in _u_pairs:
        if len(arc_pair) < 1:
            continue
        fa = unified_edges[arc_pair[0]]
        la = unified_edges[arc_pair[-1]]
        # 같은 U 쌍 내부 연결선(fa.start↔la.end) 제외 — U 안쪽에 노드 찍히는 것 방지
        _skip_fa = {_v(la.end)} if la.edge_type == "ARC" else set()
        _skip_la = {_v(fa.start)} if fa.edge_type == "ARC" else set()
        if fa.edge_type == "ARC":
            v_j = _v(fa.start)
            for in_i, in_e in in_edges.get(v_j, []):
                if in_e.edge_type != "LINE":
                    continue
                if _v(in_e.start) in _skip_fa:
                    continue
                _move_junction_upstream(fa.start, fa, in_e, U_J1)
                break
        if la.edge_type == "ARC":
            v_j = _v(la.end)
            for out_i, out_e in out_edges.get(v_j, []):
                if out_e.edge_type != "LINE":
                    continue
                if _v(out_e.end) in _skip_la:
                    continue
                _move_junction_downstream(la.end, la, out_e, U_J1)
                break

    # ------------------ [소형 복합분기 arm=[] — 처리 없음, U 섹션이 담당] ------------------

    # ------------------ [복합분기 L/R 쌍] ------------------
    COMPLEX_LR_J1 = _cn.get("complex_lr_j1", 350.0)
    COMPLEX_LR_POINT_A_X = _cn.get("complex_lr_point_a_x", 1795.0)
    COMPLEX_LR_POINT_B2_X = _cn.get("complex_lr_point_b2_x", 2100.0)
    for div_idx, mer_idx, top_line_idx, arm_path in _complex_lr_pairs:
        div_arc = unified_edges[div_idx]
        mer_arc = unified_edges[mer_idx]
        junc_A = div_arc.start
        junc_B = mer_arc.end
        top_line_e = unified_edges[top_line_idx]
        pair_X = dist(div_arc.start, mer_arc.end)
        # X = dist(div_arc2.start, mer_arc2.end) — arm 내부 arc 쌍 기준
        _arm_arcs_c = [(ai, unified_edges[ai]) for ai in arm_path
                       if unified_edges[ai].edge_type == "ARC"]
        if len(_arm_arcs_c) >= 2:
            X = dist(_arm_arcs_c[1][1].start, _arm_arcs_c[0][1].end)
        else:
            X = dist(div_arc.end, mer_arc.start)

        # if X < U_X_THRESHOLD:
        #     continue  # X < 1600: U 규칙이 처리 — 노드 삽입 금지

        # J1: junc_A/junc_B를 350mm 이동 (새 노드 삽입 아닌 기존 좌표 이동)
        v_jA = _v(junc_A)
        for in_i, in_e in in_edges.get(v_jA, []):
            if in_e.edge_type != "LINE":
                continue
            dx = in_e.end[0] - in_e.start[0]
            dy = in_e.end[1] - in_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < COMPLEX_LR_J1:
                continue
            ox, oy = dx / mag, dy / mag
            new_pt = (_snap(junc_A[0] - ox * COMPLEX_LR_J1), _snap(junc_A[1] - oy * COMPLEX_LR_J1))
            # incoming LINE의 end 이동
            in_e.end = new_pt
            in_e._data.p2 = new_pt
            # div_arc의 start 이동
            div_arc.start = new_pt
            div_arc._data.p_start = new_pt
            _update_arc_deg(div_arc, new_pt, is_start=True)
            # top_line의 start 이동
            top_line_e.start = new_pt
            top_line_e._data.p1 = new_pt

        v_jB = _v(junc_B)
        for out_i, out_e in out_edges.get(v_jB, []):
            if out_e.edge_type != "LINE":
                continue
            dx = out_e.end[0] - out_e.start[0]
            dy = out_e.end[1] - out_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < COMPLEX_LR_J1:
                continue
            ox, oy = dx / mag, dy / mag
            new_pt = (_snap(junc_B[0] + ox * COMPLEX_LR_J1), _snap(junc_B[1] + oy * COMPLEX_LR_J1))
            # outgoing LINE의 start 이동
            out_e.start = new_pt
            out_e._data.p1 = new_pt
            # mer_arc의 end 이동
            mer_arc.end = new_pt
            mer_arc._data.p_end = new_pt
            _update_arc_deg(mer_arc, new_pt, is_start=False)
            # top_line의 end 이동
            top_line_e.end = new_pt
            top_line_e._data.p2 = new_pt

        # arm_LINE: arm_path 내 두 inner arc(mer_arc2, div_arc2) 사이의 LINE
        _arm_line_idx, _arm_line_e = None, None
        for _pi in range(1, len(arm_path) - 1):
            _pe = unified_edges[arm_path[_pi]]
            if _pe.edge_type == "LINE":
                _prev_e = unified_edges[arm_path[_pi - 1]]
                _next_e = unified_edges[arm_path[_pi + 1]]
                if _prev_e.edge_type == "ARC" and _next_e.edge_type == "ARC":
                    _arm_line_idx = arm_path[_pi]
                    _arm_line_e = _pe
                    break

        # Point A: top LINE 중간 (X ≈ 1800이고 arm LINE 존재할 때)
        if (X >= COMPLEX_LR_POINT_A_X and X <= COMPLEX_LR_POINT_A_X + 10
                and _arm_line_idx is not None):
            mid_pt = (_snap((top_line_e.start[0] + top_line_e.end[0]) * 0.5),
                      _snap((top_line_e.start[1] + top_line_e.end[1]) * 0.5))
            _add_line_split(top_line_idx, top_line_e, mid_pt)

        # Point B: arm 오른쪽 수직 LINE에 삽입 (X >= 1800일 때만)
        if X < COMPLEX_LR_POINT_A_X or _arm_line_idx is None:
            continue
        sx, sy = _arm_line_e.start[0], _arm_line_e.start[1]
        ex, ey = _arm_line_e.end[0], _arm_line_e.end[1]
        if X >= COMPLEX_LR_POINT_B2_X:
            _add_line_split(_arm_line_idx, _arm_line_e, (_snap(sx + (ex - sx) / 3), _snap(sy + (ey - sy) / 3)))
            _add_line_split(_arm_line_idx, _arm_line_e, (_snap(sx + (ex - sx) * 2 / 3), _snap(sy + (ey - sy) * 2 / 3)))
        else:
            _add_line_split(_arm_line_idx, _arm_line_e, (_snap((sx + ex) * 0.5), _snap((sy + ey) * 0.5)))

    # ------------------ [소형 복합분기 X<1601 — U 노드 규칙] ------------------
    SMALL_X_J1 = _cn.get("small_x_j1", 350.0)
    for div_idx, mer_idx, top_line_idx, arm_path in _small_x_complex_lr_pairs:
        div_arc = unified_edges[div_idx]
        mer_arc = unified_edges[mer_idx]
        junc_A = div_arc.start
        junc_B = mer_arc.end
        v_jA = _v(junc_A)
        for _, in_e in in_edges.get(v_jA, []):
            if in_e.edge_type == "LINE":
                _move_junction_upstream(junc_A, div_arc, in_e, SMALL_X_J1)
                break
        v_jB = _v(junc_B)
        for _, out_e in out_edges.get(v_jB, []):
            if out_e.edge_type == "LINE":
                _move_junction_downstream(junc_B, mer_arc, out_e, SMALL_X_J1)
                break

    # U-arm 복합분기: div/mer junc_A/junc_B에 350mm J1 (arm U는 U섹션이 별도 처리)
    for div_idx, mer_idx, top_line_idx, arm_path, arm_u_arcs in _u_arm_pairs:
        div_arc = unified_edges[div_idx]
        mer_arc = unified_edges[mer_idx]
        junc_A = div_arc.start
        junc_B = mer_arc.end
        v_jA = _v(junc_A)
        for _, in_e in in_edges.get(v_jA, []):
            if in_e.edge_type == "LINE":
                _move_junction_upstream(junc_A, div_arc, in_e, SMALL_X_J1)
                break
        v_jB = _v(junc_B)
        for _, out_e in out_edges.get(v_jB, []):
            if out_e.edge_type == "LINE":
                _move_junction_downstream(junc_B, mer_arc, out_e, SMALL_X_J1)
                break

    # ------------- [일반 호직호 arm=[] X>=1601 — 복합 아님 → plain_arc 처리] -------------
    # 복합 흡수/Point A·B 없이 두 호를 L/R로 고정하고 가운데 직선은 S로 보존한다.
    # plain_arc_flat에 합류시켜 양 호출부(test_logic·gui)의 U/N 탐색에서 제외 → U 오인 방지.
    from map_exporter import arc_link_type_from_arcseg as _arc_lt
    _plain_no_arm_arc_idx = set()
    # 소형 호직호(arm없음, pair_X<1601)도 L/R 타입 보존 — plain_arc_flat에 포함시켜 U 탐지 제외
    # 진짜 J3: 안쪽 끝(div.end/mer.start = 세로직선 쪽)을 350mm 이동(arc 연장, LINE 단축) → 실제 이격
    for div_idx, mer_idx, top_line_idx in _small_x_no_arm_pairs:
        div_arc = unified_edges[div_idx]
        mer_arc = unified_edges[mer_idx]
        div_arc.forced_link_type = _arc_lt(div_arc._data)
        mer_arc.forced_link_type = _arc_lt(mer_arc._data)
        _plain_no_arm_arc_idx.add(div_idx)
        _plain_no_arm_arc_idx.add(mer_idx)
        # div_arc.end를 outgoing LINE 안으로 350mm 이동
        for _oi, _oe in out_edges.get(_v(div_arc.end), []):
            if _oe.edge_type != "LINE":
                continue
            _dx = _oe.end[0] - _oe.start[0]; _dy = _oe.end[1] - _oe.start[1]
            _mag = math.hypot(_dx, _dy)
            if _mag < J3_ARC_LEN:
                continue
            _ox, _oy = _dx / _mag, _dy / _mag
            _np = (_snap(div_arc.end[0] + _ox * J3_ARC_LEN), _snap(div_arc.end[1] + _oy * J3_ARC_LEN))
            _oe.start = _np; _oe._data.p1 = _np
            div_arc.end = _np; div_arc._data.p_end = _np
            _update_arc_deg(div_arc, _np, is_start=False)
            break
        # mer_arc.start를 incoming LINE 안으로 350mm 이동
        for _ii, _ie in in_edges.get(_v(mer_arc.start), []):
            if _ie.edge_type != "LINE":
                continue
            _dx = _ie.end[0] - _ie.start[0]; _dy = _ie.end[1] - _ie.start[1]
            _mag = math.hypot(_dx, _dy)
            if _mag < J3_ARC_LEN:
                continue
            _ox, _oy = _dx / _mag, _dy / _mag
            _np = (_snap(mer_arc.start[0] - _ox * J3_ARC_LEN), _snap(mer_arc.start[1] - _oy * J3_ARC_LEN))
            _ie.end = _np; _ie._data.p2 = _np
            mer_arc.start = _np; mer_arc._data.p_start = _np
            _update_arc_deg(mer_arc, _np, is_start=True)
            break
    for div_idx, mer_idx, top_line_idx in _plain_no_arm_pairs:
        div_arc = unified_edges[div_idx]
        mer_arc = unified_edges[mer_idx]
        div_arc.forced_link_type = _arc_lt(div_arc._data)
        mer_arc.forced_link_type = _arc_lt(mer_arc._data)
        _plain_no_arm_arc_idx.add(div_idx)
        _plain_no_arm_arc_idx.add(mer_idx)
        _split_j3_diverge(div_arc, J3_ARC_LEN)
        _split_j3_merge(mer_arc, J3_ARC_LEN)

    # ------------------ [N 분기] ------------------
    for arc_pair in _n_pairs:
        if len(arc_pair) < 2:
            continue
        first_arc_idx = arc_pair[0]
        last_arc_idx = arc_pair[-1]
        if first_arc_idx >= len(unified_edges) or last_arc_idx >= len(unified_edges):
            continue
        first_arc = unified_edges[first_arc_idx]
        last_arc = unified_edges[last_arc_idx]
        if first_arc.edge_type != "ARC" or last_arc.edge_type != "ARC":
            continue

        # Y = 중간 직선 길이
        Y = 0.0
        if len(arc_pair) == 3:
            mid = unified_edges[arc_pair[1]]
            if mid.edge_type == "LINE":
                Y = dist(mid.start, mid.end)
        j2_dist = N_LONG_J2 if Y >= N_STRAIGHT_THRESHOLD else N_SHORT_J2

        junc_A = first_arc.start
        junc_B = last_arc.end
        v_jA = _v(junc_A)
        for _, in_e in in_edges.get(v_jA, []):
            if in_e.edge_type == "LINE":
                _move_junction_upstream(junc_A, first_arc, in_e, J1_DOWNSTREAM)
                break
        _split_downstream_on_outgoing_line(junc_A, j2_dist)
        v_jB = _v(junc_B)
        for _, out_e in out_edges.get(v_jB, []):
            if out_e.edge_type == "LINE":
                _move_junction_downstream(junc_B, last_arc, out_e, J1_DOWNSTREAM)
                break
        _split_upstream_on_incoming_line(junc_B, j2_dist)

    # ------------------ [일반 L/R 분기] ------------------
    # N/U 분기 junction 좌표 수집 → L/R 루프에서 제외 (_complex_pairs는 L/R 처리하므로 제외 안함)
    _nu_junc_vkeys = set()
    for arc_pair in _n_pairs + _u_pairs:
        if len(arc_pair) >= 1:
            fa = unified_edges[arc_pair[0]]
            if fa.edge_type == "ARC":
                _nu_junc_vkeys.add(_v(fa.start))
        if len(arc_pair) >= 1:
            la = unified_edges[arc_pair[-1]]
            if la.edge_type == "ARC":
                _nu_junc_vkeys.add(_v(la.end))
    for div_idx, mer_idx, top_line_idx, _arm in _complex_lr_pairs + _small_x_complex_lr_pairs:
        _nu_junc_vkeys.add(_v(unified_edges[div_idx].start))
        _nu_junc_vkeys.add(_v(unified_edges[mer_idx].end))
        top_e = unified_edges[top_line_idx]
        _nu_junc_vkeys.add(_v(top_e.start))
        _nu_junc_vkeys.add(_v(top_e.end))

    for i, arc in enumerate(unified_edges):
        if arc.edge_type != "ARC":
            continue
        if i in _un_flat:
            continue

        # Diverge: arc.start가 junction.
        #   in_edges[js] = [LINE x1 (main track incoming)]
        #   out_edges[js] = [LINE x1 (main track outgoing), ARC x1 (this arc)]
        js = _v(arc.start)
        in_js = in_edges.get(js, [])
        out_js = out_edges.get(js, [])
        in_line_cnt_s = sum(1 for _, e in in_js if e.edge_type == "LINE")
        in_arc_cnt_s = sum(1 for _, e in in_js if e.edge_type == "ARC")
        out_line_cnt_s = sum(1 for _, e in out_js if e.edge_type == "LINE")
        out_arc_cnt_s = sum(1 for _, e in out_js if e.edge_type == "ARC")

        is_diverge = (
            in_line_cnt_s == 1 and in_arc_cnt_s == 0
            and out_line_cnt_s == 1 and out_arc_cnt_s == 1
        )

        # Merge: arc.end가 junction.
        #   in_edges[je] = [LINE x1 (main track incoming), ARC x1 (this arc)]
        #   out_edges[je] = [LINE x1 (main track outgoing)]
        je = _v(arc.end)
        in_je = in_edges.get(je, [])
        out_je = out_edges.get(je, [])
        in_line_cnt_e = sum(1 for _, e in in_je if e.edge_type == "LINE")
        in_arc_cnt_e = sum(1 for _, e in in_je if e.edge_type == "ARC")
        out_line_cnt_e = sum(1 for _, e in out_je if e.edge_type == "LINE")
        out_arc_cnt_e = sum(1 for _, e in out_je if e.edge_type == "ARC")

        is_merge = (
            in_line_cnt_e == 1 and in_arc_cnt_e == 1
            and out_line_cnt_e == 1 and out_arc_cnt_e == 0
        )

        if is_diverge and _v(arc.start) not in _nu_junc_vkeys:
            junction_pt = arc.start
            orig_arc_start = arc.start
            orig_arc_end = arc.end
            v_js2 = _v(junction_pt)
            for _, in_e in in_edges.get(v_js2, []):
                if in_e.edge_type == "LINE":
                    _move_junction_upstream(junction_pt, arc, in_e, J1_DOWNSTREAM)
                    break
            _split_j2_diverge_via_virtual_P(junction_pt, arc, LR_J2_UPSTREAM,
                                            orig_arc_start=orig_arc_start, orig_arc_end=orig_arc_end)
            ve = _v(arc.end)
            for out_i, out_e in out_edges.get(ve, []):
                if out_e.edge_type != "LINE":
                    continue
                dx = out_e.end[0] - out_e.start[0]
                dy = out_e.end[1] - out_e.start[1]
                mag = math.hypot(dx, dy)
                if mag < J3_ARC_LEN:
                    continue
                ox, oy = dx / mag, dy / mag
                new_pt = (_snap(arc.end[0] + ox * J3_ARC_LEN), _snap(arc.end[1] + oy * J3_ARC_LEN))
                out_e.start = new_pt
                out_e._data.p1 = new_pt
                arc.end = new_pt
                arc._data.p_end = new_pt

        if is_merge and _v(arc.end) not in _nu_junc_vkeys:
            junction_pt = arc.end
            orig_arc_start = arc.start
            orig_arc_end = arc.end
            v_je2 = _v(junction_pt)
            for _, out_e in out_edges.get(v_je2, []):
                if out_e.edge_type == "LINE":
                    _move_junction_downstream(junction_pt, arc, out_e, J1_DOWNSTREAM)
                    break
            _split_j2_via_virtual_P(junction_pt, arc, LR_J2_UPSTREAM,
                                    orig_arc_start=orig_arc_start, orig_arc_end=orig_arc_end)
            vs = _v(arc.start)
            for in_i, in_e in in_edges.get(vs, []):
                if in_e.edge_type != "LINE":
                    continue
                dx = in_e.end[0] - in_e.start[0]
                dy = in_e.end[1] - in_e.start[1]
                mag = math.hypot(dx, dy)
                if mag < J3_ARC_LEN:
                    continue
                ox, oy = dx / mag, dy / mag
                new_pt = (_snap(arc.start[0] - ox * J3_ARC_LEN), _snap(arc.start[1] - oy * J3_ARC_LEN))
                in_e.end = new_pt
                in_e._data.p2 = new_pt
                arc.start = new_pt
                arc._data.p_start = new_pt

    # ------------------ [일반 ARC — 단순 통과 (분기/합류 없음)] ------------------
    # in: LINE 1개, ARC 0개 / out: LINE 1개, ARC 0개 인 arc의 양 끝점을 350mm 이격
    PLAIN_ARC_OFFSET = J3_ARC_LEN  # 350mm (J3_ARC_LEN 재사용)
    _all_handled_arc = (_un_flat
                        | set(idx for pair in _complex_lr_pairs + _small_x_complex_lr_pairs
                              for idx in [pair[0], pair[1]])
                        | set(idx for d, m, t in _small_x_no_arm_pairs for idx in [d, m]))
    _plain_arc_indices = set(_plain_no_arm_arc_idx)  # 일반 호직호(arm=[] X>=1601) 합류
    for i, arc in enumerate(unified_edges):
        if arc.edge_type != "ARC":
            continue
        vs = _v(arc.start)
        ve = _v(arc.end)
        in_vs  = in_edges.get(vs, [])
        out_vs = out_edges.get(vs, [])
        in_ve  = in_edges.get(ve, [])
        out_ve = out_edges.get(ve, [])
        # 단순 통과: arc.start 쪽 in=LINE 1, arc=0 / out=LINE 0, arc=1(자기자신)
        #            arc.end 쪽  in=LINE 0, arc=1(자기자신) / out=LINE 1, arc=0
        is_plain = (
            sum(1 for _, e in in_vs  if e.edge_type == "LINE") == 1 and
            sum(1 for _, e in in_vs  if e.edge_type == "ARC")  == 0 and
            sum(1 for _, e in out_vs if e.edge_type == "LINE") == 0 and
            sum(1 for _, e in out_vs if e.edge_type == "ARC")  == 1 and
            sum(1 for _, e in in_ve  if e.edge_type == "LINE") == 0 and
            sum(1 for _, e in in_ve  if e.edge_type == "ARC")  == 1 and
            sum(1 for _, e in out_ve if e.edge_type == "LINE") == 1 and
            sum(1 for _, e in out_ve if e.edge_type == "ARC")  == 0
        )
        if not is_plain:
            continue
        _plain_arc_indices.add(i)
        from map_exporter import arc_link_type_from_arcseg
        arc.forced_link_type = arc_link_type_from_arcseg(arc._data)
        for _, in_e in in_vs:
            if in_e.edge_type != "LINE":
                continue
            dx = in_e.end[0] - in_e.start[0]
            dy = in_e.end[1] - in_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < PLAIN_ARC_OFFSET:
                continue
            ox, oy = dx / mag, dy / mag
            new_pt = (_snap(arc.start[0] - ox * PLAIN_ARC_OFFSET),
                      _snap(arc.start[1] - oy * PLAIN_ARC_OFFSET))
            in_e.end = new_pt
            in_e._data.p2 = new_pt
            arc.start = new_pt
            arc._data.p_start = new_pt
            _update_arc_deg(arc, new_pt, is_start=True)
            break
        for _, out_e in out_ve:
            if out_e.edge_type != "LINE":
                continue
            dx = out_e.end[0] - out_e.start[0]
            dy = out_e.end[1] - out_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < PLAIN_ARC_OFFSET:
                continue
            ox, oy = dx / mag, dy / mag
            new_pt = (_snap(arc.end[0] + ox * PLAIN_ARC_OFFSET),
                      _snap(arc.end[1] + oy * PLAIN_ARC_OFFSET))
            out_e.start = new_pt
            out_e._data.p1 = new_pt
            arc.end = new_pt
            arc._data.p_end = new_pt
            _update_arc_deg(arc, new_pt, is_start=False)
            break

    # ------------------ [흡수된 ARC 이격] ------------------
    def _drag_other_edges_at(old_pt, new_pt, skip_ids):
        """old_pt junction에 끝점이 있는 다른 엣지(skip_ids 제외)의 해당 끝점을 new_pt로
        함께 이동. 흡수 호가 직선을 350mm 당길 때, 같은 junction을 공유하던 별개 분기
        호/직선이 뒤처져 끊기는 것(350mm 갭)을 방지. ARC는 각도도 갱신."""
        tol_pt = max(float(tol), 0.1)
        vk = _v(old_pt)
        for _, e in list(in_edges.get(vk, [])):
            if id(e) in skip_ids:
                continue
            if dist(e.end, old_pt) <= tol_pt:
                e.end = new_pt
                if e.edge_type == "LINE":
                    e._data.p2 = new_pt
                elif e.edge_type == "ARC":
                    e._data.p_end = new_pt
                    _update_arc_deg(e, new_pt, is_start=False)
        for _, e in list(out_edges.get(vk, [])):
            if id(e) in skip_ids:
                continue
            if dist(e.start, old_pt) <= tol_pt:
                e.start = new_pt
                if e.edge_type == "LINE":
                    e._data.p1 = new_pt
                elif e.edge_type == "ARC":
                    e._data.p_start = new_pt
                    _update_arc_deg(e, new_pt, is_start=True)

    for i in _absorbed_arc_indices:
        if i in _plain_arc_indices:
            continue  # 이미 처리됨
        arc = unified_edges[i]
        if arc.edge_type != "ARC":
            continue
        if not hasattr(arc, 'forced_link_type') or arc.forced_link_type is None:
            from map_exporter import arc_link_type_from_arcseg
            arc.forced_link_type = arc_link_type_from_arcseg(arc._data)
        vs = _v(arc.start)
        ve = _v(arc.end)
        for _, in_e in in_edges.get(vs, []):
            if in_e.edge_type != "LINE":
                continue
            dx = in_e.end[0] - in_e.start[0]
            dy = in_e.end[1] - in_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < PLAIN_ARC_OFFSET:
                continue
            ox, oy = dx / mag, dy / mag
            old_pt = arc.start
            new_pt = (_snap(arc.start[0] - ox * PLAIN_ARC_OFFSET),
                      _snap(arc.start[1] - oy * PLAIN_ARC_OFFSET))
            in_e.end = new_pt
            in_e._data.p2 = new_pt
            arc.start = new_pt
            arc._data.p_start = new_pt
            _update_arc_deg(arc, new_pt, is_start=True)
            # 같은 junction에 남는 별개 호/직선도 함께 이동(350mm 끊김 방지)
            _drag_other_edges_at(old_pt, new_pt, {id(in_e), id(arc)})
            break
        for _, out_e in out_edges.get(ve, []):
            if out_e.edge_type != "LINE":
                continue
            dx = out_e.end[0] - out_e.start[0]
            dy = out_e.end[1] - out_e.start[1]
            mag = math.hypot(dx, dy)
            if mag < PLAIN_ARC_OFFSET:
                continue
            ox, oy = dx / mag, dy / mag
            old_pt = arc.end
            new_pt = (_snap(arc.end[0] + ox * PLAIN_ARC_OFFSET),
                      _snap(arc.end[1] + oy * PLAIN_ARC_OFFSET))
            out_e.start = new_pt
            out_e._data.p1 = new_pt
            arc.end = new_pt
            arc._data.p_end = new_pt
            _update_arc_deg(arc, new_pt, is_start=False)
            # 같은 junction에 남는 별개 호/직선도 함께 이동(350mm 끊김 방지)
            _drag_other_edges_at(old_pt, new_pt, {id(out_e), id(arc)})
            break

    # ------------------ 엣지 재구성 ------------------
    def _arc_point_at_length(arc_edge, length_from_start):
        """ARC 시작점으로부터 arc-length 만큼 떨어진 XY."""
        cx, cy, r, ta, tb, L1, L2, ccw, sweep_deg, total_len = _arc_geometry(arc_edge)
        if total_len < 1e-9:
            return arc_edge.start
        frac = max(0.0, min(1.0, length_from_start / total_len))
        if ccw:
            end_unwrap = dxf_ccw_unwrap_end_deg(ta, tb)
            ang_deg = ta + frac * (end_unwrap - ta)
        else:
            ang_deg = ta - frac * sweep_deg
        return arc_point_at_deg(cx, cy, r, ang_deg)

    # ------------------ [주행 노드 — 4000mm 이상 LINE 균등 분할] ------------------
    DRIVING_NODE_MIN_LEN = 4000.0
    DRIVING_NODE_MIN_SEG = 2000.0
    for i, e in enumerate(unified_edges):
        if e.edge_type != "LINE":
            continue
        edge_len = dist(e.start, e.end)
        if edge_len < DRIVING_NODE_MIN_LEN:
            continue
        # 클리어런스 분할점으로 서브세그먼트 구성 — 각 서브세그먼트 독립적으로 처리
        existing_pts = sorted(line_splits.get(i, []), key=lambda p: dist(e.start, p))
        seg_pts = [e.start] + existing_pts + [e.end]
        for si in range(len(seg_pts) - 1):
            a, b = seg_pts[si], seg_pts[si + 1]
            seg_len = dist(a, b)
            if seg_len < DRIVING_NODE_MIN_LEN:
                continue
            n_splits = int(seg_len / DRIVING_NODE_MIN_SEG)
            added = []
            for k in range(1, n_splits):
                frac = k / n_splits
                pt = (_snap(a[0] + (b[0] - a[0]) * frac),
                      _snap(a[1] + (b[1] - a[1]) * frac))
                check = [a, b] + added
                if any(dist(pt, q) < DRIVING_NODE_MIN_SEG for q in check):
                    continue
                added.append(pt)
                _add_line_split(i, e, pt)

    new_unified_edges = []
    for i, e in enumerate(unified_edges):
        if i in _absorbed_line_indices:
            continue  # arc에 흡수된 LINE — 별도 엣지로 출력하지 않음
        if e.edge_type == "LINE":
            if i not in line_splits:
                new_unified_edges.append(e)
                continue
            edge_len = dist(e.start, e.end)
            if edge_len < 1e-6:
                new_unified_edges.append(e)
                continue
            raw_sorted = sorted(line_splits[i], key=lambda p: dist(e.start, p))
            valid_pts = []
            for p in raw_sorted:
                if dist(e.start, p) <= 1.0 or dist(p, e.end) <= 1.0:
                    continue
                if valid_pts and dist(valid_pts[-1], p) <= 1.0:
                    continue
                valid_pts.append(p)
            if not valid_pts:
                new_unified_edges.append(e)
                continue
            pts = [e.start] + valid_pts + [e.end]
            for k in range(len(pts) - 1):
                new_unified_edges.append(Edge(LineSeg(pts[k], pts[k+1])))
        elif e.edge_type == "ARC":
            if i not in arc_splits:
                new_unified_edges.append(e)
                continue
            cx, cy, r, ta, tb, L1, L2, ccw, sweep_deg, total_len = _arc_geometry(e)
            if total_len < 1e-6:
                new_unified_edges.append(e)
                continue
            # arc-length 중복·endpoint 근접 제거 후 정렬
            raw_lens = sorted(arc_splits[i])
            valid_lens = []
            for L in raw_lens:
                if L <= 1.0 or L >= total_len - 1.0:
                    continue
                if valid_lens and abs(valid_lens[-1] - L) <= 1.0:
                    continue
                valid_lens.append(L)
            if not valid_lens:
                new_unified_edges.append(e)
                continue
            # arc-length → XY
            split_pts = [_arc_point_at_length(e, L) for L in valid_lens]
            pts = [e.start] + split_pts + [e.end]
            for k in range(len(pts) - 1):
                sub = arc_subsegment(e._data, pts[k], pts[k+1])
                new_unified_edges.append(Edge(sub))
        else:
            new_unified_edges.append(e)

    # _complex_lr_flat: 원본 Edge 객체 set → 새 인덱스 set으로 변환
    _complex_lr_edge_objs = {unified_edges[i] for i in _complex_lr_flat}
    _complex_lr_flat_new = {
        new_i for new_i, e in enumerate(new_unified_edges)
        if e in _complex_lr_edge_objs
    }
    # _plain_arc_flat: 일반 ARC 원본 객체 → 새 인덱스 set으로 변환
    _plain_arc_edge_objs = {unified_edges[i] for i in _plain_arc_indices}
    _plain_arc_flat_new = {
        new_i for new_i, e in enumerate(new_unified_edges)
        if e in _plain_arc_edge_objs
    }
    # _intra_arm_u_idx: pre-clearance 인덱스 → post-clearance 인덱스로 remap
    # (remap 누락 시 stale 인덱스가 엉뚱한 arc를 가리켜 second-pass에서 인접 N/U분기를 잘못 제외)
    _intra_arm_u_edge_objs = {unified_edges[i] for i in _intra_arm_u_idx if i < len(unified_edges)}
    _intra_arm_u_idx_new = {
        new_i for new_i, e in enumerate(new_unified_edges)
        if e in _intra_arm_u_edge_objs
    }
    return new_unified_edges, _intra_arm_u_idx_new, _complex_lr_flat_new, _plain_arc_flat_new, _graph_scan_u_pair_objs