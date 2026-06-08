"""분기 템플릿 생성기.

각 분기 타입(U-tight / U-wide / N / 복합)을 도면 표준 지오메트리(호 반지름 450 등,
test_logic 파이프라인에서 측정)로 그린다. 결과는 원시 프리미티브 리스트:
  ("LINE", (x1,y1), (x2,y2))
  ("ARC",  (cx,cy), r, start_deg, end_deg)   # ezdxf 기준 CCW
같은 정의를 ezdxf(블록 생성)와 matplotlib(미리보기) 양쪽에서 쓴다.
좌표는 로컬 원점 기준 — 블록으로 INSERT 후 CAD에서 위치·크기·회전 조정.
"""
from __future__ import annotations
import math
from typing import List, Tuple, Any

Primitive = Tuple
STD_R = 450.0          # 표준 호 반지름
STD_STUB = 700.0       # 레일 스텁 길이(표준: 복합분기 레일 700)


def _arc_pts(cx, cy, r, a0, a1, n=40):
    a0r, a1r = math.radians(a0), math.radians(a1)
    return [(cx + r * math.cos(a0r + (a1r - a0r) * k / n),
             cy + r * math.sin(a0r + (a1r - a0r) * k / n)) for k in range(n + 1)]


# ── 템플릿 생성기 (로컬 좌표) ────────────────────────────────────────────────
def u_tight(r: float = STD_R, stub: float = STD_STUB) -> List[Primitive]:
    """tight U턴(호-호): 반원 r, 양 끝 레일 간격 2r(=900). 오른쪽으로 돌출."""
    return [
        ("ARC", (0.0, r), r, -90.0, 90.0),         # 반원: (0,0)→(r,r)→(0,2r)
        ("LINE", (0.0, 0.0), (-stub, 0.0)),         # 하단 레일 스텁
        ("LINE", (0.0, 2 * r), (-stub, 2 * r)),     # 상단 레일 스텁
    ]


def u_wide(r: float = STD_R, mid: float = 450.0, stub: float = STD_STUB) -> List[Primitive]:
    """wide U턴(호-직-호): 90°호 + 세로직선(mid) + 90°호. 폭 = 2r+mid."""
    h = 2 * r + mid
    return [
        ("LINE", (0.0, 0.0), (-stub, 0.0)),
        ("ARC", (0.0, r), r, -90.0, 0.0),           # (0,0)→(r,r)
        ("LINE", (r, r), (r, r + mid)),             # 세로 직선
        ("ARC", (0.0, r + mid), r, 0.0, 90.0),      # (r,r+mid)→(0,2r+mid)
        ("LINE", (0.0, h), (-stub, h)),
    ]


def n_branch(r: float = STD_R, h: float = 650.0, stub: float = STD_STUB) -> List[Primitive]:
    """N분기(호-직-호 S자 크로스오버): 45°호 + 대각직선 + 45°호.
    두 평행 수평레일을 수직간격 h만큼 연결. **두 호는 반대방향**(S자)이라야 함.
    하단레일(y=0)→arc1(CCW,위로 휨)→대각45°→arc2(CW,수평 복귀)→상단레일(y=h)."""
    s45, c45 = math.sin(math.radians(45)), math.cos(math.radians(45))
    rise_arc = r * (1 - c45)                          # 호 1개의 수직 상승분
    run_arc = r * s45
    diag = (h - 2 * rise_arc) / s45                   # 대각 직선 길이(h에서 자동)
    if diag < 0:
        diag = 0.0
    p0 = (0.0, 0.0)
    p1 = (run_arc, rise_arc)                          # arc1 끝 (CCW, center 위쪽)
    p2 = (p1[0] + diag * c45, p1[1] + diag * s45)     # 대각 끝
    c2 = (p2[0] + r * c45, p2[1] - r * s45)           # arc2 center (반대쪽)
    p3 = (c2[0], c2[1] + r)                            # arc2 끝 (상단레일)
    return [
        ("LINE", p0, (-stub, 0.0)),                  # 하단 레일 스텁
        ("ARC", (0.0, r), r, -90.0, -45.0),          # arc1: 위로 오목 (CCW쪽)
        ("LINE", p1, p2),                             # 대각 직선 45°
        ("ARC", c2, r, 90.0, 135.0),                 # arc2: 반대로 오목 → 수평 복귀
        ("LINE", p3, (p3[0] + stub, p3[1])),         # 상단 레일 스텁
    ]


def complex_branch(r: float = STD_R, gap: float = 1350.0,
                   railseg: float = STD_STUB) -> List[Primitive]:
    """복합분기(측정 표준 구조): 두 평행 수평레일(간격 gap, 길이 railseg) +
    오른쪽 끝의 안쪽 U(호-직-호) + 왼쪽 끝에서 바깥 호 2개→세로 through-line(길이 gap+2r).
    좌표: 안쪽 U junction=원점(0,0)/(0,-gap), 레일은 -x로 railseg, through-line은 x=-(railseg+r)."""
    top, bot = 0.0, -gap
    im = gap - 2 * r                                  # 안쪽 U 세로직선 길이(=450)
    tx = -(railseg + r)                               # through-line x 위치
    prim: List[Primitive] = []
    # 수평 레일 (오른쪽 안쪽U junction → 왼쪽 바깥 junction)
    prim += [("LINE", (0.0, top), (-railseg, top)), ("LINE", (0.0, bot), (-railseg, bot))]
    # 안쪽 U (왼쪽 -x로 r만큼 돌출, 호-직-호) — 위/아래 레일 직접 연결
    prim += [
        ("ARC", (0.0, top - r), r, 90.0, 180.0),      # (0,top)→(-r,top-r)
        ("LINE", (-r, top - r), (-r, bot + r)),       # 세로 직선
        ("ARC", (0.0, bot + r), r, 180.0, 270.0),     # (-r,bot+r)→(0,bot)
    ]
    # 바깥: 왼쪽 레일끝(-railseg)에서 호→세로 through-line(tx)→호 로 위/아래 연결
    prim += [
        ("ARC", (-railseg, top + r), r, -180.0, -90.0),   # (-railseg,top)↔(tx,top+r)
        ("LINE", (tx, top + r), (tx, bot - r)),            # 세로 through-line
        ("ARC", (-railseg, bot - r), r, 90.0, 180.0),      # (tx,bot-r)↔(-railseg,bot)
    ]
    return prim


TEMPLATES = {
    "U_tight": u_tight,
    "U_wide": u_wide,
    "N": n_branch,
    "complex": complex_branch,
}


# ── ezdxf 출력 ──────────────────────────────────────────────────────────────
def primitives_to_dxf(prims: List[Primitive], out_path: str, *,
                      layer: str = "BRANCH", as_block: bool = True,
                      block_name: str = "BRANCH_SYM") -> None:
    """프리미티브를 새 DXF로 저장. as_block=True면 블록 정의 후 INSERT(크기조정 용이)."""
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.layers.add(layer) if layer not in doc.layers else None
    msp = doc.modelspace()
    if as_block:
        blk = doc.blocks.new(name=block_name)
        target = blk
    else:
        target = msp
    for p in prims:
        if p[0] == "LINE":
            target.add_line(p[1], p[2], dxfattribs={"layer": layer})
        elif p[0] == "ARC":
            _, c, r, a0, a1 = p
            # ezdxf ARC는 CCW start→end (wrap 허용). 정렬하지 말고 그대로 전달.
            target.add_arc(c, r, a0, a1, dxfattribs={"layer": layer})
    if as_block:
        msp.add_blockref(block_name, (0, 0), dxfattribs={"layer": layer})
    doc.saveas(out_path)


# ── 미리보기 (matplotlib) ────────────────────────────────────────────────────
def render_preview(prims: List[Primitive], out_png: str, title: str = "") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 6))
    for p in prims:
        if p[0] == "LINE":
            ax.plot([p[1][0], p[2][0]], [p[1][1], p[2][1]], color="0.4", lw=2)
        elif p[0] == "ARC":
            _, c, r, a0, a1 = p
            aa1 = a1 if a1 > a0 else a1 + 360.0   # CCW wrap (ezdxf와 동일)
            pts = _arc_pts(c[0], c[1], r, a0, aa1)
            ax.plot([x for x, _ in pts], [y for _, y in pts], color="tab:blue", lw=2)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_title(title)
    plt.tight_layout()
    plt.savefig(out_png, dpi=90)
    plt.close()
