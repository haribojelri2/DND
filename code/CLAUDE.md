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
| `SNAP_TOL` | 200.0 mm | Final coordinate snapping tolerance |
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
