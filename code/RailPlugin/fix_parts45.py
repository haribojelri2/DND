# -*- coding: utf-8 -*-
# 부품 세트 DXF 수정: 호 각도 45° 통일 + 650 바이패스 등록.
#   - zw$16F7 (650 관통): 41° → 45° 재작성 (0-기반 유지)
#   - BRANCH BY PASS LEFT/RIGHT (900 터미널): 41° → 45° (기존 앵커 좌표 유지)
#   - BRANCH BY PASS LEFT_650 / RIGHT_650: 신규 등록 (45°, 0-기반)
#   45° 공통 문법(zw$1FBD와 동일): 인셋 131.8=450(1-cos45°), 접선존 318.2=450·sin45°
import ezdxf, math, shutil, os

P = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf'
BAK = P + '.bak'
if not os.path.exists(BAK):
    shutil.copy(P, BAK)
    print('백업:', BAK)

doc = ezdxf.readfile(P)
S = 450.0 * math.sin(math.radians(45))     # 318.198
INS = 450.0 - 450.0 * math.cos(math.radians(45))  # 131.802

def clear(b):
    for e in list(b):
        b.delete_entity(e)

def xover_through(b, gap, dn=True, ox=0.0, oy=0.0):
    """관통 크로스오버(N분기) 45°. dn=True: 하행(우하→좌상 이동), False: 상행. 레일 0/gap."""
    dx = gap - 2 * INS
    ylo = 114.6
    yhi = ylo + 2 * S + dx
    H = yhi + 114.6
    b.add_line((ox+0, oy+0), (ox+0, oy+H))
    b.add_line((ox+gap, oy+0), (ox+gap, oy+H))
    if dn:
        # 하단 호(우레일 접점) → 대각(우하→좌상) → 상단 호(좌레일 접점)
        b.add_line((ox+gap-INS, oy+ylo+S), (ox+INS, oy+ylo+S+dx))
        b.add_arc((ox+gap-450.0, oy+ylo), 450.0, 0, 45)
        b.add_arc((ox+450.0, oy+yhi), 450.0, 180, 225)
    else:
        # 하단 호(좌레일 접점) → 대각(좌하→우상) → 상단 호(우레일 접점)
        b.add_line((ox+INS, oy+ylo+S), (ox+gap-INS, oy+ylo+S+dx))
        b.add_arc((ox+450.0, oy+ylo), 450.0, 135, 180)
        b.add_arc((ox+gap-450.0, oy+yhi), 450.0, 315, 360)
    return H

def bypass(b, gap, left, ox=0.0, oy=0.0):
    """터미널(합류) 크로스오버 45°. left=True: 풀레일 좌측·스텁 우측(BY PASS LEFT형)."""
    dx = gap - 2 * INS
    if left:
        b.add_line((ox+gap, oy+0), (ox+gap, oy+200.0))                        # 스텁 (터미널 레일 끝단)
        b.add_arc((ox+gap-450.0, oy+200.0), 450.0, 0, 45)
        b.add_line((ox+gap-INS, oy+200.0+S), (ox+INS, oy+200.0+S+dx))         # 대각 (우하→좌상)
        b.add_arc((ox+450.0, oy+200.0+2*S+dx), 450.0, 180, 225)
        b.add_line((ox+0, oy+0), (ox+0, oy+200.0+2*S+dx+200.0))               # 풀 레일 (관통측)
    else:
        b.add_line((ox+0, oy+0), (ox+0, oy+200.0))
        b.add_arc((ox+450.0, oy+200.0), 450.0, 135, 180)
        b.add_line((ox+INS, oy+200.0+S), (ox+gap-INS, oy+200.0+S+dx))         # 대각 (좌하→우상)
        b.add_arc((ox+gap-450.0, oy+200.0+2*S+dx), 450.0, 315, 360)
        b.add_line((ox+gap, oy+0), (ox+gap, oy+200.0+2*S+dx+200.0))

# 1) zw$16F7 → 45° 650 관통 (0-기반 유지; 참고용 존치)
b = doc.blocks.get('zw$16F7')
clear(b)
H = xover_through(b, 650.0, dn=True)
print('zw$16F7: 45° 재작성 (높이 %.1f)' % H)

# 2) BRANCH N LEFT/RIGHT (900 관통) → 45° (기존 앵커 유지). LEFT=하행, RIGHT=상행.
b = doc.blocks.get('BRANCH N LEFT')
clear(b); xover_through(b, 900.0, dn=True, ox=42092.6, oy=49650.9)
b = doc.blocks.get('BRANCH N RIGHT')
clear(b); xover_through(b, 900.0, dn=False, ox=44168.9, oy=49900.9)
print('BRANCH N LEFT/RIGHT: 45° 재작성')

# 3) N분기 650 신규 등록 (0-기반)
for nm, dn in [('BRANCH N LEFT_650', True), ('BRANCH N RIGHT_650', False)]:
    if nm in doc.blocks:
        b = doc.blocks.get(nm); clear(b)
    else:
        b = doc.blocks.new(nm)
    xover_through(b, 650.0, dn=dn)
    print('%s: 등록 (45°)' % nm)

# 4) BRANCH BY PASS LEFT/RIGHT → 45° (기존 앵커 유지)
b = doc.blocks.get('BRANCH BY PASS LEFT')
clear(b); bypass(b, 900.0, True, ox=42092.6, oy=46523.2)
b = doc.blocks.get('BRANCH BY PASS RIGHT')
clear(b); bypass(b, 900.0, False, ox=43918.9, oy=46523.2)
print('BRANCH BY PASS LEFT/RIGHT: 45° 재작성')

# 5) 650 바이패스 신규 등록
for nm, left in [('BRANCH BY PASS LEFT_650', True), ('BRANCH BY PASS RIGHT_650', False)]:
    if nm in doc.blocks:
        b = doc.blocks.get(nm); clear(b)
    else:
        b = doc.blocks.new(nm)
    bypass(b, 650.0, left)
    print('%s: 등록 (45°)' % nm)

doc.saveas(P)
a = ezdxf.readfile(P).audit()
print('저장 완료. AUDIT errors=%d' % len(a.errors))
