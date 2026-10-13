# -*- coding: utf-8 -*-
# SAFE34 폭(거리2) 신축 v5 — 비대칭 신축:
#   오른쪽 그립(END) = 오른쪽 레일에 붙은 연결요소(가로 바/대각선)가 신축, 나머지 오른쪽 것들 통째 이동
#   왼쪽 그립(BASE) = 왼쪽 레일에 붙은 연결요소(대각선 램프)가 신축, 중간 레일은 고정
#   seam 규칙: END = 최우측 연결컬럼 관통 (컬럼좌단 < seam < min(컬럼우단, 캡우단))
#              BASE = 최좌측 연결컬럼 관통 (max(컬럼좌단, 캡좌단) < seam < 컬럼우단)
#   + 선택셋/spec 프레임 완전일치 재생성, 파라미터 음수 140 교정 (v4에서 계승)
import ezdxf, math
from collections import defaultdict

SRC = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_2LANE_BASE_FOLLOW.dxf'
OUT = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v5.dxf'

# ── 지오메트리 수집 ──
doc = ezdxf.readfile(SRC)
geo = {}; blk_order = {}
blk_conn = defaultdict(set)   # 연결 컬럼: throat 바 + 대각선 (minx,maxx)
blk_capL = defaultdict(list); blk_capR = defaultdict(list)
for b in doc.blocks:
    if not b.name.startswith('rail34_'): continue
    order = []
    for e in b:
        h = e.dxf.handle
        if e.dxftype() == 'LINE':
            s, en = e.dxf.start, e.dxf.end
            g = dict(kind='LINE', pts=[(s.x, s.y), (en.x, en.y)], blk=b.name)
            geo[h] = g; order.append(h)
            x0, x1 = min(s.x, en.x), max(s.x, en.x)
            if abs(s.y-en.y) < 1:
                if x1-x0 < 600: blk_conn[b.name].add((round(x0, 1), round(x1, 1)))     # throat 바
                else: blk_capL[b.name].append(x0); blk_capR[b.name].append(x1)          # 캡 바
            elif abs(s.x-en.x) >= 1:
                blk_conn[b.name].add((round(x0, 1), round(x1, 1)))                       # 대각선
        elif e.dxftype() == 'ARC':
            c = e.dxf.center; r = e.dxf.radius
            a0 = math.radians(e.dxf.start_angle); a1 = math.radians(e.dxf.end_angle)
            g = dict(kind='ARC',
                     pts=[(c.x+r*math.cos(a0), c.y+r*math.sin(a0)),
                          (c.x+r*math.cos(a1), c.y+r*math.sin(a1))], blk=b.name)
            if a1 < a0: a1 += 2*math.pi
            am = (a0+a1)/2
            g['mid'] = (c.x+r*math.cos(am), c.y+r*math.sin(am))
            geo[h] = g; order.append(h)
    blk_order[b.name] = order

def seam_for(blk, is_end):
    cols = sorted(blk_conn[blk], key=lambda c: (c[0]+c[1])/2)
    if not cols: return None
    if is_end:
        col = cols[-1]
        lo = col[0]
        hi = min([col[1]]+([min(x for x in blk_capR[blk])] if blk_capR[blk] else []))
    else:
        col = cols[0]
        lo = max([col[0]]+([max(x for x in blk_capL[blk])] if blk_capL[blk] else []))
        hi = col[1]
    if lo >= hi:
        print('경고: %s %s 구간역전 lo=%.0f hi=%.0f → 컬럼중앙 사용' % (blk, 'END' if is_end else 'BASE', lo, hi))
        return (col[0]+col[1])/2
    return (lo+hi)/2

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

# ── 파라미터 노드 맵: (graph핸들, 노드id) → 이름 ──
pnode = {}
for T in ents:
    if cs(T[0][1]) != 'BLOCKLINEARPARAMETER': continue
    own = (gv(T, '330') or [''])[0]
    nid = None
    for i, (c, v) in enumerate(T):
        if cs(c) == '100' and cs(v) == 'AcDbEvalExpr':
            for jj in range(i, min(i+5, len(T))):
                if cs(T[jj][0]) == '90': nid = cs(T[jj][1]); break
            break
    nm = (gv(T, '305') or [''])[0]
    if own and nid: pnode[(own, nid)] = nm

# ── 폭 신축 재생성 (구동 파라미터가 거리2 인 STRETCH만) ──
summary = []; cross_warn = 0
for T in ents:
    if cs(T[0][1]) != 'BLOCKSTRETCHACTION': continue
    direction = (gv(T, '301') or [''])[0]
    if direction not in ('EndXDelta', 'BaseXDelta'): continue
    tgts = gv(T, '331')
    hit = [x for x in tgts if x in geo]
    if not hit: continue
    # 구동 파라미터 판별: AcDbBlockStretchAction 이후 첫 92 = 구동 노드id
    own = (gv(T, '330') or [''])[0]
    i_s = next((i for i in range(len(T)) if cs(T[i][0]) == '100' and cs(T[i][1]) == 'AcDbBlockStretchAction'), -1)
    d92 = next((cs(T[i][1]) for i in range(i_s, len(T)) if cs(T[i][0]) == '92'), None)
    if pnode.get((own, d92)) != '거리2': continue
    blk = geo[hit[0]]['blk']
    is_end = direction == 'EndXDelta'
    seam = seam_for(blk, is_end)
    if seam is None: continue

    def find(pred, st=0):
        for i in range(st, len(T)):
            if pred(T[i]): return i
        return -1
    i_str = find(lambda t: cs(t[0]) == '100' and cs(t[1]) == 'AcDbBlockStretchAction')
    i72 = find(lambda t: cs(t[0]) == '72', i_str)
    idx1011 = [i for i in range(i72, min(i72+9, len(T))) if cs(T[i][0]) == '1011'][:2]
    idx1021 = [i for i in range(i72, min(i72+9, len(T))) if cs(T[i][0]) == '1021'][:2]
    xs = [(i, float(cs(T[i][1]))) for i in idx1011]
    ys = [float(cs(T[i][1])) for i in idx1021]
    ti = min(xs, key=lambda t: t[1])[0] if is_end else max(xs, key=lambda t: t[1])[0]
    ov = T[ti][1]; lead = ov[:len(ov)-len(ov.lstrip())]; cr = '\r' if ov.endswith('\r') else ''
    T[ti] = (T[ti][0], lead+repr(seam)+cr)
    fx = sorted([seam if i == ti else v for i, v in xs]); fy = sorted(ys)
    frame = (fx[0], fx[1], fy[0], fy[1])

    def inside(p): return frame[0] <= p[0] <= frame[1] and frame[2] <= p[1] <= frame[3]
    def spec_for(h):
        g = geo[h]; ins = [inside(p) for p in g['pts']]; n = sum(ins)
        if g['kind'] == 'ARC':
            if n == 2: return (2, [0, 1])
            if n == 1:
                global cross_warn; cross_warn += 1
                return (2, [0, 1]) if inside(g['mid']) else None
            return None
        if n == 0: return None
        if n == 2: return (2, [0, 1])
        return (1, [0] if ins[0] else [1])

    i_act = find(lambda t: cs(t[0]) == '100' and cs(t[1]) == 'AcDbBlockAction')
    i71 = find(lambda t: cs(t[0]) == '71', i_act)
    j = i71+1; sel = []
    while j < len(T) and cs(T[j][0]) == '330': sel.append(T[j]); j += 1
    sel_end = j
    i73 = find(lambda t: cs(t[0]) == '73', i_str)
    k = i73+1; specs = []
    while k < len(T) and cs(T[k][0]) == '331':
        grp = [T[k]]; h = cs(T[k][1]); k += 1
        n = int(cs(T[k][1])); grp.append(T[k]); k += 1
        for _ in range(n): grp.append(T[k]); k += 1
        specs.append((h, grp))
    spec_end = k
    spec_map = dict(specs)

    c330 = sel[0]; code_lead = c330[0][:len(c330[0])-len(c330[0].lstrip())]
    ccr = '\r' if c330[0].endswith('\r') else ''
    v0 = c330[1]; val_lead = v0[:len(v0)-len(v0.lstrip())]; vcr = '\r' if v0.endswith('\r') else ''
    def P(code, val): return (code_lead+code+ccr, val_lead+str(val)+vcr)

    kept_sel = []; kept_spec = []; dropped = 0; added = 0
    orig_members = [cs(t[1]) for t in sel]
    for h in orig_members:
        if h not in geo:
            kept_sel.append(P('330', h))
            kept_spec.append(spec_map.get(h, [P('331', h), P('74', '0')]))
            continue
        sp = spec_for(h)
        if sp is None: dropped += 1; continue
        n, idxs = sp
        kept_sel.append(P('330', h))
        kept_spec.append([P('331', h), P('74', n)]+[P('94', i) for i in idxs])
    have = set(orig_members)
    for h in blk_order[blk]:
        if h in have: continue
        sp = spec_for(h)
        if sp is None: continue
        n, idxs = sp
        kept_sel.append(P('330', h))
        kept_spec.append([P('331', h), P('74', n)]+[P('94', i) for i in idxs])
        added += 1

    def bump(i, num):
        v = T[i][1]; ld = v[:len(v)-len(v.lstrip())]; c2 = '\r' if v.endswith('\r') else ''
        T[i] = (T[i][0], ld+str(num)+c2)
    new = T[:i71]; new.append(T[i71]); new += kept_sel
    new += T[sel_end:i73]; new.append(T[i73])
    for g in kept_spec: new += g
    new += T[spec_end:]
    T[:] = new
    bump(find(lambda t: cs(t[0]) == '71', 0), len(kept_sel))
    bump(find(lambda t: cs(t[0]) == '73', 0), len(kept_spec))
    lab = (gv(T, '300') or ['?'])[0]
    summary.append('%s %s(%s) seam=%.0f 멤버%d(+%d/-%d)' % (blk, lab, 'END' if is_end else 'BASE', seam, len(kept_sel), added, dropped))

# ── 거리2 파라미터 음수 140 교정 ──
fixed_param = 0
for T in ents:
    if cs(T[0][1]) != 'BLOCKLINEARPARAMETER': continue
    if (gv(T, '305') or [''])[0] != '거리2': continue
    bx = gv(T, '1010'); ex_ = gv(T, '1011')
    if not bx or not ex_: continue
    bxv = float(bx[0])
    if not (0 <= bxv <= 60000): continue
    dist = abs(float(ex_[0])-bxv)
    for i, (c, v) in enumerate(T):
        if cs(c) == '140' and float(cs(v)) < 0:
            lead = v[:len(v)-len(v.lstrip())]; cr = '\r' if v.endswith('\r') else ''
            T[i] = (c, lead+repr(dist)+cr); fixed_param += 1

out = []
for T in ents:
    for c, v in T: out.append(c); out.append(v)
open(OUT, 'w', encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('폭 신축 %d개 재배선 (경계걸친 호 %d개):' % (len(summary), cross_warn))
for s in summary: print('  '+s)
print('거리2 파라미터 음수 140 교정: %d개' % fixed_param)
a = ezdxf.readfile(OUT).audit()
print('AUDIT errors=%d fixes=%d' % (len(a.errors), len(a.fixes)))
print('출력:', OUT)
