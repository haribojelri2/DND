# -*- coding: utf-8 -*-
# 거리2를 "레일 세로 중앙"으로 옮기고 전용 0.5 이동(위/아래)을 부여한 플렉시블 블록 생성.
#   - 기존 create_flexible_dxf.py 의 검증된 helper(build_graph/move_action/...)를 재활용
#   - 정적 base 블록(2차선_H분기_직선등간격 (1).dxf)에서 2rail_1/H2/H3/H4 재생성 (W900 제외)
#   - 거리2: 조인트 체이닝 제거 → 중앙에 배치 + 거리1(길이)에 물린 전용 Move 2개(end/base, 배수 0.5)
import os, sys, uuid, importlib.util
import ezdxf

HERE = r"C:\Users\User\Desktop\dnd\code"
spec = importlib.util.spec_from_file_location("cf", os.path.join(HERE, "create_flexible_dxf.py"))
cf = importlib.util.module_from_spec(spec); sys.modules["cf"] = cf; spec.loader.exec_module(cf)

STATIC = os.path.join(HERE, "2차선_H분기_직선등간격 (1).dxf")
OUT    = r"C:\Users\User\Downloads\2차선_대칭.dxf"
TARGETS = ["2rail_1", "2rail_H2", "2rail_H3", "2rail_H4"]

def gval(obj, code):
    return [v for c, v in obj if c == str(code)]
def ohandle(obj):
    h = gval(obj, 5); return h[0] if h else None

def set_y(obj, ycodes, y):
    """지정 group code(들)의 값을 y로 (첫 등장만)."""
    done = set(); out = []
    for c, v in obj:
        if c in ycodes and c not in done:
            out.append((c, cf.fmt(y))); done.add(c)
        else:
            out.append((c, v))
    return out

def strip_hparam(obj, hparam):
    """BLOCKMOVEACTION 선택셋에서 hparam(330) 제거 + 71 감소."""
    if hparam not in gval(obj, 330):
        return obj
    ai = next(i for i, (c, v) in enumerate(obj) if c == "100" and v == "AcDbBlockAction")
    ci = next(i for i in range(ai, len(obj)) if obj[i][0] == "71")
    ri = next(i for i in range(ci + 1, len(obj)) if obj[i][0] == "330" and obj[i][1] == hparam)
    obj = obj[:ri] + obj[ri + 1:]
    obj[ci] = ("71", str(int(obj[ci][1]) - 1))
    return obj

def build_v2(geom, H, hmove_end_h, hmove_base_h):
    # 거리2 = 중앙에 두고, 길이의 0.5로 따라가게 전용 Move 2개.
    #  ★ 핵심: Move 선택셋에 "거리2 파라미터"가 아니라 "거리2 그립"(base/end)을 넣음(ZWCAD 표준 체이닝).
    baseline = cf.build_dynamic_objects(geom, H)
    center_y = (geom.miny + geom.maxy) / 2.0
    x_mid = (geom.left_x + geom.right_x) / 2.0
    # ── nodes/edges 재구성 + 거리2 Move 2노드 ──
    nodes = [(1,H.vparam),(2,H.vbase_grip),(3,H.vbase_x),(4,H.vbase_y),(5,H.vend_grip),
             (6,H.vend_x),(7,H.vend_y),(8,H.top_stretch),(9,H.bottom_stretch),(13,H.hparam),
             (14,H.hbase_grip),(15,H.hbase_x),(16,H.hbase_y),(17,H.hend_grip),(18,H.hend_x),
             (19,H.hend_y),(20,H.right_stretch),(22,H.left_stretch)]
    me = 25
    for hh in H.move_end:  nodes.append((me, hh)); me += 1
    for hh in H.move_base: nodes.append((me, hh)); me += 1
    he_expr = me; nodes.append((he_expr, hmove_end_h));  me += 1
    hb_expr = me; nodes.append((hb_expr, hmove_base_h)); me += 1
    ni = {hh: i for i, (_e, hh) in enumerate(nodes)}
    E = []
    v = ni[H.vparam]; hn = ni[H.hparam]
    for d in [H.vbase_x, H.vbase_y]: E.append((v, ni[d], 1))
    E.append((ni[H.vbase_grip], v, 2))
    for d in [H.vend_x, H.vend_y]: E.append((v, ni[d], 1))
    E.append((ni[H.vend_grip], v, 2))
    for d in [H.top_stretch, H.bottom_stretch]: E.append((v, ni[d], 2))
    for d in [H.hbase_x, H.hbase_y]: E.append((hn, ni[d], 1))
    E.append((ni[H.hbase_grip], hn, 2))
    for d in [H.hend_x, H.hend_y]: E.append((hn, ni[d], 1))
    E.append((ni[H.hend_grip], hn, 2))
    for d in [H.right_stretch, H.left_stretch]: E.append((hn, ni[d], 2))
    for d in H.move_end + H.move_base: E.append((v, ni[d], 2))
    E.append((v, ni[hmove_end_h], 2))
    E.append((v, ni[hmove_base_h], 2))
    new_graph = cf.build_graph(H.graph, H.xdict, nodes, E)
    out = []
    for obj in baseline:
        t = obj[0][1]; h = ohandle(obj)
        if t == "ACAD_EVALUATION_GRAPH":
            out.append(new_graph)
        elif t == "BLOCKLINEARPARAMETER" and h == H.hparam:
            out.append(set_y(obj, ("1020", "1021"), center_y))
        elif t == "BLOCKLINEARGRIP" and h in (H.hbase_grip, H.hend_grip):
            out.append(set_y(obj, ("1020",), center_y))
        elif t == "BLOCKMOVEACTION":
            out.append(strip_hparam(obj, H.hparam))
        else:
            out.append(obj)
    # ★ 중앙고정(대칭) 보정: 모든 지오메트리를 0.5 반대로 이동 → 위/아래 대칭 신축, 중앙 고정.
    #   거리2 그립은 이 이동에 안 넣음(고정) → 중앙이 안 움직이니 거리2도 중앙 유지.
    all_geom = [e.handle for e in geom.entities]
    out.append(cf.move_action(hmove_end_h,  H.graph, he_expr, "중앙보정",  all_geom, x_mid, center_y, "end",  -0.5))
    out.append(cf.move_action(hmove_base_h, H.graph, hb_expr, "중앙보정1", all_geom, x_mid, center_y, "base", -0.5))
    return out

# 기존 다이나믹 잔재(손저작 2rail_1/H2) 제거 대상
STRIP_TYPES = {"BLOCKLINEARPARAMETER", "BLOCKLINEARGRIP", "BLOCKGRIPLOCATIONCOMPONENT",
               "BLOCKSTRETCHACTION", "BLOCKMOVEACTION", "ACAD_EVALUATION_GRAPH",
               "ACDB_DYNAMICBLOCKPURGEPREVENTER_VERSION", "ACDB_BLOCKREPRESENTATION_DATA"}

def main():
    doc = ezdxf.readfile(STATIC)
    recs = {b.name: b.block_record_handle for b in doc.blocks if b.name in TARGETS}

    from pathlib import Path
    pairs = cf.read_pairs(Path(STATIC))
    hgen = cf.HandleGen(max(cf.max_handle(pairs) + 1, 0x100000))  # 기존 핸들 위로 (충돌 방지)

    geoms, handles, extra, dynobjs, insh = {}, {}, {}, {}, {}
    for nm in TARGETS:
        g = cf.classify_block(doc, nm, recs[nm], [])
        geoms[nm] = g
        handles[nm] = cf.allocate_dyn_handles(hgen, len(g.groups))
        extra[nm] = (hgen.new(), hgen.new())   # 거리2 move_end, move_base
        insh[nm] = hgen.new()                  # 새 인서트 핸들
    for nm in TARGETS:
        dynobjs[nm] = build_v2(geoms[nm], handles[nm], *extra[nm])

    entries = cf.split_entries(pairs)
    new_entries = []
    skip = False
    for ent in entries:
        typ = cf.first(ent, 0)
        nm2 = cf.first(ent, 2)
        # ── 기존 다이나믹 객체/블록 제거 ──
        if typ in STRIP_TYPES:
            continue
        if typ == "DICTIONARY" and "ACAD_ENHANCEDBLOCK" in [v.strip() for c, v in ent if c.strip() == "3"]:
            continue
        junk = nm2 and (nm2.startswith("*U") or nm2.startswith("2rail_W900"))  # *U 익명 + W900(삭제)
        if typ == "BLOCK" and junk:
            skip = True; continue
        if typ == "ENDBLK" and skip:
            skip = False; continue
        if skip:
            continue
        if typ == "BLOCK_RECORD" and junk:
            continue
        if typ == "INSERT" and nm2 and (nm2.startswith("*") or nm2 in TARGETS or nm2.startswith("2rail_W900")):
            continue  # *U·W900·타겟 인서트 제거 → 타겟은 아래서 새로 추가
        # ── 타겟 BLOCK_RECORD → 다이나믹으로 재작성 ──
        if typ == "BLOCK_RECORD" and nm2 in TARGETS:
            guid = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, "lsl-flexv2-" + nm2)).upper() + "}"
            new_entries.append(cf.make_block_record(ent, handles[nm2].xdict, nm2, guid,
                                                    len(geoms[nm2].entities), insh[nm2]))
            continue
        if typ == "ENDSEC":
            prev = None
            for e in reversed(new_entries):
                if cf.first(e, 0) == "SECTION":
                    prev = cf.first(e, 2); break
            if prev == "ENTITIES":
                for i, nm in enumerate(TARGETS):
                    new_entries.append(cf.insert_entity(insh[nm], nm, i * 5000.0, 0.0))
            if prev == "OBJECTS":
                for nm in TARGETS:
                    new_entries.extend(dynobjs[nm])
            new_entries.append(ent); continue
        new_entries.append(ent)

    cf.write_pairs(Path(OUT), cf.flatten(new_entries))
    print("출력:", OUT)

if __name__ == "__main__":
    main()
