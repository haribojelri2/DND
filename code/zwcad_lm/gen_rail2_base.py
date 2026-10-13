# -*- coding: utf-8 -*-
"""
ZWCAD LM 플렉시블 블록용 2차선 레일 "기준 지오메트리" 생성기.

RailPlugin/Commands.cs 의 RailGeom.Build 를 이식.
정적(static) 블록 "RAIL2" 를 담은 DXF 를 만든다.
→ ZWCAD LM 에서 이 DXF 를 열고 BEDIT RAIL2 로 들어가 선형 파라미터/스트레치/이동 액션을
  추가하면 "플렉시블 블록"이 된다. (파라미터 저작은 코드로 불가 = BEDIT 수작업)

플렉시블 블록 스트레치 프레임을 잡기 쉽도록, 조인트/캡/throat 를 y 위치로 구분할 수 있게
콘솔에 각 그룹의 y 좌표를 출력한다.

★ 지오메트리 관계식(호가 바·edge 에 정확히 맞물리도록 — 이 관계가 깨지면 틈이 생김):
    NECK = HALF_W - R           (호 바깥 끝이 edge 에 닿음)
    ARC_DY = R + BAR_DY         (조인트 호 안쪽 끝이 바에 닿음)
    THROAT_ARC_DY = R + THROAT_BAR_DY
  → R 을 바꾸면 NECK/ARC_DY/THROAT_ARC_DY 가 자동으로 따라옴(아래 식이 처리).
"""
import math
import ezdxf

# ── 자유 파라미터(설계 선택) ─────────────────────────────
HALF_W = 960.0            # edge x 위치 (폭 절반, 전체폭 1920) — 폭 유지
R = 450.0                 # 모든 호(arc) 반지름
BAR_DY = 325.0            # 조인트 바 y 오프셋 (중심에서)
THROAT_BAR_DY = 680.0     # throat 바 (끝에서)
MINLEN = 2000.0           # 최소 길이

# ── 종속 파라미터(관계식으로 자동 계산 — 손대지 말 것) ─────
NECK = HALF_W - R                    # = 510. 바 절반길이 · 호 center x
ARC_DY = R + BAR_DY                  # = 775. 조인트 호 center y 오프셋
THROAT_ARC_DY = R + THROAT_BAR_DY    # = 1130. throat 호 center (끝에서)

# ── 기준(base) 길이 / 조인트 위치(길이 대비 비율) ─────────
BASE_LEN = 30000.0
JOINT_FRACS = [0.25, 0.75]   # 조인트 2개: 1/4, 3/4 지점. ← 플렉시블 블록 "거리 배율기" 값과 동일


def build(msp, length, joint_fracs):
    """지오메트리를 msp 에 그린다. (실제 length, 조인트 y 리스트) 반환."""
    if length < MINLEN:
        length = MINLEN

    def line(x0, y0, x1, y1):
        msp.add_line((x0, y0), (x1, y1))

    def arc(cx, cy, a0, a1):
        # ezdxf add_arc: 각도는 도(degree), CCW. Commands.cs Arc 와 동일 관례.
        msp.add_arc((cx, cy), R, a0, a1)

    # 세로 edge 2개 (x=±HALF_W, y 0→length)
    line(-HALF_W, 0, -HALF_W, length)
    line(HALF_W, 0, HALF_W, length)

    # 양 끝 입구(flare) — AddEndCaps
    cxo = HALF_W + R  # = 1410 (edge 바깥으로 R). 이 값이면 캡 호가 edge 에 자동으로 맞물림
    arc(-cxo, 0, 270, 360)
    arc(cxo, 0, 180, 270)
    arc(-cxo, length, 0, 90)
    arc(cxo, length, 90, 180)

    # 입구 throat — AddEndThroats
    line(-NECK, THROAT_BAR_DY, NECK, THROAT_BAR_DY)
    arc(-NECK, THROAT_ARC_DY, 180, 270)
    arc(NECK, THROAT_ARC_DY, 270, 360)
    line(-NECK, length - THROAT_BAR_DY, NECK, length - THROAT_BAR_DY)
    arc(-NECK, length - THROAT_ARC_DY, 90, 180)
    arc(NECK, length - THROAT_ARC_DY, 0, 90)

    # 내부 조인트 — joint_fracs 위치
    joint_ys = []
    for frac in joint_fracs:
        yc = length * frac
        joint_ys.append(yc)
        line(-NECK, yc - BAR_DY, NECK, yc - BAR_DY)
        line(-NECK, yc + BAR_DY, NECK, yc + BAR_DY)
        arc(-NECK, yc - ARC_DY, 90, 180)
        arc(NECK, yc - ARC_DY, 0, 90)
        arc(-NECK, yc + ARC_DY, 180, 270)
        arc(NECK, yc + ARC_DY, 270, 360)

    return length, joint_ys


def main():
    doc = ezdxf.new("R2018", setup=True)
    doc.units = 4  # mm
    doc.header["$INSUNITS"] = 4

    # 블록 정의 "RAIL2" 에 지오메트리 (원점 기준, 축=+Y)
    blk = doc.blocks.new(name="RAIL2")
    length, joint_ys = build(blk, BASE_LEN, JOINT_FRACS)

    # 모델스페이스에 인서트 1개
    msp = doc.modelspace()
    msp.add_blockref("RAIL2", (0, 0))

    out = "rail2_base.dxf"
    doc.saveas(out)

    # 저작 참고용 출력 (스트레치 프레임 위치 + 조인트 거리배율기)
    print(f"[OK] {out} 생성. base length={length:.0f}, joints={len(joint_ys)}")
    print(f"  상수: HALF_W={HALF_W:.0f} R={R:.0f} NECK={NECK:.0f} ARC_DY={ARC_DY:.0f} THROAT_ARC_DY={THROAT_ARC_DY:.0f}")
    print(f"  하단 끝(고정단)      y = 0")
    print(f"  하단 throat bar      y = {THROAT_BAR_DY:.0f}")
    print(f"  하단 throat arc c    y = {THROAT_ARC_DY:.0f}")
    for i, (yc, frac) in enumerate(zip(joint_ys, JOINT_FRACS)):
        print(f"  조인트#{i+1} 중심     y = {yc:.1f}   (= length*{frac})   → 거리배율기 = {frac}")
    print(f"  상단 throat bar      y = {length - THROAT_BAR_DY:.0f}")
    print(f"  상단 끝(이동단)      y = {length:.0f}")


if __name__ == "__main__":
    main()
