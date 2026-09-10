# -*- coding: utf-8 -*-
"""최종 맵 → DXF 역변환.

`map_to_cad` 는 **ori 맵** 전용이다. ori 는 clearance 이전이라 곡선 링크가 순수한
호(또는 호-직-호)여서 그대로 되풀 수 있다.

**최종 맵은 다르다.** clearance 단계에서 곡선 링크가 양옆 직선을 접선 방향으로
빨아들여, 링크 하나가 `직선 + 곡선 + 직선` 복합 형상이 된다. 실측(260410, R450):

    ori  L/R 707 (90° 호)          →  최종 L/R 1407 · 2307
    ori  U   1414 (반원)            →  최종 U   2114 (= 350 + 1414 + 350)
    ori  N   1253 · 1607            →  최종 N   1953 · 2307

이걸 순수 호로 알고 현+길이로 반지름을 역산하면 450 이 안 나오고, 형상이 찌그러져
재변환 시 N 분기 판정이 무너진다. 그래서 **접선 직선을 분리해서** 복원한다.

## 푸는 방법

링크를 `직선(s0) + 코어 + 직선(s1)` 으로 본다. 시작점 P0, 끝점 P1, 링크 길이 Lk,
시작 접선 t0(이웃 직선 링크에서 얻음), 표준 반지름 R 을 안다고 할 때

    P1 - P0 = s0·t0 + D(코어) + s1·t1(코어)      … 위치 2식
    s0 + (코어 길이) + s1 = Lk                    … 길이 1식

코어 자유변수를 하나 훑으면서(호 스윕 θ, U 의 중간직선, N 의 대각선) 각 값마다
위 3식을 s0, s1 에 대해 최소제곱으로 풀고 잔차가 가장 작은 해를 고른다.
(위치식만 쓰면 U 는 t1 = −t0, N 은 t1 = t0 이라 행렬이 특이해져 풀리지 않는다.)

사용법:
    python final_to_cad.py "최종.map" [출력.dxf] [--r 450] [--no-ports] [--merge-lines]
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

from map_to_cad import (
    MapDoc, Primitive, Pt,
    _add, _arc_prim, _build_tangents, _mul, _norm, _perp_left, _rot, _sub,
    load_map, primitive_length, primitives_to_dxf,
)

# 코어 자유변수 탐색 격자. 굵게 훑고 그 주변을 다시 잘게 훑는다(2단계).
_COARSE = 400
_REFINE = 60


# ── 공통 ────────────────────────────────────────────────────────────────────

def _best(core_fn, lo: float, hi: float, p0: Pt, p1: Pt, t0: Pt, total: float):
    """코어 자유변수 x∈[lo,hi] 를 훑어 잔차 최소해를 찾는다.

    core_fn(x) -> (D, t1, core_len)  : 코어가 만드는 변위·끝접선·길이

    위치 2식 + 길이 1식 = 3식 / 미지수 2개(s0, s1) 를 **최소제곱**으로 푼다.
    위치식만 쓰면 U 처럼 t1 = −t0 인 경우 행렬이 특이해져 해가 없다 —
    그때는 길이식이 부족한 한 축을 메운다.

    반환: (잔차, x, s0, s1, D, t1)
    """
    v0 = _sub(p1, p0)
    best = None

    def scan(a: float, b: float, n: int):
        nonlocal best
        if n <= 0 or b <= a:
            return
        for i in range(n + 1):
            x = a + (b - a) * i / n
            got = core_fn(x)
            if got is None:
                continue
            d, t1, clen = got
            v = _sub(v0, d)
            rem = total - clen                  # 남은 직선 길이 s0+s1
            c = t0[0] * t1[0] + t0[1] * t1[1]   # 단위벡터라 내적 = cos
            det = 4.0 - (c + 1.0) ** 2          # AᵀA 의 행렬식
            if abs(det) >= 1e-9:
                b0 = t0[0] * v[0] + t0[1] * v[1] + rem
                b1 = t1[0] * v[0] + t1[1] * v[1] + rem
                s0 = (2.0 * b0 - (c + 1.0) * b1) / det
                s1 = (2.0 * b1 - (c + 1.0) * b0) / det
            else:
                # t1 ∥ t0 — N 분기(차선 변경)는 나가는 방향이 들어온 방향과 같다.
                # 그래서 s0 와 s1 을 따로 정할 수 없다(코어가 구간 어디에 놓이든 끝점이 같다).
                # clearance 가 양끝을 대칭으로(350/350) 물리므로 반씩 나눈다.
                if rem < -1.0:
                    continue
                s0 = s1 = max(0.0, rem) / 2.0
            if s0 < -1.0 or s1 < -1.0:          # 접선 방향이 반대로 나오면 형상이 안 맞는 것
                continue
            ex = s0 * t0[0] + s1 * t1[0] - v[0]
            ey = s0 * t0[1] + s1 * t1[1] - v[1]
            el = s0 + s1 - rem
            r = math.sqrt(ex * ex + ey * ey + el * el)
            if best is None or r < best[0]:
                best = (r, x, max(0.0, s0), max(0.0, s1), d, t1)

    scan(lo, hi, _COARSE)
    if best is not None:                          # 찾은 지점 주변을 다시 잘게
        step = (hi - lo) / _COARSE
        scan(max(lo, best[1] - step), min(hi, best[1] + step), _REFINE)
    return best


def _arc_walk(p: Pt, t: Pt, r: float, sweep: float, turn: int) -> Tuple[Pt, Pt, Pt]:
    """p 에서 접선 t 로 출발, 반지름 r, sweep(rad), turn(+1 좌/−1 우).
    반환 (중심, 끝점, 끝접선)."""
    center = _add(p, _mul(_perp_left(t), r * turn))
    ang = sweep * turn
    return center, _add(center, _rot(_sub(p, center), ang)), _rot(t, ang)


def _emit_arc(out: List[Primitive], center: Pt, r: float, a: Pt, b: Pt, sweep: float, turn: int):
    """스윕이 180° 이상이면 반으로 쪼개서 기록(_arc_prim 이 방향을 판정하지 못하므로)."""
    if sweep < math.pi - 1e-9:
        out.append(_arc_prim(center, r, a, b))
        return
    half = _add(center, _rot(_sub(a, center), (sweep / 2.0) * turn))
    out.append(_arc_prim(center, r, a, half))
    out.append(_arc_prim(center, r, half, b))


def _assemble(p0: Pt, t0: Pt, s0: float, s1: float,
              build_core, tol: float = 1.0) -> List[Primitive]:
    """직선(s0) + 코어 + 직선(s1) 를 프리미티브로 조립."""
    out: List[Primitive] = []
    a = p0
    if s0 > tol:
        a = _add(p0, _mul(t0, s0))
        out.append(("LINE", p0, a))
    b, t1 = build_core(a, out)
    if s1 > tol:
        out.append(("LINE", b, _add(b, _mul(t1, s1))))
    return out


# ── 타입별 분해 ──────────────────────────────────────────────────────────────

def decomp_arc(p0: Pt, p1: Pt, total: float, t0: Pt, turn: int,
               r: float) -> Optional[Tuple[List[Primitive], float]]:
    """L/R — 직선 + 호(θ) + 직선."""
    def core(th):
        if th <= 1e-6:
            return None
        c0 = _mul(_perp_left(t0), r * turn)
        d = _add(c0, _rot(_mul(c0, -1.0), th * turn))
        return d, _rot(t0, th * turn), r * th

    # s0+s1 ≥ 0 이므로 Rθ ≤ 총길이 — 그만큼만 훑는다
    got = _best(core, 0.0, min(2.0 * math.pi, total / r), p0, p1, t0, total)
    if got is None:
        return None
    resid, th, s0, s1, _, _ = got

    def build(a, out):
        center, b, t1 = _arc_walk(a, t0, r, th, turn)
        _emit_arc(out, center, r, a, b, th, turn)
        return b, t1

    return _assemble(p0, t0, s0, s1, build), resid


def decomp_u(p0: Pt, p1: Pt, total: float, t0: Pt,
             r: float) -> Optional[Tuple[List[Primitive], float]]:
    """U — 직선 + 90°호 + 중간직선 + 90°호 + 직선. 회전 방향은 양쪽 다 시도."""
    q = math.pi / 2.0
    best = None
    for turn in (1, -1):
        def core(mid, turn=turn):
            _, p, t = _arc_walk((0.0, 0.0), t0, r, q, turn)
            p = _add(p, _mul(t, mid))
            _, p, t = _arc_walk(p, t, r, q, turn)
            return p, t, math.pi * r + mid

        got = _best(core, 0.0, max(0.0, total - math.pi * r), p0, p1, t0, total)
        if got is not None and (best is None or got[0] < best[0][0]):
            best = (got, turn)
    if best is None:
        return None
    (resid, mid, s0, s1, _, _), turn = best

    def build(a, out):
        c, b, t = _arc_walk(a, t0, r, q, turn)
        _emit_arc(out, c, r, a, b, q, turn)
        if mid > 1.0:
            nb = _add(b, _mul(t, mid))
            out.append(("LINE", b, nb))
            b = nb
        c, b2, t2 = _arc_walk(b, t, r, q, turn)
        _emit_arc(out, c, r, b, b2, q, turn)
        return b2, t2

    return _assemble(p0, t0, s0, s1, build), resid


def decomp_n(p0: Pt, p1: Pt, total: float, t0: Pt, r: float,
             sweep_deg: float = 45.0) -> Optional[Tuple[List[Primitive], float]]:
    """N — 직선 + α호 + 대각선 + 반대방향 α호 + 직선 (표준 α=45°)."""
    a_sw = math.radians(sweep_deg)
    best = None
    for turn in (1, -1):
        def core(diag, turn=turn):
            _, p, t = _arc_walk((0.0, 0.0), t0, r, a_sw, turn)
            p = _add(p, _mul(t, diag))
            _, p, t = _arc_walk(p, t, r, a_sw, -turn)
            return p, t, 2.0 * r * a_sw + diag

        got = _best(core, 0.0, max(0.0, total - 2.0 * r * a_sw), p0, p1, t0, total)
        if got is not None and (best is None or got[0] < best[0][0]):
            best = (got, turn)
    if best is None:
        return None
    (resid, diag, s0, s1, _, _), turn = best

    def build(a, out):
        c, b, t = _arc_walk(a, t0, r, a_sw, turn)
        _emit_arc(out, c, r, a, b, a_sw, turn)
        if diag > 1.0:
            nb = _add(b, _mul(t, diag))
            out.append(("LINE", b, nb))
            b = nb
        c, b2, t2 = _arc_walk(b, t, r, a_sw, -turn)
        _emit_arc(out, c, r, b, b2, a_sw, -turn)
        return b2, t2

    return _assemble(p0, t0, s0, s1, build), resid


# ── 직선 정리 ────────────────────────────────────────────────────────────────

def merge_collinear_lines(prims: List[Primitive], tol: float = 1.0) -> List[Primitive]:
    """같은 직선 위에서 겹치거나 맞닿은 LINE 을 하나로 합친다(ARC 는 그대로).

    링크 하나당 엔티티 하나로 뽑으면 원본에서 한 줄이던 레일이 노드마다 조각나고,
    곡선에서 분리한 접선 직선이 이웃 직선과 같은 자리를 다시 그린다.
    도면을 눈으로 볼 때만 문제인 부분이다.

    **기본으로 끄고 쓴다.** 병합하면 분할점 위치가 미세하게 달라져 재변환 ori 가
    132 → 134 노드로 어긋난다(최종 맵은 그대로). 도면을 넘겨줄 때만 켤 것.
    """
    lines = [p for p in prims if p[0] == "LINE"]
    rest = [p for p in prims if p[0] != "LINE"]

    groups: dict = {}
    for _, a, b in lines:
        d = _sub(b, a)
        n = _norm(d)
        if n < tol:
            continue                                   # 길이 0 조각은 버린다
        u = _mul(d, 1.0 / n)
        if u[0] < 0 or (abs(u[0]) < 1e-9 and u[1] < 0):
            u = _mul(u, -1.0)                          # 방향을 한쪽으로 통일
        nrm = (-u[1], u[0])                            # 왼쪽 법선
        off = _dot_u(a, nrm)                           # 원점에서의 수직 거리(부호 포함)
        # 각도·오프셋을 칸으로 묶어 같은 직선을 찾는다. 복원 좌표에 0.3mm 정도
        # 반올림 오차가 있어 칸을 너무 잘게 나누면 같은 선이 갈라진다.
        key = (round(math.atan2(u[1], u[0]) / 1e-6), round(off / tol))
        s, e = _dot_u(a, u), _dot_u(b, u)
        groups.setdefault(key, (u, nrm, off, []))[3].append((min(s, e), max(s, e)))

    out: List[Primitive] = list(rest)
    for u, nrm, off, spans in groups.values():
        spans.sort()
        cur_s, cur_e = spans[0]
        merged = []
        for s, e in spans[1:]:
            if s <= cur_e + tol:                       # 겹치거나 맞닿음
                cur_e = max(cur_e, e)
            else:
                merged.append((cur_s, cur_e))
                cur_s, cur_e = s, e
        merged.append((cur_s, cur_e))
        # 점 = (진행방향 성분)·u + (수직 오프셋)·n
        base = _mul(nrm, off)
        for s, e in merged:
            out.append(("LINE", _add(base, _mul(u, s)), _add(base, _mul(u, e))))
    return out


def _dot_u(p: Pt, u: Pt) -> float:
    return p[0] * u[0] + p[1] * u[1]


# ── 전체 복원 ────────────────────────────────────────────────────────────────

def reconstruct_final(doc: MapDoc, radius_mm: float = 450.0,
                      resid_tol_mm: float = 5.0) -> Tuple[List[Primitive], List[str]]:
    """최종 맵의 링크를 LINE/ARC 로 복원. (프리미티브, 경고) 반환."""
    import map_to_cad as M

    tan = _build_tangents(doc)
    prims: List[Primitive] = []
    warns: List[str] = []
    n_split = 0

    for lk in doc.links:
        p0, p1 = doc.nodes.get(lk.start), doc.nodes.get(lk.end)
        if p0 is None or p1 is None:
            warns.append(f"링크 {lk.id}: 노드 {lk.start}/{lk.end} 없음 — 건너뜀")
            continue
        if lk.type == "S":
            prims.append(("LINE", p0, p1))
            continue

        t0 = tan.get(lk.start)
        got = None
        if t0 is not None:
            if lk.type in ("L", "R"):
                got = decomp_arc(p0, p1, lk.length, t0, 1 if lk.type == "L" else -1, radius_mm)
            elif lk.type == "U":
                got = decomp_u(p0, p1, lk.length, t0, radius_mm)
            elif lk.type == "N":
                got = decomp_n(p0, p1, lk.length, t0, radius_mm)

        if got is not None and got[1] <= resid_tol_mm:
            out = got[0]
            if any(p[0] == "LINE" for p in out):
                n_split += 1
        else:
            # 분해 실패 — ori 용 복원기로 대체(순수 곡선 가정)
            why = "접선 정보 없음" if t0 is None else f"잔차 {got[1]:.1f}mm" if got else "해 없음"
            warns.append(f"링크 {lk.id}({lk.type}): 분해 실패({why}) → 순수 곡선으로 대체")
            if lk.type in ("L", "R"):
                out, w = M._rebuild_arc(p0, p1, lk.length, lk.type == "L", radius_mm, 5.0)
            elif lk.type == "U":
                out, w = M._rebuild_u(p0, p1, lk.length, t0, radius_mm, 5.0)
            elif lk.type == "N":
                out, w = M._rebuild_n(p0, p1, lk.length, t0, radius_mm, 5.0)
            else:
                out, w = [("LINE", p0, p1)], [f"미지 타입 {lk.type} → 직선"]
            warns.extend(f"링크 {lk.id}({lk.type}): {m}" for m in w)

        end = out[-1][2] if out and out[-1][0] == "LINE" else None
        if end is not None and _norm(_sub(end, p1)) > 2.0:
            warns.append(f"링크 {lk.id}({lk.type}): 끝점 오차 {_norm(_sub(end, p1)):.1f}mm")
        got_len = sum(primitive_length(p) for p in out)
        if abs(got_len - lk.length) > max(2.0, lk.length * 0.005):
            warns.append(f"링크 {lk.id}({lk.type}): 길이 {got_len:.1f} vs 맵 {lk.length:.1f}")
        prims.extend(out)

    warns.insert(0, f"접선 직선을 분리한 곡선 링크: {n_split}개")
    return prims, warns


def final_map_to_dxf(map_path: str | Path, dxf_path: str | Path | None = None, *,
                     radius_mm: float = 450.0, draw_ports: bool = True,
                     merge_lines: bool = False, log=print) -> Path:
    src = Path(map_path)
    out = Path(dxf_path) if dxf_path else src.with_name(src.stem + "_fromFinal.dxf")
    doc = load_map(src)
    log(f"최종 맵 읽음: NODE {len(doc.nodes)} / LINK {len(doc.links)} / PORT {len(doc.ports)}")
    prims, warns = reconstruct_final(doc, radius_mm=radius_mm)
    for w in warns[:40]:
        log("  " + w)
    if len(warns) > 40:
        log(f"  … 경고 {len(warns) - 40}건 더")
    if merge_lines:
        before = sum(1 for p in prims if p[0] == "LINE")
        prims = merge_collinear_lines(prims)
        after = sum(1 for p in prims if p[0] == "LINE")
        log(f"직선 정리: {before} → {after}개 (겹침·조각 병합)")
    ports = doc.ports if draw_ports else None
    primitives_to_dxf(prims, out, ports=ports)
    n_line = sum(1 for p in prims if p[0] == "LINE")
    log(f"DXF 저장: {out}  (LINE {n_line} / ARC {len(prims) - n_line}"
        + (f" / 포트마커 {len(doc.ports)}" if ports else "") + ")")
    return out


if __name__ == "__main__":
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    r = 450.0
    for f in flags:
        if f.startswith("--r"):
            r = float(f.split("=", 1)[1]) if "=" in f else r
    if "--r" in sys.argv:
        r = float(sys.argv[sys.argv.index("--r") + 1])
    final_map_to_dxf(args[0], args[1] if len(args) > 1 else None,
                     radius_mm=r, draw_ports="--no-ports" not in flags,
                     merge_lines="--merge-lines" in flags)
