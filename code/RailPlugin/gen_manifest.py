# -*- coding: utf-8 -*-
# 0716 도면(3차선/4차선 24종 변형) → Rail34Manifest.cs 생성.
#  분류: 레일(수직>3000) / 캡(전폭 바+코너호) / 크로스오버(대각+호2 → 부품 INSERT) /
#        보타이·아치 바(300~600 바+호) / 외부 스텁(레일을 가로지르는 짧은 수평+호) / 기타(경고)
#  앵커: y: 0=하단고정(yy 유지), 1=상단고정(y'=L-(59100-yy)), 2=비율(y'=yy*L/59100)  [yy=native-450]
#        x: 0=고정, 1=W기준(x'=x+(W-Wn))  (3차선 우측존만. 4차선은 전부 고정)
#  부품: RP_X650_UP/DN, RP_X900_UP/DN — 대각+호2, 앵커=(컬럼 좌레일x, 대각 minY)
import ezdxf, math, io
from collections import defaultdict

BASE = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist'
OUT = r'C:\Users\User\Desktop\dnd\code\RailPlugin\Rail34Manifest.cs'
Y0, L0 = 450.0, 59100.0

# 카탈로그 부품 내부 기준값 (정확값 — 반올림 금지)
_cat = ezdxf.readfile(BASE + r'\분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf')
def _fbd_refs():
    b = _cat.blocks.get('zw$1FBD')
    dg = [e for e in b if e.dxftype() == 'LINE' and abs(e.dxf.start.x-e.dxf.end.x) >= 1][0]
    return min(dg.dxf.start.y, dg.dxf.end.y)
def _ch2_refs():
    b = _cat.blocks.get('DOUBLE BRANCH 2CH')
    rails_ = [e for e in b if e.dxftype() == 'LINE' and abs(e.dxf.start.x-e.dxf.end.x) < 1]
    bar_ = [e for e in b if e.dxftype() == 'LINE' and abs(e.dxf.start.y-e.dxf.end.y) < 1][0]
    bx = min(min(e.dxf.start.x, e.dxf.end.x) for e in rails_)
    blo = min(min(e.dxf.start.y, e.dxf.end.y) for e in rails_)
    bhi = max(max(e.dxf.start.y, e.dxf.end.y) for e in rails_)
    return bx, blo, bhi, bar_.dxf.start.y
def _ch4_refs():
    b = _cat.blocks.get('DOUBLE BRANCH 4CH')
    rails_ = [e for e in b if e.dxftype() == 'LINE' and abs(e.dxf.start.x-e.dxf.end.x) < 1]
    bars_ = [e for e in b if e.dxftype() == 'LINE' and abs(e.dxf.start.y-e.dxf.end.y) < 1]
    bx = min(min(e.dxf.start.x, e.dxf.end.x) for e in rails_)
    lo = min(min(e.dxf.start.y, e.dxf.end.y) for e in rails_)
    bar1 = min(e.dxf.start.y for e in bars_)
    return bx, lo, bar1
FBD_DMINY = _fbd_refs()
CH_BX, CH_BLO, CH_BHI, CH_BBAR = _ch2_refs()
C4_X, C4_LO, C4_BAR = _ch4_refs()
ACL = (51530.7, 35577.1)   # BRANCH LEFT 호 중심 (블록 내 절대좌표)
ACR = (52430.7, 33455.2)   # BRANCH RIGHT 호 중심

# 부품 내부 앵커 (I엔트리 타깃 → 삽입점 = X(타깃)−sx·ref / Y(타깃)−sy·ref)
def part_ref(nm):
    if nm in XREFS: return XREFS[nm][0]                     # 대각 중심
    if nm == 'BRANCH LEFT': return ACL                      # 호 중심
    if nm == 'BRANCH RIGHT': return ACR
    if nm == 'DOUBLE BRANCH 2CH': return (CH_BX, CH_BBAR)   # (좌레일x, 바레벨)
    if nm == 'DOUBLE BRANCH 4CH': return (C4_X, C4_BAR)
    if nm in ('DOUBLE BRANCH 2CH_900', 'DOUBLE BRANCH 4CH_900'): return (0.0, 650.0)
    return (0.0, 0.0)                                       # RP_ 템플릿 (0-기반)

# 부품 내부 수직 레일조각 (삽입점 상대) — 조립 시점 레일 분할용
def part_rails(nm, parts):
    if nm.startswith('#'):                   # 가상 엔트리(#BOWTIE 등): 블록 아님
        return []
    if nm.startswith('RP_'):
        pv = parts[nm]
        return [[l[0], min(l[1], l[3]), max(l[1], l[3])] for l in pv['lines']
                if abs(l[0]-l[2]) < 0.6 and abs(l[1]-l[3]) > 100]
    b = _cat.blocks.get(nm)
    return [[e.dxf.start.x, min(e.dxf.start.y, e.dxf.end.y), max(e.dxf.start.y, e.dxf.end.y)]
            for e in b if e.dxftype() == 'LINE'
            and abs(e.dxf.start.x-e.dxf.end.x) < 0.6 and abs(e.dxf.start.y-e.dxf.end.y) > 100]

def _bp_refs(nm):
    b = _cat.blocks.get(nm)
    dg = [e for e in b if e.dxftype() == 'LINE' and abs(e.dxf.start.x-e.dxf.end.x) >= 1 and abs(e.dxf.start.y-e.dxf.end.y) >= 1][0]
    pc = ((dg.dxf.start.x+dg.dxf.end.x)/2.0, (dg.dxf.start.y+dg.dxf.end.y)/2.0)
    prails = [(e.dxf.start.x, min(e.dxf.start.y, e.dxf.end.y), max(e.dxf.start.y, e.dxf.end.y))
              for e in b if e.dxftype() == 'LINE' and abs(e.dxf.start.x-e.dxf.end.x) < 1]
    return pc, prails
# N분기(관통)·바이패스(터미널) 부품 refs: (대각 중심, 레일조각들) — 45° 통일본
XREFS = {nm: _bp_refs(nm) for nm in [
    'BRANCH N LEFT', 'BRANCH N RIGHT', 'BRANCH N LEFT_650', 'BRANCH N RIGHT_650',
    'BRANCH BY PASS LEFT', 'BRANCH BY PASS RIGHT', 'BRANCH BY PASS LEFT_650', 'BRANCH BY PASS RIGHT_650']}
# (터미널측, 대각방향, 정션위치) → (블록, sx, sy)
BP_MAP = {
    ('R', 'DN', 'top'):    ('BRANCH BY PASS LEFT',  1, 1),
    ('L', 'UP', 'top'):    ('BRANCH BY PASS RIGHT', 1, 1),
    ('L', 'DN', 'top'):    ('BRANCH BY PASS LEFT', -1, 1),
    ('R', 'UP', 'top'):    ('BRANCH BY PASS RIGHT', -1, 1),
    ('R', 'UP', 'bottom'): ('BRANCH BY PASS LEFT',  1, -1),
    ('L', 'DN', 'bottom'): ('BRANCH BY PASS RIGHT', 1, -1),
    ('L', 'UP', 'bottom'): ('BRANCH BY PASS LEFT', -1, -1),
    ('R', 'DN', 'bottom'): ('BRANCH BY PASS RIGHT', -1, -1),
}

def ents_of(b):
    lines, arcs = [], []
    for e in b:
        if e.dxftype() == 'LINE':
            s, en = e.dxf.start, e.dxf.end
            lines.append([s.x, s.y, en.x, en.y])
        elif e.dxftype() == 'ARC':
            c = e.dxf.center
            arcs.append([c.x, c.y, e.dxf.radius, e.dxf.start_angle, e.dxf.end_angle])
    return lines, arcs

def arc_ends(a):
    cx, cy, r, a0, a1 = a
    return [(cx+r*math.cos(math.radians(t)), cy+r*math.sin(math.radians(t))) for t in (a0, a1)]

def near(p, q, tol=0.5):
    return math.hypot(p[0]-q[0], p[1]-q[1]) < tol

parts = {}          # 부품 템플릿: name -> dict(lines=[(rel coords)], arcs=[...])
variants = []       # (name, lanes, wn, entities[])

def classify(name, lanes, b):
    lines, arcs = ents_of(b)
    used_a = [False]*len(arcs)
    out = []            # (kind, data...) kind: L(line),A(arc),I(insert)
    rails = [l for l in lines if abs(l[0]-l[2]) < 1 and abs(l[1]-l[3]) > 3000]
    # 정규화: 좌측 레일 x=900, 레일 하단 y=Y0 (0716은 이미 정규화 상태 → 이동 0. 2차선.dxf는 오프셋 좌표)
    dxn = 900.0 - min(min(l[0], l[2]) for l in rails)
    dyn = Y0 - min(min(l[1], l[3]) for l in rails)
    if abs(dxn) > 0.01 or abs(dyn) > 0.01:
        for l in lines:
            l[0] += dxn; l[1] += dyn; l[2] += dxn; l[3] += dyn
        for a in arcs:
            a[0] += dxn; a[1] += dyn
    railx = sorted(set(round(l[0], 1) for l in rails))
    xr = railx[-1]                       # 최우측 레일
    # W갭 = railx[gi-1]~railx[gi] (2차선=유일 갭, 3차선=우측갭, 4차선=가운데 갭). 경계 오른쪽 존이 W따라 이동.
    wvar = 1
    gi = 2 if lanes >= 3 else 1
    wn = railx[gi] - railx[gi-1]
    wbound = railx[gi] - 455.0
    def xa_of(x):
        return 1 if (wvar and x >= wbound) else 0
    occ = defaultdict(list)   # 레일x → 부품 레일조각 점유 [lo,hi] (레일 분할용)
    railspan = defaultdict(list)
    for l in rails:
        railspan[round(l[0], 1)].append((min(l[1], l[3]), max(l[1], l[3])))
    # 크로스오버: 대각 + 접점 호 2
    #  관통(양쪽 레일 계속): 900=zw$1FBD / 650=RP_X650
    #  터미널(한쪽 레일이 정션에서 끝남 = 합류): 900=BRANCH BY PASS L/R(+미러) / 650=RP_X650
    diags = [l for l in lines if abs(l[0]-l[2]) >= 1 and abs(l[1]-l[3]) >= 1]
    for d in diags:
        x0, x1 = min(d[0], d[2]), max(d[0], d[2])
        ymin = min(d[1], d[3]); ymax = max(d[1], d[3])
        up = (d[3] > d[1]) == (d[2] > d[0])          # 좌→우로 상승?
        colx = round(x0 - 131.8, 1)                  # 좌측 레일 x
        gap = round((x1 + 131.8) - colx)             # 레일 간격 (650/900)
        grp_a = []
        for i, a in enumerate(arcs):
            if used_a[i]: continue
            if any(near(pe, de) for pe in arc_ends(a) for de in [(d[0], d[1]), (d[2], d[3])]):
                grp_a.append(i)
        for i in grp_a: used_a[i] = True
        # 관통/터미널 판정: 정션 구간을 레일이 관통하는가
        jlo, jhi = ymin - 500.0, ymax + 500.0
        def thru(cx2):
            return any(a2 <= jlo and b2 >= jhi for a2, b2 in railspan[round(cx2, 1)])
        thruL, thruR = thru(colx), thru(colx + gap)
        sfx = '' if gap == 900 else '_650'
        tc = ((d[0]+d[2])/2.0, (d[1]+d[3])/2.0)
        if thruL == thruR:
            # 관통 = N분기 (LEFT=하행, RIGHT=상행 — 미러 불필요)
            blk = 'BRANCH N ' + ('RIGHT' if up else 'LEFT') + sfx
            parts.setdefault(blk, dict(lines=[], arcs=[], catalog=True))
            out.append(('I', blk, tc[0], tc[1], xa_of(colx), 2, 1, 1))   # 타깃=대각 중심
        else:
            # 터미널(합류) = 바이패스
            term = 'L' if not thruL else 'R'
            tiv = railspan[round(colx if term == 'L' else colx + gap, 1)]
            below = any(a2 < jlo for a2, b2 in tiv)
            junct = 'top' if below else 'bottom'     # top=터미널 레일이 정션 아래에 존재(위끝 합류)
            blk0, sx, sy = BP_MAP[(term, 'UP' if up else 'DN', junct)]
            blk = blk0 + sfx
            parts.setdefault(blk, dict(lines=[], arcs=[], catalog=True))
            out.append(('I', blk, tc[0], tc[1], xa_of(colx), 2, sx, sy))  # 타깃=대각 중심
    # 1350존 바450+호2 (4차선 넓은형 아치/보타이) → DOUBLE BRANCH 2CH (카탈로그, 레일조각 포함)
    #  2CH: 레일 0/1350 y0~1035, 바 (450,650)-(900,650), 호 c=(450/900,200) — 정방향=바 위(650), 상하미러=바 아래
    used_l = set()
    for li, l in enumerate(lines):
        if abs(l[1]-l[3]) >= 1 or l in rails: continue
        x0, x1 = min(l[0], l[2]), max(l[0], l[2])
        y = l[1]
        if abs((x1-x0)-450.0) > 1: continue
        if y < Y0+1500 or y > Y0+L0-1500: continue   # 끝단 캡(2차선 450바)은 원형 유지 — 캡 루프로
        colx = round(x0 - 450.0, 1)
        if colx not in railx or round(colx+1350.0, 1) not in railx: continue
        grp_a = []
        for i, a in enumerate(arcs):
            if used_a[i]: continue
            if any(near(pe, q) for pe in arc_ends(a) for q in [(x0, y), (x1, y)]):
                grp_a.append(i)
        if len(grp_a) != 2: continue
        acy = arcs[grp_a[0]][1]
        upward = acy < y                     # 호 중심이 바 아래 = 정방향(2CH 원형)
        for i in grp_a: used_a[i] = True
        used_l.add(li)
        parts.setdefault('DOUBLE BRANCH 2CH', dict(lines=[], arcs=[], catalog=True))
        # 타깃 = (갭 좌레일 x, 바 y). 삽입점은 조립 시점에 part_ref(CH_BX, CH_BBAR)로 환산
        out.append(('I', 'DOUBLE BRANCH 2CH', colx, y, xa_of(colx), 2, 1, 1 if upward else -1))
    # 캡·보타이·아치(바+호2) — 원형(호-직-호) 배출. 단, W갭의 ∩∪ 700쌍 보타이는 '#BOWTIE'로 병합
    #  (#BOWTIE: 네이티브=원형, 가로 스트레치=DOUBLE BRANCH_700 세로 − 직 − 세로. "다른 레일도 마찬가지")
    bow_cand = []   # [바y, x0, x1, ya_, ori('up'=∩하단/'dn'=∪상단), grp_a]
    for li, l in enumerate(lines):
        if abs(l[1]-l[3]) >= 1 or l in rails or li in used_l: continue
        x0, x1 = min(l[0], l[2]), max(l[0], l[2])
        y = l[1]
        if (x1-x0) < 1.0:                    # 900 반원의 0-길이 꼭지 잔선 → 반원 파츠 단계로
            used_l.add(li)
            continue
        if any(x0 < rx < x1 for rx in railx) and (x1-x0) <= 500: continue   # 외부 출입구(짧은 관통)만 뒤에서
        grp_a = []
        for i, a in enumerate(arcs):
            if used_a[i]: continue
            if any(near(pe, q) for pe in arc_ends(a) for q in [(x0, y), (x1, y)]):
                grp_a.append(i)
        if len(grp_a) != 2: continue
        used_l.add(li)
        cap = (abs(y-(Y0+450)) < 1 or abs(y-(Y0+L0-450)) < 1) and (x1-x0) > 100   # 2차선 캡 바=450도 포함
        ya_ = (0 if y < Y0+L0/2 else 1) if cap else 2
        if cap:
            # 캡: 바만 원형(끝 고정), 코너 호는 소비하지 않고 QMAP으로 → BRANCH L/R 파츠 매칭 (사용자 지시)
            out.append(('L', x0, y, x1, y, xa_of(x0), xa_of(x1), ya_, ya_))
            continue
        for i in grp_a: used_a[i] = True
        if wvar and abs((x0-450.0)-railx[gi-1]) < 1 and abs((x1+450.0)-railx[gi]) < 1:
            ori = 'up' if arcs[grp_a[0]][1] < y else 'dn'   # 호중심<바 = ∩(하단 반쪽)
            bow_cand.append([y, x0, x1, ya_, ori, grp_a])
            continue
        # 미쌍 보타이 = 호-직-호 원형 그대로 (파츠 없음, 레일 무분할)
        for i in grp_a:
            a = arcs[i]
            east = (round(a[3]) % 360) in (0, 270)            # 시작각 0/270 = 우레일 접선(NE/SE)
            rx = a[0] + (450.0 if east else -450.0)
            out.append(('A', a[0], a[1], a[2], a[3], a[4], xa_of(rx), ya_))
        out.append(('L', x0, y, x1, y, xa_of(x0), xa_of(x1), ya_, ya_))
    # W갭 보타이 ∩(바y)+∪(y+700) 쌍 → '#BOWTIE' I엔트리 (타깃=갭 좌레일, 하단바)
    bow_used = set()
    for ai, ca in enumerate(bow_cand):
        if ai in bow_used or ca[4] != 'up': continue
        for bi, cb in enumerate(bow_cand):
            if bi in bow_used or cb[4] != 'dn': continue
            if abs(cb[0] - (ca[0] + 700.0)) < 1 and abs(cb[1] - ca[1]) < 1:
                parts.setdefault('#BOWTIE', dict(lines=[], arcs=[]))
                out.append(('I', '#BOWTIE', ca[1] - 450.0, ca[0], xa_of(ca[1] - 450.0), 2, 1, 1))
                bow_used.add(ai); bow_used.add(bi)
                break
    for k, ca in enumerate(bow_cand):        # 미쌍 반쪽 → 원형 배출
        if k in bow_used: continue
        y, x0, x1, ya_, ori, grp_a = ca
        for i in grp_a:
            a = arcs[i]
            east = (round(a[3]) % 360) in (0, 270)
            out.append(('A', a[0], a[1], a[2], a[3], a[4], xa_of(a[0] + (450.0 if east else -450.0)), ya_))
        out.append(('L', x0, y, x1, y, xa_of(x0), xa_of(x1), ya_, ya_))
    # 900갭 반원(같은 중심 호쌍 ∩/∪) → DOUBLE BRANCH 2CH_900 (0-기반 파츠, 바 없음)
    cgroups = defaultdict(list)
    for i, a in enumerate(arcs):
        if used_a[i] or abs(a[2]-450.0) > 0.5: continue
        cgroups[(round(a[0], 1), round(a[1], 1))].append(i)
    for (scx, scy), idxs in cgroups.items():
        if len(idxs) != 2: continue
        keys = sorted(round(arcs[i][3]) % 360 for i in idxs)
        if keys == [0, 90]: sy = 1        # 0~90 + 90~180 = ∩
        elif keys == [180, 270]: sy = -1  # 180~270 + 270~360 = ∪
        else: continue
        if round(scx-450.0, 1) not in railx or round(scx+450.0, 1) not in railx: continue
        ya_ = 0 if scy < Y0+1500 else (1 if scy > Y0+L0-1500 else 2)
        parts.setdefault('DOUBLE BRANCH 2CH_900', dict(lines=[], arcs=[], catalog=True))
        # 타깃 = (좌레일 x, 반원 꼭지 y=바레벨). part_ref=(0,650)
        out.append(('I', 'DOUBLE BRANCH 2CH_900', scx-450.0, scy + sy*450.0, xa_of(scx-450.0), ya_, 1, sy))
        for i in idxs: used_a[i] = True
    # 낱개 코너 호(중간 외부 출입) → BRANCH LEFT/RIGHT 파츠 (사분면 매핑; 끝단 플레어는 위에서 원형 처리)
    #  NE=BL / NW=BR / SE=BL(y미러) / SW=BR(y미러). 타깃=호 중심. 호 r450·90°만.
    QMAP = {(0, 90): ('BRANCH LEFT', 1), (90, 180): ('BRANCH RIGHT', 1),
            (270, 0): ('BRANCH LEFT', -1), (270, 360): ('BRANCH LEFT', -1), (180, 270): ('BRANCH RIGHT', -1)}
    for i, a in enumerate(arcs):
        if used_a[i]: continue
        key = (round(a[3]) % 360, round(a[4]) % 360)
        qm = QMAP.get(key) or QMAP.get((key[0], key[1] if key[1] else 360))
        if qm is None or abs(a[2]-450.0) > 0.5: continue          # 비표준 → 뒤에서 경고
        if abs(a[1] - Y0) < 50 or abs(a[1] - (Y0 + L0)) < 50:
            # 끝 플레어(호 중심=레일 끝 행) = 호 원형 유지 — 파츠 스텁/오버행 금지 (사용자: "파란 부분 하지마")
            east = (round(a[3]) % 360) in (0, 270)
            out.append(('A', a[0], a[1], a[2], a[3], a[4],
                        xa_of(a[0] + (450.0 if east else -450.0)), 1 if a[1] > Y0 + L0/2 else 0))
            used_a[i] = True
            continue
        blk, sy = qm
        ya = 0 if a[1] < Y0+1500 else (1 if a[1] > Y0+L0-1500 else 2)
        parts.setdefault(blk, dict(lines=[], arcs=[], catalog=True))
        out.append(('I', blk, a[0], a[1], xa_of(a[0]), ya, 1, sy))   # 타깃=호 중심
        used_a[i] = True
    # ∩+∪ 쌍(하단바 간격 700) → DOUBLE BRANCH 4CH / 4CH_900 병합 (파츠 원형 유지)
    #  타깃 형식이라 직접 비교: 같은 좌레일 x + ∪바 = ∩바+700
    for fam, big in [('DOUBLE BRANCH 2CH', 'DOUBLE BRANCH 4CH'),
                     ('DOUBLE BRANCH 2CH_900', 'DOUBLE BRANCH 4CH_900')]:
        for ku in [k for k, e in enumerate(out) if e and e[0] == 'I' and e[1] == fam and e[7] > 0]:
            eu = out[ku]
            for kd in [k for k, e in enumerate(out) if e and e[0] == 'I' and e[1] == fam and e[7] < 0]:
                ed = out[kd]
                if abs(ed[2] - eu[2]) < 1 and abs(ed[3] - (eu[3] + 700.0)) < 1:
                    parts.setdefault(big, dict(lines=[], arcs=[], catalog=True))
                    out[ku] = ('I', big, eu[2], eu[3], eu[4], eu[5], 1, 1)
                    out[kd] = None
                    break
        out[:] = [e for e in out if e is not None]
    # 레일: 전체 길이로 배출 — 부품 점유 구간 분할은 조립 시점(Fill)에 현재 치수로 수행
    #  (매니페스트에서 분할하면 비율 앵커가 구멍을 늘리는데 파츠는 강체라 세로 스트레치 시 끊김)
    for l in rails:
        rx = l[0]
        ylo, yhi = sorted([l[1], l[3]])
        ya0 = 0 if abs(ylo-Y0) < 1 else 2
        ya1 = 1 if abs(yhi-(Y0+L0)) < 1 else 2
        out.append(('L', rx, ylo, rx, yhi, xa_of(rx), xa_of(rx), ya0, ya1))
    # 캡/보타이/아치 바 + 외부 출입구(스텁 그룹 → 파츠)
    for li, l in enumerate(lines):
        if abs(l[1]-l[3]) >= 1 or l in rails or li in used_l: continue
        x0, x1 = min(l[0], l[2]), max(l[0], l[2])
        y = l[1]
        crossing = any(x0 < rx < x1 for rx in railx)
        cap = (abs(y-(Y0+450)) < 1 or abs(y-(Y0+L0-450)) < 1) and (x1-x0) > 100   # 2차선 캡 바=450도 포함
        ya = 0 if y < Y0+L0/2 else 1
        if cap:
            out.append(('L', x0, y, x1, y, xa_of(x0), xa_of(x1), ya, ya))
        elif crossing:
            # 외부 출입구: 스텁 라인 + 붙은 호들 = rigid 파츠 (기준 = 교차 레일 x, 스텁 y)
            rx = [r for r in railx if x0 < r < x1][0]
            grp_a = []
            for i, a in enumerate(arcs):
                if used_a[i]: continue
                if any(near(pe, q) for pe in arc_ends(a) for q in [(x0, y), (x1, y)]):
                    grp_a.append(i)
            rel_l = [[x0-rx, 0.0, x1-rx, 0.0]]
            rel_a = [[arcs[i][0]-rx, arcs[i][1]-y, arcs[i][2], arcs[i][3], arcs[i][4]] for i in grp_a]
            sig = 'EXIT_' + '_'.join('%d' % round(v) for a2 in rel_a for v in a2[:2]) + '_%d' % round(rel_l[0][0])
            pname = None
            for k, pv in parts.items():
                if pv.get('sig') == sig: pname = k; break
            if pname is None:
                pname = 'RP_EXIT%d' % (sum(1 for k in parts if k.startswith('RP_EXIT'))+1)
                parts[pname] = dict(lines=rel_l, arcs=rel_a, sig=sig)
            for i in grp_a: used_a[i] = True
            out.append(('I', pname, rx, y, xa_of(rx), 2, 1, 1))
        else:            # 보타이/아치 바 (비율, 신축 대상 → 직선 유지)
            out.append(('L', x0, y, x1, y, xa_of(x0), xa_of(x1), 2, 2))
    # 남은 호(캡/보타이/아치 코너, 90° r450) → 코너 파츠 RP_COR_{NE,NW,SW,SE} (기준=호 중심)
    QUAD = {(0, 90): 'NE', (90, 180): 'NW', (180, 270): 'SW', (270, 0): 'SE', (270, 360): 'SE'}
    for i, a in enumerate(arcs):
        if used_a[i]: continue
        cy = a[1]
        if cy < Y0+1500: ya = 0
        elif cy > Y0+L0-1500: ya = 1
        else: ya = 2
        key = (round(a[3]) % 360, round(a[4]) % 360)
        q = QUAD.get((key[0], key[1] if key[1] != 0 else 0)) or QUAD.get(key)
        if q is None or abs(a[2]-450) > 0.5:
            print('  경고: 비표준 호 %s %s' % (name, a)); out.append(('A', a[0], a[1], a[2], a[3], a[4], xa_of(a[0]), ya)); continue
        pname = 'RP_COR_' + q
        if pname not in parts:
            parts[pname] = dict(lines=[], arcs=[[0.0, 0.0, a[2], key[0], key[1] if key[1] else 360.0]])
        out.append(('I', pname, a[0], a[1], xa_of(a[0]), ya, 1, 1))
    return wn, out

# 첫/끝 분기 클러스터를 끝 기준 앵커(ya 0/1)로 — 세로 신축 시 끝여백 1800 유지 (전 블록 표준)
def anchor_ends(out):
    feats = []                       # (ymin, ymax, out인덱스) — 레일 제외 중간(ya=2) 요소
    for k, o in enumerate(out):
        if o[0] == 'I':
            if o[5] != 2: continue
            # 파츠 실제 세로 범위 (점 취급하면 마개-정션이 갈라져 신축 시 끊김)
            nm, ty, sy = o[1], o[3], o[7]
            if nm == '#BOWTIE':
                feats.append((ty - 450.0, ty + 1150.0, k))
            else:
                pr = part_rails(nm, parts)
                if pr:
                    ref = part_ref(nm)
                    iy = ty - sy * ref[1]
                    ys = [iy + sy * v for p in pr for v in (p[1], p[2])]
                    feats.append((min(ys), max(ys), k))
                else:
                    feats.append((ty, ty, k))
        elif o[0] == 'A':
            if o[7] == 2: feats.append((o[2]-o[3], o[2]+o[3], k))
        elif o[0] == 'L':
            vert_rail = abs(o[1]-o[3]) < 1 and abs(o[2]-o[4]) > 3000
            if not vert_rail and o[7] == 2 and o[8] == 2:
                feats.append((min(o[2], o[4]), max(o[2], o[4]), k))
    if len(feats) < 2: return out, 0.0, 0.0, []
    feats.sort()
    clusters = [[feats[0]]]
    for f in feats[1:]:
        if f[0] <= max(x[1] for x in clusters[-1]) + 1600.0: clusters[-1].append(f)
        else: clusters.append([f])
    if len(clusters) < 2: return out, 0.0, 0.0, []
    first = {k for _, _, k in clusters[0]}
    last = {k for _, _, k in clusters[-1]}
    f_ext = (min(t[0] for t in clusters[0]), max(t[1] for t in clusters[0]))
    l_ext = (min(t[0] for t in clusters[-1]), max(t[1] for t in clusters[-1]))
    out2 = []
    for k, o in enumerate(out):
        o = list(o)
        if k in first:
            if o[0] == 'I': o[5] = 0
            elif o[0] == 'A': o[7] = 0
            else: o[7] = o[8] = 0
        elif k in last:
            if o[0] == 'I': o[5] = 1
            elif o[0] == 'A': o[7] = 1
            else: o[7] = o[8] = 1
        elif o[0] == 'L' and abs(o[1]-o[3]) < 1 and abs(o[2]-o[4]) > 3000:
            # 분기에서 끝나는 레일의 내부 끝점: 첫/끝 클러스터에 닿으면 해당 끝 기준 고정
            if o[7] == 2 and f_ext[0]-600 <= o[2] <= f_ext[1]+600: o[7] = 0
            if o[7] == 2 and l_ext[0]-600 <= o[2] <= l_ext[1]+600: o[7] = 1
            if o[8] == 2 and f_ext[0]-600 <= o[4] <= f_ext[1]+600: o[8] = 0
            if o[8] == 2 and l_ext[0]-600 <= o[4] <= l_ext[1]+600: o[8] = 1
        out2.append(tuple(o))
    # F0=첫 클러스터 상단, F1=끝 클러스터 하단에서 위끝까지, mids=중간 그룹 [ymin,ymax] (모두 frame)
    #  → 신축 시 그룹은 강체, 그룹 사이 "빈 구간"들이 전부 같은 비율 K로 늘어나도록 그룹별 이동
    mids = [(min(t[0] for t in c) - Y0, max(t[1] for t in c) - Y0) for c in clusters[1:-1]]
    return out2, f_ext[1] - Y0, (Y0 + L0) - l_ext[0], mids

# 출력 이름 = 「레일 네이밍 규칙.xlsx」 R{차선}_W{N분기 폭}_{H}H_{N}N_{D}D  (H=DOUBLE BRANCH 4CH/보타이, N=BRANCH N, D=DOUBLE BRANCH 쌍)
#  도면 블록은 옛 이름(rail3_01 …)으로 읽고, C# 매니페스트에 쓸 때만 치환한다. 리본 순서/인덱스는 불변.
NEW_NAME = {
    'rail3_01': 'R3_W900_1H_2N',      'rail3_02': 'R3_W650_1H_2N',
    'rail3_03': 'R3_W900_2H_2N',      'rail3_04': 'R3_W650_2H_2N',
    'rail3_05': 'R3_W900_1H_2N_2D',   'rail3_06': 'R3_W650_1H_2N_2D',
    'rail3_07': 'R3_W900_2H_2N_1D',   'rail3_08': 'R3_W650_2H_2N_1D',
    'rail34_top_01': 'R3_W900_1H_4N', 'rail34_top_02': 'R3_W650_1H_4N',
    'rail34_top_05': 'R3_W900_1H_4N_2D', 'rail34_top_06': 'R3_W650_1H_4N_2D',
    'rail4_top_01': 'R4_W650_2H_4N',  'rail4_top_02': 'R4_W650_1H_4N',
    'rail4_top_03': 'R4_W900_1H_4N',  'rail4_top_04': 'R4_W900_2H_4N',      # ※ 엑셀(03=2H, 04=1H)과 반대 — 형상(4CH 수 03=1, 04=2)에 맞춤, 사용자 결정 2026-09-06
    'rail4_top_05': 'R4_W650_1H_4N_1D', 'rail4_top_06': 'R4_W900_1H_4N_1D',
    'rail4_top_07': 'R4_W650_2H_4N_2D', 'rail4_top_08': 'R4_W900_2H_4N_2D',
    'rail4_bottom_01': 'R4_W650_2H_2N', 'rail4_bottom_02': 'R4_W650_1H_2N',
    'rail4_bottom_03': 'R4_W900_1H_2N', 'rail4_bottom_04': 'R4_W900_2H_2N',
    'rail4_bottom_05': 'R4_W650_1H_2N_2D', 'rail4_bottom_06': 'R4_W900_1H_2N_2D',
    'rail4_bottom_07': 'R4_W650_2H_2N_1D', 'rail4_bottom_08': 'R4_W900_2H_2N_1D',
    'rail34_bottom_02': 'R4_W900_1H_4N',  # ※ rail4_top_03 과 이름 중복(형상도 거의 같음) — 사용자 결정으로 그대로 둠
    'rail34_bottom_06': 'R4_W900_1H_4N_2D',
    '2rail_1': 'R2_W1350_1H',  '2rail_H2': 'R2_W1350_2H', '2rail_H3': 'R2_W1350_3H', '2rail_H4': 'R2_W1350_4H',
    '2rail_W900_H1': 'R2_W900_1H', '2rail_W900_H2': 'R2_W900_2H', '2rail_W900_H3': 'R2_W900_3H', '2rail_W900_H4': 'R2_W900_4H',
}

# 소스 순서 = 리본 순서: 3차선(0716 8 + 신형 4) → 4차선(0716 16 + 신형 2) → 2차선(2rail 8) = 38종
for fn, lanes, names in [('3차선_0716', 3, ['rail3_%02d' % i for i in range(1, 9)]),
                          ('3,4차선', 3, ['rail34_top_01', 'rail34_top_02', 'rail34_top_05', 'rail34_top_06']),
                          ('4차선_0716', 4, ['rail4_top_%02d' % i for i in range(1, 9)]
                                            + ['rail4_bottom_%02d' % i for i in range(1, 9)]),
                          ('3,4차선', 4, ['rail34_bottom_02', 'rail34_bottom_06']),
                          ('2차선', 2, ['2rail_1', '2rail_H2', '2rail_H3', '2rail_H4',
                                        '2rail_W900_H1', '2rail_W900_H2', '2rail_W900_H3', '2rail_W900_H4'])]:
    doc = ezdxf.readfile(BASE + '\\' + fn + '.dxf')
    for nm in names:
        b = doc.blocks.get(nm)
        wn, out = classify(nm, lanes, b)
        f0v, f1v, gmids = 0.0, 0.0, []
        if lanes >= 3:
            out, f0v, f1v, gmids = anchor_ends(out)   # 끝여백 1800 신축 불변 + 그룹/빈구간 균일비율 (2차선은 전체 비율)
        variants.append((nm, lanes, wn, out, f0v, f1v, gmids))
        print('%s: 엔티티 %d (I=%d)' % (nm, len(out), sum(1 for o in out if o[0] == 'I')))

# ── C# 생성 ──
w = io.StringIO()
w.write('// 자동생성: gen_manifest.py — 0716 도면 24종 변형 매니페스트 (수정 금지)\n')
w.write('using System.Collections.Generic;\n\nnamespace RailPlugin\n{\n')
w.write('    // 엔티티: L=[x1,y1,x2,y2,xa1,xa2,ya1,ya2] A=[cx,cy,r,a0,a1,xa,ya] I=[partIdx,tx,ty,xa,ya,sx,sy]\n')
w.write('    //  y는 native-450 (레일 하단=0). ya: 0=하단고정 1=상단고정(L-(59100-y)) 2=비율(y*L/59100)\n')
w.write('    //  xa: 0=고정 1=W기준(x+(W-Wn))\n')
w.write('    //  I의 (tx,ty)=타깃 앵커(대각중심/호중심/바레벨) — 삽입점은 PartRef로 환산(파츠 강체 유지).\n')
w.write('    //  레일(L 수직)은 전장 — 부품 점유(PartRails) 분할은 조립 시점에 수행. 좌표=정수 mm.\n')
w.write('    public static class Rail34Manifest\n    {\n')
w.write('        public const double L0 = 59100.0;\n')
w.write('        // DOUBLE BRANCH 2CH 내부 기준 (폭 변경 시 분해 재구성용)\n')
w.write('        public const double CH_BX = %r, CH_BLO = %r, CH_BBAR = %r, CH_BHI = %r;\n' % (CH_BX, CH_BLO, CH_BBAR, CH_BHI))
w.write('        // DOUBLE BRANCH 4CH 내부 기준 (좌레일x, 레일하단y, 하단바y)\n')
w.write('        public const double C4_X = %r, C4_LO = %r, C4_BAR = %r;\n' % (C4_X, C4_LO, C4_BAR))
for _nm in ('BRANCH LEFT', 'BRANCH RIGHT'):          # 3피스 분해(런타임)용 상시 등록
    parts.setdefault(_nm, dict(lines=[], arcs=[], catalog=True))
pn = sorted(parts.keys())
w.write('        public static readonly string[] PartNames = { %s };\n' % ', '.join('"%s"' % p for p in pn))
w.write('        // 부품 지오메트리 (앵커 상대): 라인[x1,y1,x2,y2], 호[cx,cy,r,a0,a1]\n')
def arr(items, fmt):
    if not items: return 'new double[0][]'
    return 'new[]{ %s }' % ', '.join('new[]{%s}' % ','.join(fmt % v for v in it) for it in items)
w.write('        public static readonly double[][][] PartLines = {\n')
for p in pn:
    w.write('            %s,\n' % arr(parts[p]['lines'], '%.4f'))
w.write('        };\n')
w.write('        public static readonly double[][][] PartArcs = {\n')
for p in pn:
    w.write('            %s,\n' % arr(parts[p]['arcs'], '%.4f'))
w.write('        };\n')
w.write('        // 부품 내부 앵커 (I타깃 → 삽입점 = X(tx)−sx·ref / Y(ty)−sy·ref)\n')
w.write('        public static readonly double[][] PartRef = {\n')
for p in pn:
    r = part_ref(p)
    w.write('            new[]{%r, %r},\n' % (float(r[0]), float(r[1])))
w.write('        };\n')
w.write('        // 부품 내부 수직 레일조각 [x,lo,hi] (삽입점 상대) — 조립 시점 레일 분할용\n')
w.write('        public static readonly double[][][] PartRails = {\n')
for p in pn:
    w.write('            %s,\n' % arr(part_rails(p, parts), '%.4f'))
w.write('        };\n')
w.write('        public class Variant { public string Name; public int Lanes; public double Wn; public double F0; public double F1; public double[][] G; public double[][] L; public double[][] A; public double[][] I; }\n')
w.write('        public static readonly List<Variant> Variants = new List<Variant>\n        {\n')
def arr2(xs):
    return 'new double[0][]' if not xs else 'new[]{ %s }' % ', '.join(xs)
for nm, lanes, wn, out, f0v, f1v, gmids in variants:
    # 좌표 소수점 제거(정수 mm 반올림) — 각도만 소수 유지
    Ls = ['new double[]{%d,%d,%d,%d,%d,%d,%d,%d}' % (round(o[1]), round(o[2]-Y0), round(o[3]), round(o[4]-Y0), o[5], o[6], o[7], o[8]) for o in out if o[0] == 'L']
    As = ['new double[]{%d,%d,%d,%.4f,%.4f,%d,%d}' % (round(o[1]), round(o[2]-Y0), round(o[3]), o[4], o[5], o[6], o[7]) for o in out if o[0] == 'A']
    Is = ['new double[]{%d,%d,%d,%d,%d,%d,%d}' % (pn.index(o[1]), round(o[2]), round(o[3]-Y0), o[4], o[5], o[6], o[7]) for o in out if o[0] == 'I']
    Gs = ['new double[]{%d,%d}' % (round(g[0]), round(g[1])) for g in gmids]
    w.write('            new Variant{ Name="%s", Lanes=%d, Wn=%.1f, F0=%d, F1=%d,\n' % (NEW_NAME.get(nm, nm), lanes, wn, round(f0v), round(f1v)))
    w.write('                G=%s,\n' % arr2(Gs))
    w.write('                L=%s,\n' % arr2(Ls))
    w.write('                A=%s,\n' % arr2(As))
    w.write('                I=%s },\n' % arr2(Is))
w.write('        };\n    }\n}\n')
open(OUT, 'w', encoding='utf-8').write(w.getvalue())
print('부품 %d종: %s' % (len(pn), pn))
print('출력:', OUT)
