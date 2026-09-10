# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CAD-to-MAP converter that processes DXF factory floor drawings into `.map` files for AGV (Automated Guided Vehicle) path planning. Extracts LINE/ARC geometry from DXF, builds a directed topological graph, and exports MapNode/MapLink records.

## Running the Pipeline

```bash
python test_logic.py
```

No build system, package manager, or test framework. Dependencies: `ezdxf`, `matplotlib`, `numpy`.

**Input configuration** — `test_logic.py` hardcodes two variables at the top that must be set before running:
- `DXF_PATH` — path to the input `.dxf` file (default: `../Testbed1.dxf` relative to the script)
- `DIRECTION` — `"CCW"` or `"CW"` — controls the global travel direction of the output graph

Input files go in `CadToMap_Input/`. The pipeline writes **two** output `.map` files:
- `ori_<stem>.map` — exported before clearance nodes are inserted (pre-clearance snapshot)
- `<stem>.map` — final output including clearance nodes and STB ports


(`extract_pptx.py` is an unrelated PPTX text-extraction utility, not part of the pipeline.)

## Key Constants (core.py)

| Constant | Value | Meaning |
|----------|-------|---------|
| `SNAP_TOL` | 100.0 mm | Final coordinate snapping tolerance (100mm: <200mm 실선 구간 보존. 200이면 120mm 등이 스냅으로 붕괴) |
| `INTER_MERGE_TOL` | 100.0 mm | Segment merging during processing |
| `CLEAN_TOL` | 100.0 mm | Zero-length segment removal |
| `SHORT_STRAIGHT_THRESHOLD` | 900.0 mm | Threshold to classify short straight links |

## Architecture

### Pipeline (test_logic.py)

```
DXF file
  → collect_entities_recursive()           # dxf_parser.py — recurse INSERT blocks, extract LINE/ARC/LWPOLYLINE
  → build_edges_raw_no_split_no_unify()    # geometry.py — unsplit/unidirectional snapshot (debugging only)
  → split_edges_at_intersections()         # geometry.py — find and split crossing segments
  → glue_arc_endpoints_to_lines()          # geometry.py
  → snap_segments()                        # geometry.py — quantize coords to SNAP_TOL grid
  → reproject_arcs_to_circle()             # geometry.py
  → merge_line_segments_at_degree2_nodes() # geometry.py — collapse collinear chains at degree-2 nodes
  → clean_edges()                          # geometry.py — remove zero-length segments
  → unify_edge_directions()                # topology.py — DFS from outermost node
  → export_map_from_unified_edges()        # map_exporter.py → ori_*.map (pre-clearance snapshot)
  → extract_stb_ports()                    # port_extractor.py → save ori_*.map with T-nodes
  → find_un_branch_merge_groups()          # map_exporter.py — detect U/N branch shapes (topology pass)
  → insert_clearance_nodes()               # topology.py
  → find_un_branch_merge_groups_by_x()     # map_exporter.py — second detection pass (X-axis based),
                                           #   filtered to exclude intra_arm_u_idx already handled above
  → export_map_from_unified_edges()        # map_exporter.py → *.map (final)
  → extract_stb_ports()                    # port_extractor.py
  → save_map()                             # map_exporter.py → *.map with STB T-nodes
```

### Module-based branch judgment (module_judge.py)

Drawings made with the RailPlugin "Module" tab carry, per block reference, XData `RAILPLUGIN`
`[Real L, Int16 module idx, Int16 kind=7, Real W, Int16 lanes, Real R, Real A]` (block name `RAILMOD_<NAME>_R.._L..[_W..][_A..]`).
`config.json > module_judgment.mode`: `auto` (default — use module info when any module is present, else the geometric path),
`on`, `off`. In module mode **no geometric branch detection runs** — the three judgment inputs come from modules:

- ori export `precomputed_merge_groups` (arch W ≤ 2R+50 → U, cross → N) with `emit_line_arc_line_u_links=False`
- `insert_clearance_nodes(..., module_judgment={u_pairs, n_pairs, lr_arcs, corner_arcs})` — skips its detection block
  (`if not _module_mode:`), the degree-based L/R loop, the arc-arc/arc-line-arc scans and the post-rebuild U rescan;
  only the placement rules (J1/J2/J3, 350 offsets, driving nodes) run
- final export groups from `ModuleJudge.final_merge_groups` (arch W < 1601 → U, cross → N), computed after the CW flip

Module ↔ edge binding is positional (mirror of `ModuleGeom.Build` in world coords: arc centre/radius/angle span, collinear
lines), done once after `unify_edge_directions`; later stages follow the same Edge objects. Module entities bypass the
colour/layer rail filter. Outputs `<stem>_modules.csv` (per-module type, R/L/W/A, judgment, notes, spacing warnings).
Regression rule: a drawing without modules must give byte-identical maps to the geometric path (260410: ori `2e605d35…`,
final `6792d1a5…`). Synthetic test drawings: `python module_testdxf.py <out_dir>`.

### Module Responsibilities

- **core.py** — Data classes (`LineSeg`, `ArcSeg`, `Edge`, `MapNode`, `MapLink`) and math utilities.
- **dxf_parser.py** — ezdxf ingestion; handles bulge-encoded polylines and recursive INSERT blocks. Splits ≥180° arcs at parse time via `split_near_180_arcs`.
- **geometry.py** — Segment-level operations: intersection splitting, arc 180° splitting, snapping, reprojection, collinear-chain merging.
- **topology.py** — Direction unification via DFS. Arc direction rules: line→arc uses chord midpoint; arc→line uses tangent vectors. Inserts clearance nodes.
- **map_exporter.py** — Converts unified edges to MapNode/MapLink; assigns link types (`S`/`L`/`R`/`U`/`N`), computes relative distances. Also hosts `find_un_branch_merge_groups` and `find_un_branch_merge_groups_by_x`.
- **port_extractor.py** — Matches INSERT-block STB equipment ports onto existing rail links; inserts intermediate `T` nodes.

### .map File Format

Plain text, fields separated by `/`, list-within-field separated by `|`.

- **MapNode fields**: `id` (6 chars), `type` (`G`/`T`/`L`), `reality` (`R`/`V`), `x`, `y`, `parent_link_id`, `relative_distance`, `layer_id`, `pio_device_id`, params (`disabled`, `yield_enabled`)
- **MapLink fields**: `id`, `type` (`S`/`L`/`R`/`U`/`N`), `start_node_id`, `end_node_id`, `length`, `steer` (`L`/`R`/`N`), `slope` (`U`/`D`), `speed`, `vehicle_detect`, `general_detect`, `CPS`, params (`CarrierType`, `GroupID`, `Disabled`, `Penalty`, `YieldDisabled`, `ReleaseDistance`)

### Port Extractor CSV Config (CadToMap_Input/)

| File | Purpose |
|------|---------|
| `Layer_EqPort.csv` | DXF layer names for EQ equipment ports |
| `Layer_StbPort.csv` | DXF layer names for STB transfer ports |
| `EqPort_Num.csv` | Ports-per-equipment grouping |
| `EqPort_Difference.csv` | Y-spacing between EQ ports |
| `STB_Rail_Gap.csv` | Distance threshold to nearest rail |
| `STB_Search_Range.csv` | Search radius for STB rail matching |

## Critical Geometric Conventions

- **Arc 180° ambiguity**: Arcs ≥ 180° are split; `p_mid_curve` (actual drawn arc midpoint) + `arc_should_use_ccw_sweep()` determine which half to keep CCW vs CW.
- **ArcSeg state**: Stores both current angles and originals (`dxf_start_deg`/`dxf_end_deg`) to survive split operations correctly.
- **DFS direction unification**: Traverses from the geometrically outermost node; context determines arc orientation (chord midpoint rule for line→arc, tangent rule for arc→line).
- **Two merge-group passes**: The first pass (`find_un_branch_merge_groups`) runs on the pre-clearance topology and identifies U/N shapes by geometry. The second pass (`find_un_branch_merge_groups_by_x`) runs post-clearance and is filtered to exclude indices already handled as intra-arm U-turns (`intra_arm_u_idx`).
- **Coordinate system**: 2D XY (factory floor top-down), Z ignored, units in mm.
