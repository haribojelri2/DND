# -*- coding: utf-8 -*-
"""N분기·BY PASS 부품의 수직 레일 길이를 도면 기입 치수(1670 / _650은 1420)에 맞춤.

문제: 기입 치수는 1670 인데 실측이 달랐다 — N 계열 1502(접점 114.6), BY PASS 계열 1672.8(접점 200).
해결: 호가 레일에 닿는 접점을 전 계열 198.6 으로 통일.
      호 2개(45°)+대각선의 세로 이동량이 본체 1272.79 / _650 1022.79 이므로
      1272.79 + 198.6*2 = 1670.0,  1022.79 + 198.6*2 = 1420.0 (둘 다 정확히 떨어짐).
      호·대각선은 건드리지 않는다 → 조립 앵커(대각 중심) 불변.

규칙: 부품 하단 = min(호 접점 y) − 198.6,  부품 상단 = max(호 접점 y) + 198.6.
      각 수직선의 끝이 원래 부품 하단/상단에 닿아 있었으면 새 값으로 옮기고,
      호에 접하는 쪽 끝(BY PASS 짧은 스텁의 위끝 등)은 접점 그대로 둔다.
멱등: 이미 맞춰진 블록은 변화 없음.
"""
import sys, io, math, shutil, os
import ezdxf

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DXF = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf'
CONTACT = 198.6
TARGETS = ['BRANCH N LEFT', 'BRANCH N RIGHT', 'BRANCH N LEFT_650', 'BRANCH N RIGHT_650',
           'BRANCH BY PASS LEFT', 'BRANCH BY PASS RIGHT',
           'BRANCH BY PASS LEFT_650', 'BRANCH BY PASS RIGHT_650']
EPS = 0.6

bak = DXF + '.bak_pre1670'
if not os.path.exists(bak):
    shutil.copy2(DXF, bak)
    print(f'백업 생성: {os.path.basename(bak)}')

doc = ezdxf.readfile(DXF)
changed = 0
for nm in TARGETS:
    blk = doc.blocks.get(nm)
    if blk is None:
        print(f'[건너뜀] {nm}: 블록 없음'); continue
    arcs = [e for e in blk if e.dxftype() == 'ARC']
    rails = [e for e in blk if e.dxftype() == 'LINE'
             and abs(e.dxf.start.x - e.dxf.end.x) < EPS
             and abs(e.dxf.start.y - e.dxf.end.y) > 1]
    if len(arcs) != 2 or not rails:
        print(f'[건너뜀] {nm}: 예상 형상 아님 (ARC {len(arcs)} / 수직 LINE {len(rails)})'); continue

    # 호가 수직선에 닿는 접점 (호 끝점 중 수직선 x 위에 있는 것)
    contacts = []          # (x, y)
    for a in arcs:
        c, r = a.dxf.center, a.dxf.radius
        for ang in (a.dxf.start_angle, a.dxf.end_angle):
            t = math.radians(ang)
            px, py = c.x + r*math.cos(t), c.y + r*math.sin(t)
            if any(abs(px - rl.dxf.start.x) < EPS for rl in rails):
                contacts.append((px, py))
    if not contacts:
        print(f'[건너뜀] {nm}: 레일 접점 없음'); continue

    new_bot = min(p[1] for p in contacts) - CONTACT
    new_top = max(p[1] for p in contacts) + CONTACT
    old_bot = min(min(r.dxf.start.y, r.dxf.end.y) for r in rails)
    old_top = max(max(r.dxf.start.y, r.dxf.end.y) for r in rails)

    report = []
    for rl in rails:
        s, e = rl.dxf.start, rl.dxf.end
        x = s.x
        lo, hi = min(s.y, e.y), max(s.y, e.y)
        # 부품 하단/상단에 닿아 있던 끝만 새 값으로 이동
        nlo = new_bot if abs(lo - old_bot) < EPS else lo
        nhi = new_top if abs(hi - old_top) < EPS else hi
        rl.dxf.start = (x, nlo, 0)
        rl.dxf.end   = (x, nhi, 0)
        report.append(f'x={x:.1f}: {hi-lo:.1f}→{nhi-nlo:.1f}')

    print(f'{nm}: 하단 {old_bot:.1f}→{new_bot:.1f} / 상단 {old_top:.1f}→{new_top:.1f}   ' + ',  '.join(report))
    changed += 1

if changed:
    doc.saveas(DXF)
    print(f'\n저장 완료: {changed}개 블록 처리')
