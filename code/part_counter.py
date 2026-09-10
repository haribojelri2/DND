# -*- coding: utf-8 -*-
"""정형화 부품(분기 레일 형상 세트) 수량 집계 — map 변환 시 함께 산출.

RailPlugin/RailPluginZw 로 작도한 도면에서 부품 블록을 재귀로 세어
`<도면이름>_parts.csv` 로 내보낸다.

식별 규칙
---------
- 부품      : 블록명이 ``BRANCH`` / ``DOUBLE BRANCH`` 로 시작 (카탈로그가 늘어도 자동 대응)
- 레일 래퍼 : ``RAIL_<guid>`` — 부품이 아니라 그 안을 파고들어 조립된 부품을 센다
- 내부 템플릿: ``RP_`` (직선 스케일 파츠 등) — 형상 조각이라 부품에서 제외

레일이 여러 번 삽입되면 그 안의 부품도 삽입 횟수만큼 집계된다(참조를 따라가므로 자동).
"""
from __future__ import annotations

import csv
from collections import Counter
from typing import Dict, Optional

MAX_DEPTH = 8                       # 중첩 블록 방어
SKIP_PREFIXES = ("RP_",)            # 내부 형상 템플릿(직선 등)
PART_PREFIXES = ("BRANCH", "DOUBLE BRANCH")

PART_APP = "RAILPART"               # 조립체 태그 RegApp (플러그인이 새김)
ROLE_MAIN = 0                       # 대표 — 이것만 센다
ROLE_SUB = 1                        # 종속 — 이중 계산 방지로 제외

# 블록명 정규화: 폭 변형을 한 부품으로 모은다.
#  [사용자 규칙] 고정폭 집합(900·1020·1270·1350)을 DOUBLE BRANCH 4CH 하나의 단위로 인식.
#  → 900 전용 블록(_900)도 같은 이름으로 묶고 폭만 다르게 표기한다.
CANON_NAME = {
    "DOUBLE BRANCH 2CH_900": "DOUBLE BRANCH 2CH",
    "DOUBLE BRANCH 4CH_900": "DOUBLE BRANCH 4CH",
    "BRANCH N LEFT_650": "BRANCH N LEFT",
    "BRANCH N RIGHT_650": "BRANCH N RIGHT",
    "BRANCH BY PASS LEFT_650": "BRANCH BY PASS LEFT",
    "BRANCH BY PASS RIGHT_650": "BRANCH BY PASS RIGHT",
}
# 블록 자체의 고유 폭(조립이 아닌 원형 파츠로 배치됐을 때)
NATIVE_WIDTH = {
    "DOUBLE BRANCH 2CH": 1350, "DOUBLE BRANCH 4CH": 1350,
    "DOUBLE BRANCH 2CH_900": 900, "DOUBLE BRANCH 4CH_900": 900,
    "DOUBLE BRANCH": 650, "DOUBLE BRANCH_700": 700, "DOUBLE BRANCH_1000": 1000,
    "BRANCH N LEFT": 900, "BRANCH N RIGHT": 900,
    "BRANCH N LEFT_650": 650, "BRANCH N RIGHT_650": 650,
    "BRANCH BY PASS LEFT": 900, "BRANCH BY PASS RIGHT": 900,
    "BRANCH BY PASS LEFT_650": 650, "BRANCH BY PASS RIGHT_650": 650,
}


def canon_key(name: str):
    """블록명 → 집계 키 (부품명, 폭). 폭 개념이 없는 부품은 (이름, "")."""
    n = (name or "").strip()
    w = NATIVE_WIDTH.get(n)
    return (CANON_NAME.get(n, n), w if w is not None else "")


def is_part_name(name: str) -> bool:
    """블록명이 정형화 부품인가."""
    n = (name or "").strip().upper()
    if not n or n.startswith("*"):
        return False
    if any(n.startswith(p) for p in SKIP_PREFIXES):
        return False
    return any(n.startswith(p) for p in PART_PREFIXES)


def read_tag(e):
    """조립체 태그 → (논리 부품명, 폭, 역할). 태그가 없으면 None.

    표준 폭(900·1350)이 아니면 U턴 브릿지가 호-직-호나 BRANCH 3피스로 '조립'되어
    블록명으로는 셀 수 없다. 플러그인이 대표 엔티티에 새겨둔 이 태그로 1개로 집계한다.
    """
    try:
        xd = e.get_xdata(PART_APP)
    except Exception:
        return None
    name, width, role = None, 0.0, ROLE_MAIN
    for code, val in xd:
        if code == 1000 and name is None:
            name = str(val)
        elif code == 1040:
            width = float(val)
        elif code == 1070:
            role = int(val)
    return (name, width, role) if name else None


def count_parts(doc) -> Counter:
    """모델공간을 훑어 부품 수량을 센다.

    - 레일 래퍼(RAIL_*) 안까지 전개
    - 조립체는 태그(RAILPART)를 따라 논리 부품 1개로 집계
    키: 부품명 또는 (부품명, 폭)
    """
    counter: Counter = Counter()

    def scan_tags(layout, mult: int):
        """블록/모델공간 안의 조립체 태그(비 INSERT 포함)를 집계."""
        for e in layout:
            tag = read_tag(e)
            if tag is None:
                continue
            name, width, role = tag
            if role == ROLE_MAIN:
                counter[(name, round(width))] += mult

    def walk(layout, depth: int, chain: tuple, mult: int):
        if depth > MAX_DEPTH:
            return
        scan_tags(layout, mult)
        for e in layout:
            if e.dxftype() != "INSERT":
                continue
            name = e.dxf.name
            # MINSERT(배열 삽입) 대응 — 보통 1×1
            m = mult * max(1, int(getattr(e.dxf, "row_count", 1) or 1)) \
                     * max(1, int(getattr(e.dxf, "column_count", 1) or 1))
            tag = read_tag(e)
            if tag is not None:
                # 조립체 구성원 — 대표는 scan_tags 가 이미 셌고, 어느 쪽이든 개별 부품으로는 세지 않는다
                continue
            if is_part_name(name):
                counter[canon_key(name)] += m
                continue                       # 부품 내부는 더 들어가지 않는다
            if name in chain:                  # 순환 참조 방어
                continue
            blk = doc.blocks.get(name)
            if blk is None:
                continue
            walk(blk, depth + 1, chain + (name,), m)

    walk(doc.modelspace(), 0, (), 1)
    return counter


def count_geometry(doc) -> dict:
    """부품에 속하지 않은 직선/호의 개수와 총 길이(mm).

    제외 대상
    ---------
    - 부품 블록(``BRANCH`` / ``DOUBLE BRANCH``) 내부의 모든 형상
    - 조립체 구성 요소(RAILPART 태그가 붙은 엔티티 — 호·바 전부)

    포함 대상
    ---------
    - 레일 직선: ``RP_RAIL_V`` / ``RP_BAR_H`` 스케일 파츠 → 블록을 파고들어
      변환 행렬을 적용하므로 실제 길이가 그대로 잡힌다.
    - 그 밖의 LINE / ARC
    """
    import math
    from ezdxf.math import Matrix44

    st = {"line_count": 0, "line_len": 0.0, "arc_count": 0, "arc_len": 0.0}

    def walk(layout, m, depth: int, chain: tuple):
        if depth > MAX_DEPTH:
            return
        for e in layout:
            t = e.dxftype()
            if read_tag(e) is not None:        # 조립체 구성 = 부품 취급
                continue
            if t == "LINE":
                a, b = m.transform(e.dxf.start), m.transform(e.dxf.end)
                st["line_count"] += 1
                st["line_len"] += math.dist((a.x, a.y), (b.x, b.y))
            elif t == "ARC":
                c = m.transform(e.dxf.center)
                # 반지름은 변환의 크기 배율을 적용(균일 스케일 가정)
                p = m.transform((e.dxf.center.x + e.dxf.radius, e.dxf.center.y, 0))
                r = math.dist((c.x, c.y), (p.x, p.y))
                sweep = (e.dxf.end_angle - e.dxf.start_angle) % 360.0
                st["arc_count"] += 1
                st["arc_len"] += r * math.radians(sweep)
            elif t == "INSERT":
                name = e.dxf.name
                if is_part_name(name) or name in chain:
                    continue                    # 부품 내부는 세지 않는다
                blk = doc.blocks.get(name)
                if blk is None:
                    continue
                mm = Matrix44.chain(
                    Matrix44.scale(e.dxf.xscale, e.dxf.yscale, e.dxf.zscale or 1),
                    Matrix44.z_rotate(math.radians(e.dxf.rotation)),
                    Matrix44.translate(e.dxf.insert.x, e.dxf.insert.y, 0), m)
                walk(blk, mm, depth + 1, chain + (name,))

    walk(doc.modelspace(), Matrix44(), 0, ())
    return st


def _split_key(key):
    """집계 키 → (부품명, 폭문자열). 폭이 없는 항목은 빈 칸."""
    if isinstance(key, tuple):
        name, w = key
        return name, ("" if w == "" or w is None else str(w))
    return key, ""


def save_parts_csv(path: str, counter: Counter, extra: Optional[Dict[str, int]] = None,
                   geom: Optional[dict] = None) -> int:
    """부품 수량 + (선택) 직선·호 통계를 CSV 로 저장. 반환=총 수량.

    geom 은 count_geometry() 결과 — 부품에 속하지 않은 직선/호만 집계된 값이다.
    """
    rows = sorted(counter.items(), key=lambda kv: (_split_key(kv[0])[0], -kv[1]))
    total = sum(counter.values())
    # 엑셀에서 바로 열리도록 UTF-8 BOM
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["부품명", "폭", "수량"])
        for key, n in rows:
            name, width = _split_key(key)
            w.writerow([name, width, n])
        if extra:
            for k, v in extra.items():
                w.writerow([k, "", v])
        w.writerow(["합계", "", total])
        if geom:
            w.writerow([])
            w.writerow(["형상(부품 제외)", "개수", "총 길이(mm)"])
            w.writerow(["직선", geom["line_count"], round(geom["line_len"], 1)])
            w.writerow(["호", geom["arc_count"], round(geom["arc_len"], 1)])
            w.writerow(["합계", geom["line_count"] + geom["arc_count"],
                        round(geom["line_len"] + geom["arc_len"], 1)])
    return total


def table_lines(counter: Counter, geom: Optional[dict] = None) -> list:
    """표 문자열 목록 (AutoCAD RAILCOUNT 와 같은 모양). GUI 로그·콘솔 공용."""
    rows = sorted(counter.items(), key=lambda kv: (_split_key(kv[0])[0],
                                                   int(_split_key(kv[0])[1] or 0)))
    out = [f"{'부품명':<26} {'폭':>6} {'수량':>5}", "-" * 42]
    for key, n in rows:
        name, width = _split_key(key)
        out.append(f"{name:<26} {width:>6} {n:>5}")
    out.append("-" * 42)
    out.append(f"{len(counter)}종 {sum(counter.values())}개")
    if geom:
        out.append("")
        out.append(f"{'형상(부품 제외)':<20} {'개수':>7} {'총 길이(mm)':>14}")
        out.append("-" * 42)
        out.append(f"{'직선':<20} {geom['line_count']:>7} {geom['line_len']:>14,.1f}")
        out.append(f"{'호':<20} {geom['arc_count']:>7} {geom['arc_len']:>14,.1f}")
    return out


def print_table(counter: Counter, geom: Optional[dict] = None) -> None:
    """콘솔에 표로 출력."""
    for line in table_lines(counter, geom):
        print(line)


def summary_text(counter: Counter) -> str:
    """로그용 한 줄 요약."""
    if not counter:
        return "부품 없음"
    def label(key):
        name, width = _split_key(key)
        return f"{name}(W{width})" if width else name
    top = ", ".join(f"{label(k)} {v}" for k, v in
                    sorted(counter.items(), key=lambda kv: -kv[1])[:3])
    return f"{len(counter)}종 {sum(counter.values())}개 (최다: {top})"


# ── 단독 실행: 부품 수량만 빠르게 확인 ──────────────────────────────────────
#   python part_counter.py <도면.dxf>          → 표만 출력
#   python part_counter.py <도면.dxf> --csv    → <도면이름>_parts.csv 도 저장
if __name__ == "__main__":
    import sys
    from pathlib import Path

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    want_csv = "--csv" in sys.argv
    if not args:
        print("사용법: python part_counter.py <도면.dxf> [--csv]")
        raise SystemExit(1)

    import ezdxf
    path = Path(args[0])
    doc = ezdxf.readfile(str(path))
    parts = count_parts(doc)
    geom = count_geometry(doc)
    if not parts and not geom["line_count"] and not geom["arc_count"]:
        print("집계할 형상이 없습니다 (플러그인으로 작도한 도면인지 확인하세요).")
        raise SystemExit(0)
    print_table(parts, geom)
    if want_csv:
        out = path.parent / (path.stem + "_parts.csv")
        save_parts_csv(str(out), parts, geom=geom)
        print(f"\n저장됨: {out}")
