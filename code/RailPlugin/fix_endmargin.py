# -*- coding: utf-8 -*-
# 3,4차선.dxf — 모델공간에 배치된 6종만: 끝여백(캡 호접점 ↔ 첫/끝 분기 경계) ~6000 → 1800 재배치.
#  ★원래 있던 다른 블록 정의(미배치 rail34 10종·2rail 등)는 수정 금지 (사용자 지시)
#  - 캡/플레어(끝단 1350 이내 접촉)와 레일은 고정
#  - 중간 분기(크로스오버/출입/보타이)는 y-근접 클러스터로 묶어 강체 이동
#  - 첫 클러스터 하단 = 호접점+1800, 끝 클러스터 상단 = 호접점−1800, 중간은 중심 비례 배치
import ezdxf, math, shutil, os

P = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\3,4차선.dxf'
BAK = P + '.bak'
MARGIN = 1800.0
TARGET = ['rail34_top_01', 'rail34_top_02', 'rail34_top_05', 'rail34_top_06',
          'rail34_bottom_02', 'rail34_bottom_06']
if not os.path.exists(BAK):
    shutil.copy(P, BAK)
    print('백업:', BAK)
else:
    shutil.copy(BAK, P)     # 원본 복원 후 대상만 재적용
    print('백업에서 복원:', P)

doc = ezdxf.readfile(P)

def arc_span(e):
    c, r = e.dxf.center, e.dxf.radius
    a0, a1 = e.dxf.start_angle % 360, e.dxf.end_angle % 360
    if a1 <= a0: a1 += 360
    ys = [c.y + r * math.sin(math.radians(a0)), c.y + r * math.sin(math.radians(a1))]
    for q in (90, 270, 450, 630):
        if a0 < q < a1: ys.append(c.y + r * math.sin(math.radians(q % 360)))
    return min(ys), max(ys)

for b in doc.blocks:
    if b.name not in TARGET: continue
    ents = [e for e in b if e.dxftype() in ('LINE', 'ARC')]
    lines = [e for e in ents if e.dxftype() == 'LINE']
    rails = [e for e in lines if abs(e.dxf.start.x-e.dxf.end.x) < 1 and abs(e.dxf.start.y-e.dxf.end.y) > 3000]
    ylo = min(min(e.dxf.start.y, e.dxf.end.y) for e in rails)
    yhi = max(max(e.dxf.start.y, e.dxf.end.y) for e in rails)
    b0, b1 = ylo + 900.0, yhi - 900.0          # 캡 호접점 (레일끝 안쪽 900)
    mid = []                                     # (miny, maxy, e)
    for e in ents:
        if e in rails: continue
        if e.dxftype() == 'LINE':
            mn, mx = sorted([e.dxf.start.y, e.dxf.end.y])
        else:
            mn, mx = arc_span(e)
        if mn < b0 + 10 or mx > b1 - 10: continue   # 끝단 가구(캡/플레어) 고정
        mid.append([mn, mx, e])
    if not mid:
        print('%s: 중간 분기 없음' % b.name); continue
    # y-근접 클러스터링 (간격 1600 이내 병합 — 마개(dome)와 분기 정션은 한 덩어리로 묶여 함께 이동)
    mid.sort(key=lambda t: t[0])
    clusters = [[mid[0]]]
    for t in mid[1:]:
        if t[0] <= max(x[1] for x in clusters[-1]) + 1600.0: clusters[-1].append(t)
        else: clusters.append([t])
    ext = [(min(t[0] for t in c), max(t[1] for t in c)) for c in clusters]
    f0, f1 = ext[0][0], ext[-1][1]
    n0, n1 = b0 + MARGIN, b1 - MARGIN            # 새 전체 경계
    # 중심 비례 사상 (클러스터 강체): 첫 하단→n0, 끝 상단→n1
    c_old = [(a + bb) / 2 for a, bb in ext]
    h = [bb - a for a, bb in ext]
    t0, t1 = c_old[0], c_old[-1]
    nt0, nt1 = n0 + h[0] / 2, n1 - h[-1] / 2
    k = (nt1 - nt0) / (t1 - t0) if len(clusters) > 1 and t1 > t0 else 0.0
    dys = []
    for ci, cl in enumerate(clusters):
        newc = nt0 + (c_old[ci] - t0) * k if len(clusters) > 1 else (n0 + n1) / 2
        dy = newc - c_old[ci]
        dys.append(dy)
        for mn, mx, e in cl:
            if e.dxftype() == 'LINE':
                s, t = e.dxf.start, e.dxf.end
                e.dxf.start = (s.x, s.y + dy, 0)
                e.dxf.end = (t.x, t.y + dy, 0)
            else:
                c = e.dxf.center
                e.dxf.center = (c.x, c.y + dy, 0)
    # 분기에서 끝나는 레일(중간 레일)의 내부 끝점도 해당 클러스터를 따라 이동 (연결 유지)
    nrail = 0
    for e in rails:
        s, t = e.dxf.start, e.dxf.end
        pts = [list(s), list(t)]
        moved = False
        for p in pts:
            if not (b0 + 10 < p[1] < b1 - 10): continue      # 블록 끝단에 닿는 끝점은 고정
            for ci, (a, bb) in enumerate(ext):
                if a - 600 <= p[1] <= bb + 600:
                    p[1] += dys[ci]; moved = True; break
        if moved:
            e.dxf.start = (pts[0][0], pts[0][1], 0)
            e.dxf.end = (pts[1][0], pts[1][1], 0)
            nrail += 1
    print('%s: 클러스터 %d개(dy %s), 레일끝 추종 %d개' % (
        b.name, len(clusters), [round(v) for v in dys], nrail))

try:
    doc.saveas(P)
    out = P
except PermissionError:
    out = P.replace('.dxf', '_end1800.dxf')
    doc.saveas(out)
print('저장:', out)
a = ezdxf.readfile(out).audit()
print('AUDIT errors=%d' % len(a.errors))
