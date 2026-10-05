# -*- coding: utf-8 -*-
"""MODULE FORMAT MAP → CAD 역변환 (모듈 단위 복원).

MAP 의 MODULE 레코드(종류·각도·기준점)와 MODULEPARAM(R/L/W1/W2/A/M1/M2)으로 플러그인과 같은 모듈 블록
(RAILMOD_ 블록 + RAILPLUGIN XData)을 다시 놓고, 모듈 밖 링크는 기존 역변환(map_to_cad.reconstruct)으로
선·호를 되푼다.

  모듈 배치   플러그인 모듈 후보 × 회전 4가지를 놓아 보고, 순방향 대조(module_map.match_module)가
              MAP 의 MODULE 레코드와 **같은 종류·각도·기준점**을 돌려주는 배치만 쓴다(왕복이 어긋나지 않게).
              폭(W)은 MAP 에 따로 적지 않으므로 W1/W2 중 그 모듈 NODE 좌표(슬롯 + 마진)와 맞는 쪽을 고른다.
  모듈 사이   MODULE 레코드의 슬롯 연결("ID-번호")끼리 슬롯 점을 직선으로 잇는다(마진으로 줄어든 S 링크와
              겹침으로 합쳐진 U/N 링크는 모듈 형상 + 이 직선으로 대신한다).
  모듈 밖     모듈 NODE 가 아닌 노드가 낀 링크만 기존 방식으로 되풀고, 슬롯 NODE 쪽 끝은 마진만큼 슬롯까지 늘인다.

결과 도면에는 MODULEPARAM 을 도면 파라미터(RAILPLUGIN_MODULEPARAM)로 기록해, 그대로 다시 CAD→MAP 할 수 있다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import module_judge as mj
import module_map as mm
from map_to_cad import MapDoc, MapLinkRec, reconstruct

Pt = Tuple[float, float]


@dataclass
class ModRec:
    id: str
    type: str
    angle: int
    ref: Pt
    links: List[str]


@dataclass
class ModMap:
    nodes: Dict[str, Pt] = field(default_factory=dict)
    node_mod: Dict[str, Tuple[str, int]] = field(default_factory=dict)     # 노드 → (모듈 ID, 슬롯 번호)
    links: List[MapLinkRec] = field(default_factory=list)
    modules: List[ModRec] = field(default_factory=list)
    param: Optional[Tuple[float, ...]] = None


def has_modules(path) -> bool:
    with open(path, encoding="utf-8", errors="replace") as f:
        return any(ln.startswith("MODULE/") for ln in f)


def load(path) -> ModMap:
    mp = ModMap()
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            s = raw.rstrip("\n").split("/")
            try:
                if s[0] == "NODE":
                    mp.nodes[s[1]] = (float(s[4]), float(s[5]))
                    if len(s) > 15 and s[14]:
                        mp.node_mod[s[1]] = (s[14], int(s[15]))
                elif s[0] == "LINK":
                    mp.links.append(MapLinkRec(s[1], s[2], s[3], s[4], float(s[5])))
                elif s[0] == "MODULE":
                    mp.modules.append(ModRec(s[1], s[2], int(float(s[3])), (float(s[4]), float(s[5])), s[6:]))
                elif s[0] == "MODULEPARAM":
                    mp.param = tuple(float(v) for v in s[1:8])
            except (IndexError, ValueError):
                continue
    return mp


# ── 모듈 배치 풀기 ─────────────────────────────────────────────────────────
def _names_for(t: str) -> List[str]:
    return [n for n, ts in mm.FAMILY.items() if t in ts]


def _instance(idx: int, R: float, L: float, W: float, A: float, ins: Pt, rot: float) -> mj.ModuleInstance:
    """플러그인 블록을 ins 에 rot(도, 반시계) 로 놓았을 때의 월드 조각 (module_judge._instance 와 같은 변환)."""
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    w = lambda p: (ins[0] + p[0] * c - p[1] * s, ins[1] + p[0] * s + p[1] * c)
    R, L, W, A = mj.clamp(idx, R, L, W, A)
    loc, _ = mj.build_local(idx, R, L, W, A)
    pcs = [mj.Piece(p.kind, p.role, w(p.a), w(p.b), c=w(p.c) if p.c else None, r=p.r,
                    m=w(p.m) if p.m else None) for p in loc]
    return mj.ModuleInstance(no=0, idx=idx, name=mj.DEFS[idx][0], R=R, L=L, W=W, A=A, handle="", layer="",
                             block="", insert=ins, rotation=rot, mirrored=False, source="역변환", pieces=pcs)


def solve_placement(rec: ModRec, R, L, W, A, mc) -> Optional[Tuple[str, Pt, float, "mm.SMod"]]:
    """MODULE 레코드와 같은 (종류, 각도, 기준점) 으로 대조되는 플러그인 모듈 배치 (이름, 삽입점, 회전, 대조결과)."""
    E = float(mc["through_extra_mm"])
    tslots, _ = mm.template(rec.type, R, L, W, A, E)
    slot1 = mm.add(rec.ref, mm.rot_cw(tslots[0].pos, rec.angle))
    for name in _names_for(rec.type):
        idx = next(i for i, d in enumerate(mj.DEFS) if d[0] == name)
        for rot in (0.0, 90.0, 180.0, 270.0):
            probe = _instance(idx, R, L, W, A, (0.0, 0.0), rot)
            for e, _o in mm._free_ends(probe, 0.5):
                ins = (slot1[0] - e[0], slot1[1] - e[1])
                inst = _instance(idx, R, L, W, A, ins, rot)
                sm = mm.match_module(inst, mc, lambda *_: None)
                if sm and sm.type == rec.type and sm.angle % 360 == rec.angle % 360 \
                        and mm.dist(sm.ref, rec.ref) < 1.0:
                    return name, ins, rot, sm
    return None


# ── 본체 ──────────────────────────────────────────────────────────────────
def module_map_to_dxf(map_path, dxf_path=None, *, cfg: Optional[dict] = None, radius_mm: float = 450.0,
                      log: Callable[[str], None] = print) -> dict:
    from module_testdxf import Lay

    map_path = Path(map_path)
    dxf_path = Path(dxf_path) if dxf_path else map_path.with_name(map_path.stem + "_fromMap.dxf")
    mp = load(map_path)
    if not mp.modules or mp.param is None:
        raise ValueError("MODULE / MODULEPARAM 레코드가 없습니다 - 모듈 형식 MAP 이 아닙니다.")
    R, L, W1, W2, A, M1, M2 = mp.param
    mc = mm.cfg_of(cfg)
    log(f"MAP 읽음: NODE {len(mp.nodes)}, LINK {len(mp.links)}, MODULE {len(mp.modules)}, "
        f"파라미터 R/L/W1/W2/A/M1/M2 = " + "/".join(f"{v:g}" for v in mp.param))

    lay = Lay()
    lay.param = mp.param
    lay.doc.layers.add("RAIL_MODULE", color=3)
    warns: List[str] = []
    slots: Dict[Tuple[str, int], Tuple[Pt, Pt, float]] = {}      # (모듈, 슬롯) → (슬롯 점, 바깥 방향, 마진)
    by_id = {m.id: m for m in mp.modules}

    # 1) 모듈
    nodes_of: Dict[str, List[Tuple[int, Pt]]] = {}
    for nid, (mid, sl) in mp.node_mod.items():
        nodes_of.setdefault(mid, []).append((sl, mp.nodes[nid]))
    placed = 0
    for rec in mp.modules:
        uses_w = rec.type in mm.USES_W
        cand_w = [W1, W2] if uses_w else [W1 or 900.0]
        cand_w = [w for w in dict.fromkeys(cand_w) if w > 0] or [900.0]
        best = None
        for W in cand_w:
            got = solve_placement(rec, R, L, W, A, mc)
            if not got:
                continue
            sm = got[3]
            # 이 모듈 NODE(슬롯 + 마진)와 얼마나 맞나
            err = 0.0
            for sl, p in nodes_of.get(rec.id, []):
                s = sm.slots[sl - 1]
                q = mm.add(s.pos, mm.mul(s.out, M2 if s.m2 else M1))
                err += mm.dist(p, q)
            if best is None or err < best[0]:
                best = (err, W, got)
        if best is None:
            warns.append(f"모듈 {rec.id}({rec.type}, {rec.angle}°) 을 플러그인 모듈로 되살리지 못함 - 건너뜀")
            continue
        err, W, (name, ins, rot, sm) = best
        if err > 1.0 * max(1, len(nodes_of.get(rec.id, []))):
            warns.append(f"모듈 {rec.id}({rec.type}) NODE 와 슬롯 위치가 {err:.0f}mm 어긋남 - 폭이 W1/W2 가 아닐 수 있음")
        lay.place(name, (0.0, 0.0), ins, rot + 90.0, False, R=R, L=L, W=W, A=A)
        ref = list(lay.msp)[-1]
        ref.dxf.layer = "RAIL_MODULE"
        for k, s in enumerate(sm.slots, 1):
            slots[(rec.id, k)] = (s.pos, s.out, M2 if s.m2 else M1)
        placed += 1

    # 2) 모듈 사이: 슬롯 연결끼리 직선
    done = set()
    for rec in mp.modules:
        for k, lk in enumerate(rec.links, 1):
            if not lk or "-" not in lk:
                continue
            oid, osl = lk.rsplit("-", 1)
            key = tuple(sorted([(rec.id, k), (oid, int(osl))]))
            if key in done or (rec.id, k) not in slots or (oid, int(osl)) not in slots:
                continue
            done.add(key)
            lay.line(slots[(rec.id, k)][0], slots[(oid, int(osl))][0])

    # 3) 모듈 밖 링크: 모듈 노드끼리(같은 모듈이거나 서로 연결된 모듈)가 아닌 링크만 되푼다
    linked = {(a[0], b[0]) for a, b in done} | {(b[0], a[0]) for a, b in done}

    def module_pair(a: str, b: str) -> bool:
        if a not in mp.node_mod or b not in mp.node_mod:
            return False
        ma, mb = mp.node_mod[a][0], mp.node_mod[b][0]
        return ma == mb or (ma, mb) in linked

    rest = MapDoc()
    rest.nodes = dict(mp.nodes)
    rest.links = [lk for lk in mp.links if not module_pair(lk.start, lk.end)]
    # 슬롯 이격이 다음 곡선 시작을 지나쳐(CAD→MAP 이 남은 길이를 다음 링크에서 뺌) 길이 < 현 인 곡선 링크는
    #  호 길이로 되풀 수 없다 → 파라미터 R 의 호로 두 점을 잇는다(MAP 에 이미 정보가 줄어 있어 정확한 왕복은 불가).
    fixed = 0
    for i, lk in enumerate(rest.links):
        if lk.type in ("L", "R"):
            c = mm.dist(mp.nodes[lk.start], mp.nodes[lk.end])
            if lk.length < c and 0 < c <= 2 * R:
                rest.links[i] = MapLinkRec(lk.id, lk.type, lk.start, lk.end, 2 * R * math.asin(c / (2 * R)))
                fixed += 1
    if fixed:
        warns.append(f"곡선 링크 {fixed}개는 길이가 두 점 거리보다 짧아(슬롯 이격이 곡선을 지나침) R {R:g} 호로 복원")
    prims, w2 = reconstruct(rest, radius_mm=R or radius_mm)
    warns += w2
    for p in prims:
        if p[0] == "LINE":
            lay.line(p[1], p[2])
        else:
            _, c, r, a0, a1 = p
            lay.msp.add_arc(c, r, a0, a1, dxfattribs={"layer": "RAIL"})
    # 슬롯 NODE 에서 모듈 밖으로 나가는 링크: 마진 구간(슬롯 → NODE)을 이어 준다
    stub = 0
    for lk in rest.links:
        for nid in (lk.start, lk.end):
            if nid in mp.node_mod and mp.node_mod[nid] in slots:
                pos, _out, mg = slots[mp.node_mod[nid]]
                if mg > 0:
                    lay.line(pos, mp.nodes[nid])
                    stub += 1

    try:
        import ezdxf.zoom
        ezdxf.zoom.extents(lay.msp, factor=1.05)
    except Exception:
        pass
    lay.save(str(dxf_path))
    for m in warns[:20]:
        log("  " + m)
    if len(warns) > 20:
        log(f"  ... 경고 {len(warns) - 20}건 더")
    log(f"DXF 저장: {dxf_path}  (모듈 {placed}/{len(mp.modules)}, 모듈 밖 링크 {len(rest.links)}, 마진 구간 {stub})")
    n_line = sum(1 for e in lay.msp if e.dxftype() == "LINE")
    n_arc = sum(1 for e in lay.msp if e.dxftype() == "ARC")
    return {"dxf": str(dxf_path), "modules": placed, "module_total": len(mp.modules),
            "plain_links": len(rest.links), "lines": n_line, "arcs": n_arc,
            "nodes": len(mp.nodes), "links": len(mp.links), "ports": 0, "warnings": warns}


if __name__ == "__main__":
    import sys
    module_map_to_dxf(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
