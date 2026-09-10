# -*- coding: utf-8 -*-
# 부품 세트 DXF에 900폭 U턴 브릿지 등록 (0-기반, 초록 ACI 3).
#   DOUBLE BRANCH 2CH_900: 레일 0/900 (h1035) + 반원(∩) c=(450,200) r450 — 바 없음(스텁간격 0)
#   DOUBLE BRANCH 4CH_900: 레일 0/900 (h2000) + 하단 ∩ c=(450,200) + 상단 ∪ c=(450,1800)
#   원본 1350 대응: 2CH(레일1035, 바650레벨) / 4CH(레일2000, 바 650·1350레벨, 간격 700)
import ezdxf

P = r'C:\Users\User\Desktop\dnd\code\zwcad_lm\dist\분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf'
doc = ezdxf.readfile(P)
G = {'color': 3}

def clear(b):
    for e in list(b):
        b.delete_entity(e)

def mk(nm, four):
    if nm in doc.blocks:
        b = doc.blocks.get(nm); clear(b)
    else:
        b = doc.blocks.new(nm)
    H = 2000.0 if four else 1035.0
    for x in (0.0, 900.0):
        b.add_line((x, 0), (x, H), dxfattribs=G)
    b.add_arc((450.0, 200.0), 450.0, 0, 90, dxfattribs=G)
    b.add_arc((450.0, 200.0), 450.0, 90, 180, dxfattribs=G)
    if four:
        b.add_arc((450.0, 1800.0), 450.0, 270, 360, dxfattribs=G)
        b.add_arc((450.0, 1800.0), 450.0, 180, 270, dxfattribs=G)
    print('%s: 등록 (레일 h%.0f)' % (nm, H))

mk('DOUBLE BRANCH 2CH_900', False)
mk('DOUBLE BRANCH 4CH_900', True)
doc.saveas(P)
a = ezdxf.readfile(P).audit()
print('저장 완료. AUDIT errors=%d' % len(a.errors))
