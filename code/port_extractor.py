from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ─── 데이터 클래스 ─────────────────────────────────────────────────────────────

@dataclass
class TransferNode:
    """DXF INSERT 블록에서 추출한 EQ/STB 좌표."""
    x: float
    y: float


# ─── STB 노드 수집 ────────────────────────────────────────────────────────────

def _collect_stb_nodes(doc, keyword: str = "STB") -> List[TransferNode]:
    from ezdxf.math import Vec3
    result: List[TransferNode] = []
    seen: set = set()

    for e in doc.modelspace():
        if e.dxftype() != "INSERT":
            continue
        block_name = e.dxf.name or ""
        if keyword.upper() not in block_name.upper():
            continue
        print(f"  [debug] STB 컨테이너 '{block_name}'")
        def _recurse(virtual_insert, depth=0):
            if depth > 10:
                return
            try:
                for ve in virtual_insert.virtual_entities():
                    if ve.dxftype() != "INSERT":
                        continue
                    vname = ve.dxf.name or ""
                    if vname.startswith("*"):
                        continue
                    block = doc.blocks.get(vname)
                    if block is None:
                        continue
                    child_inserts = [
                        be for be in block
                        if be.dxftype() == "INSERT" and not (be.dxf.name or "").startswith("*")
                    ]
                    if child_inserts:
                        _recurse(ve, depth + 1)
                    else:
                        xs, ys = [], []
                        for be in block:
                            if be.dxftype() == "LINE":
                                xs += [be.dxf.start.x, be.dxf.end.x]
                                ys += [be.dxf.start.y, be.dxf.end.y]
                        if not xs:
                            continue
                        try:
                            m = ve.matrix44()
                        except Exception:
                            continue
                        lx = (min(xs) + max(xs)) / 2
                        ly = (min(ys) + max(ys)) / 2
                        wcs = m.transform(Vec3(lx, ly, 0))
                        cx = round(wcs.x, 0)
                        cy = round(wcs.y, 0)
                        print(f"  [debug] BBox center WCS=({cx},{cy}) from '{vname}'")
                        key = (cx, cy)
                        if key not in seen:
                            seen.add(key)
                            result.append(TransferNode(x=cx, y=cy))
            except Exception as ex:
                print(f"  [debug] 오류 depth={depth}: {ex}")

        _recurse(e)

    return result


@dataclass
class Port:
    id: str
    type: str            # EQ / STB / UTB / STK / TL / CONV
    carrier_type: str
    x: float
    y: float
    node_id: str
    node_alignment: str  # L / R / U
    z: int = 0
    slide_distance: int = 0
    hoist_distance: int = 0
    stb_zone: str = ""
    ssid: str = ""
    n2: str = ""
    group_id: str = ""
    disabled: str = ""


def format_port_line(p: Port) -> str:
    return (
        f"PORT/{p.id}/{p.type}/{p.carrier_type}"
        f"/{int(p.x)}/{int(p.y)}/{p.z}"
        f"/{p.node_id}/{p.node_alignment}"
        f"/{p.slide_distance}/{p.hoist_distance}"
        f"/{p.stb_zone}/{p.ssid}/{p.n2}"
        f"/{p.group_id}|{p.disabled}"
    )


# ─── 링크 인덱스 빌더 ─────────────────────────────────────────────────────────

def _build_link_index(
    nodes_by_id: Dict,
    links: List,
) -> Tuple[Dict[float, List], Dict[float, List]]:
    """
    MapNode/MapLink 리스트에서 수직(x 기준) / 수평(y 기준) 링크 인덱스 생성.

    vertical_links[x]   : 해당 x 좌표의 수직 링크 목록
    horizontal_links[y] : 해당 y 좌표의 수평 링크 목록
    """
    vert: Dict[float, List] = {}
    horiz: Dict[float, List] = {}

    for lk in links:
        sn = nodes_by_id.get(lk.start_node_id)
        en = nodes_by_id.get(lk.end_node_id)
        if sn is None or en is None:
            continue
        sx, sy = float(sn.x), float(sn.y)
        ex, ey = float(en.x), float(en.y)
        if abs(sx - ex) < 1.0:       # 수직 링크
            key = round((sx + ex) / 2, 0)
            vert.setdefault(key, []).append((lk, sn, en))
        elif abs(sy - ey) < 1.0:     # 수평 링크
            key = round((sy + ey) / 2, 0)
            horiz.setdefault(key, []).append((lk, sn, en))

    return vert, horiz


# ─── STB nodeAlignment 결정 ───────────────────────────────────────────────────

def _alignment(
    entries: List,
    is_vertical: bool,
    from_plus_side: bool,
) -> str:
    """
    레일 방향과 접근 방향으로 nodeAlignment를 결정한다.

    수직 레일(X 기준 오프셋):
      max_y가 startNode → plus방향="R" / minus방향="L"
      max_y가 endNode   → plus방향="L" / minus방향="R"

    수평 레일(Y 기준 오프셋):
      max_x가 startNode → plus방향="L" / minus방향="R"
      max_x가 endNode   → plus방향="R" / minus방향="L"
    """
    for _, sn, en in entries:
        if is_vertical:
            at_start = (max(float(sn.y), float(en.y)) == float(sn.y))
            return ("R" if at_start else "L") if from_plus_side else ("L" if at_start else "R")
        else:
            at_start = (max(float(sn.x), float(en.x)) == float(sn.x))
            return ("L" if at_start else "R") if from_plus_side else ("R" if at_start else "L")
    return "F"


# ─── 포트 좌표 기반 STB 포트 추출 ─────────────────────────────────────────────

def collect_port_nodes_by_color(doc, port_colors: List[int]) -> List[TransferNode]:
    """선택된 ACI 색상의 LINE을 가진 리프 INSERT 블록의 BBox 중심점을 포트 위치로 수집."""
    if not port_colors:
        return []
    from dxf_parser import _resolve_color
    from ezdxf.math import Vec3
    color_set = set(port_colors)
    result: List[TransferNode] = []
    seen: set = set()

    def _recurse(virtual_insert, depth=0):
        if depth > 10:
            return
        try:
            for ve in virtual_insert.virtual_entities():
                if ve.dxftype() != "INSERT":
                    continue
                vname = ve.dxf.name or ""
                if vname.startswith("*"):
                    continue
                block = doc.blocks.get(vname)
                if block is None:
                    continue
                child_inserts = [
                    be for be in block
                    if be.dxftype() == "INSERT" and not (be.dxf.name or "").startswith("*")
                ]
                if child_inserts:
                    _recurse(ve, depth + 1)
                else:
                    xs, ys = [], []
                    for be in block:
                        if be.dxftype() == "LINE" and _resolve_color(be, doc) in color_set:
                            xs += [be.dxf.start.x, be.dxf.end.x]
                            ys += [be.dxf.start.y, be.dxf.end.y]
                    if not xs:
                        continue
                    try:
                        m = ve.matrix44()
                    except Exception:
                        continue
                    lx = (min(xs) + max(xs)) / 2
                    ly = (min(ys) + max(ys)) / 2
                    wcs = m.transform(Vec3(lx, ly, 0))
                    cx = round(wcs.x, 0)
                    cy = round(wcs.y, 0)
                    key = (cx, cy)
                    if key not in seen:
                        seen.add(key)
                        result.append(TransferNode(x=cx, y=cy))
        except Exception:
            pass

    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            _recurse(e)
    return result


def extract_stb_ports(
    doc,
    nodes: List,
    links: List,
    *,
    next_node_id: int = 1,
    extra_port_nodes: Optional[List[TransferNode]] = None,
) -> Tuple[List[Port], List, int]:
    """
    DXF 문서에서 블록명에 'STB'가 포함된 INSERT 블록의 사각형 LWPOLYLINE
    무게중심을 추출해, 기존 nodes/links의 수직/수평 링크에 매칭해 STB 포트를
    생성한다.

    탐색 방식
    --------
    - 각 STB 좌표에서 모든 수직/수평 링크 키까지의 거리를 구해
      가장 가까운 키부터 순서대로 시도한다.
    - 링크 양 끝 노드 좌표와 일치 → 기존 노드 ID 재사용
    - 매칭되면 break

    Parameters
    ----------
    doc            : ezdxf document (STB centroid를 직접 추출)
    nodes          : MapNode 리스트
    links          : MapLink 리스트
    next_node_id   : 신규 노드 ID 시작값

    Returns
    -------
    ports        : STB Port 리스트
    new_t_nodes  : 새로 생성된 T타입 MapNode 리스트
    next_node_id : 갱신된 다음 ID 값
    """
    from map_exporter import MapNode

    stb_nodes: List[TransferNode] = list(extra_port_nodes) if extra_port_nodes else []
    print(f"  포트 노드: {len(stb_nodes)}")

    nodes_by_id: Dict[str, object] = {n.id: n for n in nodes}
    new_nodes: List = []
    vert, horiz = _build_link_index(nodes_by_id, links)

    ports: List[Port] = []
    count = 1

    for stb in stb_nodes:
        pid = "STB" + str(count).zfill(5)
        rx, ry = round(stb.x, 0), round(stb.y, 0)

        # 각 STB 위치에서 모든 수직/수평 링크 키까지의 거리 리스트 구성
        # 튜플: (거리, link_dict, key, is_vert, from_plus)
        candidates: List[Tuple[float, Dict[float, List], float, bool, bool]] = []
        for xk in vert.keys():
            candidates.append((abs(xk - rx), vert, xk, True, xk > rx))
        for yk in horiz.keys():
            candidates.append((abs(yk - ry), horiz, yk, False, yk > ry))

        candidates.sort(key=lambda t: t[0])

        made = False
        for _dist, link_dict, key, is_vert, from_plus in candidates:
            align = _alignment(link_dict[key], is_vert, from_plus)

            for lk, sn_n, en_n in link_dict[key]:
                if is_vert:
                    lo_c = min(float(sn_n.y), float(en_n.y))
                    hi_c = max(float(sn_n.y), float(en_n.y))
                    coord = ry
                    nx, ny = key, ry
                    sn_coord = float(sn_n.y)
                    en_coord = float(en_n.y)
                else:
                    lo_c = min(float(sn_n.x), float(en_n.x))
                    hi_c = max(float(sn_n.x), float(en_n.x))
                    coord = rx
                    nx, ny = rx, key
                    sn_coord = float(sn_n.x)
                    en_coord = float(en_n.x)

                if lo_c < coord < hi_c:
                    nid = str(next_node_id).zfill(6)
                    rel = abs(nx - float(sn_n.x)) + abs(ny - float(sn_n.y))
                    new_node = MapNode(
                        id=nid, type="T", reality="R", x=nx, y=ny,
                        parent_link_id=lk.id, relative_distance=str(rel), layer_id="0",
                    )
                    new_nodes.append(new_node)
                    nodes_by_id[nid] = new_node
                    next_node_id += 1
                    ports.append(Port(pid, "STB", "F400", rx, ry, nid, align))
                    count += 1
                    made = True
                    break
                elif coord == sn_coord:
                    ports.append(Port(pid, "STB", "F400", rx, ry, sn_n.id, align))
                    count += 1
                    made = True
                    break
                elif coord == en_coord:
                    ports.append(Port(pid, "STB", "F400", rx, ry, en_n.id, align))
                    count += 1
                    made = True
                    break

            if made:
                break

    print(f"  STB 포트: {len(ports)}개")
    return ports, new_nodes, next_node_id
