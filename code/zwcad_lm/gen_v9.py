# -*- coding: utf-8 -*-
# v9: 전 블록(16개) 정션 균등 재배치 + 아치/보타이 대칭화. 배선은 v6b(top_01 방식) 그대로.
#   - 대각선 컬럼별: 첫/끝 고정, 가운데 균등 간격 (그룹=대각+끝점공유 호, 수직이동→접선보존)
#   - 짧은 바 피처(아치/보타이): 최외곽 쌍을 레일 중심 대칭으로, 홀수면 가운데 피처는 중심으로
import ezdxf, math
from collections import defaultdict

SRC = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v6b.dxf'
OUT = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v9.dxf'

doc = ezdxf.readfile(SRC)
moves = {}   # handle -> dy

for b in doc.blocks:
    if not b.name.startswith('rail34_'): continue
    G = {}
    rail_ys = []
    for e in b:
        h = e.dxf.handle
        if e.dxftype() == 'LINE':
            s, en = e.dxf.start, e.dxf.end
            G[h] = dict(kind='LINE', pts=[(s.x, s.y), (en.x, en.y)])
            if abs(s.x-en.x) < 1 and abs(s.y-en.y) > 30000: rail_ys += [s.y, en.y]
        elif e.dxftype() == 'ARC':
            c = e.dxf.center; r = e.dxf.radius
            a0 = math.radians(e.dxf.start_angle); a1 = math.radians(e.dxf.end_angle)
            G[h] = dict(kind='ARC', pts=[(c.x+r*math.cos(a0), c.y+r*math.sin(a0)),
                                         (c.x+r*math.cos(a1), c.y+r*math.sin(a1))])
    if not rail_ys: continue
    rail_c = (min(rail_ys)+max(rail_ys))/2
    def touches(g1, g2, tol=0.5):
        return any(math.hypot(p[0]-q[0], p[1]-q[1]) < tol for p in g1['pts'] for q in g2['pts'])
    def group_of(h):
        return [h] + [h2 for h2, g2 in G.items() if g2['kind'] == 'ARC' and touches(G[h], g2)]

    # 1) 대각선: x-컬럼 클러스터별 균등화
    diags = [(h, g) for h, g in G.items() if g['kind'] == 'LINE'
             and abs(g['pts'][0][0]-g['pts'][1][0]) >= 1 and abs(g['pts'][0][1]-g['pts'][1][1]) >= 1]
    cols = defaultdict(list)
    for h, g in diags:
        cols[round(min(p[0] for p in g['pts']), -2)].append((h, g))
    blocklog = []
    for cx, lst in sorted(cols.items()):
        lst.sort(key=lambda x: min(p[1] for p in x[1]['pts']))
        ys = [min(p[1] for p in g['pts']) for h, g in lst]
        if len(lst) < 3: continue
        step = (ys[-1]-ys[0])/(len(lst)-1)
        for i, ((h, g), y0) in enumerate(zip(lst, ys)):
            dy = (ys[0]+i*step) - y0
            if abs(dy) < 0.01: continue
            for hh in group_of(h): moves[hh] = dy
        gaps0 = [round(ys[i+1]-ys[i]) for i in range(len(ys)-1)]
        blocklog.append('대각컬럼x%d: %s → 균등 %.1f' % (cx, gaps0, step))

    # 2) 짧은 바 피처(아치/보타이): y근접 클러스터 → 대칭화
    bars = [(h, g) for h, g in G.items() if g['kind'] == 'LINE'
            and abs(g['pts'][0][1]-g['pts'][1][1]) < 1 and abs(g['pts'][0][0]-g['pts'][1][0]) < 600]
    bars.sort(key=lambda x: x[1]['pts'][0][1])
    feats = []
    for h, g in bars:
        y = g['pts'][0][1]
        if feats and y - feats[-1]['ys'][-1] < 2000:
            feats[-1]['ys'].append(y); feats[-1]['hs'].append(h)
        else:
            feats.append(dict(ys=[y], hs=[h]))
    if len(feats) >= 2:
        centers = [sum(f['ys'])/len(f['ys']) for f in feats]
        d_lo = rail_c-centers[0]; d_hi = centers[-1]-rail_c
        d_sym = (d_lo+d_hi)/2
        tgt = {0: rail_c-d_sym, len(feats)-1: rail_c+d_sym}
        if len(feats) % 2 == 1: tgt[len(feats)//2] = rail_c
        for fi, t in tgt.items():
            dy = t-centers[fi]
            if abs(dy) < 0.01: continue
            grp = set()
            for h in feats[fi]['hs']:
                for hh in group_of(h): grp.add(hh)
            for hh in grp:
                moves[hh] = moves.get(hh, 0)+dy
            blocklog.append('바피처%d: y%.0f → %.0f (Δ%+.0f)' % (fi, centers[fi], t, dy))
    if blocklog:
        print('%s:' % b.name)
        for s in blocklog: print('   '+s)

print('이동 대상 총 %d개' % len(moves))

# ── raw 패치 ──
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
patched = 0
for T in ents:
    t = cs(T[0][1])
    if t not in ('LINE', 'ARC'): continue
    h = next((cs(v) for c, v in T if cs(c) == '5'), None)
    if h not in moves: continue
    dy = moves[h]
    for i, (c, v) in enumerate(T):
        code = cs(c)
        if (t == 'LINE' and code in ('20', '21')) or (t == 'ARC' and code == '20'):
            lead = v[:len(v)-len(v.lstrip())]; cr = '\r' if v.endswith('\r') else ''
            T[i] = (c, lead+repr(float(cs(v))+dy)+cr)
    patched += 1
out = []
for T in ents:
    for c, v in T: out.append(c); out.append(v)
open(OUT, 'w', encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('엔티티 %d개 이동' % patched)
a = ezdxf.readfile(OUT).audit()
print('AUDIT errors=%d fixes=%d' % (len(a.errors), len(a.fixes)))
print('출력:', OUT)
