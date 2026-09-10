# -*- coding: utf-8 -*-
"""모듈 판정 시험 도면 생성기 — 플러그인과 같은 형식(RAILMOD_ 블록 + RAILPLUGIN XData)으로 그린다.

형상은 module_judge.build_local(= RailPlugin ModuleGeom.Build 를 옮긴 것, 플러그인 실물 블록과 0.01mm 일치 확인)을
쓰고, 모듈 사이 직선 레일은 LINE(레이어 RAIL)으로 잇는다. 회로마다 파일 하나(연결 요소 하나)로 만든다.

    python module_testdxf.py <출력폴더>

회로(모두 반시계 주행이 되게 연결)
  A  코너 4방향(회전 0/90/180/270) + 대칭 CURVE RIGHT + BRANCH 분기·합류 곁길
  B  왕복 루프 W=900  : U(반원) 2 + DOUBLE BRANCH(반원)
  C  왕복 루프 W=1350 : U 2 + DOUBLE BRANCH (최종 U, 원본은 U 아님)
  C2 왕복 루프 W=2000 : U 2 + DOUBLE BRANCH (U 아님 → 코너/일반 분기)
  D  U BRANCH LEFT(본선 분기) / U BRANCH RIGHT(역주행 합류) + BRANCH 곁길
  E  이중 루프 : N LEFT(W900, 대각 900) / N RIGHT(W650, 대각 546)
  F  S RIGHT → S LEFT 차선 이동
  G  BY PASS LEFT / BY PASS RIGHT 곁길 합류
  H  Y 두 갈래 → 코너로 줄기 시작 / BRANCH 합류
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import ezdxf

import module_judge as mj

R0, L0 = 450.0, 200.0
S0 = L0 + R0          # CURVE 코너 한 변 = L + R


def _rot(deg, p):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def _num(v: float) -> str:
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return s.replace(".", "p").replace("-", "m")


class Placed:
    def __init__(self, ins, rot, sx):
        self.ins, self.rot, self.sx = ins, rot, sx

    def w(self, p):
        q = _rot(self.rot, (self.sx * p[0], p[1]))
        return (self.ins[0] + q[0], self.ins[1] + q[1])


class Lay:
    def __init__(self):
        self.doc = ezdxf.new("R2018", setup=False)
        self.doc.header["$INSUNITS"] = 4
        if "RAILPLUGIN" not in self.doc.appids:
            self.doc.appids.new("RAILPLUGIN")
        self.doc.layers.add("RAIL", color=1)
        self.msp = self.doc.modelspace()

    def line(self, p, q):
        if math.hypot(q[0] - p[0], q[1] - p[1]) > 1e-6:
            self.msp.add_line(p, q, dxfattribs={"layer": "RAIL"})

    def block(self, idx, r, l, w, a) -> str:
        name, uses_w, uses_a = mj.DEFS[idx]
        bn = "RAILMOD_" + name.replace(" ", "-") + "_R" + _num(r) + "_L" + _num(l)
        if uses_w:
            bn += "_W" + _num(w)
        if uses_a:
            bn += "_A" + _num(a)
        if bn not in self.doc.blocks:
            blk = self.doc.blocks.new(bn)
            pieces, _ = mj.build_local(idx, r, l, w, a)
            for p in pieces:
                if p.kind == "LINE":
                    blk.add_line(p.a, p.b)
                else:
                    a0 = math.degrees(math.atan2(p.a[1] - p.c[1], p.a[0] - p.c[0]))
                    a1 = math.degrees(math.atan2(p.b[1] - p.c[1], p.b[0] - p.c[0]))
                    blk.add_arc(p.c, p.r, a0 % 360.0, a1 % 360.0)
        return bn

    def place(self, name, anchor, at, heading, mirror=False, R=R0, L=L0, W=900.0, A=45.0) -> Placed:
        """모듈 로컬 점 anchor 를 월드 at 에 놓는다. heading = 로컬 +Y 가 향할 월드 방향(도)."""
        idx = mj.DEFS.index(next(d for d in mj.DEFS if d[0] == name))
        r, l, w, a = mj.clamp(idx, R, L, W, A)
        rot = (heading - 90.0) % 360.0
        sx = -1.0 if mirror else 1.0
        q = _rot(rot, (sx * anchor[0], anchor[1]))
        ins = (at[0] - q[0], at[1] - q[1])
        bn = self.block(idx, r, l, w, a)
        e = self.msp.add_blockref(bn, ins, dxfattribs={"rotation": rot, "xscale": sx})
        e.set_xdata("RAILPLUGIN", [(1040, l), (1070, idx), (1070, 7), (1040, w), (1070, 2),
                                   (1040, r), (1040, a)])
        pm = Placed(ins, rot, sx)
        pm.r, pm.l, pm.w_, pm.a = r, l, w, a
        pm.h = mj.cross_rise(r, w, a) if mj.DEFS[idx][2] else 0.0
        return pm

    def save(self, path):
        self.doc.saveas(path)


class Turtle:
    def __init__(self, lay: Lay, p, h):
        self.lay, self.p, self.h = lay, p, h % 360.0

    def _dir(self):
        return (math.cos(math.radians(self.h)), math.sin(math.radians(self.h)))

    def fwd(self, d):
        u = self._dir()
        q = (self.p[0] + d * u[0], self.p[1] + d * u[1])
        self.lay.line(self.p, q)
        self.p = q
        return self

    def to(self, x=None, y=None):
        u = self._dir()
        if x is not None:
            d = (x - self.p[0]) / u[0]
        else:
            d = (y - self.p[1]) / u[1]
        assert d > -1e-6, f"뒤로 가는 선: {d}"
        return self.fwd(d)

    def mod(self, name, entry, exit_, turn=0.0, mirror=False, **par) -> Placed:
        pm = self.lay.place(name, entry, self.p, self.h, mirror, **par)
        self.p = pm.w(exit_(pm) if callable(exit_) else exit_)
        self.h = (self.h + turn) % 360.0
        return pm

    def corner_left(self, **par):
        return self.mod("CURVE LEFT", (0, 0), lambda m: (-m.r - m.l, m.l + m.r), +90, **par)

    def corner_right(self, **par):
        return self.mod("CURVE RIGHT", (0, 0), lambda m: (m.r + m.l, m.l + m.r), -90, **par)


def thru(m):
    return (0.0, 2 * m.l + m.r)


# ─────────────────────────────── 회로 ───────────────────────────────

def circuit_A():
    lay = Lay()
    T = Turtle(lay, (0.0, 0.0), 0)
    T.fwd(1000)
    bd = T.mod("BRANCH RIGHT", (0, 0), thru)                       # 분기: 오른쪽(남)으로
    B = bd.w((bd.r + bd.l, bd.l + bd.r))
    T.fwd(2000)
    # 합류: BRANCH LEFT 를 서쪽 향으로 놓고 역주행(동쪽) — 곁길이 남쪽에서 들어온다
    mg = lay.place("BRANCH LEFT", thru(bd), T.p, 180)
    stub = mg.w((-mg.r - mg.l, mg.l + mg.r))
    T.p = mg.w((0, 0))
    # 곁길
    Ts = Turtle(lay, B, 270)
    Ts.fwd(600).corner_left()
    Ts.to(x=stub[0] - S0).corner_left()
    Ts.to(y=stub[1])
    # 본선 나머지 — 코너 4방향, 하나는 대칭 CURVE RIGHT(좌회전으로 동작)
    T.fwd(800).corner_left()
    T.fwd(2000)
    T.mod("CURVE RIGHT", (0, 0), lambda m: (m.r + m.l, m.l + m.r), +90, mirror=True)
    T.to(x=0.0).corner_left()
    T.to(y=S0).corner_left()
    assert math.hypot(T.p[0], T.p[1]) < 1e-6, T.p
    return lay


def circuit_racetrack(W):
    """동쪽 차선(x=W) 북행, 서쪽 차선(x=0) 남행. 위·아래 U, 가운데 DOUBLE BRANCH."""
    lay = Lay()
    lay.place("U", (0, 0), (W, 0.0), 270, W=W)                     # 아래 U: 로컬 x=0 → 동쪽 차선
    y1 = 1000.0
    db = lay.place("DOUBLE BRANCH", (0, 0), (0.0, y1), 90, W=W)    # 로컬 x=0 = 서쪽, x=W = 동쪽
    top = y1 + 2 * db.l + db.r
    y3 = top + 1200.0
    lay.place("U", (0, 0), (0.0, y3), 90, W=W)                     # 위 U
    lay.line((W, 0.0), (W, y1))
    lay.line((W, top), (W, y3))
    lay.line((0.0, y3), (0.0, top))
    lay.line((0.0, y1), (0.0, 0.0))
    return lay


def circuit_D():
    """동쪽 변(북행): 아래 BRANCH RIGHT(남향 배치, 역주행 합류) + 위 U BRANCH LEFT(본선 분기).
       서쪽 변(남행): 위 U BRANCH RIGHT(북향 배치, 역주행 합류) + 아래 BRANCH LEFT(분기)."""
    lay = Lay()
    Wd = 1500.0
    X, Xw = 8000.0, 0.0
    # 동쪽 변
    yc = 2000.0                                                    # 합류 모듈 북쪽 끝
    mg = lay.place("BRANCH RIGHT", (0, 0), (X, yc), 270)
    south = mg.w(thru(mg))
    ub = lay.place("U BRANCH LEFT", (Wd, 0), (X, yc + 1800.0), 90, W=Wd)
    leg_bot = ub.w((0, 0))
    ub_top = ub.w((Wd, 2 * ub.l + ub.r))
    lay.line((X, yc), ub.w((Wd, 0)))
    # 안쪽 차선: U 다리 아래 → 남행 → 코너(남→동) → 합류 모듈 곁가지 끝
    stub_w = mg.w((mg.r + mg.l, mg.l + mg.r))
    Ti = Turtle(lay, leg_bot, 270)
    Ti.to(y=stub_w[1] + S0).corner_left()
    Ti.to(x=stub_w[0])
    # 서쪽 변 (남행)
    yb = 2000.0                                                    # 분기 모듈 북쪽 끝(남행 진입)
    bl = lay.place("BRANCH LEFT", (0, 0), (Xw, yb), 270)
    bl_s = bl.w(thru(bl))
    port = bl.w((-bl.r - bl.l, bl.l + bl.r))                       # 동쪽(안쪽)으로 분기
    Tb = Turtle(lay, port, 0)
    Tb.to(x=Xw + Wd - S0).corner_left()                            # 동→북
    ur = lay.place("U BRANCH RIGHT", (0, 0), (Xw, yb + 1800.0), 90, W=Wd)
    Tb.to(y=ur.w((Wd, 0))[1])
    ur_top = ur.w(thru(ur))
    lay.line(ur.w((0, 0)), (Xw, yb))
    # 바깥 사각형 연결
    ytop = max(ub_top[1], ur_top[1]) + 1500.0
    T = Turtle(lay, ub_top, 90)
    T.to(y=ytop).corner_left()
    T.to(x=Xw + S0).corner_left()
    T.to(y=ur_top[1])
    T2 = Turtle(lay, bl_s, 270)
    T2.to(y=-1500.0).corner_left()
    T2.to(x=X - S0).corner_left()
    T2.to(y=south[1])
    return lay


def circuit_E():
    """이중 루프(바깥·안쪽 모두 반시계). 동쪽 변 N LEFT(W900), 서쪽 변 N RIGHT(W650)."""
    lay = Lay()
    Xo, Xi = 10000.0, 10000.0 - 900.0          # 동쪽: 바깥, 안쪽
    Xow, Xiw = 0.0, 650.0                      # 서쪽: 바깥, 안쪽
    yn = 3000.0
    ne = lay.place("N LEFT", (0, 0), (Xi, yn), 90, W=900.0)        # 로컬 x=0 안쪽, x=W 바깥
    ne_top = 2 * ne.l + ne.h
    nw = lay.place("N RIGHT", (0, 0), (Xiw, yn + ne_top), 270, W=650.0)   # 남향: 로컬 x=0 안쪽, x=W 바깥
    nw_len = 2 * nw.l + nw.h
    # 바깥 루프
    T = Turtle(lay, (Xo, yn + ne_top), 90)
    T.fwd(1500).corner_left()
    T.to(x=Xow + S0).corner_left()
    T.to(y=yn + ne_top)                        # 서쪽 바깥 차선이 N RIGHT 윗끝(바깥)으로
    T2 = Turtle(lay, (Xow, yn + ne_top - nw_len), 270)
    T2.to(y=0.0 + S0).corner_left()
    T2.to(x=Xo - S0).corner_left()
    T2.to(y=yn)
    # 안쪽 루프
    T3 = Turtle(lay, (Xi, yn + ne_top), 90)
    T3.fwd(800).corner_left()
    T3.to(x=Xiw + S0).corner_left()
    T3.to(y=yn + ne_top)
    T4 = Turtle(lay, (Xiw, yn + ne_top - nw_len), 270)
    T4.to(y=1200.0 + S0).corner_left()
    T4.to(x=Xi - S0).corner_left()
    T4.to(y=yn)
    return lay


def circuit_F():
    """사각 루프 아래 변(동행)에서 S RIGHT 로 남쪽 900 이동 후 S LEFT 로 복귀."""
    lay = Lay()
    T = Turtle(lay, (0.0, 0.0), 0)
    T.fwd(800)
    T.mod("S RIGHT", (0, 0), lambda m: (m.w_, 2 * m.l + m.h), 0, W=900.0)   # 로컬 x=0 → x=W (남쪽으로)
    T.fwd(800)
    T.mod("S LEFT", (900.0, 0.0), lambda m: (0.0, 2 * m.l + m.h), 0, W=900.0)  # 로컬 x=W → x=0 (북쪽으로)
    T.fwd(800).corner_left()
    T.fwd(3000).corner_left()
    T.to(x=0.0).corner_left()
    T.to(y=S0).corner_left()
    assert math.hypot(T.p[0], T.p[1]) < 1e-6, T.p
    return lay


def circuit_G():
    """동쪽 변(북행): BRANCH RIGHT 분기 → 코너 → 곁길 → BY PASS LEFT 합류(W1300).
       서쪽 변(남행): BRANCH LEFT 분기(안쪽) → 코너(우회전) → 곁길 → BY PASS RIGHT 합류(W1500)."""
    lay = Lay()
    X, Xw, y0 = 9000.0, 0.0, 1500.0
    # 동쪽 변(북행)
    T = Turtle(lay, (X, y0), 90)
    T.fwd(800)
    br = T.mod("BRANCH RIGHT", (0, 0), thru)                       # 동쪽(바깥)으로 분기
    port = br.w((br.r + br.l, br.l + br.r))
    Wg = (br.r + br.l) + 600.0 + S0                                # 곁길 간격 = 분기 곁가지 + 직선 600 + 코너
    T.fwd(1500)
    bp = lay.place("BY PASS LEFT", (0, 0), T.p, 90, W=Wg)          # 로컬 x=0 관통, x=W 곁길(끝남)
    leg = bp.w((Wg, 0))
    T.p = bp.w((0, 2 * bp.l + bp.h))
    Ts = Turtle(lay, port, 0)
    Ts.fwd(600).corner_left()                                      # 동→북
    Ts.to(y=leg[1])
    # 위 변 → 서쪽 변(남행)
    T.fwd(1000).corner_left()
    T.to(x=Xw + S0).corner_left()
    T.fwd(800)
    Ww = 1800.0
    bl = T.mod("BRANCH LEFT", (0, 0), thru)                      # 남행 기준 왼쪽 = 동쪽(안쪽)으로 분기
    port2 = bl.w((-bl.r - bl.l, bl.l + bl.r))
    T.fwd(1000)
    bq = lay.place("BY PASS RIGHT", (Ww, 0), T.p, 270, W=Ww)       # 남향: 로컬 x=W 가 관통(서쪽 본선)
    leg2 = bq.w((0, 0))
    T.p = bq.w((Ww, 2 * bq.l + bq.h))
    Tq = Turtle(lay, port2, 0)
    Tq.to(x=Xw + Ww - S0).corner_right()                           # 동→남
    Tq.to(y=leg2[1])
    # 아래 변으로 닫기
    T.to(y=y0).corner_left()
    T.to(x=X - S0).corner_left()
    assert math.hypot(T.p[0] - X, T.p[1] - y0) < 1e-6, T.p
    return lay


def circuit_H():
    """Y 두 갈래: 왼쪽 갈래는 코너 3개로 돌아와 줄기 시작, 오른쪽 갈래는 BRANCH LEFT(남향 배치) 합류."""
    lay = Lay()
    y_ins = 3000.0                                                  # 합류 모듈 북쪽 끝
    mg = lay.place("BRANCH LEFT", (0, 0), (0.0, y_ins), 270)
    south = mg.w(thru(mg))
    stub_e = mg.w((-mg.r - mg.l, mg.l + mg.r))                      # 동쪽 곁가지 끝
    y0 = y_ins + 1200.0
    lay.line((0.0, y_ins), (0.0, y0))
    Y = lay.place("Y", (0, 0), (0.0, y0), 90)
    oL = Y.w((-Y.r - Y.l, Y.l + Y.r))
    oR = Y.w((Y.r + Y.l, Y.l + Y.r))
    TL = Turtle(lay, oL, 180)
    TL.fwd(1000).corner_left()
    TL.to(y=south[1] - 1500.0).corner_left()
    TL.to(x=-S0).corner_left()
    TL.to(y=south[1])
    TR = Turtle(lay, oR, 0)
    TR.fwd(1000).corner_right()
    TR.to(y=stub_e[1] + S0).corner_right()
    TR.to(x=stub_e[0])
    return lay


CIRCUITS = {
    "A": circuit_A,
    "B": lambda: circuit_racetrack(900.0),
    "C": lambda: circuit_racetrack(1350.0),
    "C2": lambda: circuit_racetrack(2000.0),
    "D": circuit_D,
    "E": circuit_E,
    "F": circuit_F,
    "G": circuit_G,
    "H": circuit_H,
}


def main(out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for key, fn in CIRCUITS.items():
        lay = fn()
        p = out / f"module_test_{key}.dxf"
        lay.save(str(p))
        print("saved", p)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
