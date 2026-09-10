from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import ezdxf


ROOT = Path("/Users/jinhyeok/Desktop/LSL")
EXAMPLE = ROOT / "2차선_flexible block 예시.dxf"
ORIGINAL = ROOT / "2026/진행중/D&D TS/객체화/2차선.dxf"
OUTPUT = ROOT / "2026/진행중/D&D TS/객체화/2차선_flexible_all.dxf"


TARGET_BLOCKS = [
    "2rail_H3",
    "2rail_H4",
    "2rail_W900_H1",
    "2rail_W900_H2",
    "2rail_W900_H3",
    "2rail_W900_H4",
]

EXAMPLE_MOVE_MULTIPLIERS = {
    "905": 2 / 3,
    "906": 1 / 3,
    "907": 2 / 3,
    "908": 1 / 3,
}


@dataclass
class EntityInfo:
    handle: str
    kind: str
    x1: float
    y1: float
    x2: float | None = None
    y2: float | None = None
    a0: float | None = None
    a1: float | None = None


@dataclass
class UShape:
    left_top_arc: str | None = None
    right_top_arc: str | None = None
    top_line: str | None = None
    left_bottom_arc: str | None = None
    right_bottom_arc: str | None = None
    bottom_line: str | None = None
    top_y: float | None = None
    bottom_y: float | None = None
    ratio: float = 0.0

    def handles(self) -> list[str]:
        return [
            h
            for h in [
                self.left_top_arc,
                self.top_line,
                self.right_top_arc,
                self.left_bottom_arc,
                self.bottom_line,
                self.right_bottom_arc,
            ]
            if h
        ]


@dataclass
class BlockGeom:
    name: str
    record: str
    entities: list[EntityInfo]
    left_line: str
    right_line: str
    top_outer_left: str
    top_outer_right: str
    bottom_outer_left: str
    bottom_outer_right: str
    bottom_port: UShape
    top_port: UShape
    groups: list[UShape]
    minx: float
    maxx: float
    miny: float
    maxy: float
    left_x: float
    right_x: float
    is_w900: bool


@dataclass
class DynHandles:
    xdict: str
    graph: str
    purge: str
    vparam: str
    vbase_grip: str
    vbase_x: str
    vbase_y: str
    vend_grip: str
    vend_x: str
    vend_y: str
    top_stretch: str
    bottom_stretch: str
    hparam: str
    hbase_grip: str
    hbase_x: str
    hbase_y: str
    hend_grip: str
    hend_x: str
    hend_y: str
    right_stretch: str
    left_stretch: str
    move_end: list[str] = field(default_factory=list)
    move_base: list[str] = field(default_factory=list)


class HandleGen:
    def __init__(self, start: int) -> None:
        self.value = start

    def new(self) -> str:
        h = f"{self.value:X}"
        self.value += 1
        return h


def pair(code: str | int, value: str | int | float) -> tuple[str, str]:
    return (str(code), str(value))


def entry(kind: str, handle: str | None = None) -> list[tuple[str, str]]:
    tags = [pair(0, kind)]
    if handle:
        tags.append(pair(5, handle))
    return tags


def read_pairs(path: Path) -> list[tuple[str, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


def write_pairs(path: Path, pairs: list[tuple[str, str]]) -> None:
    out: list[str] = []
    for code, value in pairs:
        out.append(str(code))
        out.append(str(value))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def split_entries(pairs: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    entries: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    for code, value in pairs:
        if code.strip() == "0":
            if cur:
                entries.append(cur)
            cur = [(code, value)]
        else:
            if not cur:
                cur = [(code, value)]
            else:
                cur.append((code, value))
    if cur:
        entries.append(cur)
    return entries


def flatten(entries: list[list[tuple[str, str]]]) -> list[tuple[str, str]]:
    return [tag for ent in entries for tag in ent]


def first(ent: list[tuple[str, str]], code: str | int) -> str | None:
    c = str(code)
    for code0, value in ent:
        if code0.strip() == c:
            return value.strip()
    return None


def all_values(ent: list[tuple[str, str]], code: str | int) -> list[str]:
    c = str(code)
    return [value.strip() for code0, value in ent if code0.strip() == c]


def update_move_multiplier(ent: list[tuple[str, str]]) -> list[tuple[str, str]]:
    handle = first(ent, 5)
    if handle not in EXAMPLE_MOVE_MULTIPLIERS:
        return ent
    return [
        (code, fmt_ratio(EXAMPLE_MOVE_MULTIPLIERS[handle]) if code.strip() == "140" else value)
        for code, value in ent
    ]


def max_handle(pairs: list[tuple[str, str]]) -> int:
    max_value = 0
    for code, value in pairs:
        if code.strip() in {"5", "105"}:
            try:
                max_value = max(max_value, int(value.strip(), 16))
            except ValueError:
                pass
    return max_value


def fmt(x: float) -> str:
    if abs(x) < 1e-12:
        return "0.0"
    return repr(float(x))


def fmt_ratio(x: float) -> str:
    frac = Fraction(x).limit_denominator(32)
    if abs(float(frac) - x) < 1e-9:
        if frac.denominator == 1:
            return f"{frac.numerator}.0"
        return f"{frac.numerator / frac.denominator:.16g}"
    return fmt(x)


def line_entity(handle: str, owner: str, x1: float, y1: float, x2: float, y2: float) -> list[tuple[str, str]]:
    return [
        pair(0, "LINE"),
        pair(5, handle),
        pair(330, owner),
        pair(100, "AcDbEntity"),
        pair(8, "0"),
        pair(100, "AcDbLine"),
        pair(10, fmt(x1)),
        pair(20, fmt(y1)),
        pair(30, "0.0"),
        pair(11, fmt(x2)),
        pair(21, fmt(y2)),
        pair(31, "0.0"),
    ]


def insert_entity(handle: str, name: str, x: float, y: float, color: int | None = None) -> list[tuple[str, str]]:
    tags = [
        pair(0, "INSERT"),
        pair(5, handle),
        pair(330, "1F"),
        pair(100, "AcDbEntity"),
        pair(8, "0"),
    ]
    if color is not None:
        tags.append(pair(62, color))
    tags.extend(
        [
            pair(100, "AcDbBlockReference"),
            pair(2, name),
            pair(10, fmt(x)),
            pair(20, fmt(y)),
            pair(30, "0.0"),
        ]
    )
    return tags


def load_entities(doc: ezdxf.EzDxf, name: str, extra_lines: list[EntityInfo] | None = None) -> list[EntityInfo]:
    ents: list[EntityInfo] = []
    for e in doc.blocks.get(name):
        if e.dxftype() == "LINE":
            s, t = e.dxf.start, e.dxf.end
            ents.append(EntityInfo(e.dxf.handle, "LINE", float(s.x), float(s.y), float(t.x), float(t.y)))
        elif e.dxftype() == "ARC":
            c = e.dxf.center
            ents.append(
                EntityInfo(
                    e.dxf.handle,
                    "ARC",
                    float(c.x),
                    float(c.y),
                    a0=float(e.dxf.start_angle),
                    a1=float(e.dxf.end_angle),
                )
            )
    if extra_lines:
        ents.extend(extra_lines)
    return ents


def close(a: float, b: float, tol: float = 1e-4) -> bool:
    return abs(a - b) <= tol


def angle_key(a0: float | None, a1: float | None) -> tuple[int, int]:
    return (int(round(a0 or 0)) % 360, int(round(a1 or 0)) % 360)


def find_line_at(lines: list[EntityInfo], y: float) -> str | None:
    candidates = [e for e in lines if close(e.y1, y) and close(e.y2 or e.y1, y)]
    if not candidates:
        return None
    candidates.sort(key=lambda e: (abs((e.x2 or e.x1) - e.x1), e.handle), reverse=True)
    return candidates[0].handle


def classify_block(doc: ezdxf.EzDxf, name: str, record: str, extra_lines: list[EntityInfo] | None = None) -> BlockGeom:
    ents = load_entities(doc, name, extra_lines)
    lines = [e for e in ents if e.kind == "LINE"]
    arcs = [e for e in ents if e.kind == "ARC"]
    vertical = [e for e in lines if close(e.x1, e.x2 or e.x1) and not close(e.y1, e.y2 or e.y1)]
    if len(vertical) < 2:
        raise ValueError(f"{name}: vertical guide lines not found")
    vertical.sort(key=lambda e: e.x1)
    left_line, right_line = vertical[0], vertical[-1]

    xs: list[float] = []
    ys: list[float] = []
    for e in lines:
        xs.extend([e.x1, e.x2 if e.x2 is not None else e.x1])
        ys.extend([e.y1, e.y2 if e.y2 is not None else e.y1])
    for e in arcs:
        xs.extend([e.x1 - 450.0, e.x1 + 450.0])
        ys.extend([e.y1 - 450.0, e.y1 + 450.0])
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)

    top_y = max(e.y1 for e in arcs)
    bottom_y = min(e.y1 for e in arcs)
    top_arcs = [e for e in arcs if close(e.y1, top_y)]
    bottom_arcs = [e for e in arcs if close(e.y1, bottom_y)]
    top_arcs.sort(key=lambda e: e.x1)
    bottom_arcs.sort(key=lambda e: e.x1)

    top_outer_left = top_arcs[0].handle
    top_outer_right = top_arcs[-1].handle
    bottom_outer_left = bottom_arcs[0].handle
    bottom_outer_right = bottom_arcs[-1].handle

    port_bottom_y = bottom_y + 900.0
    port_top_y = top_y - 900.0
    internal_centers = sorted({round(e.y1, 6) for e in arcs if not close(e.y1, top_y) and not close(e.y1, bottom_y) and not close(e.y1, port_bottom_y) and not close(e.y1, port_top_y)})

    def shape_for_pair(y_a: float, y_b: float) -> UShape:
        y_low, y_high = sorted([y_a, y_b])
        s = UShape(top_y=y_low, bottom_y=y_high)
        for e in arcs:
            key = angle_key(e.a0, e.a1)
            if close(e.y1, y_low):
                if key == (90, 180):
                    s.left_top_arc = e.handle
                elif key == (0, 90):
                    s.right_top_arc = e.handle
            if close(e.y1, y_high):
                if key == (180, 270):
                    s.left_bottom_arc = e.handle
                elif key == (270, 0):
                    s.right_bottom_arc = e.handle
        s.top_line = find_line_at(lines, y_low + 450.0)
        s.bottom_line = find_line_at(lines, y_high - 450.0)
        return s

    bottom_port = shape_for_pair(port_bottom_y, port_bottom_y)
    # Port shapes are single-center U pairs, so fill explicitly.
    for e in arcs:
        key = angle_key(e.a0, e.a1)
        if close(e.y1, port_bottom_y):
            if key == (180, 270):
                bottom_port.left_bottom_arc = e.handle
            elif key == (270, 0):
                bottom_port.right_bottom_arc = e.handle
        if close(e.y1, port_top_y):
            pass
    bottom_port.bottom_line = find_line_at(lines, port_bottom_y - 450.0)

    top_port = UShape(top_y=port_top_y)
    for e in arcs:
        key = angle_key(e.a0, e.a1)
        if close(e.y1, port_top_y):
            if key == (90, 180):
                top_port.left_top_arc = e.handle
            elif key == (0, 90):
                top_port.right_top_arc = e.handle
    top_port.top_line = find_line_at(lines, port_top_y + 450.0)

    groups: list[UShape] = []
    for i in range(0, len(internal_centers), 2):
        if i + 1 >= len(internal_centers):
            break
        s = shape_for_pair(internal_centers[i], internal_centers[i + 1])
        groups.append(s)
    groups.sort(key=lambda g: g.top_y if g.top_y is not None else 0.0)
    for idx, group in enumerate(groups):
        group.ratio = (idx + 1) / (len(groups) + 1)

    return BlockGeom(
        name=name,
        record=record,
        entities=ents,
        left_line=left_line.handle,
        right_line=right_line.handle,
        top_outer_left=top_outer_left,
        top_outer_right=top_outer_right,
        bottom_outer_left=bottom_outer_left,
        bottom_outer_right=bottom_outer_right,
        bottom_port=bottom_port,
        top_port=top_port,
        groups=groups,
        minx=minx,
        maxx=maxx,
        miny=miny,
        maxy=maxy,
        left_x=left_line.x1,
        right_x=right_line.x1,
        is_w900=abs(right_line.x1 - left_line.x1) < 1000.0,
    )


def detect_w900_zero_lines(doc: ezdxf.EzDxf, hgen: HandleGen, block_records: dict[str, str]) -> dict[str, list[EntityInfo]]:
    result: dict[str, list[EntityInfo]] = {}
    for name in [b for b in TARGET_BLOCKS if "W900" in b]:
        arcs: list[EntityInfo] = []
        for e in doc.blocks.get(name):
            if e.dxftype() == "ARC":
                c = e.dxf.center
                arcs.append(EntityInfo(e.dxf.handle, "ARC", float(c.x), float(c.y), a0=float(e.dxf.start_angle), a1=float(e.dxf.end_angle)))
        extra: list[EntityInfo] = []
        used: set[tuple[float, float, str]] = set()
        by_center: dict[tuple[float, float], list[EntityInfo]] = {}
        for e in arcs:
            by_center.setdefault((round(e.x1, 6), round(e.y1, 6)), []).append(e)
        for (x, y), group in by_center.items():
            keys = {angle_key(e.a0, e.a1) for e in group}
            if {(90, 180), (0, 90)} <= keys:
                key = (x, y + 450.0, "top")
                if key not in used:
                    h = hgen.new()
                    extra.append(EntityInfo(h, "LINE", x, y + 450.0, x, y + 450.0))
                    used.add(key)
            if {(180, 270), (270, 0)} <= keys:
                key = (x, y - 450.0, "bottom")
                if key not in used:
                    h = hgen.new()
                    extra.append(EntityInfo(h, "LINE", x, y - 450.0, x, y - 450.0))
                    used.add(key)
        result[name] = extra
    return result


def make_block_record(ent: list[tuple[str, str]], xdict: str, name: str, guid: str, entity_count: int, insert_handle: str) -> list[tuple[str, str]]:
    handle = first(ent, 5)
    if not handle:
        raise ValueError(f"BLOCK_RECORD without handle: {name}")
    tags = [pair(0, "BLOCK_RECORD"), pair(5, handle), pair(102, "{ACAD_XDICTIONARY"), pair(360, xdict), pair(102, "}")]
    tags.extend(
        [
            pair(330, "1"),
            pair(100, "AcDbSymbolTableRecord"),
            pair(100, "AcDbBlockTableRecord"),
            pair(2, name),
            pair(340, "0"),
            pair(102, "{BLKREFS"),
            pair(331, insert_handle),
            pair(102, "}"),
            pair(70, "0"),
            pair(280, "1"),
            pair(281, "0"),
            pair(1001, "AcDbBlockRepETag"),
            pair(1070, "1"),
            pair(1071, str(entity_count)),
            pair(1001, "AcDbDynamicBlockTrueName"),
            pair(1000, name),
            pair(1001, "AcDbDynamicBlockGUID"),
            pair(1000, guid),
        ]
    )
    return tags


def dict_object(handle: str, owner: str, graph: str, purge: str) -> list[tuple[str, str]]:
    return [
        pair(0, "DICTIONARY"),
        pair(5, handle),
        pair(330, owner),
        pair(100, "AcDbDictionary"),
        pair(280, "1"),
        pair(281, "1"),
        pair(3, "ACAD_ENHANCEDBLOCK"),
        pair(360, graph),
        pair(3, "AcDbDynamicBlockRoundTripPurgePreventer"),
        pair(360, purge),
    ]


def purge_object(handle: str, owner: str) -> list[tuple[str, str]]:
    return [
        pair(0, "ACDB_DYNAMICBLOCKPURGEPREVENTER_VERSION"),
        pair(5, handle),
        pair(102, "{ACAD_REACTORS"),
        pair(330, owner),
        pair(102, "}"),
        pair(330, owner),
        pair(100, "AcDbDynamicBlockPurgePreventer"),
        pair(70, "1"),
    ]


def linear_parameter(handle: str, owner: str, expr_id: int, name: str, distance_name: str, x0: float, y0: float, x1: float, y1: float, base_grip_id: int, end_grip_id: int, label_offset: float, label_size: float) -> list[tuple[str, str]]:
    return [
        pair(0, "BLOCKLINEARPARAMETER"),
        pair(5, handle),
        pair(330, owner),
        pair(100, "AcDbEvalExpr"),
        pair(90, expr_id),
        pair(98, "33"),
        pair(99, "274"),
        pair(100, "AcDbBlockElement"),
        pair(300, name),
        pair(98, "33"),
        pair(99, "274"),
        pair(1071, "0"),
        pair(100, "AcDbBlockParameter"),
        pair(280, "1"),
        pair(281, "0"),
        pair(100, "AcDbBlock2PtParameter"),
        pair(1010, fmt(x0)),
        pair(1020, fmt(y0)),
        pair(1030, "0.0"),
        pair(1011, fmt(x1)),
        pair(1021, fmt(y1)),
        pair(1031, "0.0"),
        pair(170, "4"),
        pair(91, base_grip_id),
        pair(91, end_grip_id),
        pair(91, "0"),
        pair(91, "0"),
        pair(171, "1"),
        pair(92, base_grip_id),
        pair(301, "DisplacementX"),
        pair(172, "1"),
        pair(93, base_grip_id),
        pair(302, "DisplacementY"),
        pair(173, "1"),
        pair(94, end_grip_id),
        pair(303, "DisplacementX"),
        pair(174, "1"),
        pair(95, end_grip_id),
        pair(304, "DisplacementY"),
        pair(177, "0"),
        pair(100, "AcDbBlockLinearParameter"),
        pair(305, distance_name),
        pair(306, ""),
        pair(140, fmt(label_offset)),
        pair(307, ""),
        pair(96, "1"),
        pair(141, fmt(label_size)),
        pair(142, "0.0"),
        pair(143, "0.0"),
        pair(175, "0"),
    ]


def linear_grip(handle: str, owner: str, expr_id: int, name: str, comp_x_id: int, comp_y_id: int, x: float, y: float, dx: float, dy: float) -> list[tuple[str, str]]:
    return [
        pair(0, "BLOCKLINEARGRIP"),
        pair(5, handle),
        pair(330, owner),
        pair(100, "AcDbEvalExpr"),
        pair(90, expr_id),
        pair(98, "33"),
        pair(99, "274"),
        pair(100, "AcDbBlockElement"),
        pair(300, name),
        pair(98, "33"),
        pair(99, "274"),
        pair(1071, "0"),
        pair(100, "AcDbBlockGrip"),
        pair(91, comp_x_id),
        pair(92, comp_y_id),
        pair(1010, fmt(x)),
        pair(1020, fmt(y)),
        pair(1030, "0.0"),
        pair(280, "1"),
        pair(93, "-1"),
        pair(100, "AcDbBlockLinearGrip"),
        pair(140, fmt(dx)),
        pair(141, fmt(dy)),
        pair(142, "0.0"),
    ]


def grip_component(handle: str, owner: str, expr_id: int, param_id: int, name: str, max_value: bool = False) -> list[tuple[str, str]]:
    return [
        pair(0, "BLOCKGRIPLOCATIONCOMPONENT"),
        pair(5, handle),
        pair(330, owner),
        pair(100, "AcDbEvalExpr"),
        pair(90, expr_id),
        pair(98, "33"),
        pair(99, "274"),
        pair(1, ""),
        pair(70, "40"),
        pair(140, "1.797693134862314E+99" if max_value else "0.0"),
        pair(100, "AcDbBlockGripExpr"),
        pair(91, param_id),
        pair(300, name),
    ]


def stretch_action(handle: str, owner: str, expr_id: int, label: str, driver_id: int, direction: str, action_refs: list[str], stretch_specs: list[tuple[str, list[int]]], box: tuple[float, float, float, float], include_vertical_param: str | None = None) -> list[tuple[str, str]]:
    tags = [
        pair(0, "BLOCKSTRETCHACTION"),
        pair(5, handle),
        pair(330, owner),
        pair(100, "AcDbEvalExpr"),
        pair(90, expr_id),
        pair(98, "33"),
        pair(99, "274"),
        pair(100, "AcDbBlockElement"),
        pair(300, label),
        pair(98, "33"),
        pair(99, "274"),
        pair(1071, "0"),
        pair(100, "AcDbBlockAction"),
        pair(70, "1" if include_vertical_param else "0"),
    ]
    if include_vertical_param:
        tags.append(pair(91, "1"))
    all_refs = ([include_vertical_param] if include_vertical_param else []) + action_refs
    tags.extend([pair(71, len(all_refs))])
    for h in all_refs:
        tags.append(pair(330, h))
    x0, y0, x1, y1 = box
    tags.extend(
        [
            pair(1010, fmt((x0 + x1) / 2.0)),
            pair(1020, fmt((y0 + y1) / 2.0)),
            pair(1030, "0.0"),
            pair(100, "AcDbBlockStretchAction"),
            pair(92, driver_id),
            pair(301, "EndXDelta" if direction == "end" else "BaseXDelta"),
            pair(93, driver_id),
            pair(302, "EndYDelta" if direction == "end" else "BaseYDelta"),
            pair(72, "2"),
            pair(1011, fmt(x0)),
            pair(1021, fmt(y0)),
            pair(1011, fmt(x1)),
            pair(1021, fmt(y1)),
            pair(73, len(stretch_specs)),
        ]
    )
    for h, indices in stretch_specs:
        tags.append(pair(331, h))
        tags.append(pair(74, len(indices)))
        for idx in indices:
            tags.append(pair(94, idx))
    if include_vertical_param:
        tags.extend([pair(75, "1"), pair(95, "1"), pair(76, "2"), pair(94, "0"), pair(94, "1")])
    else:
        tags.append(pair(75, "0"))
    tags.extend([pair(140, "1.0"), pair(141, "0.0"), pair(280, "0")])
    return tags


def move_action(handle: str, owner: str, expr_id: int, label: str, refs: list[str], x: float, y: float, direction: str, ratio: float, hparam_id: int = 13) -> list[tuple[str, str]]:
    return [
        pair(0, "BLOCKMOVEACTION"),
        pair(5, handle),
        pair(330, owner),
        pair(100, "AcDbEvalExpr"),
        pair(90, expr_id),
        pair(98, "33"),
        pair(99, "274"),
        pair(100, "AcDbBlockElement"),
        pair(300, label),
        pair(98, "33"),
        pair(99, "274"),
        pair(1071, "0"),
        pair(100, "AcDbBlockAction"),
        pair(70, "1"),
        pair(91, hparam_id),
        pair(71, len(refs)),
        *[tag for h in refs for tag in [pair(330, h)]],
        pair(1010, fmt(x)),
        pair(1020, fmt(y)),
        pair(1030, "0.0"),
        pair(100, "AcDbBlockMoveAction"),
        pair(92, "1"),
        pair(301, "EndXDelta" if direction == "end" else "BaseXDelta"),
        pair(93, "1"),
        pair(302, "EndYDelta" if direction == "end" else "BaseYDelta"),
        pair(140, fmt_ratio(ratio)),
        pair(141, "0.0"),
        pair(280, "0"),
    ]


def build_graph(handle: str, owner: str, nodes: list[tuple[int, str]], edges: list[tuple[int, int, int]]) -> list[tuple[str, str]]:
    incoming: dict[int, list[int]] = {i: [] for i in range(len(nodes))}
    outgoing: dict[int, list[int]] = {i: [] for i in range(len(nodes))}
    for idx, (src, dst, _etype) in enumerate(edges):
        outgoing[src].append(idx)
        incoming[dst].append(idx)

    tags = [
        pair(0, "ACAD_EVALUATION_GRAPH"),
        pair(5, handle),
        pair(102, "{ACAD_REACTORS"),
        pair(330, owner),
        pair(102, "}"),
        pair(330, owner),
        pair(100, "AcDbEvalGraph"),
        pair(96, max(expr for expr, _ in nodes)),
        pair(97, max(expr for expr, _ in nodes)),
    ]
    for idx, (expr, h) in enumerate(nodes):
        inc = incoming[idx]
        out = outgoing[idx]
        tags.extend(
            [
                pair(91, idx),
                pair(93, "32"),
                pair(95, expr),
                pair(360, h),
                pair(92, inc[0] if inc else -1),
                pair(92, inc[-1] if inc else -1),
                pair(92, out[0] if out else -1),
                pair(92, out[-1] if out else -1),
            ]
        )
    for idx, (src, dst, etype) in enumerate(edges):
        inc = incoming[dst]
        out = outgoing[src]
        pos_i = inc.index(idx)
        pos_o = out.index(idx)
        tags.extend(
            [
                pair(92, idx),
                pair(93, "0"),
                pair(94, etype),
                pair(91, src),
                pair(91, dst),
                pair(92, inc[pos_i - 1] if pos_i > 0 else -1),
                pair(92, inc[pos_i + 1] if pos_i + 1 < len(inc) else -1),
                pair(92, out[pos_o - 1] if pos_o > 0 else -1),
                pair(92, out[pos_o + 1] if pos_o + 1 < len(out) else -1),
                pair(92, "-1"),
            ]
        )
    return tags


def build_dynamic_objects(geom: BlockGeom, handles: DynHandles) -> list[list[tuple[str, str]]]:
    nodes: list[tuple[int, str]] = [
        (1, handles.vparam),
        (2, handles.vbase_grip),
        (3, handles.vbase_x),
        (4, handles.vbase_y),
        (5, handles.vend_grip),
        (6, handles.vend_x),
        (7, handles.vend_y),
        (8, handles.top_stretch),
        (9, handles.bottom_stretch),
        (13, handles.hparam),
        (14, handles.hbase_grip),
        (15, handles.hbase_x),
        (16, handles.hbase_y),
        (17, handles.hend_grip),
        (18, handles.hend_x),
        (19, handles.hend_y),
        (20, handles.right_stretch),
        (22, handles.left_stretch),
    ]
    move_expr = 25
    for h in handles.move_end:
        nodes.append((move_expr, h))
        move_expr += 1
    for h in handles.move_base:
        nodes.append((move_expr, h))
        move_expr += 1

    node_index = {h: idx for idx, (_expr, h) in enumerate(nodes)}
    edges: list[tuple[int, int, int]] = []
    v = node_index[handles.vparam]
    h = node_index[handles.hparam]
    for dst in [handles.vbase_x, handles.vbase_y]:
        edges.append((v, node_index[dst], 1))
    edges.append((node_index[handles.vbase_grip], v, 2))
    for dst in [handles.vend_x, handles.vend_y]:
        edges.append((v, node_index[dst], 1))
    edges.append((node_index[handles.vend_grip], v, 2))
    for dst in [handles.top_stretch, handles.bottom_stretch]:
        edges.append((v, node_index[dst], 2))

    for dst in [handles.hbase_x, handles.hbase_y]:
        edges.append((h, node_index[dst], 1))
    edges.append((node_index[handles.hbase_grip], h, 2))
    for dst in [handles.hend_x, handles.hend_y]:
        edges.append((h, node_index[dst], 1))
    edges.append((node_index[handles.hend_grip], h, 2))
    for dst in [handles.right_stretch, handles.left_stretch]:
        edges.append((h, node_index[dst], 2))
    for dst in handles.move_end + handles.move_base:
        edges.append((v, node_index[dst], 2))

    x_mid = (geom.left_x + geom.right_x) / 2.0
    h_anchor_index = len(geom.groups) // 2 if geom.groups else -1
    h_y = ((geom.groups[h_anchor_index].top_y or 0.0) if geom.groups else (geom.miny + geom.maxy) / 2.0)
    width = geom.right_x - geom.left_x
    objects: list[list[tuple[str, str]]] = [
        dict_object(handles.xdict, geom.record, handles.graph, handles.purge),
        build_graph(handles.graph, handles.xdict, nodes, edges),
        purge_object(handles.purge, handles.xdict),
        linear_parameter(handles.vparam, handles.graph, 1, "선형", "거리1", geom.minx + 450.0, geom.miny, geom.minx + 450.0, geom.maxy, 2, 5, 9782.709112879196, 10000.0),
        linear_grip(handles.vbase_grip, handles.graph, 2, "기준 그립", 3, 4, geom.minx + 450.0, geom.miny, 0.0, -(geom.maxy - geom.miny)),
        grip_component(handles.vbase_x, handles.graph, 3, 1, "UpdatedBaseX"),
        grip_component(handles.vbase_y, handles.graph, 4, 1, "UpdatedBaseY"),
        linear_grip(handles.vend_grip, handles.graph, 5, "끝 그립", 6, 7, geom.minx + 450.0, geom.maxy, 0.0, geom.maxy - geom.miny),
        grip_component(handles.vend_x, handles.graph, 6, 1, "UpdatedEndX", True),
        grip_component(handles.vend_y, handles.graph, 7, 1, "UpdatedEndY", True),
    ]

    top_refs = [geom.top_outer_left, geom.left_line, geom.top_port.left_top_arc, geom.top_port.top_line, geom.top_port.right_top_arc, geom.right_line, geom.top_outer_right]
    top_refs = [x for x in top_refs if x]
    top_specs = [(geom.left_line, [1]), (geom.right_line, [1])]
    top_specs.extend([(x, [0, 1]) for x in [geom.top_outer_left, geom.top_outer_right, geom.top_port.left_top_arc, geom.top_port.right_top_arc, geom.top_port.top_line] if x])
    objects.append(
        stretch_action(
            handles.top_stretch,
            handles.graph,
            8,
            "신축",
            1,
            "end",
            top_refs,
            top_specs,
            (geom.minx - 1000.0, geom.maxy + 1200.0, geom.maxx + 1000.0, geom.maxy - 5600.0),
        )
    )

    bottom_refs = [geom.bottom_outer_left, geom.left_line, geom.bottom_port.left_bottom_arc, geom.bottom_port.bottom_line, geom.bottom_port.right_bottom_arc, geom.right_line, geom.bottom_outer_right]
    bottom_refs = [x for x in bottom_refs if x]
    bottom_specs = [(geom.left_line, [0]), (geom.right_line, [0])]
    bottom_specs.extend([(x, [0, 1]) for x in [geom.bottom_outer_left, geom.bottom_outer_right, geom.bottom_port.left_bottom_arc, geom.bottom_port.right_bottom_arc, geom.bottom_port.bottom_line] if x])
    objects.append(
        stretch_action(
            handles.bottom_stretch,
            handles.graph,
            9,
            "신축1",
            1,
            "base",
            bottom_refs,
            bottom_specs,
            (geom.minx - 1000.0, geom.miny + 5600.0, geom.maxx + 1000.0, geom.miny - 1200.0),
        )
    )

    objects.extend(
        [
            linear_parameter(handles.hparam, handles.graph, 13, "선형1", "거리2", geom.left_x, h_y, geom.right_x, h_y, 14, 17, -3170.262420574189, 900.0),
            linear_grip(handles.hbase_grip, handles.graph, 14, "기준 그립", 15, 16, geom.left_x, h_y, -width, 0.0),
            grip_component(handles.hbase_x, handles.graph, 15, 13, "UpdatedBaseX"),
            grip_component(handles.hbase_y, handles.graph, 16, 13, "UpdatedBaseY"),
            linear_grip(handles.hend_grip, handles.graph, 17, "끝 그립", 18, 19, geom.right_x, h_y, width, 0.0),
            grip_component(handles.hend_x, handles.graph, 18, 13, "UpdatedEndX", True),
            grip_component(handles.hend_y, handles.graph, 19, 13, "UpdatedEndY", True),
        ]
    )

    right_action_refs: list[str] = [geom.bottom_port.bottom_line, geom.bottom_port.right_bottom_arc, geom.bottom_outer_right, geom.right_line]
    right_specs: list[tuple[str, list[int]]] = [(geom.right_line, [0, 1]), (geom.bottom_outer_right, [0, 1])]
    right_specs.extend([(x, [0, 1]) for x in [geom.bottom_port.right_bottom_arc, geom.top_port.right_top_arc, geom.top_outer_right] if x])
    for line in [geom.bottom_port.bottom_line, geom.top_port.top_line]:
        if line:
            right_specs.append((line, [1]))
    for g in geom.groups:
        right_action_refs.extend([g.right_top_arc, g.top_line, g.bottom_line, g.right_bottom_arc])
        for arc in [g.right_top_arc, g.right_bottom_arc]:
            if arc:
                right_specs.append((arc, [0, 1]))
        for line in [g.top_line, g.bottom_line]:
            if line:
                right_specs.append((line, [1]))
    right_action_refs.extend([geom.top_outer_right, geom.top_port.right_top_arc, geom.top_port.top_line])
    right_action_refs = [x for x in right_action_refs if x]
    objects.append(
        stretch_action(
            handles.right_stretch,
            handles.graph,
            20,
            "신축2",
            13,
            "end",
            right_action_refs,
            right_specs,
            (x_mid + 60.0, geom.maxy + 1000.0, geom.maxx + 2000.0, geom.miny - 1000.0),
        )
    )

    left_action_refs: list[str] = [geom.bottom_port.bottom_line, geom.bottom_port.left_bottom_arc, geom.bottom_outer_left, geom.left_line]
    left_specs: list[tuple[str, list[int]]] = [(geom.left_line, [0, 1]), (geom.bottom_outer_left, [0, 1])]
    left_specs.extend([(x, [0, 1]) for x in [geom.bottom_port.left_bottom_arc, geom.top_port.left_top_arc, geom.top_outer_left] if x])
    for line in [geom.bottom_port.bottom_line, geom.top_port.top_line]:
        if line:
            left_specs.append((line, [0]))
    for g in geom.groups:
        left_action_refs.extend([g.left_top_arc, g.top_line, g.bottom_line, g.left_bottom_arc])
        for arc in [g.left_top_arc, g.left_bottom_arc]:
            if arc:
                left_specs.append((arc, [0, 1]))
        for line in [g.top_line, g.bottom_line]:
            if line:
                left_specs.append((line, [0]))
    left_action_refs.extend([geom.top_outer_left, geom.top_port.left_top_arc, geom.top_port.top_line])
    left_action_refs = [x for x in left_action_refs if x]
    objects.append(
        stretch_action(
            handles.left_stretch,
            handles.graph,
            22,
            "신축3",
            13,
            "base",
            left_action_refs,
            left_specs,
            (geom.minx - 2000.0, geom.maxy + 1000.0, x_mid - 60.0, geom.miny - 1000.0),
            include_vertical_param=handles.vparam,
        )
    )

    h_move_index = h_anchor_index
    expr = 25
    for idx, g in sorted(enumerate(geom.groups), key=lambda item: item[1].ratio, reverse=True):
        refs = g.handles()
        if idx == h_move_index:  # 거리2는 "앉은 조인트"의 Move(위/아래)에만 — 여러 조인트에 물리면 그립이 이동량 합산으로 날아감
            refs = refs + [handles.hparam]
        cy = ((g.top_y or 0.0) + (g.bottom_y or 0.0)) / 2.0
        objects.append(move_action(handles.move_end[len(handles.move_end) - 1 - idx] if False else handles.move_end[len([gg for gg in geom.groups if gg.ratio > g.ratio])], handles.graph, expr, f"이동{expr - 25 if expr > 25 else ''}", refs, x_mid, cy, "end", g.ratio))
        expr += 1
    for idx, g in sorted(enumerate(geom.groups), key=lambda item: item[1].ratio):
        refs = g.handles()
        if idx == h_move_index:  # 거리2는 "앉은 조인트"의 Move(위/아래)에만 — 여러 조인트에 물리면 그립이 이동량 합산으로 날아감
            refs = refs + [handles.hparam]
        cy = ((g.top_y or 0.0) + (g.bottom_y or 0.0)) / 2.0
        objects.append(move_action(handles.move_base[idx], handles.graph, expr, f"이동{expr - 25 if expr > 25 else ''}", refs, x_mid, cy, "base", 1.0 - g.ratio))
        expr += 1

    return objects


def allocate_dyn_handles(hgen: HandleGen, group_count: int) -> DynHandles:
    return DynHandles(
        xdict=hgen.new(),
        graph=hgen.new(),
        purge=hgen.new(),
        vparam=hgen.new(),
        vbase_grip=hgen.new(),
        vbase_x=hgen.new(),
        vbase_y=hgen.new(),
        vend_grip=hgen.new(),
        vend_x=hgen.new(),
        vend_y=hgen.new(),
        top_stretch=hgen.new(),
        bottom_stretch=hgen.new(),
        hparam=hgen.new(),
        hbase_grip=hgen.new(),
        hbase_x=hgen.new(),
        hbase_y=hgen.new(),
        hend_grip=hgen.new(),
        hend_x=hgen.new(),
        hend_y=hgen.new(),
        right_stretch=hgen.new(),
        left_stretch=hgen.new(),
        move_end=[hgen.new() for _ in range(group_count)],
        move_base=[hgen.new() for _ in range(group_count)],
    )


def main() -> None:
    example_pairs = read_pairs(EXAMPLE)
    original_doc = ezdxf.readfile(ORIGINAL)
    example_doc = ezdxf.readfile(EXAMPLE)
    hgen = HandleGen(max(max_handle(example_pairs) + 1, 0x1100))

    block_records: dict[str, str] = {}
    for block in example_doc.blocks:
        if block.name.startswith("2rail"):
            block_records[block.name] = block.block_record_handle

    zero_lines = detect_w900_zero_lines(example_doc, hgen, block_records)

    original_positions: dict[str, tuple[float, float, int | None]] = {}
    for ins in original_doc.modelspace().query("INSERT"):
        name = ins.dxf.name
        if name in TARGET_BLOCKS:
            original_positions[name] = (float(ins.dxf.insert.x), float(ins.dxf.insert.y), int(ins.dxf.color) if ins.dxf.hasattr("color") else None)

    insert_handles = {name: hgen.new() for name in TARGET_BLOCKS}
    dyn_handles: dict[str, DynHandles] = {}
    geoms: dict[str, BlockGeom] = {}
    for name in TARGET_BLOCKS:
        geom = classify_block(example_doc, name, block_records[name], zero_lines.get(name, []))
        geoms[name] = geom
        dyn_handles[name] = allocate_dyn_handles(hgen, len(geom.groups))

    entries = split_entries(example_pairs)
    new_entries: list[list[tuple[str, str]]] = []
    current_block: str | None = None

    for ent in entries:
        typ = first(ent, 0)
        if typ == "BLOCK":
            current_block = first(ent, 2)
            new_entries.append(ent)
            continue
        if typ == "ENDBLK":
            if current_block in zero_lines:
                owner = block_records[current_block]
                for e in zero_lines[current_block]:
                    new_entries.append(line_entity(e.handle, owner, e.x1, e.y1, e.x2 or e.x1, e.y2 or e.y1))
            current_block = None
            new_entries.append(ent)
            continue
        if typ == "BLOCK_RECORD":
            name = first(ent, 2)
            if name in TARGET_BLOCKS:
                dh = dyn_handles[name]
                guid = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"lsl-flexible-{name}")).upper() + "}"
                entity_count = len(geoms[name].entities)
                new_entries.append(make_block_record(ent, dh.xdict, name, guid, entity_count, insert_handles[name]))
            else:
                new_entries.append(ent)
            continue
        if typ == "ENDSEC":
            # Insert missing model-space block references before ENTITIES ENDSEC.
            prev_section = None
            # Look back at the latest SECTION marker in the accumulated stream.
            for e in reversed(new_entries):
                if first(e, 0) == "SECTION":
                    prev_section = first(e, 2)
                    break
            if prev_section == "ENTITIES":
                for name in TARGET_BLOCKS:
                    x, y, color = original_positions[name]
                    new_entries.append(insert_entity(insert_handles[name], name, x, y, color))
            # Insert custom dynamic objects before OBJECTS ENDSEC.
            if prev_section == "OBJECTS":
                for name in TARGET_BLOCKS:
                    new_entries.extend(build_dynamic_objects(geoms[name], dyn_handles[name]))
            new_entries.append(ent)
            continue
        if typ == "BLOCKMOVEACTION":
            new_entries.append(update_move_multiplier(ent))
            continue
        new_entries.append(ent)

    write_pairs(OUTPUT, flatten(new_entries))
    print(OUTPUT)


if __name__ == "__main__":
    main()
