# -*- coding: utf-8 -*-
# v8 지오메트리: rail34_top_02 정션 균등 재배치 (순수 수직 이동, 접선 보존)
#   - 왼쪽 정션 6개(대각+호2): 첫/끝 고정, 가운데 4개를 균등 간격으로
#   - 오른쪽 아치 2개(바+호2): 레일 중심(30000) 기준 대칭으로
#   그룹 식별 = 끝점 공유(대각/바와 끝점이 붙은 호). 출력: SAFE34_v8_geo.dxf
import ezdxf, math
SRC = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v6b.dxf'
OUT = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v8_geo.dxf'
BLK = 'rail34_top_02'

doc = ezdxf.readfile(SRC)
b = doc.blocks.get(BLK)
ents_g = {}
for e in b:
    h = e.dxf.handle
    if e.dxftype() == 'LINE':
        s, en = e.dxf.start, e.dxf.end
        ents_g[h] = dict(kind='LINE', pts=[(s.x, s.y), (en.x, en.y)])
    elif e.dxftype() == 'ARC':
        c = e.dxf.center; r = e.dxf.radius
        a0 = math.radians(e.dxf.start_angle); a1 = math.radians(e.dxf.end_angle)
        ents_g[h] = dict(kind='ARC', cy=c.y,
                         pts=[(c.x+r*math.cos(a0), c.y+r*math.sin(a0)),
                              (c.x+r*math.cos(a1), c.y+r*math.sin(a1))])

def touches(g1, g2, tol=0.5):
    return any(math.hypot(p[0]-q[0], p[1]-q[1]) < tol for p in g1['pts'] for q in g2['pts'])

# 그룹: (기준 y, [핸들들], Δ)
moves = {}   # handle -> dy

# 1) 왼쪽 정션: 대각선 + 붙은 호들
diags = [(h, g) for h, g in ents_g.items() if g['kind'] == 'LINE'
         and abs(g['pts'][0][0]-g['pts'][1][0]) >= 1 and abs(g['pts'][0][1]-g['pts'][1][1]) >= 1]
diags.sort(key=lambda x: min(p[1] for p in x[1]['pts']))
ys = [min(p[1] for p in g['pts']) for h, g in diags]
first, last = ys[0], ys[-1]
step = (last-first)/(len(diags)-1)
targets = [first + i*step for i in range(len(diags))]
print('왼쪽 정션 현재:', [round(y) for y in ys])
print('왼쪽 정션 목표:', [round(t) for t in targets])
for (h, g), y0, t in zip(diags, ys, targets):
    dy = t-y0
    if abs(dy) < 0.01: continue
    grp = [h] + [h2 for h2, g2 in ents_g.items() if g2['kind'] == 'ARC' and touches(g, g2)]
    for hh in grp: moves[hh] = dy
    print('  정션 y%.0f → %.0f (Δ%+.1f), 그룹 %d개' % (y0, t, dy, len(grp)))

# 2) 오른쪽 아치: 짧은 수평 바(370) 중 보타이(중심 30000 근처 쌍) 제외한 것 = 상/하 아치
bars = [(h, g) for h, g in ents_g.items() if g['kind'] == 'LINE'
        and abs(g['pts'][0][1]-g['pts'][1][1]) < 1 and abs(g['pts'][0][0]-g['pts'][1][0]) < 600]
bars.sort(key=lambda x: x[1]['pts'][0][1])
bys = [g['pts'][0][1] for h, g in bars]
rail_c = 30000.0
arch_lo = bars[0]; arch_hi = bars[-1]
d_lo = rail_c - arch_lo[1]['pts'][0][1]; d_hi = arch_hi[1]['pts'][0][1] - rail_c
d_sym = (d_lo+d_hi)/2
for (h, g), tgt in ((arch_lo, rail_c-d_sym), (arch_hi, rail_c+d_sym)):
    dy = tgt - g['pts'][0][1]
    if abs(dy) < 0.01: continue
    grp = [h] + [h2 for h2, g2 in ents_g.items() if g2['kind'] == 'ARC' and touches(g, g2)]
    for hh in grp: moves[hh] = dy
    print('  아치 y%.0f → %.0f (Δ%+.1f), 그룹 %d개' % (g['pts'][0][1], tgt, dy, len(grp)))
print('이동 대상 총 %d개' % len(moves))

# ── raw 패치: 해당 핸들의 y 좌표(20/21) 이동 ──
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
print('엔티티 %d개 이동 완료' % patched)
a = ezdxf.readfile(OUT).audit()
print('AUDIT errors=%d fixes=%d' % (len(a.errors), len(a.fixes)))
print('출력:', OUT)
