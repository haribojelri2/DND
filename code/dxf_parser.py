from __future__ import annotations
import math
import copy
from typing import List, Tuple, Optional, Any, Dict, Set

import ezdxf
from ezdxf.math import Matrix44, Vec3
from geometry import split_near_180_arcs

from core import *

DEBUG_DXF = False


def _resolve_color(ent, doc) -> int:
    """엔티티의 실제 ACI 색상 반환. 256(BYLAYER)는 레이어에서, 0(BYBLOCK)은 7로 처리."""
    c = int(getattr(ent.dxf, "color", 256) or 256)
    if c == 256:
        try:
            layer = doc.layers.get(ent.dxf.layer)
            if layer is not None:
                c = int(getattr(layer.dxf, "color", 7) or 7)
        except Exception:
            c = 7
    return c if c > 0 else 7


def scan_entity_colors(doc) -> Dict[int, int]:
    """모델공간 ACI 색상 → 엔티티 수 반환."""
    counts: Dict[int, int] = {}

    def _count(ent, parent_color: Optional[int] = None):
        c = parent_color if parent_color is not None else _resolve_color(ent, doc)
        et = ent.dxftype()
        if et in ("LINE", "ARC", "LWPOLYLINE", "CIRCLE"):
            counts[c] = counts.get(c, 0) + 1
        elif et == "POLYLINE":
            from ezdxf.render.polyline import virtual_polyline_entities
            for ve in virtual_polyline_entities(ent):
                _count(ve, parent_color=c)

    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            for ve in iter_insert_virtual_entities(e):
                _count(ve)
        else:
            _count(e)
    return counts


def scan_entity_layers(doc) -> Dict[str, int]:
    """모델공간 레이어 이름 → 엔티티 수 반환."""
    counts: Dict[str, int] = {}

    def _count(ent):
        et = ent.dxftype()
        layer = str(getattr(ent.dxf, "layer", "0"))
        if et in ("LINE", "ARC", "LWPOLYLINE", "CIRCLE"):
            counts[layer] = counts.get(layer, 0) + 1
        elif et == "POLYLINE":
            from ezdxf.render.polyline import virtual_polyline_entities
            for ve in virtual_polyline_entities(ent):
                _count(ve)

    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            for ve in iter_insert_virtual_entities(e):
                _count(ve)
        else:
            _count(e)
    return counts


def collect_entities_recursive(
    doc,
    rail_color: Optional[int] = None,
    rail_layers: Optional[List[str]] = None,
) -> Tuple[List[LineSeg], List[ArcSeg]]:
    """모델공간 전체: LINE/ARC, LWPOLYLINE·POLYLINE(bulge→LINE/ARC 분해). INSERT는 virtual_entities(WCS).

    rail_color와 rail_layers는 AND 조건으로 적용됨.
    둘 다 지정 시 색상·레이어 모두 일치해야 추출. 각각 None이면 해당 조건은 무시.

    반환
    ----
    lines : 레일 직선 세그먼트
    arcs  : 레일 호 세그먼트
    """
    lines: List[LineSeg] = []
    arcs: List[ArcSeg] = []
    ident = Matrix44()
    _rail_layers_set: Optional[Set[str]] = set(rail_layers) if rail_layers else None

    def add_line_xy(p1, p2, layer: str = "0"):
        if dist(p1, p2) > MIN_LINE_LENGTH:
            lines.append(LineSeg(p1, p2, layer=layer))

    def add_arc_wcs(arc_ent, layer: str = "0"):
        p0, p1 = arc_entity_endpoints_world_xy(arc_ent, ident)
        cx, cy, r, sa, ea = transform_arc_to_xy(ident, arc_ent)
        pm = arc_entity_midpoint_on_curve_world_xy(arc_ent, ident)
        base_arc = ArcSeg(
            cx, cy, r, sa, ea,
            p_start=p0, p_end=p1,
            p_mid_curve=pm,
            dxf_start_deg=float(sa), dxf_end_deg=float(ea),
            layer=layer,
        )
        split = split_near_180_arcs([base_arc], target_deg=180.0, tol_deg=1.0)
        for seg in split:
            seg.layer = layer
        arcs.extend(split)

    _EQUIPMENT_TYPES = frozenset({"SPLINE", "CIRCLE", "ELLIPSE", "TEXT", "MTEXT", "DIMENSION"})

    def _is_equipment_block(name: str) -> bool:
        """SPLINE/CIRCLE/ELLIPSE 등 장비 심볼 타입을 포함하거나, LINE/ARC가 폐루프를 형성하면 장비 블록으로 판단."""
        if not name or name.startswith("*"):
            return False
        try:
            blk = doc.blocks.get(name)
            if blk is None:
                return False
            ents = list(blk)
            if any(be.dxftype() in _EQUIPMENT_TYPES for be in ents):
                return True
            # LINE/ARC만으로 구성된 닫힌 윤곽(폐루프) → 장비 외곽선으로 판단
            pts = []
            for be in ents:
                et = be.dxftype()
                if et == "LINE":
                    pts.append((round(float(be.dxf.start.x), 1), round(float(be.dxf.start.y), 1)))
                    pts.append((round(float(be.dxf.end.x), 1), round(float(be.dxf.end.y), 1)))
                elif et == "ARC":
                    sp = be.start_point
                    ep = be.end_point
                    pts.append((round(float(sp.x), 1), round(float(sp.y), 1)))
                    pts.append((round(float(ep.x), 1), round(float(ep.y), 1)))
                elif et not in ("ATTDEF", "ATTRIB", "INSERT"):
                    return False
            if len(pts) < 4:
                return False
            from collections import Counter
            return all(v == 2 for v in Counter(pts).values())
        except Exception:
            return False

    def _is_leaf_block(name: str) -> bool:
        """중첩 INSERT 없는 단순 블록이면 True — 레일 심볼 가능성 높음."""
        if not name or name.startswith("*"):
            return True
        try:
            blk = doc.blocks.get(name)
            if blk is None:
                return True
            return not any(
                be.dxftype() == "INSERT" and not (be.dxf.name or "").startswith("*")
                for be in blk
            )
        except Exception:
            return True

    def dispatch(ent, parent_color: Optional[int] = None, depth: int = 0, block_ctx: str = ""):
        et = ent.dxftype()

        if et == "INSERT":
            if depth >= 20:
                return
            raw = int(getattr(ent.dxf, "color", 256) or 256)
            layer_name = str(getattr(ent.dxf, "layer", "0"))
            if parent_color is not None and raw == 0:
                c = parent_color
            else:
                c = _resolve_color(ent, doc)
            block_name = str(getattr(ent.dxf, "name", "") or "")
            # 장비 블록(SPLINE/CIRCLE/ELLIPSE 포함)은 레일 추출 대상에서 제외
            if _is_equipment_block(block_name):
                return
            # 리프 블록(중첩 INSERT 없음)만 color 상속, 컨테이너 블록은 상속 안 함
            child_parent = c if _is_leaf_block(block_name) else None
            try:
                for ve in ent.virtual_entities():
                    dispatch(ve, parent_color=child_parent, depth=depth + 1, block_ctx=block_name)
            except Exception:
                pass
            return

        # 리프 엔티티: 색상/레이어 결정 후 레일 필터 (AND 조건)
        raw = int(getattr(ent.dxf, "color", 256) or 256)
        layer_name = str(getattr(ent.dxf, "layer", "0"))
        if parent_color is not None and raw == 0:
            c = parent_color
        else:
            c = _resolve_color(ent, doc)
        if rail_color is not None and c != rail_color:
            return
        if _rail_layers_set is not None and layer_name not in _rail_layers_set:
            return

        if DEBUG_DXF and rail_color is not None:
            layer_n = str(getattr(ent.dxf, "layer", "?"))
            src = f"block={block_ctx}" if block_ctx else "modelspace"
            print(f"[PASS] {et} raw={raw} resolved={c} layer={layer_n} parent={parent_color} from={src}")

        if et == "LINE":
            s, t = ent.dxf.start, ent.dxf.end
            add_line_xy((float(s.x), float(s.y)), (float(t.x), float(t.y)), layer=layer_name)
        elif et == "ARC":
            add_arc_wcs(ent, layer=layer_name)
        elif et == "LWPOLYLINE":
            from ezdxf.render.polyline import virtual_lwpolyline_entities
            for ve in virtual_lwpolyline_entities(ent):
                dispatch(ve, parent_color=c, depth=depth)
        elif et == "POLYLINE":
            from ezdxf.render.polyline import virtual_polyline_entities
            for ve in virtual_polyline_entities(ent):
                if ve.dxftype() in ("LINE", "ARC"):
                    dispatch(ve, parent_color=c, depth=depth)

    msp = doc.modelspace()
    for e in msp:
        if e.dxftype() == "INSERT":
            block_name = str(getattr(e.dxf, "name", "") or "")
            if "STB" in block_name.upper():
                continue
        dispatch(e)
    lines = remove_contained_collinear_lines(lines)
    return lines, arcs


def remove_contained_collinear_lines(lines, tol=2.0):
    """같은 직선 위에서 더 긴 선에 완전히 포함되는 짧은 LINE을 제거.

    본선 위에 짧은 레일 조각이 덧그려진 경우(부분 겹침 중복)는 clean_edges의
    끝점-완전일치 중복 제거로 안 걸러져서, split 시 막다른 스텁 노드가 생긴다.
    여기서 collinear-contained 중복을 미리 없애 N분기 등이 본선에 제대로 붙게 한다.
    (완전 겹침만 제거 — 일부만 겹쳐 길이를 연장하는 선은 보존)
    """
    n = len(lines)
    keep = [True] * n
    prm = []
    for L in lines:
        x1, y1 = L.p1
        x2, y2 = L.p2
        dx, dy = x2 - x1, y2 - y1
        ln = math.hypot(dx, dy)
        ux, uy = (dx / ln, dy / ln) if ln > 1e-9 else (0.0, 0.0)
        prm.append((x1, y1, ux, uy, ln))
    for i in range(n):
        if not keep[i]:
            continue
        xi, yi, ui, vi, ni = prm[i]
        if ni <= 1e-9:
            continue
        for j in range(n):
            if i == j or not keep[j]:
                continue
            nj = prm[j][4]
            if nj > ni + tol:
                continue  # j가 i보다 길면 i에 포함 불가
            contained = True
            tlo = thi = None
            for (px, py) in (lines[j].p1, lines[j].p2):
                perp = abs((px - xi) * (-vi) + (py - yi) * ui)  # i 무한직선까지 수직거리
                if perp > tol:
                    contained = False
                    break
                t = (px - xi) * ui + (py - yi) * vi  # i 위로의 사영 위치
                tlo = t if tlo is None else min(tlo, t)
                thi = t if thi is None else max(thi, t)
            if not contained:
                continue
            if tlo >= -tol and thi <= ni + tol:
                # j가 i 구간 안에 완전 포함 → 제거. 길이 같으면(상호포함) 인덱스 큰 쪽만 제거
                if nj < ni - tol or (abs(nj - ni) <= tol and j > i):
                    keep[j] = False
    return [L for k, L in zip(keep, lines) if k]

def transform_arc_to_xy(m: Matrix44, arc_ent):
    """중심은 OCS → WCS, 반지름·각은 WCS XY 투영(지도 평면)."""
    ocs = arc_ent.ocs()
    c = arc_ent.dxf.center
    zc = float(getattr(c, "z", 0) or 0)
    cc = Vec3(c.x, c.y, zc)
    c_w = m.transform(ocs.to_wcs(cc))
    s_w = m.transform(arc_ent.start_point)
    e_w = m.transform(arc_ent.end_point)
    r_w = math.hypot(s_w.x - c_w.x, s_w.y - c_w.y)
    sa_o = math.degrees(math.atan2(s_w.y - c_w.y, s_w.x - c_w.x))
    ea_o = math.degrees(math.atan2(e_w.y - c_w.y, e_w.x - c_w.x))
    return (c_w.x, c_w.y, r_w, sa_o, ea_o)

def arc_entity_endpoints_world_xy(arc_ent, m: Matrix44) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """ARC 끝점: ezdxf WCS(start_point/end_point, OCS·extrusion 반영) 후 블록 등 추가 변환 m."""
    s_w = m.transform(arc_ent.start_point)
    e_w = m.transform(arc_ent.end_point)
    return ((float(s_w.x), float(s_w.y)), (float(e_w.x), float(e_w.y)))

def arc_entity_midpoint_on_curve_world_xy(arc_ent, m: Matrix44) -> Optional[Tuple[float, float]]:
    """DXF가 실제로 그리는 호 위의 중간 점(ezdxf angles(3) 중간). 180° 반원 어느 쪽인지 구분용."""
    try:
        ag = list(arc_ent.angles(3))
        if len(ag) < 3:
            sa = float(arc_ent.dxf.start_angle)
            ea = float(arc_ent.dxf.end_angle)
            mid_a = (sa + ea) * 0.5
        else:
            mid_a = float(ag[1])
        v = list(arc_ent.vertices([mid_a]))[0]
        vw = m.transform(v)
        return (float(vw.x), float(vw.y))
    except Exception:
        return None
def clean_edges(segments, tolerance=INTER_MERGE_TOL):
    """길이 0인 세그먼트와 중복 세그먼트를 제거 (LINE·ARC 모두).

    ARC 중복은 끝점만으로 판별하면 같은 현(chord)의 minor/major 호를 잘못
    병합할 수 있어, 중심·반지름과 실제 호 중간점(p_mid_curve)까지 키에 포함해
    완전히 동일한 호만 제거한다. (중복 호가 남으면 N분기 탐지가 호를 자기
    복제본과 짝지어 N-S-N으로 깨짐)
    """
    seen = set()
    result = []
    for seg in segments:
        if isinstance(seg, LineSeg):
            if dist(seg.p1, seg.p2) <= tolerance:
                continue  # 길이 0 제거
            key = (
                round(min(seg.p1[0], seg.p2[0]), 6),
                round(min(seg.p1[1], seg.p2[1]), 6),
                round(max(seg.p1[0], seg.p2[0]), 6),
                round(max(seg.p1[1], seg.p2[1]), 6),
            )
            if key in seen:
                continue  # 중복 제거
            seen.add(key)
        elif isinstance(seg, ArcSeg):
            ep = tuple(sorted((
                (round(seg.p_start[0], 3), round(seg.p_start[1], 3)),
                (round(seg.p_end[0], 3), round(seg.p_end[1], 3)),
            )))
            if seg.p_mid_curve is not None:
                midk = (round(seg.p_mid_curve[0], 3), round(seg.p_mid_curve[1], 3))
            else:
                # 호 중간점이 없으면 방향까지 구분되도록 각도 스냅샷 사용
                midk = (round(seg.start_deg, 3), round(seg.end_deg, 3))
            key = ("ARC", ep, round(seg.cx, 3), round(seg.cy, 3), round(seg.r, 3), midk)
            if key in seen:
                continue  # 중복 호 제거
            seen.add(key)
        result.append(seg)
    return result

def build_edges_raw_no_split_no_unify(lines, arcs, *, clean=False):
    """DXF collect만: 분할/glue/snap/방향 통일 없음. clean=True면 길이0·중복 직선만 제거."""
    segs = list(lines) + list(arcs)
    if clean:
        segs = clean_edges(segs, tolerance=CLEAN_TOL)
    return [Edge(s) for s in segs]

def iter_insert_virtual_entities(insert_entity, *, max_depth: int = 20, depth: int = 0):
    """INSERT를 virtual_entities로 펼치고, 중첩 INSERT는 재귀한다. (ezdxf: WCS 기준)"""
    try:
        stream = insert_entity.virtual_entities()
    except Exception:
        return
    for ve in stream:
        if ve.dxftype() == "INSERT" and depth < max_depth:
            yield from iter_insert_virtual_entities(ve, max_depth=max_depth, depth=depth + 1)
        else:
            yield ve

