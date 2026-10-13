# -*- coding: utf-8 -*-
# SAFE34 폭(거리2) 신축 전면 재생성 — rail2_final과 동형 구조로.
#  1) 프레임 seam을 throat 바 중앙으로 (바를 관통)
#  2) 선택셋+spec을 프레임과 완전 일치로 재생성:
#     - 끝점 2개 프레임 안 = 74=2 통째이동 (레일·호·램프)
#     - 끝점 1개 안 = 74=1 그 점만 신축 (throat 바·캡 바)
#     - 끝점 0개 = 액션에서 제외
#     → 바만 신축, 호는 직선에 붙은 채 통째 이동, 중간 직선은 왼쪽과 함께 이동
#  3) 파라미터(비지오) 멤버는 그대로 보존 (base-follow 유지)
#  4) 거리2 파라미터 저장값 140이 음수인 것 교정
import ezdxf, math
from collections import defaultdict

SRC = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_2LANE_BASE_FOLLOW.dxf'
OUT = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v4.dxf'

# ── 지오메트리 수집 ──
doc = ezdxf.readfile(SRC)
geo = {}          # handle -> dict(kind, pts, blk, throat?)
blk_order = {}    # blk -> [handles 순서]
for b in doc.blocks:
    if not b.name.startswith('rail34_'): continue
    order = []
    for e in b:
        h = e.dxf.handle
        if e.dxftype() == 'LINE':
            s, en = e.dxf.start, e.dxf.end
            g = dict(kind='LINE', pts=[(s.x, s.y), (en.x, en.y)], blk=b.name)
            if abs(s.y-en.y) < 1 and abs(s.x-en.x) < 600: g['throat'] = True
            geo[h] = g; order.append(h)
        elif e.dxftype() == 'ARC':
            c = e.dxf.center; r = e.dxf.radius
            a0 = math.radians(e.dxf.start_angle); a1 = math.radians(e.dxf.end_angle)
            geo[h] = dict(kind='ARC',
                          pts=[(c.x+r*math.cos(a0), c.y+r*math.sin(a0)),
                               (c.x+r*math.cos(a1), c.y+r*math.sin(a1))],
                          mid=None, blk=b.name)
            if a1 < a0: a1 += 2*math.pi
            am = (a0+a1)/2
            geo[h]['mid'] = (c.x+r*math.cos(am), c.y+r*math.sin(am))
            order.append(h)
    blk_order[b.name] = order
throat = set(h for h, g in geo.items() if g.get('throat'))
# 블록별 throat 컬럼 (x범위 클러스터)
blk_cols = defaultdict(set)
for h in throat:
    p = geo[h]['pts']
    blk_cols[geo[h]['blk']].add((round(min(p[0][0], p[1][0]), 1), round(max(p[0][0], p[1][0]), 1)))
for blk, cs in blk_cols.items():
    if len(cs) > 1: print('주의: %s throat 컬럼 %d개 %s' % (blk, len(cs), sorted(cs)))

# ── raw 파싱 (포맷 보존) ──
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

def gv(T, code):
    return [cs(v) for c, v in T if cs(c) == code]

# ── 폭 신축 재생성 ──
summary = []
for T in ents:
    if cs(T[0][1]) != 'BLOCKSTRETCHACTION': continue
    tgts = gv(T, '331')
    hit = [x for x in tgts if x in throat]
    if not hit: continue
    blk = geo[hit[0]]['blk']
    direction = (gv(T, '301') or [''])[0]   # EndXDelta / BaseXDelta
    is_end = direction == 'EndXDelta'
    cols = sorted(blk_cols[blk], key=lambda c: (c[0]+c[1])/2)
    col = cols[-1] if is_end else cols[0]
    seam = (col[0]+col[1])/2

    def find(pred, st=0):
        for i in range(st, len(T)):
            if pred(T[i]): return i
        return -1
    # 프레임: 72 뒤 1011/1021 두 쌍
    i_str = find(lambda t: cs(t[0]) == '100' and cs(t[1]) == 'AcDbBlockStretchAction')
    i72 = find(lambda t: cs(t[0]) == '72', i_str)
    idx1011 = [i for i in range(i72, min(i72+9, len(T))) if cs(T[i][0]) == '1011'][:2]
    idx1021 = [i for i in range(i72, min(i72+9, len(T))) if cs(T[i][0]) == '1021'][:2]
    xs = [(i, float(cs(T[i][1]))) for i in idx1011]
    ys = [float(cs(T[i][1])) for i in idx1021]
    ti = min(xs, key=lambda t: t[1])[0] if is_end else max(xs, key=lambda t: t[1])[0]
    ov = T[ti][1]; lead = ov[:len(ov)-len(ov.lstrip())]; cr = '\r' if ov.endswith('\r') else ''
    T[ti] = (T[ti][0], lead+repr(seam)+cr)
    fx = sorted([seam if i == ti else v for i, v in xs])
    fy = sorted(ys)
    frame = (fx[0], fx[1], fy[0], fy[1])

    def inside(p):
        return frame[0] <= p[0] <= frame[1] and frame[2] <= p[1] <= frame[3]
    def spec_for(h):
        g = geo[h]; ins = [inside(p) for p in g['pts']]; n = sum(ins)
        if g['kind'] == 'ARC':
            if n == 2: return (2, [0, 1])
            if n == 1:   # 경계 걸친 호: 중점 위치로 결정
                return (2, [0, 1]) if inside(g['mid']) else None
            return None
        if n == 0: return None
        if n == 2: return (2, [0, 1])
        return (1, [0] if ins[0] else [1])

    # 선택셋(71/330)과 spec(73/331) 슬라이스
    i_act = find(lambda t: cs(t[0]) == '100' and cs(t[1]) == 'AcDbBlockAction')
    i71 = find(lambda t: cs(t[0]) == '71', i_act)
    j = i71+1; sel = []
    while j < len(T) and cs(T[j][0]) == '330': sel.append(T[j]); j += 1
    sel_end = j
    i73 = find(lambda t: cs(t[0]) == '73', i_str)
    k = i73+1; specs = []   # (handle, [원본 태그들])
    while k < len(T) and cs(T[k][0]) == '331':
        grp = [T[k]]; h = cs(T[k][1]); k += 1
        n = int(cs(T[k][1])); grp.append(T[k]); k += 1
        for _ in range(n): grp.append(T[k]); k += 1
        specs.append((h, grp))
    spec_end = k
    spec_map = dict(specs)

    # 포맷 리드 샘플
    c330 = sel[0]; code_lead = c330[0][:len(c330[0])-len(c330[0].lstrip())]
    ccr = '\r' if c330[0].endswith('\r') else ''
    v0 = c330[1]; val_lead = v0[:len(v0)-len(v0.lstrip())]; vcr = '\r' if v0.endswith('\r') else ''
    def P(code, val): return (code_lead+code+ccr, val_lead+str(val)+vcr)

    kept_sel = []; kept_spec = []; dropped = []; changed = 0
    orig_members = [cs(t[1]) for t in sel]
    for h in orig_members:
        if h not in geo:   # 파라미터 등 비지오 → 그대로 보존
            kept_sel.append(P('330', h))
            kept_spec.append(spec_map.get(h, [P('331', h), P('74', '0')]))
            continue
        sp = spec_for(h)
        if sp is None: dropped.append(h); continue
        n, idxs = sp
        old = spec_map.get(h)
        newg = [P('331', h), P('74', n)]+[P('94', i) for i in idxs]
        if old is None or [cs(v) for c, v in old] != [cs(v) for c, v in newg]: changed += 1
        kept_sel.append(P('330', h)); kept_spec.append(newg)
    added = []
    have = set(orig_members)
    for h in blk_order[blk]:
        if h in have: continue
        sp = spec_for(h)
        if sp is None: continue
        n, idxs = sp
        kept_sel.append(P('330', h))
        kept_spec.append([P('331', h), P('74', n)]+[P('94', i) for i in idxs])
        added.append(h)
    # 바 sanity: 이 액션에서 바는 정확히 한 점, 움직이는 쪽 끝
    for h in throat:
        if geo[h]['blk'] != blk: continue
        sp = spec_for(h)
        if sp and sp[0] == 1:
            p = geo[h]['pts']; mi = sp[1][0]
            side_ok = (p[mi][0] > seam) if is_end else (p[mi][0] < seam)
            assert side_ok, '바 %s 이동점이 잘못된 쪽' % h

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
    summary.append('%s %s(%s) seam=%.0f 멤버%d(추가%d 제외%d spec변경%d)'
                   % (blk, lab, 'END' if is_end else 'BASE', seam, len(kept_sel), len(added), len(dropped), changed))

# ── 거리2 파라미터 음수값 교정 ──
fixed_param = 0
for T in ents:
    if cs(T[0][1]) != 'BLOCKLINEARPARAMETER': continue
    if (gv(T, '305') or [''])[0] != '거리2': continue
    bx = gv(T, '1010'); ex_ = gv(T, '1011')
    if not bx or not ex_: continue
    bxv = float(bx[0])
    if not (0 <= bxv <= 60000): continue   # rail34 로컬좌표만 (2rail 제외)
    dist = abs(float(ex_[0])-bxv)
    for i, (c, v) in enumerate(T):
        if cs(c) == '140' and float(cs(v)) < 0:
            lead = v[:len(v)-len(v.lstrip())]; cr = '\r' if v.endswith('\r') else ''
            T[i] = (c, lead+repr(dist)+cr); fixed_param += 1

out = []
for T in ents:
    for c, v in T: out.append(c); out.append(v)
open(OUT, 'w', encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('폭 신축 %d개 재생성:' % len(summary))
for s in summary: print('  '+s)
print('거리2 파라미터 음수 140 교정: %d개' % fixed_param)
a = ezdxf.readfile(OUT).audit()
print('AUDIT errors=%d fixes=%d' % (len(a.errors), len(a.fixes)))
print('출력:', OUT)
