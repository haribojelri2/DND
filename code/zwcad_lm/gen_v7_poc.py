# -*- coding: utf-8 -*-
# v7 POC (top_02만): 왼쪽 그립 = 램프 대각선이 45° 유지하며 신축.
#   원리: 대각선 왼끝은 수평(-Δ), 오른끝은 수직(±Δ) → 기울기 45° 유지, 호 접선 보존.
#   구현: 신축3(W1) = seam 1384 수평 (v5식) + 신규 수직 신축 2개(141 각도오프셋 270/90):
#     W2상(141=270): 상행 대각선 오른끝 + 상행 정션호 + 중간레일 아래끝 → +Y
#     W2하(141=90):  하행 대각선 오른끝 + 하행 정션호 + 중간레일 위끝 → -Y
#   그래프에 노드 2 + 엣지 2(거리2→W2) 추가. 나머지 블록은 v6 그대로.
import ezdxf, math

SRC = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v8_geo.dxf'
OUT = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v8.dxf'
BLK = 'rail34_top_02'
SEAM_W1 = 1384.0

# ── top_02 지오 분류 ──
doc = ezdxf.readfile(SRC)
b = doc.blocks.get(BLK)
geo = {}
for e in b:
    h = e.dxf.handle
    if e.dxftype() == 'LINE':
        s, en = e.dxf.start, e.dxf.end
        geo[h] = dict(kind='LINE', pts=[(s.x, s.y), (en.x, en.y)])
    elif e.dxftype() == 'ARC':
        c = e.dxf.center; r = e.dxf.radius
        a0 = math.radians(e.dxf.start_angle); a1 = math.radians(e.dxf.end_angle)
        geo[h] = dict(kind='ARC', pts=[(c.x+r*math.cos(a0), c.y+r*math.sin(a0)),
                                       (c.x+r*math.cos(a1), c.y+r*math.sin(a1))])
diag_up = []; diag_dn = []        # (handle, 오른끝 idx)
arc_up = []; arc_dn = []          # handle (정션호: 통째)
midrail = None                    # (handle, 아래끝 idx, 위끝 idx)
for h, g in geo.items():
    (x0, y0), (x1, y1) = g['pts']
    if g['kind'] == 'LINE':
        if abs(x0-x1) < 1 and abs(x0-1550) < 5 and abs(y0-y1) > 5000:
            midrail = (h, 0 if y0 < y1 else 1, 1 if y0 < y1 else 0)
        elif abs(y0-y1) >= 1 and abs(x0-x1) >= 1:   # 대각선
            ri = 0 if x0 > x1 else 1                 # 오른끝(중간레일쪽)
            li = 1-ri
            if g['pts'][ri][1] > g['pts'][li][1]: diag_up.append((h, ri))
            else: diag_dn.append((h, ri))
    else:   # ARC: 정션호 = 양끝 x가 [1400,1600] 구간 안(1418~1550)
        if all(1400 <= p[0] <= 1600 for p in g['pts']):
            rail_i = 0 if abs(g['pts'][0][0]-1550) < abs(g['pts'][1][0]-1550) else 1
            if g['pts'][rail_i][1] > g['pts'][1-rail_i][1]: arc_up.append(h)
            else: arc_dn.append(h)
print('상행대각 %d 하행대각 %d 상행호 %d 하행호 %d 중간레일 %s' %
      (len(diag_up), len(diag_dn), len(arc_up), len(arc_dn), midrail))
assert midrail and len(diag_up) == 3 and len(diag_dn) == 3 and len(arc_up) == 3 and len(arc_dn) == 3

# ── raw 파싱 ──
raw = open(SRC, encoding='utf-8', errors='ignore').read().split('\n')
pairs = [(raw[j], raw[j+1]) for j in range(0, len(raw)-1, 2)]
def cs(x): return x.strip()
ents = []; cur = None
for c, v in pairs:
    if cs(c) == '0':
        if cur: ents.append(cur)
        cur = [(c, v)]
    else:
        if cur is None: cur = [(c, v)]
        else: cur.append((c, v))
if cur: ents.append(cur)
def gv(T, code): return [cs(v) for c, v in T if cs(c) == code]
def maxh(ents):
    m = 0
    for T in ents:
        for c, v in T:
            if cs(c) == '5':
                try: m = max(m, int(cs(v), 16))
                except ValueError: pass
    return m
hgen = maxh(ents)+1

# ── 신축3(top_02) 찾기 + W1로 재배선 (seam 1384) ──
tgt3 = None
for T in ents:
    if cs(T[0][1]) == 'BLOCKSTRETCHACTION' and (gv(T, '300') or [''])[0] == '신축3':
        if len([x for x in gv(T, '331') if x in geo]) > 5: tgt3 = T; break
assert tgt3 is not None
GRAPH = gv(tgt3, '330')[0]
def find(T, pred, st=0):
    for i in range(st, len(T)):
        if pred(T[i]): return i
    return -1
i_str = find(tgt3, lambda t: cs(t[0]) == '100' and cs(t[1]) == 'AcDbBlockStretchAction')
SRC92 = next(cs(tgt3[i][1]) for i in range(i_str, len(tgt3)) if cs(tgt3[i][0]) == '92')   # 거리2 expr id

# W1 프레임 seam 교체 + 멤버 재생성
i72 = find(tgt3, lambda t: cs(t[0]) == '72', i_str)
idx1011 = [i for i in range(i72, min(i72+9, len(tgt3))) if cs(tgt3[i][0]) == '1011'][:2]
idx1021 = [i for i in range(i72, min(i72+9, len(tgt3))) if cs(tgt3[i][0]) == '1021'][:2]
xs = [(i, float(cs(tgt3[i][1]))) for i in idx1011]
ys = [float(cs(tgt3[i][1])) for i in idx1021]
ti = max(xs, key=lambda t: t[1])[0]     # BASE: 우변을 seam으로
ov = tgt3[ti][1]; lead = ov[:len(ov)-len(ov.lstrip())]; cr = '\r' if ov.endswith('\r') else ''
tgt3[ti] = (tgt3[ti][0], lead+repr(SEAM_W1)+cr)
fx = sorted([SEAM_W1 if i == ti else v for i, v in xs]); fy = sorted(ys)
frame = (fx[0], fx[1], fy[0], fy[1])
def inside(p): return frame[0] <= p[0] <= frame[1] and frame[2] <= p[1] <= frame[3]
def spec_for(h):
    g = geo[h]; ins = [inside(p) for p in g['pts']]; n = sum(ins)
    if n == 0: return None
    if g['kind'] == 'ARC': return (2, [0, 1]) if n == 2 else None
    if n == 2: return (2, [0, 1])
    return (1, [0] if ins[0] else [1])
i_act = find(tgt3, lambda t: cs(t[0]) == '100' and cs(t[1]) == 'AcDbBlockAction')
i71 = find(tgt3, lambda t: cs(t[0]) == '71', i_act)
j = i71+1; sel = []
while j < len(tgt3) and cs(tgt3[j][0]) == '330': sel.append(tgt3[j]); j += 1
sel_end = j
i73 = find(tgt3, lambda t: cs(t[0]) == '73', i_str)
k = i73+1; specs = []
while k < len(tgt3) and cs(tgt3[k][0]) == '331':
    grp = [tgt3[k]]; h = cs(tgt3[k][1]); k += 1
    n = int(cs(tgt3[k][1])); grp.append(tgt3[k]); k += 1
    for _ in range(n): grp.append(tgt3[k]); k += 1
    specs.append((h, grp))
spec_end = k
spec_map = dict(specs)
c330 = sel[0]; code_lead = c330[0][:len(c330[0])-len(c330[0].lstrip())]
ccr = '\r' if c330[0].endswith('\r') else ''
v0 = c330[1]; val_lead = v0[:len(v0)-len(v0.lstrip())]; vcr = '\r' if v0.endswith('\r') else ''
def P(code, val): return (code_lead+str(code)+ccr, val_lead+str(val)+vcr)
kept_sel = []; kept_spec = []
orig_members = [cs(t[1]) for t in sel]
for h in orig_members:
    if h not in geo:
        kept_sel.append(P('330', h)); kept_spec.append(spec_map.get(h, [P('331', h), P('74', '0')]))
        continue
    sp = spec_for(h)
    if sp is None: continue
    n, idxs = sp
    kept_sel.append(P('330', h)); kept_spec.append([P('331', h), P('74', n)]+[P('94', i) for i in idxs])
have = set(orig_members)
for h in geo:
    if h in have: continue
    sp = spec_for(h)
    if sp is None: continue
    n, idxs = sp
    kept_sel.append(P('330', h)); kept_spec.append([P('331', h), P('74', n)]+[P('94', i) for i in idxs])
def bump(T, i, num):
    v = T[i][1]; ld = v[:len(v)-len(v.lstrip())]; c2 = '\r' if v.endswith('\r') else ''
    T[i] = (T[i][0], ld+str(num)+c2)
new = tgt3[:i71]; new.append(tgt3[i71]); new += kept_sel
new += tgt3[sel_end:i73]; new.append(tgt3[i73])
for g2 in kept_spec: new += g2
new += tgt3[spec_end:]
tgt3[:] = new
bump(tgt3, find(tgt3, lambda t: cs(t[0]) == '71', 0), len(kept_sel))
bump(tgt3, find(tgt3, lambda t: cs(t[0]) == '73', 0), len(kept_spec))
print('W1(신축3) 재배선: 멤버 %d' % len(kept_sel))

# ── 그래프 파싱 ──
gT = next(T for T in ents if cs(T[0][1]) == 'ACAD_EVALUATION_GRAPH' and (gv(T, '5') or [''])[0] == GRAPH)
i_hdr = find(gT, lambda t: cs(t[0]) == '100' and cs(t[1]) == 'AcDbEvalGraph')
i96 = find(gT, lambda t: cs(t[0]) == '96', i_hdr); i97 = find(gT, lambda t: cs(t[0]) == '97', i_hdr)
maxexpr = int(cs(gT[i97][1]))
k = i97+1
nodes = []; edges = []   # 원시 슬라이스 (시작idx, 태그수)
while k < len(gT):
    t0 = cs(gT[k][0])
    if t0 == '91': nodes.append(k); k += 8
    elif t0 == '92': edges.append(k); k += 10
    else: break
N = len(nodes); E = len(edges)
print('그래프: 노드 %d 엣지 %d maxexpr %d' % (N, E, maxexpr))
# 거리2 파라미터 노드 (360=param handle, param의 90=SRC92)
p_handle = None
for T in ents:
    if cs(T[0][1]) == 'BLOCKLINEARPARAMETER' and (gv(T, '330') or [''])[0] == GRAPH:
        i_ee = find(T, lambda t: cs(t[0]) == '100' and cs(t[1]) == 'AcDbEvalExpr')
        e90 = next((cs(T[i][1]) for i in range(i_ee, min(i_ee+5, len(T))) if cs(T[i][0]) == '90'), None)
        if e90 == SRC92: p_handle = (gv(T, '5') or [''])[0]; break
assert p_handle, '거리2 param not found'
src_idx = None; src_node_at = None
for at in nodes:
    if cs(gT[at+3][1]) == p_handle:
        src_idx = int(cs(gT[at][1])); src_node_at = at; break
assert src_idx is not None
# src 노드의 outgoing 마지막 엣지
outL_at = src_node_at+7                       # 92 x4 중 4번째 = lastOut
prev_lastout = int(cs(gT[outL_at][1]))
print('거리2 노드 idx=%d (handle %s), lastOut 엣지=%d' % (src_idx, p_handle, prev_lastout))

# ── 신규 액션 2개 생성 ──
def fmt_h(n): return format(n, 'X')
H_UP = fmt_h(hgen); hgen += 1
H_DN = fmt_h(hgen); hgen += 1
EXPR_UP = maxexpr+1; EXPR_DN = maxexpr+2
def mk_action(handle, expr, label, ang, members, frame_):
    """members: [(handle, 74, [94..])], frame_=(x0,x1,y0,y1)"""
    t = [('0', 'BLOCKSTRETCHACTION'), ('5', handle), ('330', GRAPH),
         ('100', 'AcDbEvalExpr'), ('90', str(expr)), ('98', '33'), ('99', '274'),
         ('100', 'AcDbBlockElement'), ('300', label), ('98', '33'), ('99', '274'), ('1071', '0'),
         ('100', 'AcDbBlockAction'), ('70', '0'), ('71', str(len(members)))]
    for h, _n, _i in members: t.append(('330', h))
    t += [('1010', '1490.0'), ('1020', '30000.0'), ('1030', '0.0'),
          ('100', 'AcDbBlockStretchAction'), ('92', SRC92), ('301', 'BaseXDelta'),
          ('93', SRC92), ('302', 'BaseYDelta'), ('72', '2'),
          ('1011', repr(frame_[0])), ('1021', repr(frame_[3])),
          ('1011', repr(frame_[1])), ('1021', repr(frame_[2])),
          ('73', str(len(members)))]
    for h, n, idxs in members:
        t.append(('331', h)); t.append(('74', str(n)))
        for i in idxs: t.append(('94', str(i)))
    t += [('75', '0'),
          ('140', '1.0'), ('141', repr(float(ang))), ('280', '0')]
    return t

mem_up = [(h, 1, [ri]) for h, ri in diag_up] + [(h, 2, [0, 1]) for h in arc_up] + [(midrail[0], 1, [midrail[1]])]
mem_dn = [(h, 1, [ri]) for h, ri in diag_dn] + [(h, 2, [0, 1]) for h in arc_dn] + [(midrail[0], 1, [midrail[2]])]
act_up = mk_action(H_UP, EXPR_UP, '신축V상', 270.0, mem_up, (1400.0, 1600.0, -1000.0, 50000.0))
act_dn = mk_action(H_DN, EXPR_DN, '신축V하', 90.0, mem_dn, (1400.0, 1600.0, 10000.0, 61000.0))

# ── 그래프 패치 ──
# 1) 96/97 = maxexpr+2
bump(gT, i96, EXPR_DN); bump(gT, i97, EXPR_DN)
# 2) src 노드 lastOut → E+1, 기존 마지막 out 엣지의 nextOut(-1) → E
def setv(T, i, num):
    v = T[i][1]; ld = v[:len(v)-len(v.lstrip())]; c2 = '\r' if v.endswith('\r') else ''
    T[i] = (T[i][0], ld+str(num)+c2)
setv(gT, outL_at, E+1)
if prev_lastout >= 0:
    at = edges[prev_lastout]
    setv(gT, at+8, E)     # 엣지레코드: [92id,93,94,91src,91dst,92 inPrev,92 inNext,92 outPrev,92 outNext,92 -1]
# 3) 신규 노드/엣지 레코드 삽입 (그래프 태그 끝에)
gl = gT[i96][0][:len(gT[i96][0])-len(gT[i96][0].lstrip())]
gcr = '\r' if gT[i96][0].endswith('\r') else ''
vl = gT[i96][1][:len(gT[i96][1])-len(gT[i96][1].lstrip())]
vcr2 = '\r' if gT[i96][1].endswith('\r') else ''
def G(code, val): return (gl+str(code)+gcr, vl+str(val)+vcr2)
# 노드 레코드는 노드 구역(첫 엣지 레코드 앞)에, 엣지 레코드는 맨 뒤에 — 원본 순서 보존
node_recs = [G('91', N),   G('93', 32), G('95', EXPR_UP), G('360', H_UP),
             G('92', E),   G('92', E),  G('92', -1), G('92', -1),
             G('91', N+1), G('93', 32), G('95', EXPR_DN), G('360', H_DN),
             G('92', E+1), G('92', E+1), G('92', -1), G('92', -1)]
edge_recs = [G('92', E),   G('93', 0), G('94', 2), G('91', src_idx), G('91', N),
             G('92', -1), G('92', -1), G('92', prev_lastout), G('92', E+1), G('92', -1),
             G('92', E+1), G('93', 0), G('94', 2), G('91', src_idx), G('91', N+1),
             G('92', -1), G('92', -1), G('92', E), G('92', -1), G('92', -1)]
ins_at = edges[0] if edges else len(gT)     # 첫 엣지 레코드 위치 (setv로 이미 수정된 엣지 인덱스는 위치 불변)
gT[ins_at:ins_at] = node_recs
gT.extend(edge_recs)

# ── $HANDSEED 갱신 (새 핸들 반영) ──
for T in ents:
    for i in range(len(T)-1):
        if cs(T[i][0]) == '9' and cs(T[i][1]) == '$HANDSEED':
            setv(T, i+1, format(hgen+16, 'X'))
            break

# ── 신규 액션을 신축3 뒤에 삽입 + 저장 ──
pos = ents.index(tgt3)
ents.insert(pos+1, act_up); ents.insert(pos+2, act_dn)
out = []
for T in ents:
    for c, v in T: out.append(c); out.append(v)
open(OUT, 'w', encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('신규 액션: 신축V상 h=%s (expr %d, 141=270), 신축V하 h=%s (expr %d, 141=90)' % (H_UP, EXPR_UP, H_DN, EXPR_DN))
a = ezdxf.readfile(OUT).audit()
print('AUDIT errors=%d fixes=%d' % (len(a.errors), len(a.fixes)))
print('출력:', OUT)
