# test_disjoint_paths.py
import sys
import json
import math
from pathlib import Path

# Load config
base = Path(__file__).resolve().parent
with open(base / "config.json", encoding="utf-8-sig") as f:
    cfg = json.load(f)

import ezdxf
from core import *
from dxf_parser import *
from geometry import *
from topology import *

dxf_str = cfg["io"]["dxf_path"]
DXF_PATH = Path(dxf_str) if Path(dxf_str).is_absolute() else (base / dxf_str)

doc = ezdxf.readfile(str(DXF_PATH))
lines, arcs = collect_entities_recursive(doc, rail_color=None)
split_lines, arcs, intersection_vertices = split_edges_at_intersections(lines, arcs)
glue_arc_endpoints_to_lines(split_lines, arcs, tol=max(SNAP_TOL, INTER_MERGE_TOL))
snap_segments(split_lines, arcs, tol=SNAP_TOL)
reproject_arcs_to_circle(arcs)
split_lines = merge_line_segments_at_degree2_nodes(split_lines, arcs, tol=SNAP_TOL)
all_segments = split_lines + arcs
all_segments = clean_edges(all_segments)
unified_edges = unify_edge_directions(all_segments, tolerance=INTER_MERGE_TOL, start_direction="CCW")

# Build adjacency graph
from collections import defaultdict
in_edges = defaultdict(list)
out_edges = defaultdict(list)
def _v(p):
    cell = max(float(SNAP_TOL), 0.1)
    return (int(math.floor(float(p[0]) / cell)), int(math.floor(float(p[1]) / cell)))

for i, e in enumerate(unified_edges):
    in_edges[_v(e.end)].append((i, e))
    out_edges[_v(e.start)].append((i, e))

def find_shortest_path(start_v, end_v, exclude_edges):
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

def check_disjoint_paths(i):
    arc = unified_edges[i]
    js = _v(arc.start)
    in_js = in_edges.get(js, [])
    out_js = out_edges.get(js, [])
    out_lines = [(oi, oe) for oi, oe in out_js if oe.edge_type == "LINE"]
    if not out_lines:
        return False, []
    top_line_idx, top_line_e = out_lines[0]
    vb = _v(top_line_e.end)
    in_vb = in_edges.get(vb, [])
    merge_arcs = [(mi, me) for mi, me in in_vb if me.edge_type == "ARC"]
    if not merge_arcs:
        return False, []
    merge_arc_idx = merge_arcs[0][0]
    
    div_arc_end_v = _v(arc.end)
    mer_arc_start_v = _v(merge_arcs[0][1].start)
    
    # We must exclude:
    # 1. top_line_idx (the main track between junctions)
    # 2. i (the diverge arc itself)
    # 3. merge_arc_idx (the merge arc itself)
    # This prevents path-finding from going onto the main track through the junctions!
    base_exclude = {top_line_idx, i, merge_arc_idx}
    
    # Path 1
    path1 = find_shortest_path(div_arc_end_v, mer_arc_start_v, base_exclude)
    if not path1:
        return False, []
        
    # Path 2 (must be edge-disjoint from Path 1)
    path2 = find_shortest_path(div_arc_end_v, mer_arc_start_v, base_exclude | set(path1))
    
    if path2:
        return True, (path1, path2)
    return False, [path1]

print(f"{'LOOP ID':<10} | {'MER ID':<10} | {'X':<8} | {'NESTED LOOP (3-TRACKS)?':<25} | {'PATHS'}")
print("-" * 90)

for i, arc in enumerate(unified_edges):
    if arc.edge_type != "ARC":
        continue
    js = _v(arc.start)
    in_js = in_edges.get(js, [])
    out_js = out_edges.get(js, [])
    if not (sum(1 for _, e in in_js if e.edge_type == "LINE") == 1 and
            sum(1 for _, e in in_js if e.edge_type == "ARC") == 0 and
            sum(1 for _, e in out_js if e.edge_type == "LINE") == 1 and
            sum(1 for _, e in out_js if e.edge_type == "ARC") == 1):
        continue
    out_lines = [(oi, oe) for oi, oe in out_js if oe.edge_type == "LINE"]
    if not out_lines:
        continue
    top_line_idx, top_line_e = out_lines[0]
    vb = _v(top_line_e.end)
    in_vb = in_edges.get(vb, [])
    out_vb = out_edges.get(vb, [])
    if not (sum(1 for _, e in in_vb if e.edge_type == "LINE") == 1 and
            sum(1 for _, e in in_vb if e.edge_type == "ARC") == 1 and
            sum(1 for _, e in out_vb if e.edge_type == "LINE") == 1 and
            sum(1 for _, e in out_vb if e.edge_type == "ARC") == 0):
        continue
    merge_arcs = [(mi, me) for mi, me in in_vb if me.edge_type == "ARC"]
    if not merge_arcs:
        continue
    merge_arc_idx = merge_arcs[0][0]
    _pair_X = dist(arc.start, merge_arcs[0][1].end)

    is_complex, paths = check_disjoint_paths(i)
    comp_str = "YES (REAL RED)" if is_complex else "NO (FAKE BLUE)"
    print(f"#{i:<9} | #{merge_arc_idx:<8} | {_pair_X:<8.0f} | {comp_str:<25} | {paths}")
