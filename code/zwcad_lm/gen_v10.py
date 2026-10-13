# -*- coding: utf-8 -*-
# v10: 왼쪽 레일 접점 완전 균등(i/(n+1), 끝 여백 포함) + 배율 연쇄 갱신.
#   스테이션 = END구동 분수배율 MOVE 액션의 선택셋(지오) 그룹.
#   대각선 포함 스테이션만 재배치(보타이 등은 유지). 스테이션째 이동 → 아치 동반, 페어 유지.
#   중간레일 끝점(스테이션 이동에 붙은 것) 이동 + 해당 분수 STRETCH 배율 보정.
#   모든 관련 배율: new = old ± Δ/60000 (END:+, BASE:-).
import ezdxf, math
from collections import defaultdict

SRC = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v6b.dxf'
OUT = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\SAFE34_v15.dxf'
L = 60000.0

doc = ezdxf.readfile(SRC)
geo = {}; blkof = {}
blk_rails = defaultdict(list)      # 긴 수직(바깥 레일)
blk_inner = defaultdict(list)      # 짧은 수직(중간/내부 레일)
for b in doc.blocks:
    if not b.name.startswith('rail34_'): continue
    for e in b:
        h = e.dxf.handle; blkof[h] = b.name
        if e.dxftype() == 'LINE':
            s, en = e.dxf.start, e.dxf.end
            geo[h] = dict(kind='LINE', pts=[(s.x, s.y), (en.x, en.y)])
            if abs(s.x-en.x) < 1 and abs(s.y-en.y) > 3000:
                (blk_rails if abs(s.y-en.y) > 57000 else blk_inner)[b.name].append(h)
        elif e.dxftype() == 'ARC':
            c = e.dxf.center; r = e.dxf.radius
            a0 = math.radians(e.dxf.start_angle); a1 = math.radians(e.dxf.end_angle)
            geo[h] = dict(kind='ARC', pts=[(c.x+r*math.cos(a0), c.y+r*math.sin(a0)),
                                           (c.x+r*math.cos(a1), c.y+r*math.sin(a1))])

def is_diag(h):
    g = geo[h]
    return g['kind'] == 'LINE' and abs(g['pts'][0][0]-g['pts'][1][0]) >= 1 and abs(g['pts'][0][1]-g['pts'][1][1]) >= 1

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
def setval(T, i, val):
    v = T[i][1]; ld = v[:len(v)-len(v.lstrip())]; cr = '\r' if v.endswith('\r') else ''
    T[i] = (T[i][0], ld+str(val)+cr)

# ── 스테이션 수집: END구동 분수 MOVE의 지오 선택셋 ──
stations = defaultdict(list)   # blk -> [dict(members, mult_end, T_end, T_base)]
movers = []                    # (T, side, geo_members)  side: +1 END / -1 BASE
for T in ents:
    if cs(T[0][1]) != 'BLOCKMOVEACTION': continue
    m = gv(T, '140')
    if not m: continue
    mv = float(m[0])
    if not (0.001 < mv < 0.999): continue
    sel = gv(T, '330')[1:]
    gm = [x for x in sel if x in geo]
    if not gm: continue
    side = +1 if (gv(T, '301') or [''])[0].startswith('End') else -1
    movers.append((T, side, gm))
    if side == +1:
        stations[blkof[gm[0]]].append(dict(members=gm, mult=mv, T=T))

# ── 블록별 재배치 계산 ──
moves = {}          # handle -> dy
endpoint_moves = [] # (handle, point_idx, dy, station)  내부레일 끝점
mem2st = {}         # 멤버 handle -> 스테이션 dict
for blk, sts in sorted(stations.items()):
    rails = blk_rails[blk]
    lrx = min(min(p[0] for p in geo[h]['pts']) for h in rails)
    rys = [p[1] for h in rails for p in geo[h]['pts']]
    ylo, yhi = min(rys)+900, max(rys)-900     # 캡 코너 접점 사이 스팬
    # 대각선 포함 스테이션
    jst = [s for s in sts if any(is_diag(h) for h in s['members'])]
    # 접점(왼쪽 레일 위 호 끝점) 기준 y
    for s in jst:
        ts = [p[1] for h in s['members'] if geo[h]['kind'] == 'ARC'
              for p in geo[h]['pts'] if abs(p[0]-lrx) < 0.5]
        s['tan'] = min(ts) if ts else None
    jst = [s for s in jst if s['tan'] is not None]
    jst.sort(key=lambda s: s['tan'])
    n = len(jst)
    if n < 2: continue
    S = yhi-ylo
    # 모서리 스냅 측정 보정: 캡바 오프셋 450 vs 꺾임점 오프셋 318.2 → 끝여백 m = 중간빨강 c - 131.8
    ECAP = 450.0; EELB = 450.0*math.sin(math.radians(45))
    if n % 2 == 0:
        # 교대 패턴: 빨강(끝여백 m, 쌍 사이 c) / 초록 g(쌍 내부). 모서리 측정으로 m+ECAP+EELB == c+2*EELB
        greens = [jst[i+1]['tan']-jst[i]['tan'] for i in range(0, n, 2)]
        g = sum(greens)/len(greens)
        npair = n//2
        c = (S - npair*g + 2*(ECAP-EELB)) / (npair+1)
        m = c - (ECAP-EELB)
        targets = []
        y = ylo + m - c   # 첫 스텝에서 c 더해지므로 보정
        for i in range(n):
            y += c if i % 2 == 0 else g
            targets.append(y)
        r_corner = m + ECAP + EELB
    else:
        targets = [ylo + (i+1)*S/(n+1) for i in range(n)]
        m = c = g = S/(n+1); r_corner = 0
    log = []
    for s, tgt in zip(jst, targets):
        d = tgt - s['tan']
        s['dy'] = d; s['tgt'] = tgt
        for h in s['members']: moves[h] = d
        log.append('%+.0f' % d)
    print('%s: 접점 %d개 — 끝여백 m=%.1f 중간 c=%.1f 초록 g=%.1f (모서리측정 빨강 %.1f 통일), Δ=[%s]'
          % (blk, n, m, c, g, r_corner, ','.join(log)))
    # ★ 세로 신축 시 구간 비례 성장: 새 배율 = (모서리y − 아래캡바) / 캡바스팬
    capb = min(rys)+450; capt = max(rys)-450; span = capt-capb
    for s in jst:
        dg0 = sorted([h for h in s['members'] if is_diag(h)],
                     key=lambda h: min(p[0] for p in geo[h]['pts']))[0]
        pts = geo[dg0]['pts']
        Lp, Rp = (pts[0], pts[1]) if pts[0][0] < pts[1][0] else (pts[1], pts[0])
        elbow = s['tgt'] + (EELB if Rp[1] > Lp[1] else -EELB)
        s['mult_new'] = (elbow-capb)/span
    for s in sts:      # 비정션 스테이션(보타이 등): 멤버 평균 y 기준
        if 'mult_new' in s or not s['members']: continue
        ys2 = [p[1] for h in s['members'] if h in geo for p in geo[h]['pts']]
        if not ys2: continue
        ref = sum(ys2)/len(ys2) + moves.get(s['members'][0], 0.0)
        s['mult_new'] = (ref-capb)/span
    for s in sts:
        for h in s.get('members', []): mem2st[h] = s
    # 아치(짧은 바 피처) 대칭 보정: 스테이션 이동 후 잔여 비대칭 δ 제거
    def touch2(g1, g2):
        return any(math.hypot(p[0]-q[0], p[1]-q[1]) < 0.5 for p in g1['pts'] for q in g2['pts'])
    bars_f = [(h, geo[h]) for h in geo
              if blkof[h] == blk and geo[h]['kind'] == 'LINE'
              and abs(geo[h]['pts'][0][1]-geo[h]['pts'][1][1]) < 1
              and abs(geo[h]['pts'][0][0]-geo[h]['pts'][1][0]) < 600]
    bars_f.sort(key=lambda x: x[1]['pts'][0][1])
    feats = []
    for h, g in bars_f:
        y = g['pts'][0][1]
        if feats and y-feats[-1]['ys'][-1] < 2000: feats[-1]['ys'].append(y); feats[-1]['hs'].append(h)
        else: feats.append(dict(ys=[y], hs=[h]))
    if len(feats) >= 2:
        rc = (min(rys)+max(rys))/2
        c0 = sum(feats[0]['ys'])/len(feats[0]['ys']) + moves.get(feats[0]['hs'][0], 0.0)
        c1 = sum(feats[-1]['ys'])/len(feats[-1]['ys']) + moves.get(feats[-1]['hs'][0], 0.0)
        dsym = ((rc-c0)+(c1-rc))/2
        for fi, tgt in ((0, rc-dsym), (len(feats)-1, rc+dsym)):
            cc = c0 if fi == 0 else c1
            dd = tgt-cc
            if abs(dd) < 0.5: continue
            grp = set()
            for h in feats[fi]['hs']:
                grp.add(h)
                for h2, g2 in geo.items():
                    if blkof[h2] == blk and g2['kind'] == 'ARC' and touch2(geo[h], g2): grp.add(h2)
            for hh in grp: moves[hh] = moves.get(hh, 0.0)+dd
            print('   아치%d 대칭보정 δ=%+.1f' % (fi, dd))
    # 우측 컬럼 스큐 보정: 스테이션 내 2번째 대각선(우측)의 좌측 대비 y오프셋을 중앙값으로 통일
    st_offs = []
    for s in jst:
        dgs = sorted([h for h in s['members'] if is_diag(h)],
                     key=lambda h: min(p[0] for p in geo[h]['pts']))
        if len(dgs) >= 2:
            st_offs.append((s, dgs, min(p[1] for p in geo[dgs[1]]['pts'])-min(p[1] for p in geo[dgs[0]]['pts'])))
    if st_offs:
        offs = sorted(o for _s, _d, o in st_offs)
        med = offs[len(offs)//2]
        for s, dgs, off in st_offs:
            dd = med-off
            if abs(dd) < 0.5: continue
            grp = set([dgs[1]])
            for h2, g2 in geo.items():
                if blkof[h2] == blk and g2['kind'] == 'ARC' and touch2(geo[dgs[1]], g2): grp.add(h2)
            for hh in grp: moves[hh] = moves.get(hh, 0.0)+dd
            print('   우측컬럼 스큐보정 δ=%+.1f (스테이션 tan=%.0f)' % (dd, s['tan']))
    # 내부 레일 끝점: 이동된 엔티티의 옛 끝점과 일치하면 동반 이동 (스테이션 멤버 우선 매칭)
    for h in blk_inner[blk]:
        for pi in (0, 1):
            p = geo[h]['pts'][pi]
            cands = [mh for mh, d in moves.items() if blkof[mh] == blk
                     and any(math.hypot(p[0]-q[0], p[1]-q[1]) < 0.5 for q in geo[mh]['pts'])]
            cands.sort(key=lambda mh: 0 if mh in mem2st else 1)
            if cands:
                mh = cands[0]
                endpoint_moves.append((h, pi, moves[mh], mem2st.get(mh)))

# 내부레일 후퇴구간에 접선으로 붙은 엔티티(U턴 브릿지 등): 끝 스테이션 Δ와 함께 이동
extra2st = {}   # 끝 어셈블리 소속(브릿지 등) handle -> 정션 스테이션
for h, pi, d, _st in endpoint_moves:
    g = geo[h]; blk = blkof[h]
    rx = g['pts'][pi][0]; y_old = g['pts'][pi][1]; y_new = y_old + d
    zlo, zhi = min(y_old, y_new)-1, max(y_old, y_new)+1
    for h2, g2 in geo.items():
        if blkof[h2] != blk: continue
        if g2['kind'] == 'LINE' and abs(g2['pts'][0][0]-g2['pts'][1][0]) < 1 and abs(g2['pts'][0][1]-g2['pts'][1][1]) > 3000: continue
        if any(abs(p[0]-rx) < 0.5 and zlo <= p[1] <= zhi for p in g2['pts']):
            if h2 not in moves: moves[h2] = d
            if _st is not None: extra2st[h2] = _st
# 끝 브릿지 스테이션 배율 = 인접 정션 스테이션 배율 (레일 끝과 같은 속도로 성장해야 부착 유지)
for blk2, sts2 in stations.items():
    for s in sts2:
        if any(is_diag(h) for h in s['members']): continue
        adopt = [extra2st[h] for h in s['members'] if h in extra2st and 'mult_new' in extra2st[h]]
        if adopt:
            s['mult_new'] = adopt[0]['mult_new']
            print('%s 브릿지 스테이션 배율 동기화 → %.4f' % (blk2, s['mult_new']))

# 연쇄(브릿지 등): 이동 안 된 비레일 엔티티가 이동된 것과 끝점 공유하면 같은 Δ (반복)
railset = set(h for v in blk_rails.values() for h in v) | set(h for v in blk_inner.values() for h in v)
changed = True
while changed:
    changed = False
    for h, g in geo.items():
        if h in moves or h in railset: continue
        for mh, d in list(moves.items()):
            if blkof[mh] != blkof[h]: continue
            if any(math.hypot(p[0]-q[0], p[1]-q[1]) < 0.5 for p in g['pts'] for q in geo[mh]['pts']):
                moves[h] = d; changed = True; break
print('이동 엔티티 %d개, 내부레일 끝점 %d개' % (len(moves), len(endpoint_moves)))

# ── 배율 전면 재설정 (세로 신축 시 구간 비례 성장 보장) ──
# 0) 무버 미포함 이동 엔티티(U브릿지 등) → 같은 Δ의 끝 스테이션 무버에 편입
covered = set()
for _T, _s, gm in movers: covered.update(gm)
def append_members(T, handles):
    i_act = next(i for i in range(len(T)) if cs(T[i][0]) == '100' and cs(T[i][1]) == 'AcDbBlockAction')
    i71 = next(i for i in range(i_act, len(T)) if cs(T[i][0]) == '71')
    j = i71+1
    while j < len(T) and cs(T[j][0]) == '330': j += 1
    smp = T[i71+1] if cs(T[i71+1][0]) == '330' else None
    cl = smp[0][:len(smp[0])-len(smp[0].lstrip())]; ccr = '\r' if smp[0].endswith('\r') else ''
    vl = smp[1][:len(smp[1])-len(smp[1].lstrip())]; vcr = '\r' if smp[1].endswith('\r') else ''
    newt = [(cl+'330'+ccr, vl+h+vcr) for h in handles]
    T[j:j] = newt
    setval(T, i71, int(cs(T[i71][1]))+len(handles))
adopted = 0
for h in list(moves):
    if h in covered or h not in geo: continue
    st = None
    for s in stations[blkof[h]]:
        if 'dy' in s and abs(s['dy']-moves[h]) < 0.02: st = s; break
    if st is None: continue
    key = frozenset(st['members'])
    for T, side, gm in movers:
        if frozenset(gm) == key:
            append_members(T, [h])
            gm.append(h)
    st['members'].append(h); mem2st[h] = st; covered.add(h); adopted += 1
print('무버 편입(브릿지 등): %d개' % adopted)
# 1) MOVE 140 = 스테이션 새 배율 (END=m, BASE=1-m)
smap = {}
for blk2, sts2 in stations.items():
    for s in sts2:
        if 'mult_new' in s: smap[frozenset(s['members'])] = s['mult_new']
fixed_m = 0
for T, side, gm in movers:
    mn = smap.get(frozenset(gm))
    if mn is None:
        print('경고: 스테이션 미매칭 무버 %s' % (gv(T, '300') or ['?'])[0]); continue
    val = mn if side > 0 else 1.0-mn
    for i, (c, v) in enumerate(T):
        if cs(c) == '140':
            setval(T, i, repr(val)); fixed_m += 1
            break
# 2) 분수 STRETCH (내부레일 끝점) 140 = 부착 스테이션 배율
ep = {}
for h, pi, d, st in endpoint_moves:
    if st is not None and 'mult_new' in st: ep[(h, pi)] = st['mult_new']
fixed_s = 0
for T in ents:
    if cs(T[0][1]) != 'BLOCKSTRETCHACTION': continue
    m = gv(T, '140')
    if not m: continue
    mv = float(m[0])
    if not (0.001 < mv < 0.999): continue
    side = +1 if (gv(T, '301') or [''])[0].startswith('End') else -1
    k = 0
    while k < len(T) and not (cs(T[k][0]) == '100' and cs(T[k][1]) == 'AcDbBlockStretchAction'): k += 1
    while k < len(T) and cs(T[k][0]) != '73': k += 1
    if k >= len(T): continue
    k += 1; hits = []
    while k < len(T) and cs(T[k][0]) == '331':
        h = cs(T[k][1]); k += 1
        n2 = int(cs(T[k][1])); k += 1
        for _ in range(n2):
            if (h, int(cs(T[k][1]))) in ep: hits.append(ep[(h, int(cs(T[k][1])))])
            k += 1
    if not hits: continue
    assert len(set(round(x, 6) for x in hits)) == 1
    val = hits[0] if side > 0 else 1.0-hits[0]
    for i, (c, v) in enumerate(T):
        if cs(c) == '140':
            setval(T, i, repr(val)); fixed_s += 1
            break
print('배율 재설정: MOVE %d개, STRETCH %d개' % (fixed_m, fixed_s))
# 검산: 구간 비례 성장 (m_{i+1}-m_i == 모서리간격/스팬)
for blk2, sts2 in sorted(stations.items()):
    ms = sorted(s['mult_new'] for s in sts2 if 'mult_new' in s and any(is_diag(h) for h in s['members']))
    if len(ms) < 2: continue
    grow = [round((ms[0])*58200, 1)]+[round((ms[i+1]-ms[i])*58200, 1) for i in range(len(ms)-1)]+[round((1-ms[-1])*58200, 1)]
    R = set(grow[0::2]); G = set(grow[1::2])
    if len(R) != 1 or len(G) != 1: print('★성장 불균등 %s: %s' % (blk2, grow))

# ── 지오메트리 패치 ──
patched = 0
for T in ents:
    t = cs(T[0][1])
    if t not in ('LINE', 'ARC'): continue
    h = next((cs(v) for c, v in T if cs(c) == '5'), None)
    if h is None: continue
    if h in moves:
        d = moves[h]
        for i, (c, v) in enumerate(T):
            code = cs(c)
            if (t == 'LINE' and code in ('20', '21')) or (t == 'ARC' and code == '20'):
                setval(T, i, repr(float(cs(v))+d))
        patched += 1
    else:
        # 내부레일 끝점 부분 이동
        eps = [(pi, d) for (hh, pi, d, _st) in endpoint_moves if hh == h]
        if not eps: continue
        for pi, d in eps:
            code = '20' if pi == 0 else '21'
            for i, (c, v) in enumerate(T):
                if cs(c) == code:
                    setval(T, i, repr(float(cs(v))+d)); break
        patched += 1
out = []
for T in ents:
    for c, v in T: out.append(c); out.append(v)
open(OUT, 'w', encoding='utf-8').write('\n'.join(out)+('\n' if not out[-1].endswith('\n') else ''))
print('지오 패치 %d개' % patched)
a = ezdxf.readfile(OUT).audit()
print('AUDIT errors=%d fixes=%d' % (len(a.errors), len(a.fixes)))
print('출력:', OUT)
