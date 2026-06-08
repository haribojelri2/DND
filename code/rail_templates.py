"""레일(차선) 템플릿 생성기.

차선 = 직선 레일에 붙은 분기 개수. 2차선부터 시작.
2차선 = test_big.dxf 블록 A$C31676947 의 표준 지오메트리를 그대로 재현:
  - 세로 edge 2개 (x=500, x=2420, y 500→47250) → 레일 폭 1920
  - 호 r=500 20개 + 가로 920 조인트바 → 양끝 캡 + 내부 조인트(bowtie)
프리미티브 형식·DXF/미리보기 함수는 branch_templates와 공유.
좌표는 로컬 원점 기준 — 블록으로 INSERT 후 CAD에서 위치·크기·회전 조정.
"""
from __future__ import annotations
from typing import List, Tuple
from branch_templates import primitives_to_dxf, render_preview  # noqa: F401 (재사용)

Primitive = Tuple


def rail_2lane() -> List[Primitive]:
    """2차선 직선 레일 (블록 A$C31676947 표준 재현)."""
    R = 500.0
    arcs = [  # (cx, cy, start_deg, end_deg)  — CCW start→end
        (0, 500, 270, 0), (1000, 1680, 180, 270), (2920, 500, 180, 270), (1920, 1680, 270, 0),
        (1000, 15370, 90, 180), (1920, 15370, 0, 90), (1000, 17020, 180, 270), (1920, 17020, 270, 0),
        (0, 23700, 270, 0), (0, 21700, 0, 90), (1000, 30720, 90, 180), (1920, 30720, 0, 90),
        (1000, 32370, 180, 270), (1920, 32370, 270, 0), (2920, 23700, 180, 270), (2920, 21700, 90, 180),
        (2920, 47250, 90, 180), (0, 47250, 0, 90), (1000, 46070, 90, 180), (1920, 46070, 0, 90),
    ]
    lines = [  # (x1,y1,x2,y2)
        (500, 47250, 500, 500),        # 좌 edge
        (2420, 47250, 2420, 500),      # 우 edge
        (1000, 1180, 1920, 1180),      # 조인트 바 (920)
        (1000, 15870, 1920, 15870), (1000, 16520, 1920, 16520),
        (1000, 31220, 1920, 31220), (1000, 31870, 1920, 31870),
        (1000, 46570, 1920, 46570),
    ]
    prim: List[Primitive] = []
    for cx, cy, a0, a1 in arcs:
        prim.append(("ARC", (float(cx), float(cy)), R, float(a0), float(a1)))
    for x1, y1, x2, y2 in lines:
        prim.append(("LINE", (float(x1), float(y1)), (float(x2), float(y2))))
    return prim


TEMPLATES = {
    "rail_2lane": rail_2lane,
}
