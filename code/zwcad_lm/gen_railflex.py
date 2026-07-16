# -*- coding: utf-8 -*-
# gen_railflex.py — 수정된 3/4차선 DXF(모델스페이스 raw LINE/ARC)를 플렉시블 블록으로 재저작.
#   SAFE34_v15(ZWCAD LM 검증본)의 액션 구조를 그대로 재현:
#     거리1(세로): 양끝 그립 + 캡 신축(신축/신축1) + 스테이션 MOVE 쌍(END=f, BASE=1-f)
#               + 내부레일 끝점 분수 STRETCH + 이동거리2(0.5 시트 이동)
#     거리2(폭):   중앙 시임 기준 신축2(END)/신축3(BASE, 거리1 base-follow 포함)
#   스테이션 배수: f=(elbow-capb)/span, elbow=좌측레일 접점 y ± 450·sin45 (v15 공식 그대로)
# 사용:
#   python gen_railflex.py validate   # v15 16블록 회귀검증 (분류기 vs 저장된 액션)
#   python gen_railflex.py generate   # 3차선/4차선_수정.dxf → *_flex.dxf
import os, sys, math, uuid, importlib.util
from collections import defaultdict
import ezdxf

sys.stdout.reconfigure(encoding='utf-8')
CODE = r"C:\Users\User\Desktop\dnd\code"
_spec = importlib.util.spec_from_file_location("cf", os.path.join(CODE, "create_flexible_dxf.py"))
cf = importlib.util.module_from_spec(_spec); sys.modules["cf"] = cf; _spec.loader.exec_module(cf)

V15 = os.path.join(CODE, "zwcad_lm", "dist", "SAFE34_v15.dxf")
DONOR = os.path.join(CODE, "2차선_H분기_직선등간격 (1).dxf")
# (src, 블록 접두어, out, rigid_end_dist, rigid_interp)
#   rigid_end_dist: 캡에서 이 거리 안의 끝 스테이션(진출입 램프)은 캡과 함께 강체 이동
#   (배율 END=1/0, BASE=0/1) → 캡~램프 구간(흰색 마킹)이 신축되지 않음. None=비활성.
#   rigid_interp: 'seg'(3차선, N분기 끝 두 구간 등식) | 'gap'(4차선, 간격 비율 유지)
INPUTS = [
    (r"C:\Users\User\Downloads\3차선_수정.dxf", "rail3", r"C:\Users\User\Downloads\3차선_수정_flex_v6.dxf", 5000.0, 'seg'),
    (r"C:\Users\User\Downloads\4차선_수정.dxf", "rail4", r"C:\Users\User\Downloads\4차선_수정_flex_v6.dxf", 5000.0, 'order'),
]
# 중간 조인트 등간격 재배치(지오메트리 이동) 여부 — 원본 치수 보존 요구로 비활성.
REDISTRIBUTE = False
EELB = 450.0 * math.sin(math.radians(45.0))
TOL = 0.5
# 중앙 H분기(게이트 쌍, 길이고정 대상) 판정 윈도우. 게이트는 중심±800~950.
# 4500이면 4차선의 중앙 정션 쌍(±3836)까지 삼켜 그 사이 간격이 신축 불가가 됨 → 3000.
CENTER_WIN = 3000.0

# ───────────────────────── 지오메트리 모델 ─────────────────────────
def ent_line(x0, y0, x1, y1, layer, handle=None):
    return dict(kind='LINE', pts=[(x0, y0), (x1, y1)], layer=layer, h=handle)

def ent_arc(cx, cy, r, a0, a1, layer, handle=None):
    p0 = (cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0)))
    p1 = (cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1)))
    return dict(kind='ARC', pts=[p0, p1], cx=cx, cy=cy, r=r, a0=a0, a1=a1, layer=layer, h=handle)

def load_ents(container):
    out = []
    for e in container:
        if e.dxftype() == 'LINE':
            s, t = e.dxf.start, e.dxf.end
            out.append(ent_line(s.x, s.y, t.x, t.y, e.dxf.layer, e.dxf.handle))
        elif e.dxftype() == 'ARC':
            c = e.dxf.center
            out.append(ent_arc(c.x, c.y, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle,
                               e.dxf.layer, e.dxf.handle))
    return out

def shift_ent(e, dx, dy):
    e = dict(e)
    e['pts'] = [(x - dx, y - dy) for x, y in e['pts']]
    if e['kind'] == 'ARC':
        e['cx'] -= dx; e['cy'] -= dy
    return e

def is_vert(e):
    return e['kind'] == 'LINE' and abs(e['pts'][0][0] - e['pts'][1][0]) < 1.0 \
        and abs(e['pts'][0][1] - e['pts'][1][1]) >= 1.0

def is_diag(e):
    return e['kind'] == 'LINE' and abs(e['pts'][0][0] - e['pts'][1][0]) >= 1.0 \
        and abs(e['pts'][0][1] - e['pts'][1][1]) >= 1.0

def touch(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1]) < TOL

# ───────────────────────── 클러스터링 ─────────────────────────
def bbox_of(e):
    if e['kind'] == 'LINE':
        xs = [p[0] for p in e['pts']]; ys = [p[1] for p in e['pts']]
        return (min(xs), max(xs), min(ys), max(ys))
    return (e['cx'] - e['r'], e['cx'] + e['r'], e['cy'] - e['r'], e['cy'] + e['r'])

def cluster(ents, margin=1500.0):
    n = len(ents); parent = list(range(n))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    def uni(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    boxes = [bbox_of(e) for e in ents]
    order = sorted(range(n), key=lambda i: boxes[i][0])
    for ii in range(n):
        i = order[ii]
        for jj in range(ii + 1, n):
            j = order[jj]
            if boxes[j][0] > boxes[i][1] + margin: break
            if not (boxes[j][2] > boxes[i][3] + margin or boxes[i][2] > boxes[j][3] + margin):
                uni(i, j)
    groups = defaultdict(list)
    for i in range(n): groups[find(i)].append(i)
    return [[ents[i] for i in g] for g in groups.values()]

# ───────────────────────── 유닛 분류 ─────────────────────────
class Unit:
    pass

def classify_unit(ents, rigid_end_dist=None, rigid_interp='seg', center_fix=None):
    """블록 로컬(또는 임의) 좌표의 엔티티들을 레일/캡/스테이션으로 분류.
    rigid_end_dist: 캡에서 이 거리 안의 끝 스테이션을 캡과 강체 결합(mult_end 1/0).
      None이면 SAFE34_v15 방식(전 구간 위치 비례, 끝 정션 포함 전부 위치 배수).
    rigid_interp: 중간 피처 배수 보간 좌표계 (rigid 모드에서만).
      'seg' = H중점~램프 바깥끝 직선 (3차선: N분기 끝 기준 두 구간 등식 유지)
      'gap' = 구조물 사이 간격 누적 좌표 (간격 균일 신축)
    center_fix: 중앙 H분기(중심±CENTER_WIN) 배수를 0.5로 강제(길이 고정).
      기본값 = rigid 모드에서 True, v15 모드에서도 True 권장(v15 중앙=0.5)."""
    if center_fix is None:
        center_fix = True
    u = Unit()
    ys_all = [p[1] for e in ents for p in e['pts']]
    H = max(ys_all) - min(ys_all)
    verts = [i for i, e in enumerate(ents) if is_vert(e)]
    def dy(i): return abs(ents[i]['pts'][0][1] - ents[i]['pts'][1][1])
    # 외곽 레일 = 캡 호(r450)에 닿는 전고 수직선(H-900). 내부 레일은 스테이션에서 끝남.
    u.fulls = [i for i in verts if dy(i) >= H - 2000.0]
    u.inners = [i for i in verts if 3000.0 < dy(i) < H - 2000.0]
    if len(u.fulls) < 2:
        raise ValueError('외곽 레일 미검출 (fulls=%d)' % len(u.fulls))
    rail_ids = set(u.fulls) | set(u.inners)
    rys = [p[1] for i in u.fulls for p in ents[i]['pts']]
    u.rail_ymin, u.rail_ymax = min(rys), max(rys)
    u.capb = u.rail_ymin + 450.0
    u.capt = u.rail_ymax - 450.0
    u.span = u.capt - u.capb
    u.rail_xs = sorted(ents[i]['pts'][0][0] for i in rail_ids)
    u.ents = ents

    # 비레일 조립체 (끝점 접촉 union-find)
    others = [i for i in range(len(ents)) if i not in rail_ids]
    parent = {i: i for i in others}
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for ii in range(len(others)):
        for jj in range(ii + 1, len(others)):
            a, b = others[ii], others[jj]
            if any(touch(p, q) for p in ents[a]['pts'] for q in ents[b]['pts']):
                ra, rb = find(a), find(b)
                if ra != rb: parent[ra] = rb
    comps_map = defaultdict(list)
    for i in others: comps_map[find(i)].append(i)

    u.cap_top = []; u.cap_bottom = []; u.stations = []
    raw_stations = []
    for members in comps_map.values():
        pys = [p[1] for i in members for p in ents[i]['pts']]
        cy = sum(pys) / len(pys)
        if cy > u.capt - 1000.0:
            u.cap_top.extend(members)
        elif cy < u.capb + 1000.0:
            u.cap_bottom.extend(members)
        else:
            raw_stations.append(dict(members=members, cy=cy))

    # 정션(대각선 보유) 배수: elbow=좌측레일 접점 ± EELB  (v10 공식)
    def station_mult(members):
        """멤버 집합의 (anchor, mult, is_junction). 정션이면 elbow, 아니면 평균 y."""
        diags = [i for i in members if is_diag(ents[i])]
        pys = [p[1] for i in members for p in ents[i]['pts']]
        cy = sum(pys) / len(pys)
        if diags:
            tangs = []
            for i in members:
                if ents[i]['kind'] != 'ARC': continue
                for p in ents[i]['pts']:
                    for rx in u.rail_xs:
                        if abs(p[0] - rx) < TOL:
                            tangs.append((rx, p[1]))
            if tangs:
                lrx = min(rx for rx, _y in tangs)
                tan = min(y for rx, y in tangs if rx == lrx)
                d0 = min(diags, key=lambda i: min(p[0] for p in ents[i]['pts']))
                L, R = sorted(ents[d0]['pts'], key=lambda p: p[0])
                elbow = tan + (EELB if R[1] > L[1] else -EELB)
                return elbow, (elbow - u.capb) / u.span, True
            return cy, (cy - u.capb) / u.span, True
        return cy, None, False

    # y-밴드 중첩(간격<300) 컴포넌트 병합: 같은 높이의 좌/우 정션 쌍, 게이트 in/out 쌍 → 한 스테이션(강체)
    for st in raw_stations:
        pys = [p[1] for i in st['members'] for p in ents[i]['pts']]
        st['ymin'], st['ymax'] = min(pys), max(pys)
    raw_stations.sort(key=lambda s: s['ymin'])
    merged = []
    for st in raw_stations:
        if merged and st['ymin'] <= merged[-1]['ymax'] + 300.0:
            g = merged[-1]
            g['members'] = g['members'] + st['members']
            g['ymax'] = max(g['ymax'], st['ymax'])
        else:
            merged.append(st)
    raw_stations = merged
    for st in raw_stations:
        st['anchor'], st['mult'], st['junction'] = station_mult(st['members'])
        if not st['junction']:
            st['mult'] = None   # 아래에서 채움 (끝점 접속 채택 or 자체 중심)

    # 내부레일 끝점 → 접촉 컴포넌트 매핑
    ep_touch = {}   # (ent_idx, pt_idx) → ('st', station) | ('top'|'bottom', None)
    for i in u.inners:
        for pi in (0, 1):
            p = ents[i]['pts'][pi]
            for st in raw_stations:
                if any(touch(p, q) for j in st['members'] for q in ents[j]['pts']):
                    ep_touch[(i, pi)] = ('st', st); break
            else:
                if any(touch(p, q) for j in u.cap_top for q in ents[j]['pts']):
                    ep_touch[(i, pi)] = ('top', None)
                elif any(touch(p, q) for j in u.cap_bottom for q in ents[j]['pts']):
                    ep_touch[(i, pi)] = ('bottom', None)

    # 비정션(브릿지 등): 내부레일 "끝점 근방(<2500)"에 부착 → 그 끝점 스테이션 배수 채택(부착 유지),
    #                  아니면 자체 중심 (비례 성장)
    for st in raw_stations:
        if st['mult'] is not None: continue
        adopt = None; adopt_src = None; best = 2500.0
        for j in st['members']:
            for q in ents[j]['pts']:
                for i in u.inners:
                    rx = ents[i]['pts'][0][0]
                    ry0, ry1 = sorted(p[1] for p in ents[i]['pts'])
                    if abs(q[0] - rx) < TOL and ry0 - TOL <= q[1] <= ry1 + TOL:
                        for pi in (0, 1):
                            d = abs(q[1] - ents[i]['pts'][pi][1])
                            if d < best:
                                t = ep_touch.get((i, pi))
                                if t and t[0] == 'st' and t[1] is not st and t[1]['mult'] is not None:
                                    best = d; adopt = t[1]['mult']; adopt_src = t[1]
        if adopt is not None:
            st['mult'] = adopt; st['adopted'] = True; st['adopted_from'] = adopt_src
        else:
            pys = [p[1] for i2 in st['members'] for p in ents[i2]['pts']]
            st['anchor'] = sum(pys) / len(pys)
            st['mult'] = (st['anchor'] - u.capb) / u.span
    # 끝 스테이션 캡 강체 결합: END 드래그 배수 mult_end (기본 = mult)
    for st in raw_stations:
        st['mult_end'] = st['mult']
        if rigid_end_dist is not None:
            if u.capt - st['anchor'] < rigid_end_dist:
                st['mult_end'] = 1.0; st['rigid'] = 'top'
            elif st['anchor'] - u.capb < rigid_end_dist:
                st['mult_end'] = 0.0; st['rigid'] = 'bottom'
    if rigid_end_dist is not None:
        # 강체 끝 정션에 어댑션된 브릿지(U턴 등, 끝점 부착 lockstep)도 캡과 함께 고정
        for st in raw_stations:
            src = st.get('adopted_from')
            if src is not None and src.get('rigid'):
                st['rigid'] = src['rigid']; st['mult_end'] = src['mult_end']
    # 캡 강체 모드: 중간 N분기 배수 = 중앙 H중점(0.5)~램프 바깥끝(1/0) 선형 보간.
    #   ★ 기준점 = "N분기 끝"(구조물 밴드의 중앙쪽 끝 = 레일 접점, 사용자 측정 방식).
    #   각 구간(N분기 끝~N분기 끝~H중점)이 그려진 길이에 비례해 성장 → 같게 그려진
    #   구간은 어떤 신축에서도 같게 유지. 피처(분기 쌍 <2000 체인)는 배수 공유(강체).
    if rigid_end_dist is not None:
        center_y = (u.capb + u.capt) / 2.0
        def st_band(st):
            ys = [p[1] for i in st['members'] for p in ents[i]['pts']]
            return min(ys), max(ys)
        for half in ('top', 'bottom'):
            up = half == 'top'
            rigs = [s for s in raw_stations if s.get('rigid') == half]
            if not rigs: continue
            mids = [st for st in raw_stations if not st.get('rigid')
                    and (st['anchor'] > center_y + CENTER_WIN if up
                         else st['anchor'] < center_y - CENTER_WIN)]
            mids.sort(key=lambda s: abs(s['anchor'] - center_y))
            feats = []
            for st in mids:
                if feats and abs(st['anchor'] - feats[-1][-1]['anchor']) < 2000.0:
                    feats[-1].append(st)
                else:
                    feats.append([st])
            if rigid_interp == 'order':
                # SAFE34_v15 방식: 피처 순번 등분 배수 m = 0.5 ± 0.5·(k+1)/(n+1).
                #   등간격 그리드에 그려진 도면(4차선)이 신축 후에도 등간격 유지.
                n = len(feats)
                for k, f in enumerate(feats):
                    m = 0.5 + 0.5 * (k + 1) / (n + 1) if up else 0.5 - 0.5 * (k + 1) / (n + 1)
                    for st in f: st['mult_end'] = m
            elif rigid_interp == 'seg':
                # H중점(0.5)~끝 스테이션 바깥끝(1.0) 직선: N분기 끝 기준 구간이 좌표 비례 성장
                ramp = max(rigs, key=lambda s: s['anchor'] if up else -s['anchor'])
                R = st_band(ramp)[1] if up else st_band(ramp)[0]
                for f in feats:
                    if up:
                        bj = min(st_band(st)[0] for st in f)   # 중앙쪽 끝(아래끝)
                        m = 0.5 + 0.5 * (bj - center_y) / (R - center_y)
                    else:
                        bj = max(st_band(st)[1] for st in f)   # 중앙쪽 끝(위끝)
                        m = 0.5 - 0.5 * (center_y - bj) / (center_y - R)
                    for st in f: st['mult_end'] = m
            else:
                # 'gap': 간격 누적 좌표. 중앙 구조물 바깥끝(0.5) → 고정존 안쪽끝(1/0).
                #   모든 구조물(중앙 H·피처·고정존)은 크기 불변, 간격만 길이 비례 균일 신축.
                cen_sts = [s for s in raw_stations if not s.get('rigid')
                           and abs(s['anchor'] - center_y) <= CENTER_WIN]
                if cen_sts:
                    C = max(st_band(s)[1] for s in cen_sts) if up \
                        else min(st_band(s)[0] for s in cen_sts)
                else:
                    C = center_y
                Z = min(st_band(s)[0] for s in rigs) if up \
                    else max(st_band(s)[1] for s in rigs)   # 고정존 안쪽끝
                bands = []
                for f in feats:
                    b0 = min(st_band(st)[0] for st in f)
                    b1 = max(st_band(st)[1] for st in f)
                    bands.append((b0, b1))
                bands.sort(key=lambda b: b[0] if up else -b[1])
                gaps = []; prev = C
                for b0, b1 in bands:
                    gaps.append(abs((b0 if up else b1) - prev))
                    prev = b1 if up else b0
                gaps.append(abs(Z - prev))
                total = sum(gaps)
                cum = 0.0
                for f, gp in zip(sorted(feats, key=lambda f: abs(f[0]['anchor'] - center_y)),
                                 gaps[:-1]):
                    cum += gp
                    m = 0.5 + 0.5 * cum / total if up else 0.5 - 0.5 * cum / total
                    for st in f: st['mult_end'] = m
        # 중앙 H분기: 길이 고정 → 전 멤버 0.5로 강체 이동 (중점은 정확히 0.5Δ).
        #   4차선의 중앙 H는 ±3836 정션 쌍이라 윈도우 4500 필요 (3차선 게이트는 ±800).
        for st in raw_stations:
            if not st.get('rigid') and abs(st['anchor'] - center_y) <= CENTER_WIN:
                st['mult_end'] = 0.5
    u.stations = sorted(raw_stations, key=lambda s: s['mult'])

    # 내부레일 끝점 배수 (fracstretch), 캡(또는 캡 강체 스테이션)에 붙으면 캡 신축 편입
    u.inner_eps = []       # (ent_idx, pt_idx, mult)
    u.inner_cap_top = []   # (ent_idx, pt_idx) 캡 신축에 74=1로 편입
    u.inner_cap_bottom = []
    for i in u.inners:
        for pi in (0, 1):
            t = ep_touch.get((i, pi))
            if t is None:
                p = ents[i]['pts'][pi]
                u.inner_eps.append((i, pi, (p[1] - u.capb) / u.span))
            elif t[0] == 'st':
                if t[1].get('rigid') == 'top':
                    u.inner_cap_top.append((i, pi))
                elif t[1].get('rigid') == 'bottom':
                    u.inner_cap_bottom.append((i, pi))
                else:
                    u.inner_eps.append((i, pi, t[1]['mult']))
            elif t[0] == 'top':
                u.inner_cap_top.append((i, pi))
            else:
                u.inner_cap_bottom.append((i, pi))

    # 폭(거리2) 시임: 가운데 레일 갭 우선. 호(강체)는 시임을 가로지를 수 없으므로
    # 갭 안에서 호 몸통이 없는 자유 x구간을 찾아 시임 배치. 자유 구간 없는 갭(U-호 게이트 등)은
    # 바깥쪽 갭으로 넘어감. (새 4차선: 중앙 갭이 U-호로 막혀 3-4레일 갭의 2582~2650 구간 사용)
    def arc_xrange(e):
        a0, a1 = e['a0'] % 360.0, e['a1'] % 360.0
        if a1 < a0: a1 += 360.0
        xs = [p[0] for p in e['pts']]
        for ext, xv in ((0.0, e['cx'] + e['r']), (180.0, e['cx'] - e['r'])):
            for k in (ext, ext + 360.0):
                if a0 - 1e-9 <= k <= a1 + 1e-9: xs.append(xv)
        return min(xs), max(xs)
    MARG = 10.0
    n = len(u.rail_xs)
    gi0 = (n + 1) // 2
    order = [gi0] + [gi0 + k for k in range(1, n - gi0)] + [gi0 - k for k in range(1, gi0)]
    u.seam = (u.rail_xs[gi0 - 1] + u.rail_xs[gi0]) / 2.0
    for gi in order:
        lo, hi = u.rail_xs[gi - 1] + MARG, u.rail_xs[gi] - MARG
        if hi <= lo: continue
        ivs = sorted((max(lo, x0 - MARG), min(hi, x1 + MARG))
                     for x0, x1 in (arc_xrange(e) for e in ents if e['kind'] == 'ARC')
                     if x1 > lo and x0 < hi)
        free = []; cur = lo
        for x0, x1 in ivs:
            if x0 > cur: free.append((cur, x0))
            cur = max(cur, x1)
        if cur < hi: free.append((cur, hi))
        if not free: continue
        mid = (u.rail_xs[gi - 1] + u.rail_xs[gi]) / 2.0
        best = min(free, key=lambda iv: 0.0 if iv[0] <= mid <= iv[1]
                   else min(abs(iv[0] - mid), abs(iv[1] - mid)))
        u.seam = mid if best[0] <= mid <= best[1] else (best[0] + best[1]) / 2.0
        break
    return u

def width_side(u, e):
    """거리2 신축 멤버십: ('end',spec)|('base',spec)|('cross',idx_end,idx_base)"""
    if e['kind'] == 'ARC':
        # 호는 몸통(각도 중앙점) 위치로 판정 — 시임 위 중심(U-호)의 float 동전던지기 방지
        a0, a1 = e['a0'], e['a1']
        if a1 < a0: a1 += 360.0
        am = math.radians((a0 + a1) / 2.0)
        mx = e['cx'] + e['r'] * math.cos(am)
        return ('end', [0, 1]) if mx > u.seam else ('base', [0, 1])
    s0 = e['pts'][0][0] > u.seam
    s1 = e['pts'][1][0] > u.seam
    if s0 and s1: return ('end', [0, 1])
    if not s0 and not s1: return ('base', [0, 1])
    return ('cross', 0 if s0 else 1, 1 if s0 else 0)

def vertical_coverage(u):
    """검증용: 엔티티/포인트별 세로 액션 배수 맵 생성.
    반환: end_move[id]=f, base_move[id]=f, frac[(id,pi)]=(f_end,f_base),
          cap_top[id]=spec, cap_bottom[id]=spec (spec=[pt_idx..] 74=2면 [0,1])"""
    ents = u.ents
    end_move = {}; base_move = {}
    for st in u.stations:
        for i in st['members']:
            end_move[i] = st['mult']; base_move[i] = 1.0 - st['mult']
    frac = {}
    for i, pi, f in u.inner_eps:
        frac[(i, pi)] = (f, 1.0 - f)
    cap_top = {i: [0, 1] for i in u.cap_top}
    cap_bottom = {i: [0, 1] for i in u.cap_bottom}
    for i in u.fulls:
        top_pi = max((0, 1), key=lambda pi: ents[i]['pts'][pi][1])
        cap_top[i] = [top_pi]
        cap_bottom[i] = [1 - top_pi]
    for i, pi in u.inner_cap_top: cap_top.setdefault(i, []).append(pi)
    for i, pi in u.inner_cap_bottom: cap_bottom.setdefault(i, []).append(pi)
    return end_move, base_move, frac, cap_top, cap_bottom

# ───────────────────────── v15 저장 액션 파서 (검증용) ─────────────────────────
def read_pairs_str(path):
    raw = open(path, encoding='utf-8', errors='ignore').read().split('\n')
    return [(raw[j].strip(), raw[j + 1].strip()) for j in range(0, len(raw) - 1, 2)]

def split_ents_pairs(pairs):
    ents = []; cur = None
    for c, v in pairs:
        if c == '0':
            if cur: ents.append(cur)
            cur = [(c, v)]
        elif cur is not None:
            cur.append((c, v))
    if cur: ents.append(cur)
    return ents

def gvv(T, code):
    return [v for c, v in T if c == code]

def parse_v15_actions(path):
    """블록명 → dict(movers=[(dir,mult,[refs])], stretches=[(dir,mult,label,{h:[idx..]})])"""
    ents = split_ents_pairs(read_pairs_str(path))
    rec2name = {}; xd2rec = {}; graph2xd = {}
    for T in ents:
        if T[0][1] == 'BLOCK_RECORD':
            h = (gvv(T, '5') or [''])[0].upper(); nm = (gvv(T, '2') or [''])[0]
            xs = gvv(T, '360')
            rec2name[h] = nm
            if xs: xd2rec[xs[0].upper()] = h
    for T in ents:
        if T[0][1] == 'DICTIONARY':
            h = (gvv(T, '5') or [''])[0].upper()
            for n, r in zip(gvv(T, '3'), gvv(T, '360')):
                if n == 'ACAD_ENHANCEDBLOCK': graph2xd[r.upper()] = h
    def blk_of(T):
        g = (gvv(T, '330') or [''])[0].upper()
        xd = graph2xd.get(g)
        rec = xd2rec.get(xd or '', '')
        return rec2name.get(rec, '')
    out = defaultdict(lambda: dict(movers=[], stretches=[]))
    for T in ents:
        t = T[0][1]
        if t == 'BLOCKMOVEACTION':
            blk = blk_of(T)
            if not blk.startswith('rail34'): continue
            mult = float(gvv(T, '140')[0])
            d = 'end' if gvv(T, '301')[0].startswith('End') else 'base'
            i71 = next(i for i, (c, v) in enumerate(T) if c == '71')
            refs = []
            j = i71 + 1
            while j < len(T) and T[j][0] == '330':
                refs.append(T[j][1].upper()); j += 1
            out[blk]['movers'].append((d, mult, refs))
        elif t == 'BLOCKSTRETCHACTION':
            blk = blk_of(T)
            if not blk.startswith('rail34'): continue
            mult = float(gvv(T, '140')[-1])
            d = 'end' if gvv(T, '301')[0].startswith('End') else 'base'
            lab = (gvv(T, '300') or [''])[0]
            k = next(i for i, (c, v) in enumerate(T) if c == '73')
            spec = {}
            j = k + 1
            while j < len(T) and T[j][0] == '331':
                h = T[j][1].upper(); j += 1
                cnt = int(T[j][1]); j += 1
                idxs = []
                for _ in range(cnt):
                    idxs.append(int(T[j][1])); j += 1
                spec[h] = idxs
            out[blk]['stretches'].append((d, mult, lab, spec))
    return out

def validate_v15():
    doc = ezdxf.readfile(V15)
    stored = parse_v15_actions(V15)
    total_diff = 0
    for b in doc.blocks:
        if not b.name.startswith('rail34_'): continue
        ents = load_ents(b)
        u = classify_unit(ents)
        end_move, base_move, frac, cap_top, cap_bottom = vertical_coverage(u)
        h2i = {e['h'].upper(): i for i, e in enumerate(ents)}
        sv = stored[b.name]
        diffs = []
        # 1) 무버 배수 커버리지 (엔티티→END/BASE 배수)
        sv_end = {}; sv_base = {}
        for d, mult, refs in sv['movers']:
            for h in refs:
                if h not in h2i: continue   # 파라미터 등 비지오 참조
                (sv_end if d == 'end' else sv_base)[h2i[h]] = mult
        my_end = dict(end_move)
        for i, mult in sv_end.items():
            mine = my_end.pop(i, None)
            if mine is None or abs(mine - mult) > 1e-4:
                diffs.append('END무버 %s: 저장=%.6f 계산=%s' % (ents[i]['h'], mult, mine))
        for i, mine in my_end.items():
            diffs.append('END무버 잉여 %s: 계산=%.6f' % (ents[i]['h'], mine))
        # 2) 분수 STRETCH
        sv_frac = {}
        for d, mult, lab, spec in sv['stretches']:
            if not (0.001 < mult < 0.999): continue
            for h, idxs in spec.items():
                for pi in idxs:
                    key = (h2i[h], pi)
                    fe, fb = sv_frac.get(key, (None, None))
                    if d == 'end': sv_frac[key] = (mult, fb)
                    else: sv_frac[key] = (fe, mult)
        my_frac = dict(frac)
        for key, (fe, fb) in sv_frac.items():
            mine = my_frac.pop(key, None)
            if mine is None or (fe is not None and abs(mine[0] - fe) > 1e-4) \
               or (fb is not None and abs(mine[1] - fb) > 1e-4):
                diffs.append('frac %s.%d: 저장=(%s,%s) 계산=%s'
                             % (ents[key[0]]['h'], key[1], fe, fb, mine))
        for key, mine in my_frac.items():
            diffs.append('frac 잉여 %s.%d: 계산=(%.6f,%.6f)' % (ents[key[0]]['h'], key[1], mine[0], mine[1]))
        # 3) 캡 신축 스펙
        for d, mult, lab, spec in sv['stretches']:
            if lab not in ('신축', '신축1'): continue
            mymap = cap_top if lab == '신축' else cap_bottom
            svmap = {h2i[h]: sorted(idxs) for h, idxs in spec.items() if h in h2i}
            mymap2 = {i: sorted(v) for i, v in mymap.items()}
            if svmap != mymap2:
                only_sv = {ents[i]['h']: v for i, v in svmap.items() if mymap2.get(i) != v}
                only_my = {ents[i]['h']: v for i, v in mymap2.items() if svmap.get(i) != v}
                diffs.append('%s 스펙: 저장측=%s 계산측=%s' % (lab, only_sv, only_my))
        # 4) 폭 신축 스펙
        for d, mult, lab, spec in sv['stretches']:
            if lab not in ('신축2', '신축3'): continue
            for h, idxs in spec.items():
                if h not in h2i: continue   # param1 base-follow
                e = ents[h2i[h]]
                side = width_side(u, e)
                if side[0] == 'cross':
                    want = [side[1]] if lab == '신축2' else [side[2]]
                else:
                    want = [0, 1] if (side[0] == 'end') == (lab == '신축2') else None
                if want is None:
                    diffs.append('%s에 반대편 %s' % (lab, e['h']))
                elif sorted(idxs) != sorted(want):
                    diffs.append('%s %s: 저장=%s 계산=%s' % (lab, e['h'], idxs, want))
        st_ms = ['%.4f%s' % (s['mult'], '*' if s.get('adopted') else '') for s in u.stations]
        print('%-18s 스테이션 %d [%s] frac %d cap(%d/%d) %s'
              % (b.name, len(u.stations), ','.join(st_ms), len(u.inner_eps),
                 len(cap_top), len(cap_bottom), ('OK' if not diffs else 'DIFF %d' % len(diffs))))
        for d in diffs[:12]: print('    ' + d)
        total_diff += len(diffs)
    print('총 диффs:', total_diff)
    return total_diff

# ───────────────────────── 저작 (raw DXF emit) ─────────────────────────
def line_tags(h, owner, layer, x0, y0, x1, y1):
    return [cf.pair(0, 'LINE'), cf.pair(5, h), cf.pair(330, owner),
            cf.pair(100, 'AcDbEntity'), cf.pair(8, layer), cf.pair(100, 'AcDbLine'),
            cf.pair(10, cf.fmt(x0)), cf.pair(20, cf.fmt(y0)), cf.pair(30, '0.0'),
            cf.pair(11, cf.fmt(x1)), cf.pair(21, cf.fmt(y1)), cf.pair(31, '0.0')]

def arc_tags(h, owner, layer, cx, cy, r, a0, a1):
    return [cf.pair(0, 'ARC'), cf.pair(5, h), cf.pair(330, owner),
            cf.pair(100, 'AcDbEntity'), cf.pair(8, layer), cf.pair(100, 'AcDbCircle'),
            cf.pair(10, cf.fmt(cx)), cf.pair(20, cf.fmt(cy)), cf.pair(30, '0.0'),
            cf.pair(40, cf.fmt(r)), cf.pair(100, 'AcDbArc'),
            cf.pair(50, cf.fmt(a0)), cf.pair(51, cf.fmt(a1))]

def insert_tags(h, owner, name, x, y):
    return [cf.pair(0, 'INSERT'), cf.pair(5, h), cf.pair(330, owner),
            cf.pair(100, 'AcDbEntity'), cf.pair(8, '0'), cf.pair(100, 'AcDbBlockReference'),
            cf.pair(2, name), cf.pair(10, cf.fmt(x)), cf.pair(20, cf.fmt(y)), cf.pair(30, '0.0')]

def stretch_action_m(handle, owner, expr_id, label, driver_id, direction,
                     refs, specs, box, mult=1.0, include_vparam=None):
    tags = cf.stretch_action(handle, owner, expr_id, label, driver_id, direction,
                             refs, specs, box, include_vertical_param=include_vparam)
    if mult != 1.0:
        for i in range(len(tags) - 1, -1, -1):
            if tags[i][0] == '140':
                tags[i] = cf.pair(140, cf.fmt_ratio(mult)); break
    return tags

def build_unit_objects(u, H, rec, hgen, param_label_off=9782.709112879196):
    """유닛 하나의 다이나믹 객체 일체 생성. 반환 (objects, xdict_handle)."""
    ents = u.ents
    hs = [e['h'] for e in ents]
    xdict = hgen.new(); graph = hgen.new(); purge = hgen.new()
    vparam = hgen.new(); vbg = hgen.new(); vbx = hgen.new(); vby = hgen.new()
    veg = hgen.new(); vex = hgen.new(); vey = hgen.new()
    st_top = hgen.new(); st_bot = hgen.new()
    hparam = hgen.new(); hbg = hgen.new(); hbx = hgen.new(); hby = hgen.new()
    heg = hgen.new(); hex_ = hgen.new(); hey = hgen.new()
    st_r = hgen.new(); mv_we = hgen.new(); mv_wb = hgen.new(); st_l = hgen.new()
    mv_end = [hgen.new() for _ in u.stations]
    mv_base = [hgen.new() for _ in u.stations]
    fr_end = [hgen.new() for _ in u.inner_eps]
    fr_base = [hgen.new() for _ in u.inner_eps]

    minx = min(bbox_of(e)[0] for e in ents); maxx = max(bbox_of(e)[1] for e in ents)
    miny = min(bbox_of(e)[2] for e in ents); maxy = max(bbox_of(e)[3] for e in ents)
    x_rail_mid = (u.rail_xs[0] + u.rail_xs[-1]) / 2.0
    y_mid = (u.capb + u.capt) / 2.0

    # ── eval graph 노드/엣지 (v15 순서) ──
    nodes = [(1, vparam), (2, vbg), (3, vbx), (4, vby), (5, veg), (6, vex), (7, vey),
             (8, st_top), (9, st_bot),
             (50, hparam), (51, hbg), (52, hbx), (53, hby), (54, heg), (55, hex_), (56, hey),
             (57, st_r), (58, mv_we), (59, mv_wb), (70, st_l)]
    expr = 80
    mv_exprs = []
    for h in mv_end + mv_base:
        nodes.append((expr, h)); mv_exprs.append(expr); expr += 1
    fr_exprs = []
    for h in fr_end + fr_base:
        nodes.append((expr, h)); fr_exprs.append(expr); expr += 1
    ni = {h: i for i, (_e, h) in enumerate(nodes)}
    E = [(ni[vparam], ni[vbx], 1), (ni[vparam], ni[vby], 1),
         (ni[vparam], ni[vex], 1), (ni[vparam], ni[vey], 1),
         (ni[vbg], ni[vparam], 2), (ni[veg], ni[vparam], 2),
         (ni[vparam], ni[st_top], 2), (ni[vparam], ni[st_bot], 2),
         (ni[vparam], ni[mv_we], 2), (ni[vparam], ni[mv_wb], 2)]
    for h in mv_end + mv_base + fr_end + fr_base:
        E.append((ni[vparam], ni[h], 2))
    E += [(ni[hparam], ni[hbx], 1), (ni[hparam], ni[hby], 1),
          (ni[hparam], ni[hex_], 1), (ni[hparam], ni[hey], 1),
          (ni[hbg], ni[hparam], 2), (ni[heg], ni[hparam], 2),
          (ni[hparam], ni[st_r], 2), (ni[hparam], ni[st_l], 2)]

    objs = [cf.dict_object(xdict, rec, graph, purge),
            cf.build_graph(graph, xdict, nodes, E),
            cf.purge_object(purge, xdict)]
    # ── 거리1 ──
    objs.append(cf.linear_parameter(vparam, graph, 1, '선형', '거리1',
                                    0.0, 0.0, 0.0, H, 2, 5, param_label_off, 10000.0))
    objs.append(cf.linear_grip(vbg, graph, 2, '기준 그립', 3, 4, 0.0, 0.0, 0.0, -H))
    objs.append(cf.grip_component(vbx, graph, 3, 1, 'UpdatedBaseX'))
    objs.append(cf.grip_component(vby, graph, 4, 1, 'UpdatedBaseY'))
    objs.append(cf.linear_grip(veg, graph, 5, '끝 그립', 6, 7, 0.0, H, 0.0, H))
    objs.append(cf.grip_component(vex, graph, 6, 1, 'UpdatedEndX', True))
    objs.append(cf.grip_component(vey, graph, 7, 1, 'UpdatedEndY', True))

    # 캡 신축 (신축=END/top, 신축1=BASE/bottom)
    def cap_stretch(handle, expr_id, label, direction, cap_ids, inner_caps):
        cap_pys = [p[1] for i in cap_ids for p in ents[i]['pts']]
        other_ids = [i for i in range(len(ents))
                     if i not in cap_ids and i not in u.fulls]
        other_pys = [p[1] for i in other_ids for p in ents[i]['pts']] or [y_mid]
        if direction == 'end':
            cut = (min(cap_pys) + max(other_pys)) / 2.0
            box = (minx - 1000.0, maxy + 2000.0, maxx + 1000.0, cut)
        else:
            cut = (max(cap_pys) + min(other_pys)) / 2.0
            box = (minx - 1000.0, cut, maxx + 1000.0, miny - 2000.0)
        refs = [hs[i] for i in cap_ids]
        specs = [(hs[i], [0, 1]) for i in cap_ids]
        for i in u.fulls:
            pi = max((0, 1), key=lambda k: ents[i]['pts'][k][1]) if direction == 'end' \
                else min((0, 1), key=lambda k: ents[i]['pts'][k][1])
            refs.append(hs[i]); specs.append((hs[i], [pi]))
        for i, pi in inner_caps:
            refs.append(hs[i]); specs.append((hs[i], [pi]))
        return stretch_action_m(handle, graph, expr_id, label, 1, direction, refs, specs, box)
    objs.append(cap_stretch(st_top, 8, '신축', 'end', u.cap_top, u.inner_cap_top))
    objs.append(cap_stretch(st_bot, 9, '신축1', 'base', u.cap_bottom, u.inner_cap_bottom))

    # ── 거리2 ──
    width = u.rail_xs[-1] - u.rail_xs[0]
    objs.append(cf.linear_parameter(hparam, graph, 50, '선형1', '거리2',
                                    u.rail_xs[0], y_mid, u.rail_xs[-1], y_mid, 51, 54,
                                    width, 900.0))
    objs.append(cf.linear_grip(hbg, graph, 51, '기준 그립', 52, 53, u.rail_xs[0], y_mid, -width, 0.0))
    objs.append(cf.grip_component(hbx, graph, 52, 50, 'UpdatedBaseX'))
    objs.append(cf.grip_component(hby, graph, 53, 50, 'UpdatedBaseY'))
    objs.append(cf.linear_grip(heg, graph, 54, '끝 그립', 55, 56, u.rail_xs[-1], y_mid, width, 0.0))
    objs.append(cf.grip_component(hex_, graph, 55, 50, 'UpdatedEndX', True))
    objs.append(cf.grip_component(hey, graph, 56, 50, 'UpdatedEndY', True))

    r_refs = []; r_specs = []; l_refs = []; l_specs = [(vparam, [])]
    for i, e in enumerate(ents):
        side = width_side(u, e)
        if side[0] == 'end':
            r_refs.append(hs[i]); r_specs.append((hs[i], [0, 1]))
        elif side[0] == 'base':
            l_refs.append(hs[i]); l_specs.append((hs[i], [0, 1]))
        else:
            r_refs.append(hs[i]); r_specs.append((hs[i], [side[1]]))
            l_refs.append(hs[i]); l_specs.append((hs[i], [side[2]]))
    objs.append(stretch_action_m(st_r, graph, 57, '신축2', 50, 'end', r_refs, r_specs,
                                 (u.seam, maxy + 1000.0, maxx + 2000.0, miny - 1000.0)))
    objs.append(cf.move_action(mv_we, graph, 58, '이동거리2', [hparam],
                               x_rail_mid, y_mid, 'end', 0.5, 50))
    objs.append(cf.move_action(mv_wb, graph, 59, '이동거리2_1', [hparam],
                               x_rail_mid, y_mid, 'base', 0.5, 50))
    objs.append(stretch_action_m(st_l, graph, 70, '신축3', 50, 'base', l_refs, l_specs,
                                 (minx - 2000.0, maxy + 1000.0, u.seam, miny - 1000.0),
                                 include_vparam=vparam))

    # ── 스테이션 MOVE 쌍 ──  (캡 강체 스테이션은 mult_end=1/0)
    lab = 0
    for k, st in enumerate(u.stations):   # END 오름차순
        objs.append(cf.move_action(mv_end[k], graph, mv_exprs[k], '이동%d' % lab,
                                   [hs[i] for i in st['members']],
                                   x_rail_mid, st['anchor'], 'end', st['mult_end'], 13))
        lab += 1
    for k, st in enumerate(reversed(u.stations)):   # BASE 내림차순(미러)
        objs.append(cf.move_action(mv_base[k], graph, mv_exprs[len(u.stations) + k], '이동%d' % lab,
                                   [hs[i] for i in st['members']],
                                   x_rail_mid, st['anchor'], 'base', 1.0 - st['mult_end'], 13))
        lab += 1
    # ── 내부레일 끝점 분수 STRETCH ──
    fi = 0
    for k, (i, pi, f) in enumerate(u.inner_eps):
        p = ents[i]['pts'][pi]
        box = (p[0] - 10.0, p[1] + 10.0, p[0] + 10.0, p[1] - 10.0)
        objs.append(stretch_action_m(fr_end[k], graph, fr_exprs[fi], '신축%d' % lab, 1, 'end',
                                     [hs[i]], [(hs[i], [pi])], box, mult=f))
        lab += 1; fi += 1
    for k, (i, pi, f) in enumerate(u.inner_eps):
        p = ents[i]['pts'][pi]
        box = (p[0] - 10.0, p[1] + 10.0, p[0] + 10.0, p[1] - 10.0)
        objs.append(stretch_action_m(fr_base[k], graph, fr_exprs[fi], '신축%d' % lab, 1, 'base',
                                     [hs[i]], [(hs[i], [pi])], box, mult=1.0 - f))
        lab += 1; fi += 1
    return objs, xdict

def redistribute_equal_halves(local, rigid_end_dist):
    """중앙 H 중점 기준 등간격 재배치 (3차선 요구): 중앙~끝램프 사이의 중간 조인트
    피처(간격<2000 체인)들을 [중앙, 램프 anchor] 등분 위치로 강체 이동. local을 직접 수정."""
    u = classify_unit(local, rigid_end_dist)
    center_y = (u.capb + u.capt) / 2.0
    ramps = {st.get('rigid'): st for st in u.stations if st.get('rigid')}
    if 'top' not in ramps or 'bottom' not in ramps:
        return []
    log = []
    for half in ('top', 'bottom'):
        ramp_a = ramps[half]['anchor']
        if half == 'top':
            mids = [st for st in u.stations if not st.get('rigid') and st['anchor'] > center_y + 3000.0]
        else:
            mids = [st for st in u.stations if not st.get('rigid') and st['anchor'] < center_y - 3000.0]
        if not mids: continue
        mids.sort(key=lambda s: abs(s['anchor'] - center_y))
        feats = []
        for st in mids:
            if feats and abs(st['anchor'] - feats[-1][-1]['anchor']) < 2000.0:
                feats[-1].append(st)
            else:
                feats.append([st])
        n = len(feats)
        for k, f in enumerate(feats):
            cur = sum(st['anchor'] for st in f) / len(f)
            tgt = center_y + (k + 1) / (n + 1) * (ramp_a - center_y)
            d = tgt - cur
            if abs(d) < 0.01: continue
            for st in f:
                for i in st['members']:
                    e = local[i]
                    e['pts'] = [(x, y + d) for x, y in e['pts']]
                    if e['kind'] == 'ARC': e['cy'] += d
            log.append((half, k, d))
    return log


def prune_orphans(entries):
    """도너에서 물려온 고아 객체 정리: 소유자가 스트립된 XRECORD, 대상 없는 DICTIONARY 항목."""
    changed = True
    while changed:
        changed = False
        have = set()
        for ent in entries:
            h = cf.first(ent, 5) or cf.first(ent, 105)
            if h: have.add(h.upper())
        keep = []
        for ent in entries:
            t = cf.first(ent, 0)
            if t in ('XRECORD', 'DICTIONARY'):
                own = cf.first(ent, 330)
                if own and own != '0' and own.upper() not in have:
                    changed = True; continue
            if t == 'GROUP':
                refs = [v.strip() for c, v in ent if c.strip() == '340']
                alive = [h for h in refs if h.upper() in have]
                if not alive:
                    changed = True; continue
                if len(alive) != len(refs):
                    ent[:] = [(c, v) for c, v in ent
                              if c.strip() != '340' or v.strip().upper() in have]
                    changed = True
            keep.append(ent)
        entries[:] = keep
        for ent in entries:
            if cf.first(ent, 0) != 'DICTIONARY': continue
            out = []; i = 0
            while i < len(ent):
                c = ent[i][0].strip()
                if c == '3' and i + 1 < len(ent) and ent[i + 1][0].strip() in ('350', '360') \
                        and ent[i + 1][1].strip().upper() not in have:
                    i += 2; changed = True; continue
                out.append(ent[i]); i += 1
            ent[:] = out


# ───────────────────────── 파일 생성 ─────────────────────────
def generate(src, prefix, out_path, rigid_end_dist=None, rigid_interp='seg'):
    doc = ezdxf.readfile(src)
    world = load_ents(doc.modelspace())
    units_raw = cluster(world)
    print('%s: 엔티티 %d → 클러스터 %d' % (os.path.basename(src), len(world), len(units_raw)))

    # 정렬·명명: 행(위→아래, 20m 이상 벌어져야 다른 행) 다음 x
    def unit_ymax(g): return max(p[1] for e in g for p in e['pts'])
    def unit_xmin(g): return min(p[0] for e in g for p in e['pts'])
    row_tops = []
    for v in sorted((unit_ymax(g) for g in units_raw), reverse=True):
        if not row_tops or row_tops[-1] - v > 20000.0:
            row_tops.append(v)
    def row_of(g):
        ym = unit_ymax(g)
        return min(range(len(row_tops)), key=lambda k: abs(row_tops[k] - ym))
    units_raw.sort(key=lambda g: (row_of(g), unit_xmin(g)))
    multi_row = len(row_tops) > 1

    donor = cf.read_pairs(__import__('pathlib').Path(DONOR))
    hgen = cf.HandleGen(max(cf.max_handle(donor) + 1, 0x100000))

    blocks = []   # dict(name, rec, ins, ents(local), unit, insert_xy, H)
    for gi, g in enumerate(units_raw):
        row_i = row_of(g) if multi_row else 0
        n_in_row = sum(1 for b in blocks if b['row'] == row_i)
        if multi_row:
            name = '%s_%s_%02d' % (prefix, ('top', 'bottom')[row_i] if len(row_tops) == 2 else 'r%d' % row_i,
                                   n_in_row + 1)
        else:
            name = '%s_%02d' % (prefix, n_in_row + 1)
        # 로컬 변환: 좌측 외곽레일 x→900, 레일 하단 y→450 (v15 관례)
        probe = classify_unit(g)
        left_full_x = min(probe.ents[i]['pts'][0][0] for i in probe.fulls)
        dx = left_full_x - 900.0
        dyy = probe.rail_ymin - 450.0
        local = [shift_ent(e, dx, dyy) for e in g]
        for e in local: e['h'] = hgen.new()
        # ★ 지오메트리 재배치 없음 — 원본 도면 치수 그대로 보존 (사용자 요구).
        #   등간격이 필요하면 REDISTRIBUTE=True (redistribute_equal_halves 사용).
        mv_log = redistribute_equal_halves(local, rigid_end_dist) if (rigid_end_dist and REDISTRIBUTE) else []
        u = classify_unit(local, rigid_end_dist, rigid_interp)
        H = (u.rail_ymax - u.rail_ymin) + 900.0
        rec = hgen.new(); ins = hgen.new()
        blocks.append(dict(name=name, rec=rec, ins=ins, local=local, unit=u,
                           insert=(dx, dyy), H=H, row=row_i))
        st_ms = ['%s%s' % (('R' + s['rigid'][0].upper()) if s.get('rigid') else '%.4f' % s['mult_end'],
                           '*' if s.get('adopted') else '') for s in u.stations]
        mv_s = (' 재배치[' + ','.join('%s%d:%+.0f' % (h[0], k, d) for h, k, d in mv_log) + ']') if mv_log else ''
        print('  %-16s ins=(%.0f,%.0f) H=%.0f 레일 %d(내부 %d) 스테이션 %d [%s] frac %d 시임 %.0f%s'
              % (name, dx, dyy, H, len(u.fulls) + len(u.inners), len(u.inners),
                 len(u.stations), ','.join(st_ms), len(u.inner_eps), u.seam, mv_s))

    # 다이나믹 객체 생성
    all_objs = {}; xdicts = {}
    for b in blocks:
        objs, xd = build_unit_objects(b['unit'], b['H'], b['rec'], hgen)
        all_objs[b['name']] = objs; xdicts[b['name']] = xd

    # 도너 스켈레톤에 조립 (gen_3rail_poc 방식)
    STRIP = {'BLOCKLINEARPARAMETER', 'BLOCKLINEARGRIP', 'BLOCKGRIPLOCATIONCOMPONENT',
             'BLOCKSTRETCHACTION', 'BLOCKMOVEACTION', 'ACAD_EVALUATION_GRAPH',
             'ACDB_DYNAMICBLOCKPURGEPREVENTER_VERSION', 'ACDB_BLOCKREPRESENTATION_DATA'}
    entries = cf.split_entries(donor)
    # 모델스페이스 레코드 핸들 (INSERT owner)
    msp_rec = '1F'
    for ent in entries:
        if cf.first(ent, 0) == 'BLOCK_RECORD' and (cf.first(ent, 2) or '') == '*Model_Space':
            msp_rec = cf.first(ent, 5) or '1F'
    new = []; skip = False; in_brtab = False
    for ent in entries:
        t = cf.first(ent, 0); nm = cf.first(ent, 2)
        junk = nm and (nm.startswith('*U') or nm.startswith('2rail'))
        if t in STRIP: continue
        if t == 'DICTIONARY' and 'ACAD_ENHANCEDBLOCK' in [v.strip() for c, v in ent if c.strip() == '3']:
            continue
        if t == 'BLOCK' and junk: skip = True; continue
        if t == 'ENDBLK' and skip: skip = False; continue
        if skip: continue
        if t == 'BLOCK_RECORD' and junk: continue
        if t == 'INSERT' and nm and (nm.startswith('*') or nm.startswith('2rail')): continue
        if t == 'TABLE' and nm == 'BLOCK_RECORD': in_brtab = True
        if t == 'ENDTAB' and in_brtab:
            in_brtab = False
            for b in blocks:
                guid = '{' + str(uuid.uuid5(uuid.NAMESPACE_URL, 'railflex-' + b['name'])).upper() + '}'
                new.append([cf.pair(0, 'BLOCK_RECORD'), cf.pair(5, b['rec']),
                            cf.pair(102, '{ACAD_XDICTIONARY'), cf.pair(360, xdicts[b['name']]),
                            cf.pair(102, '}'), cf.pair(330, '1'),
                            cf.pair(100, 'AcDbSymbolTableRecord'), cf.pair(100, 'AcDbBlockTableRecord'),
                            cf.pair(2, b['name']), cf.pair(340, '0'),
                            cf.pair(102, '{BLKREFS'), cf.pair(331, b['ins']), cf.pair(102, '}'),
                            cf.pair(70, '0'), cf.pair(280, '1'), cf.pair(281, '0'),
                            cf.pair(1001, 'AcDbBlockRepETag'), cf.pair(1070, '1'),
                            cf.pair(1071, str(len(b['local']))),
                            cf.pair(1001, 'AcDbDynamicBlockTrueName'), cf.pair(1000, b['name']),
                            cf.pair(1001, 'AcDbDynamicBlockGUID'), cf.pair(1000, guid)])
            new.append(ent); continue
        if t == 'ENDSEC':
            prev = None
            for e in reversed(new):
                if cf.first(e, 0) == 'SECTION': prev = cf.first(e, 2); break
            if prev == 'BLOCKS':
                for b in blocks:
                    new.append([cf.pair(0, 'BLOCK'), cf.pair(5, hgen.new()), cf.pair(330, b['rec']),
                                cf.pair(100, 'AcDbEntity'), cf.pair(8, '0'),
                                cf.pair(100, 'AcDbBlockBegin'), cf.pair(2, b['name']), cf.pair(70, '0'),
                                cf.pair(10, '0.0'), cf.pair(20, '0.0'), cf.pair(30, '0.0'),
                                cf.pair(3, b['name']), cf.pair(1, '')])
                    for e in b['local']:
                        if e['kind'] == 'LINE':
                            new.append(line_tags(e['h'], b['rec'], e['layer'],
                                                 e['pts'][0][0], e['pts'][0][1],
                                                 e['pts'][1][0], e['pts'][1][1]))
                        else:
                            new.append(arc_tags(e['h'], b['rec'], e['layer'],
                                                e['cx'], e['cy'], e['r'], e['a0'], e['a1']))
                    new.append([cf.pair(0, 'ENDBLK'), cf.pair(5, hgen.new()), cf.pair(330, b['rec']),
                                cf.pair(100, 'AcDbEntity'), cf.pair(8, '0'),
                                cf.pair(100, 'AcDbBlockEnd')])
            if prev == 'ENTITIES':
                for b in blocks:
                    new.append(insert_tags(b['ins'], msp_rec, b['name'], b['insert'][0], b['insert'][1]))
            if prev == 'OBJECTS':
                for b in blocks:
                    new.extend(all_objs[b['name']])
            new.append(ent); continue
        new.append(ent)

    prune_orphans(new)
    cf.write_pairs(__import__('pathlib').Path(out_path), cf.flatten(new))
    d = ezdxf.readfile(out_path); a = d.audit()
    print('  AUDIT errors=%d fixes=%d → %s' % (len(a.errors), len(a.fixes), out_path))
    if a.errors:
        for er in a.errors[:8]: print('   ', er)
    return blocks

# ───────────────────────── 검증: 왕복 지오메트리 + 신축 시뮬레이션 ─────────────────────────
def verify_output(src, out_path, blocks):
    """1) 출력 블록 내용 == 생성 시 로컬 지오메트리(재배치 반영) + INSERT 위치
       2) 총 엔티티 수 == 원본"""
    orig_n = len(load_ents(ezdxf.readfile(src).modelspace()))
    doc = ezdxf.readfile(out_path)
    def sig(e):
        ps = sorted((round(p[0], 3), round(p[1], 3)) for p in e['pts'])
        return (e['kind'], tuple(ps))
    ok = True; total = 0
    ins_pos = {i.dxf.name: (i.dxf.insert.x, i.dxf.insert.y) for i in doc.modelspace().query('INSERT')}
    for b in blocks:
        got = load_ents(doc.blocks.get(b['name']))
        total += len(got)
        if sorted(map(sig, got)) != sorted(map(sig, b['local'])):
            ok = False; print('  블록 지오메트리 불일치: %s' % b['name'])
        px, py = ins_pos.get(b['name'], (None, None))
        if px is None or abs(px - b['insert'][0]) > 1e-6 or abs(py - b['insert'][1]) > 1e-6:
            ok = False; print('  INSERT 위치 불일치: %s' % b['name'])
    if total != orig_n:
        ok = False
    print('  왕복 지오메트리: %s (원본 %d, 출력 %d, 재배치 반영)' % ('일치' if ok else '불일치!', orig_n, total))
    return ok

def simulate_block(doc, actions_by_blk, name, driver, direction, delta):
    """액션 의미대로 이동/신축 적용한 새 pts 목록 반환."""
    b = doc.blocks.get(name)
    ents = load_ents(b)
    idx = {e['h'].upper(): i for i, e in enumerate(ents)}
    disp = defaultdict(lambda: [ [0.0, 0.0], [0.0, 0.0] ])
    for kind, drv, d, mult, refspec in actions_by_blk[name]:
        if drv != driver or d != direction: continue
        for h, idxs in refspec.items():
            if h not in idx: continue
            for pi in idxs:
                disp[idx[h]][pi][0] += delta[0] * mult
                disp[idx[h]][pi][1] += delta[1] * mult
    out = []
    for i, e in enumerate(ents):
        mv = disp.get(i)
        pts = list(e['pts'])
        if mv:
            pts = [(pts[k][0] + mv[k][0], pts[k][1] + mv[k][1]) for k in (0, 1)]
        ne = dict(e); ne['pts'] = pts
        if e['kind'] == 'ARC' and mv:
            # 호는 항상 통째 이동(양끝 동일 변위) — 검증
            assert abs(mv[0][0] - mv[1][0]) < 1e-6 and abs(mv[0][1] - mv[1][1]) < 1e-6, \
                '%s 호 부분이동!' % e['h']
            ne['cx'] = e['cx'] + mv[0][0]; ne['cy'] = e['cy'] + mv[0][1]
        out.append(ne)
    return ents, out

def parse_out_actions(out_path):
    """출력 파일의 액션을 시뮬레이션용으로 파싱: blk → [(kind,driver,dir,mult,{h:[pi..]})]"""
    ents = split_ents_pairs(read_pairs_str(out_path))
    rec2name = {}; xd2rec = {}; graph2xd = {}
    for T in ents:
        if T[0][1] == 'BLOCK_RECORD':
            h = (gvv(T, '5') or [''])[0].upper(); nm = (gvv(T, '2') or [''])[0]
            for c, v in T:
                if c == '360': xd2rec[v.upper()] = h
            rec2name[h] = nm
    for T in ents:
        if T[0][1] == 'DICTIONARY':
            h = (gvv(T, '5') or [''])[0].upper()
            for n, r in zip(gvv(T, '3'), gvv(T, '360')):
                if n == 'ACAD_ENHANCEDBLOCK': graph2xd[r.upper()] = h
    # graph → param expr 매핑으로 driver 식별 (expr1=거리1, expr50=거리2)
    out = defaultdict(list)
    for T in ents:
        t = T[0][1]
        if t not in ('BLOCKMOVEACTION', 'BLOCKSTRETCHACTION'): continue
        g = (gvv(T, '330') or [''])[0].upper()
        blk = rec2name.get(xd2rec.get(graph2xd.get(g, ''), ''), '')
        if not blk: continue
        mult = float(gvv(T, '140')[-1] if t == 'BLOCKSTRETCHACTION' else gvv(T, '140')[0])
        d = 'end' if gvv(T, '301')[0].startswith('End') else 'base'
        drv = int(gvv(T, '92')[0])   # 92 = driver param expr id
        if t == 'BLOCKMOVEACTION':
            i71 = next(i for i, (c, v) in enumerate(T) if c == '71')
            refspec = {}
            j = i71 + 1
            while j < len(T) and T[j][0] == '330':
                refspec[T[j][1].upper()] = [0, 1]; j += 1
            out[blk].append((t, drv, d, mult, refspec))
        else:
            k = next(i for i, (c, v) in enumerate(T) if c == '73')
            refspec = {}
            j = k + 1
            while j < len(T) and T[j][0] == '331':
                h = T[j][1].upper(); j += 1
                cnt = int(T[j][1]); j += 1
                idxs = []
                for _ in range(cnt): idxs.append(int(T[j][1])); j += 1
                if idxs: refspec[h] = idxs
                # 74=0 (파라미터 base-follow)는 지오 아님 → skip
            out[blk].append((t, drv, d, mult, refspec))
    return out

def pt_on(e, p, tol=1.0):
    if e['kind'] == 'LINE':
        a, b = e['pts']
        ax, ay = a; bx, by = b; px, py = p
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        if L2 < 1e-9: return math.hypot(px - ax, py - ay) < tol
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
        return math.hypot(px - (ax + t * vx), py - (ay + t * vy)) < tol
    dr = abs(math.hypot(p[0] - e['cx'], p[1] - e['cy']) - e['r'])
    if dr > tol: return False
    ang = math.degrees(math.atan2(p[1] - e['cy'], p[0] - e['cx'])) % 360
    a0 = e['a0'] % 360; a1 = e['a1'] % 360
    sweep = (a1 - a0) % 360
    rel = (ang - a0) % 360
    return rel <= sweep + 0.5 or rel >= 360 - 0.5

def simulate_verify(out_path):
    doc = ezdxf.readfile(out_path)
    acts = parse_out_actions(out_path)
    names = sorted(acts.keys())
    fails = 0
    for name in names:
        base = load_ents(doc.blocks.get(name))
        # 원 연결쌍: 끝점이 상대 몸통 위에 있는 쌍
        adj = []
        for i, e in enumerate(base):
            for j, f in enumerate(base):
                if i == j: continue
                for pi in (0, 1):
                    if pt_on(f, e['pts'][pi]):
                        adj.append((i, pi, j))
        for driver, d, delta in [(1, 'end', (0, 3000)), (1, 'base', (0, -3000)),
                                 (50, 'end', (1000, 0)), (50, 'base', (-1000, 0))]:
            _b, moved = simulate_block(doc, acts, name, driver, d, delta)
            bad = 0
            for i, pi, j in adj:
                if not pt_on(moved[j], moved[i]['pts'][pi], tol=1.0):
                    bad += 1
            if bad:
                fails += 1
                print('  %s %s%+d: 연결 파괴 %d/%d' % (name, ('거리1' if driver == 1 else '거리2'),
                                                    delta[0] + delta[1], bad, len(adj)))
    print('  신축 시뮬레이션: %s (%d블록 × 4방향)' % ('전체 연결 유지 OK' if fails == 0 else 'FAIL %d' % fails,
                                               len(names)))
    return fails == 0

# ───────────────────────── main ─────────────────────────
if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'validate'
    if mode == 'validate':
        validate_v15()
    else:
        for src, prefix, out, rigid, interp in INPUTS:
            print('===== %s' % src)
            try:
                blocks = generate(src, prefix, out, rigid, interp)
            except PermissionError:
                print('  ★ 출력 파일이 잠겨 있어 건너뜀(CAD에서 열림?): %s' % out)
                print('    디스크의 기존 파일이 최신 코드와 다를 수 있음 — 닫고 재실행 필요')
                continue
            verify_output(src, out, blocks)
            simulate_verify(out)
