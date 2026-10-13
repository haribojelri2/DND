# -*- coding: utf-8 -*-
# 3차선 POC: 3,4차선.dxf 클러스터0을 블록화 + 거리1 길이신축(상단/하단 직선 신축, 가운데 분기 rigid).
#   CLASSES 있는 2차선 정적파일을 베이스로 사용(2rail 블록은 strip).
import os, sys, uuid, importlib.util
import ezdxf

HERE = r"C:\Users\User\Desktop\dnd\code"
spec = importlib.util.spec_from_file_location("cf", os.path.join(HERE, "create_flexible_dxf.py"))
cf = importlib.util.module_from_spec(spec); sys.modules["cf"] = cf; spec.loader.exec_module(cf)

SRC34 = os.path.join(HERE, "zwcad_lm", "dist", "3rail.dxf")   # 사용자가 준 단일 3차선 블록
SRCBLK = "3rail2"
BASE  = os.path.join(HERE, "2차선_H분기_직선등간격 (1).dxf")   # CLASSES 보유
OUT   = os.path.join(HERE, "zwcad_lm", "dist", "3rail_flex.dxf")
BLK   = "3rail2"

def arc_entity(h, owner, cx, cy, r, a0, a1):
    return [cf.pair(0,"ARC"),cf.pair(5,h),cf.pair(330,owner),cf.pair(100,"AcDbEntity"),cf.pair(8,"0"),
            cf.pair(100,"AcDbCircle"),cf.pair(10,cf.fmt(cx)),cf.pair(20,cf.fmt(cy)),cf.pair(30,"0.0"),cf.pair(40,cf.fmt(r)),
            cf.pair(100,"AcDbArc"),cf.pair(50,cf.fmt(a0)),cf.pair(51,cf.fmt(a1))]

# ── 3rail2 블록 지오메트리 읽기 ──
doc = ezdxf.readfile(SRC34)
geo = []  # (kind, dict)
for e in doc.blocks.get(SRCBLK):
    if e.dxftype() not in ("LINE","ARC"): continue
    if e.dxftype()=="LINE":
        geo.append(("LINE", dict(x0=e.dxf.start.x,y0=e.dxf.start.y,x1=e.dxf.end.x,y1=e.dxf.end.y)))
    else:
        geo.append(("ARC", dict(cx=e.dxf.center.x,cy=e.dxf.center.y,r=e.dxf.radius,a0=e.dxf.start_angle,a1=e.dxf.end_angle)))
ys = []
for k,d in geo:
    if k=="LINE": ys += [d["y0"],d["y1"]]
    else: ys += [d["cy"]-d["r"], d["cy"]+d["r"]]
xs = []
for k,d in geo:
    if k=="LINE": xs += [d["x0"],d["x1"]]
    else: xs += [d["cx"]-d["r"], d["cx"]+d["r"]]
miny,maxy=min(ys),max(ys); minx,maxx=min(xs),max(xs)
# U분기(turnout)가 y≈89000~99600에 걸침. 하단 신축 경계를 그 위로 올려 U분기 전체를 rigid 유닛으로 유지.
TOP_B = maxy-6000; BOT_B = 100000
left_x = min(d["x0"] for k,d in geo if k=="LINE" and abs(d["x0"]-d["x1"])<1)
print("y=[%.0f..%.0f] x=[%.0f..%.0f] TOP_B=%.0f BOT_B=%.0f left_x=%.0f"%(miny,maxy,minx,maxx,TOP_B,BOT_B,left_x))

# ── 핸들 발급 ──
pairs0 = cf.read_pairs(__import__("pathlib").Path(BASE))
hgen = cf.HandleGen(max(cf.max_handle(pairs0)+1, 0x100000))
REC = hgen.new()          # BLOCK_RECORD 핸들
INS = hgen.new()          # insert
# 지오메트리 엔티티 핸들 부여 + 상/하 영역 분류
geom_ents = []            # 블록에 넣을 태그들
top_specs=[]; bot_specs=[]; top_refs=[]; bot_refs=[]
for k,d in geo:
    h = hgen.new()
    if k=="LINE":
        geom_ents.append(cf.line_entity(h, REC, d["x0"],d["y0"],d["x1"],d["y1"]))
        yA,yB = d["y0"],d["y1"]
        # 상단: 점이 TOP_B 위인지
        in0_t, in1_t = yA>TOP_B, yB>TOP_B
        if in0_t and in1_t: top_refs.append(h); top_specs.append((h,[0,1]))
        elif in0_t: top_refs.append(h); top_specs.append((h,[0]))
        elif in1_t: top_refs.append(h); top_specs.append((h,[1]))
        in0_b, in1_b = yA<BOT_B, yB<BOT_B
        if in0_b and in1_b: bot_refs.append(h); bot_specs.append((h,[0,1]))
        elif in0_b: bot_refs.append(h); bot_specs.append((h,[0]))
        elif in1_b: bot_refs.append(h); bot_specs.append((h,[1]))
    else:
        geom_ents.append(arc_entity(h, REC, d["cx"],d["cy"],d["r"],d["a0"],d["a1"]))
        if d["cy"]>TOP_B: top_refs.append(h); top_specs.append((h,[0,1]))
        if d["cy"]<BOT_B: bot_refs.append(h); bot_specs.append((h,[0,1]))
entity_count = len(geom_ents)

# ── 다이나믹 핸들 ──
xdict=hgen.new(); graph=hgen.new(); purge=hgen.new()
vparam=hgen.new(); vbg=hgen.new(); vbx=hgen.new(); vby=hgen.new(); veg=hgen.new(); vex=hgen.new(); vey=hgen.new()
tstr=hgen.new(); bstr=hgen.new()

nodes=[(1,vparam),(2,vbg),(3,vbx),(4,vby),(5,veg),(6,vex),(7,vey),(8,tstr),(9,bstr)]
ni={h:i for i,(_e,h) in enumerate(nodes)}
E=[]
v=ni[vparam]
for d in [vbx,vby]: E.append((v,ni[d],1))
E.append((ni[vbg],v,2))
for d in [vex,vey]: E.append((v,ni[d],1))
E.append((ni[veg],v,2))
for d in [tstr,bstr]: E.append((v,ni[d],2))

objs=[]
objs.append(cf.dict_object(xdict, REC, graph, purge))
objs.append(cf.build_graph(graph, xdict, nodes, E))
objs.append(cf.purge_object(purge, xdict))
objs.append(cf.linear_parameter(vparam, graph, 1, "선형", "거리1", left_x, miny, left_x, maxy, 2, 5, (maxy-miny)*0.16, maxy-miny))
objs.append(cf.linear_grip(vbg, graph, 2, "기준 그립", 3,4, left_x, miny, 0.0, -(maxy-miny)))
objs.append(cf.grip_component(vbx, graph, 3, 1, "UpdatedBaseX"))
objs.append(cf.grip_component(vby, graph, 4, 1, "UpdatedBaseY"))
objs.append(cf.linear_grip(veg, graph, 5, "끝 그립", 6,7, left_x, maxy, 0.0, maxy-miny))
objs.append(cf.grip_component(vex, graph, 6, 1, "UpdatedEndX", True))
objs.append(cf.grip_component(vey, graph, 7, 1, "UpdatedEndY", True))
objs.append(cf.stretch_action(tstr, graph, 8, "신축", 1, "end", top_refs, top_specs,
                              (minx-1000, maxy+1200, maxx+1000, TOP_B)))
objs.append(cf.stretch_action(bstr, graph, 9, "신축1", 1, "base", bot_refs, bot_specs,
                              (minx-1000, BOT_B, maxx+1000, miny-1200)))
print("top_specs=%d bot_specs=%d"%(len(top_specs),len(bot_specs)))

# ── 베이스에 조립: 2rail strip + 3rail_poc 블록/레코드/인서트/객체 추가 ──
STRIP={"BLOCKLINEARPARAMETER","BLOCKLINEARGRIP","BLOCKGRIPLOCATIONCOMPONENT","BLOCKSTRETCHACTION",
       "BLOCKMOVEACTION","ACAD_EVALUATION_GRAPH","ACDB_DYNAMICBLOCKPURGEPREVENTER_VERSION","ACDB_BLOCKREPRESENTATION_DATA"}
entries = cf.split_entries(pairs0)
new=[]; skip=False; in_brtab=False
guid = "{"+str(uuid.uuid5(uuid.NAMESPACE_URL,"3rail-poc")).upper()+"}"
rec=[cf.pair(0,"BLOCK_RECORD"),cf.pair(5,REC),cf.pair(102,"{ACAD_XDICTIONARY"),cf.pair(360,xdict),cf.pair(102,"}"),
     cf.pair(330,"1"),cf.pair(100,"AcDbSymbolTableRecord"),cf.pair(100,"AcDbBlockTableRecord"),cf.pair(2,BLK),
     cf.pair(340,"0"),cf.pair(102,"{BLKREFS"),cf.pair(331,INS),cf.pair(102,"}"),cf.pair(70,"0"),cf.pair(280,"1"),cf.pair(281,"0"),
     cf.pair(1001,"AcDbBlockRepETag"),cf.pair(1070,"1"),cf.pair(1071,str(entity_count)),
     cf.pair(1001,"AcDbDynamicBlockTrueName"),cf.pair(1000,BLK),
     cf.pair(1001,"AcDbDynamicBlockGUID"),cf.pair(1000,guid)]
for ent in entries:
    t=cf.first(ent,0); nm=cf.first(ent,2)
    junk = nm and (nm.startswith("*U") or nm.startswith("2rail"))
    if t in STRIP: continue
    if t=="DICTIONARY" and "ACAD_ENHANCEDBLOCK" in [v.strip() for c,v in ent if c.strip()=="3"]: continue
    if t=="BLOCK" and junk: skip=True; continue
    if t=="ENDBLK" and skip: skip=False; continue
    if skip: continue
    if t=="BLOCK_RECORD" and junk: continue
    if t=="INSERT" and nm and (nm.startswith("*") or nm.startswith("2rail")): continue
    if t=="TABLE" and nm=="BLOCK_RECORD": in_brtab=True
    if t=="ENDTAB" and in_brtab:
        new.append(rec); in_brtab=False   # BLOCK_RECORD 테이블 끝에 새 레코드 삽입
        new.append(ent); continue
    if t=="ENDSEC":
        prev=None
        for e in reversed(new):
            if cf.first(e,0)=="SECTION": prev=cf.first(e,2); break
        if prev=="BLOCKS":
            # 새 BLOCK 정의 (헤더 + 지오메트리 + ENDBLK)
            new.append([cf.pair(0,"BLOCK"),cf.pair(5,hgen.new()),cf.pair(330,REC),cf.pair(100,"AcDbEntity"),cf.pair(8,"0"),
                        cf.pair(100,"AcDbBlockBegin"),cf.pair(2,BLK),cf.pair(70,"0"),
                        cf.pair(10,"0.0"),cf.pair(20,"0.0"),cf.pair(30,"0.0"),cf.pair(3,BLK),cf.pair(1,"")])
            for ge in geom_ents: new.append(ge)
            new.append([cf.pair(0,"ENDBLK"),cf.pair(5,hgen.new()),cf.pair(330,REC),cf.pair(100,"AcDbEntity"),cf.pair(8,"0"),cf.pair(100,"AcDbBlockEnd")])
        if prev=="ENTITIES":
            new.append(cf.insert_entity(INS, BLK, 0.0, 0.0))
        if prev=="OBJECTS":
            for o in objs: new.append(o)
        new.append(ent); continue
    new.append(ent)

cf.write_pairs(__import__("pathlib").Path(OUT), cf.flatten(new))
d=ezdxf.readfile(OUT); a=d.audit()
print("AUDIT errors=%d fixes=%d"%(len(a.errors),len(a.fixes)))
print("출력:",OUT)
