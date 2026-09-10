from __future__ import annotations
import math, copy, json, argparse, sys
from pathlib import Path

from typing import *
import ezdxf

import itertools
from core import *
from dxf_parser import *
from geometry import *
from topology import *
from map_exporter import export_map_from_unified_edges, find_un_branch_merge_groups, find_un_branch_merge_groups_by_x, save_map
from topology import insert_clearance_nodes
from port_extractor import extract_stb_ports, collect_port_nodes_by_color
from part_counter import (count_parts, count_geometry, save_parts_csv,
                          summary_text, print_table)

# ---------------------------------------------------------
# config 로드
def _get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):  # PyInstaller exe
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

_base = _get_base_dir()
_config_path = _base / "config.json"
with open(_config_path, encoding="utf-8-sig") as _f:
    _cfg = json.load(_f)

# CLI 인자 (dxf_path는 인자 > config 순서로 우선)
_parser = argparse.ArgumentParser()
_parser.add_argument("dxf_path", nargs="?", default=None, help="입력 DXF 파일 경로")
_args = _parser.parse_args()

_dxf_str = _args.dxf_path or _cfg["io"]["dxf_path"]
DXF_PATH = Path(_dxf_str) if Path(_dxf_str).is_absolute() else (_base / _dxf_str)
MAP_OUT = DXF_PATH.parent / (DXF_PATH.stem + ".map")
ORI_MAP_OUT = DXF_PATH.parent / ("ori_" + DXF_PATH.stem + ".map")

DIRECTION = _cfg["io"]["direction"]

# tolerance
_tol = _cfg["tolerance"]
SNAP_TOL               = _tol["snap_tol"]
INTER_MERGE_TOL        = _tol["inter_merge_tol"]
CLEAN_TOL              = _tol["clean_tol"]
SNAP_DECIMALS          = _tol["snap_decimals"]
SHORT_STRAIGHT_THRESHOLD = _tol["short_straight_threshold"]

# branch detection
_bd = _cfg["branch_detection"]
N_BRANCH_MIN_ARC_SWEEP_DEG    = _bd["n_branch_min_arc_sweep_deg"]
N_BRANCH_DIAGONAL_AXIS_TOL_DEG = _bd["n_branch_diagonal_axis_tol_deg"]
SCALE_TO_MM                   = _bd["scale_to_mm"]
U_BRANCH_ARC_SUM_TARGET_MM    = _bd.get("u_branch_arc_sum_target_mm", 2000.0) + 350.0
# 표준 호 반지름 R — 아래 두 값이 여기서 파생된다(하드코딩 금지)
RAIL_ARC_RADIUS_MM            = _bd.get("rail_arc_radius_mm", 480.0)
RAIL_ARC_RADIUS_TOL_MM        = _bd.get("rail_arc_radius_tol_mm", 5.0)
# ori U 폭 게이트 = 2R+50. tight 호-호 U(폭 2R)만 통과, 3R U턴브릿지는 제외
ORI_U_X_THRESHOLD_MM          = 2.0 * RAIL_ARC_RADIUS_MM + 50.0

# ---------------------------------------------------------
_cf = _cfg.get("color_filter", {})
RAIL_COLOR = _cf.get("rail_color") or None
PORT_COLORS = _cf.get("port_colors") or []
RAIL_LAYERS = _cf.get("rail_layers") or None  # [] → None (필터 없음)

doc = ezdxf.readfile(str(DXF_PATH))
lines, arcs = collect_entities_recursive(doc, rail_color=RAIL_COLOR, rail_layers=RAIL_LAYERS)
if RAIL_COLOR is not None or RAIL_LAYERS:
    print(f"레일 필터링 완료: LINE {len(lines)}개, ARC {len(arcs)}개")
edges_raw_no_split_no_unify = build_edges_raw_no_split_no_unify(lines, arcs)
split_lines, arcs, intersection_vertices = split_edges_at_intersections(lines, arcs)
glue_arc_endpoints_to_lines(split_lines, arcs, tol=max(SNAP_TOL, INTER_MERGE_TOL))
snap_segments(split_lines, arcs, tol=SNAP_TOL)
reproject_arcs_to_circle(arcs)
split_lines = merge_line_segments_at_degree2_nodes(split_lines, arcs, tol=SNAP_TOL)
all_segments = split_lines + arcs
all_segments = clean_edges(all_segments)
unified_edges = unify_edge_directions(all_segments, tolerance=INTER_MERGE_TOL, start_direction="CCW")

# ---------------------------------------------------------
# 대기 노드 적용 전 원본 저장 (CW이면 반전 후 저장, 탐지를 위해 복원)

if DIRECTION.upper() == "CW":
    for e in unified_edges:
        e.reverse()
    unified_edges = list(reversed(unified_edges))
nodes, links = export_map_from_unified_edges(
    unified_edges,
    ORI_MAP_OUT,
    tol=INTER_MERGE_TOL,
    scale_to_mm=SCALE_TO_MM,
    short_straight_threshold=SHORT_STRAIGHT_THRESHOLD,
    header="#LSL - Jcolab",
    u_branch_arc_sum_target_mm=U_BRANCH_ARC_SUM_TARGET_MM,
    u_x_threshold_mm=ORI_U_X_THRESHOLD_MM,  # =2R+50. ori는 tight 호-호 U만 (호직호·반지름 큰 U 제외). 최종 맵은 1601로 별도 기준
    line_arc_line_u_radius_mm=RAIL_ARC_RADIUS_MM,
    line_arc_line_u_radius_tol_mm=RAIL_ARC_RADIUS_TOL_MM,
)
_extra_ori = collect_port_nodes_by_color(doc, PORT_COLORS)
stb_ports, new_t_nodes, _ = extract_stb_ports(doc, nodes, links, next_node_id=len(nodes) + 1, extra_port_nodes=_extra_ori)
nodes.extend(new_t_nodes)
save_map(str(ORI_MAP_OUT), nodes, links, header="#LSL - Jcolab", ports=stb_ports)
# ori 는 대기(clearance) 노드 삽입 전 스냅샷 — 최종 맵과 개수가 다르다
print(f"[ori] NODE: {len(nodes)}개, LINK: {len(links)}개, STB 포트: {len(stb_ports)}개")
print(f"[완료] 원본: {ORI_MAP_OUT} 저장됨")
if DIRECTION.upper() == "CW":
    unified_edges = list(reversed(unified_edges))
    for e in unified_edges:
        e.reverse()

# ---------------------------------------------------------
# U/N 분기 ARC 인덱스를 먼저 식별한 뒤 clearance node 삽입

merge_groups = find_un_branch_merge_groups(
    unified_edges,
    INTER_MERGE_TOL,
    SHORT_STRAIGHT_THRESHOLD,
    scale_to_mm=SCALE_TO_MM,
    n_branch_min_arc_sweep_deg=N_BRANCH_MIN_ARC_SWEEP_DEG,
    n_branch_diagonal_axis_tol_deg=N_BRANCH_DIAGONAL_AXIS_TOL_DEG,
    u_branch_arc_sum_target_mm=U_BRANCH_ARC_SUM_TARGET_MM,
)
n_arc_pairs = [indices for indices, branch_type in merge_groups if branch_type == "N"]
u_arc_pairs = [indices for indices, branch_type in merge_groups if branch_type == "U"]

unified_edges, intra_arm_u_idx, complex_lr_flat, plain_arc_flat, graph_scan_u_pair_objs = insert_clearance_nodes(
    unified_edges,
    tol=SNAP_TOL,
    n_arc_indices=n_arc_pairs,
    u_arc_indices=u_arc_pairs,
    cfg=_cfg,
)
merge_groups_x = find_un_branch_merge_groups_by_x(
    unified_edges,
    INTER_MERGE_TOL,
    SHORT_STRAIGHT_THRESHOLD,
    scale_to_mm=SCALE_TO_MM,
    n_branch_min_arc_sweep_deg=N_BRANCH_MIN_ARC_SWEEP_DEG,
    n_branch_diagonal_axis_tol_deg=N_BRANCH_DIAGONAL_AXIS_TOL_DEG,
    u_x_threshold_mm=1601.0,  # 폭 1600 미만만 U (clearance 단계와 동일 기준)
    # 복합분기로 이미 처리된 호(cflat) 등을 U 탐색 후보에서 제외 — 인접 U의 짝을
    # 가로채 잘못된 쌍을 만들고 그 U가 누락되는 비대칭 버그 방지
    exclude_indices=set(complex_lr_flat) | set(intra_arm_u_idx) | set(plain_arc_flat),
)

merge_groups_x = [
    (indices, btype) for indices, btype in merge_groups_x
    if not any(idx in intra_arm_u_idx for idx in indices)
    and not any(idx in complex_lr_flat for idx in indices)
    and not any(idx in plain_arc_flat for idx in indices)
]

# 그래프 스캔 U 쌍(topology에서 탐지)을 post-clearance 인덱스로 변환해 직접 추가
_id_to_post_idx = {id(e): j for j, e in enumerate(unified_edges)}
_existing_covered = set(idx for idxs, _ in merge_groups_x for idx in idxs)
for _pair_objs in graph_scan_u_pair_objs:
    _idxs = tuple(_id_to_post_idx.get(id(e)) for e in _pair_objs)
    if any(idx is None for idx in _idxs):
        continue
    if any(idx in _existing_covered for idx in _idxs):
        continue
    if any(idx in intra_arm_u_idx or idx in complex_lr_flat or idx in plain_arc_flat for idx in _idxs):
        continue
    merge_groups_x.append((_idxs, "U"))
    _existing_covered.update(_idxs)

# CW 방향이면 모든 탐지 완료 후 반전 + 인덱스 재매핑
if DIRECTION.upper() == "CW":
    N = len(unified_edges)
    _lr_swap = {"L": "R", "R": "L"}
    for e in unified_edges:
        e.reverse()
        ft = getattr(e, "forced_link_type", None)
        if ft in _lr_swap:
            e.forced_link_type = _lr_swap[ft]
    unified_edges = list(reversed(unified_edges))
    merge_groups_x = [
        (tuple(N - 1 - idx for idx in reversed(idxs)), btype)
        for idxs, btype in merge_groups_x
    ]

nodes, links = export_map_from_unified_edges(
    unified_edges,
    MAP_OUT,
    tol=INTER_MERGE_TOL,
    scale_to_mm=SCALE_TO_MM,
    short_straight_threshold=SHORT_STRAIGHT_THRESHOLD,
    precomputed_merge_groups=merge_groups_x,
    line_arc_line_u_radius_mm=RAIL_ARC_RADIUS_MM,
    line_arc_line_u_radius_tol_mm=RAIL_ARC_RADIUS_TOL_MM,
    header="#LSL - Jcolab",
)

_extra_final = collect_port_nodes_by_color(doc, PORT_COLORS)
stb_ports, new_t_nodes, _ = extract_stb_ports(
    doc,
    nodes,
    links,
    next_node_id=len(nodes) + 1,
    extra_port_nodes=_extra_final,
)
nodes.extend(new_t_nodes)

print(f"[최종] NODE: {len(nodes)}개, LINK: {len(links)}개, STB 포트: {len(stb_ports)}개, 신규 T노드: {len(new_t_nodes)}개 (대기 노드 포함)")

save_map(
    str(MAP_OUT),
    nodes,
    links,
    header="#LSL - Jcolab",
    ports=stb_ports,
)
print(f"[완료] {MAP_OUT} 저장됨")

# 정형화 부품 수량 집계 (플러그인으로 작도한 도면일 때만 산출)
#  ※ 부가 산출물이므로 실패해도 map 변환 결과는 그대로 살린다.
try:
    _parts = count_parts(doc)
    _geom = count_geometry(doc)      # 부품에 안 들어간 직선·호 (개수 + 총 길이)
except Exception as _e:
    _parts, _geom = None, None
    print(f"[경고] 부품 집계 실패: {_e}")
if _parts:
    print(f"[부품] {summary_text(_parts)}")
    if _geom:
        print(f"[형상] 부품 제외 — 직선 {_geom['line_count']}개 {_geom['line_len']:,.0f}mm"
              f" / 호 {_geom['arc_count']}개 {_geom['arc_len']:,.0f}mm")
    PARTS_OUT = DXF_PATH.parent / (DXF_PATH.stem + "_parts.csv")
    try:
        save_parts_csv(str(PARTS_OUT), _parts, geom=_geom)
        print(f"[부품] 저장됨: {PARTS_OUT}")
    except OSError as _e:
        # 대개 CSV 가 엑셀에서 열려 있어 잠긴 경우 — 파일 대신 화면으로 내보낸다
        print(f"[경고] 부품 CSV 저장 실패({_e.strerror}): {PARTS_OUT}")
        print("       엑셀 등에서 열려 있으면 닫고 다시 실행하세요. 아래는 같은 내용입니다.")
        print_table(_parts, _geom)
