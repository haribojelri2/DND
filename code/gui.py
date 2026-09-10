from __future__ import annotations
import json, sys, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import ezdxf
from core import *
from dxf_parser import (collect_entities_recursive, build_edges_raw_no_split_no_unify,
                        clean_edges, scan_entity_colors, scan_entity_layers,
                        scan_colors_and_layers)
from geometry import (split_edges_at_intersections, glue_arc_endpoints_to_lines,
                      snap_segments, reproject_arcs_to_circle,
                      merge_line_segments_at_degree2_nodes)
from topology import unify_edge_directions, insert_clearance_nodes
from map_exporter import (export_map_from_unified_edges,
                          find_un_branch_merge_groups,
                          find_un_branch_merge_groups_by_x, save_map)
from port_extractor import extract_stb_ports, collect_port_nodes_by_color, collect_port_nodes_by_layer
from part_counter import (count_parts, count_geometry, save_parts_csv,
                          summary_text, table_lines)
from map_to_cad import map_to_dxf
from module_judge import ModuleJudge, decide_modules
# 최종 맵 역변환(final_to_cad)은 형상 복원 방식이 달라 GUI 에서 뺐다 — CLI 로만 사용


def _get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


_base = _get_base_dir()
_config_path = _base / "config.json"


def load_cfg() -> dict:
    with open(_config_path, encoding="utf-8-sig") as f:
        return json.load(f)


def save_cfg(cfg: dict):
    with open(_config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _dedup_port_nodes(nodes):
    """좌표(반올림) 기준 중복 포트 제거 — 색상·레이어 양쪽에서 잡힌 포트 합집합."""
    seen = set()
    out = []
    for n in nodes:
        k = (round(n.x), round(n.y))
        if k not in seen:
            seen.add(k)
            out.append(n)
    return out


# ── 파이프라인 (별도 스레드에서 실행) ──────────────────────────────────────
def run_pipeline(dxf_path: str, cfg: dict, log,
                 rail_color: int | None = None,
                 port_colors: list | None = None,
                 rail_layers: list | None = None,
                 port_layers: list | None = None):
    DXF_PATH = Path(dxf_path)
    MAP_OUT     = DXF_PATH.parent / (DXF_PATH.stem + ".map")
    ORI_MAP_OUT = DXF_PATH.parent / ("ori_" + DXF_PATH.stem + ".map")

    DIRECTION = cfg["io"]["direction"]
    _tol = cfg["tolerance"]
    SNAP_TOL               = _tol["snap_tol"]
    INTER_MERGE_TOL        = _tol["inter_merge_tol"]
    SHORT_STRAIGHT_THRESHOLD = _tol["short_straight_threshold"]
    _bd = cfg["branch_detection"]
    SCALE_TO_MM                    = _bd["scale_to_mm"]
    N_BRANCH_MIN_ARC_SWEEP_DEG     = _bd["n_branch_min_arc_sweep_deg"]
    N_BRANCH_DIAGONAL_AXIS_TOL_DEG = _bd["n_branch_diagonal_axis_tol_deg"]
    U_BRANCH_ARC_SUM_TARGET_MM     = _bd.get("u_branch_arc_sum_target_mm", 2000.0) + 350.0
    # 표준 호 반지름 R — test_logic.py 와 동일 기준(sync)
    RAIL_ARC_RADIUS_MM             = _bd.get("rail_arc_radius_mm", 480.0)
    RAIL_ARC_RADIUS_TOL_MM         = _bd.get("rail_arc_radius_tol_mm", 5.0)
    ORI_U_X_THRESHOLD_MM           = 2.0 * RAIL_ARC_RADIUS_MM + 50.0

    log("DXF 읽는 중...")
    doc = ezdxf.readfile(str(DXF_PATH))
    # 분기 판정 방식: CAD 에 플러그인 기본 모듈이 있으면 모듈 정보로 판정(형상 추정 안 함)
    _modules, _mmsg = decide_modules(doc, cfg)
    log(_mmsg)
    _rl = rail_layers if rail_layers else None
    if rail_color is not None:
        log(f"레일 색상 필터링 중... (색상 {rail_color})")
    if _rl:
        log(f"레일 레이어 필터링 중... ({', '.join(_rl)})")
    lines, arcs = collect_entities_recursive(doc, rail_color=rail_color, rail_layers=_rl,
                                             module_bypass_filter=_modules is not None)
    if rail_color is not None or _rl:
        log(f"레일 필터링 완료: LINE {len(lines)}개, ARC {len(arcs)}개")
    if port_colors:
        log(f"포트 색상 필터링 중... (색상 {port_colors})")
    build_edges_raw_no_split_no_unify(lines, arcs)
    split_lines, arcs, _ = split_edges_at_intersections(lines, arcs)
    glue_arc_endpoints_to_lines(split_lines, arcs, tol=max(SNAP_TOL, INTER_MERGE_TOL))
    snap_segments(split_lines, arcs, tol=SNAP_TOL)
    reproject_arcs_to_circle(arcs)
    split_lines = merge_line_segments_at_degree2_nodes(split_lines, arcs, tol=SNAP_TOL)
    all_segments = split_lines + arcs
    all_segments = clean_edges(all_segments)
    unified_edges = unify_edge_directions(all_segments, tolerance=INTER_MERGE_TOL, start_direction="CCW")
    mjudge = None
    if _modules is not None:
        mjudge = ModuleJudge(_modules, cfg, tol=INTER_MERGE_TOL)
        mjudge.bind(unified_edges)      # 모듈 ↔ 엣지 대응(위치 대조). 이후 단계는 같은 엣지 객체를 따라간다

    log("원본 맵 내보내는 중...")
    if DIRECTION.upper() == "CW":
        for e in unified_edges:
            e.reverse()
        unified_edges = list(reversed(unified_edges))
    nodes, links = export_map_from_unified_edges(
        unified_edges, ORI_MAP_OUT,
        tol=INTER_MERGE_TOL, scale_to_mm=SCALE_TO_MM,
        short_straight_threshold=SHORT_STRAIGHT_THRESHOLD,
        header="#LSL - Jcolab",
        u_branch_arc_sum_target_mm=U_BRANCH_ARC_SUM_TARGET_MM,  # test_logic.py ori와 동일 기준(sync)
        u_x_threshold_mm=ORI_U_X_THRESHOLD_MM,  # =2R+50. ori는 tight 호-호 U만 (호직호·반지름 큰 U 제외). 최종 맵은 1601로 별도 기준
        line_arc_line_u_radius_mm=RAIL_ARC_RADIUS_MM,
        line_arc_line_u_radius_tol_mm=RAIL_ARC_RADIUS_TOL_MM,
        # 모듈 판정: U/N 병합을 모듈에서 받고, 형상 U 탐지(직-호-직)는 끈다
        precomputed_merge_groups=(mjudge.ori_merge_groups(unified_edges) if mjudge else None),
        emit_line_arc_line_u_links=(mjudge is None),
    )
    _extra_ori = _dedup_port_nodes(
        collect_port_nodes_by_color(doc, port_colors or [])
        + collect_port_nodes_by_layer(doc, port_layers or []))
    stb_ports, new_t_nodes, _ = extract_stb_ports(doc, nodes, links, next_node_id=len(nodes) + 1,
                                                   extra_port_nodes=_extra_ori)
    nodes.extend(new_t_nodes)
    save_map(str(ORI_MAP_OUT), nodes, links, header="#LSL - Jcolab", ports=stb_ports)
    # ori 는 대기(clearance) 노드 삽입 전 스냅샷 — 최종 맵과 개수가 다르므로 여기서 따로 찍는다
    log(f"[ori] NODE {len(nodes)}개  LINK {len(links)}개  STB포트 {len(stb_ports)}개")
    log(f"원본 저장됨: {ORI_MAP_OUT}")
    if DIRECTION.upper() == "CW":
        unified_edges = list(reversed(unified_edges))
        for e in unified_edges:
            e.reverse()

    log("대기 노드 삽입 중...")
    if mjudge is not None:
        # 모듈 판정: U/N 링크·일반 분기 호(분기/합류)·단순 통과 곡선 호를 모듈에서 받는다
        _mj_cats = mjudge.clearance_inputs(unified_edges)
        n_arc_pairs, u_arc_pairs = _mj_cats["n_pairs"], _mj_cats["u_pairs"]
    else:
        _mj_cats = None
        merge_groups = find_un_branch_merge_groups(
            unified_edges, INTER_MERGE_TOL, SHORT_STRAIGHT_THRESHOLD,
            scale_to_mm=SCALE_TO_MM,
            n_branch_min_arc_sweep_deg=N_BRANCH_MIN_ARC_SWEEP_DEG,
            n_branch_diagonal_axis_tol_deg=N_BRANCH_DIAGONAL_AXIS_TOL_DEG,
            u_branch_arc_sum_target_mm=U_BRANCH_ARC_SUM_TARGET_MM,
        )
        n_arc_pairs = [idx for idx, bt in merge_groups if bt == "N"]
        u_arc_pairs = [idx for idx, bt in merge_groups if bt == "U"]

    unified_edges, intra_arm_u_idx, complex_lr_flat, plain_arc_flat, graph_scan_u_pair_objs = insert_clearance_nodes(
        unified_edges, tol=SNAP_TOL,
        n_arc_indices=n_arc_pairs, u_arc_indices=u_arc_pairs,
        cfg=cfg, module_judgment=_mj_cats,
    )

    merge_groups_x = []     # 모듈 판정이면 CW 반전 뒤 모듈에서 만든다(아래)
    if mjudge is None:
        merge_groups_x = find_un_branch_merge_groups_by_x(
            unified_edges, INTER_MERGE_TOL, SHORT_STRAIGHT_THRESHOLD,
            scale_to_mm=SCALE_TO_MM,
            n_branch_min_arc_sweep_deg=N_BRANCH_MIN_ARC_SWEEP_DEG,
            n_branch_diagonal_axis_tol_deg=N_BRANCH_DIAGONAL_AXIS_TOL_DEG,
            u_x_threshold_mm=1601.0,
            exclude_indices=set(complex_lr_flat) | set(intra_arm_u_idx) | set(plain_arc_flat),
        )
        merge_groups_x = [
            (idx, bt) for idx, bt in merge_groups_x
            if not any(i in intra_arm_u_idx for i in idx)
            and not any(i in complex_lr_flat for i in idx)
            and not any(i in plain_arc_flat for i in idx)
        ]

        _id_to_post_idx = {id(e): j for j, e in enumerate(unified_edges)}
        _existing_covered = set(idx for idxs, _ in merge_groups_x for idx in idxs)
        for _pair_objs in graph_scan_u_pair_objs:
            _idxs = tuple(_id_to_post_idx.get(id(e)) for e in _pair_objs)
            if any(idx is None for idx in _idxs):
                continue
            if any(idx in _existing_covered for idx in _idxs):
                continue
            if any(idx in intra_arm_u_idx or idx in complex_lr_flat or idx in plain_arc_flat for idx in _idxs):
                continue
            merge_groups_x.append((_idxs, "U"))
            _existing_covered.update(_idxs)

    if DIRECTION.upper() == "CW":
        N = len(unified_edges)
        _lr_swap = {"L": "R", "R": "L"}
        for e in unified_edges:
            e.reverse()
            ft = getattr(e, "forced_link_type", None)
            if ft in _lr_swap:
                e.forced_link_type = _lr_swap[ft]
        unified_edges = list(reversed(unified_edges))
        merge_groups_x = [
            (tuple(N - 1 - idx for idx in reversed(idxs)), btype)
            for idxs, btype in merge_groups_x
        ]
    if mjudge is not None:
        merge_groups_x = mjudge.final_merge_groups(unified_edges)

    log("최종 맵 내보내는 중...")
    nodes, links = export_map_from_unified_edges(
        unified_edges, MAP_OUT,
        tol=INTER_MERGE_TOL, scale_to_mm=SCALE_TO_MM,
        short_straight_threshold=SHORT_STRAIGHT_THRESHOLD,
        precomputed_merge_groups=merge_groups_x,
        line_arc_line_u_radius_mm=RAIL_ARC_RADIUS_MM,
        line_arc_line_u_radius_tol_mm=RAIL_ARC_RADIUS_TOL_MM,
        emit_line_arc_line_u_links=(mjudge is None),
        header="#LSL - Jcolab",
    )
    _extra_final = _dedup_port_nodes(
        collect_port_nodes_by_color(doc, port_colors or [])
        + collect_port_nodes_by_layer(doc, port_layers or []))
    if _extra_final:
        log(f"포트 필터링 완료: {len(_extra_final)}개 포트 위치 검출 (색상+레이어 합집합)")
    stb_ports, new_t_nodes, _ = extract_stb_ports(doc, nodes, links, next_node_id=len(nodes) + 1,
                                                   extra_port_nodes=_extra_final)
    nodes.extend(new_t_nodes)
    save_map(str(MAP_OUT), nodes, links, header="#LSL - Jcolab", ports=stb_ports)
    _self_loops = sum(1 for _l in links if _l.start_node_id == _l.end_node_id)
    if _self_loops:
        log(f"[주의] 시작·끝 노드가 같은 링크 {_self_loops}개 - 대기 노드 두 개가 "
            f"{INTER_MERGE_TOL:.0f}mm 안에 겹침(분기·곡선 사이 직선이 짧음)")

    # 정형화 부품 수량 집계 (플러그인으로 작도한 도면일 때만 산출)
    #  ※ 부가 산출물이므로 여기서 실패해도 map 변환 결과는 그대로 살린다.
    try:
        _parts = count_parts(doc)
        _geom = count_geometry(doc)      # 부품에 안 들어간 직선·호 (개수 + 총 길이)
    except Exception as _e:
        _parts, _geom = None, None
        log(f"[경고] 부품 집계 실패: {_e}")
    if _parts:
        log(f"부품 수량: {summary_text(_parts)}")
        if _geom:
            log(f"형상(부품 제외): 직선 {_geom['line_count']}개 {_geom['line_len']:,.0f}mm"
                f" / 호 {_geom['arc_count']}개 {_geom['arc_len']:,.0f}mm")
        PARTS_OUT = DXF_PATH.parent / (DXF_PATH.stem + "_parts.csv")
        try:
            save_parts_csv(str(PARTS_OUT), _parts, geom=_geom)
            log(f"저장됨: {PARTS_OUT}")
        except OSError as _e:
            # 대개 CSV 가 엑셀에서 열려 있어 잠긴 경우 — 파일 대신 로그로 내보낸다
            log(f"[경고] 부품 CSV 를 저장하지 못했습니다: {_e.strerror}")
            log(f"        {PARTS_OUT}")
            log("        (엑셀 등에서 열려 있으면 닫고 다시 실행하세요. 아래는 같은 내용입니다)")
            for _ln in table_lines(_parts, _geom):
                log("        " + _ln)

    # 모듈 판정 보고: 모듈별 종류·R/L/W/A·판정 결과·확인 필요 사항
    if mjudge is not None:
        for _ln in mjudge.summary_lines():
            log(_ln)
        MODULES_OUT = DXF_PATH.parent / (DXF_PATH.stem + "_modules.csv")
        try:
            mjudge.save_csv(str(MODULES_OUT))
            log(f"저장됨: {MODULES_OUT}")
        except OSError as _e:
            log(f"[경고] 모듈 CSV 를 저장하지 못했습니다: {_e.strerror} - {MODULES_OUT}")

    log(f"[최종] NODE {len(nodes)}개  LINK {len(links)}개  STB포트 {len(stb_ports)}개  (대기 노드 포함)")
    log(f"저장됨: {MAP_OUT}")


# ── GUI ────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    # 색·글꼴 — 기본 ttk 회색 대신 흰 카드 + 절제된 파란 강조 하나.
    BG, CARD, LINE = "#EEF1F4", "#FFFFFF", "#D8DEE4"
    INK, MUTED = "#1F2328", "#6B7684"
    ACCENT, ACCENT_HI, ACCENT_LO = "#1D6FD0", "#1760B8", "#12508F"
    FONT = ("맑은 고딕", 9)
    FONT_B = ("맑은 고딕", 9, "bold")
    FONT_H = ("맑은 고딕", 10, "bold")

    def __init__(self):
        super().__init__()
        self.title("DXF ↔ MAP 변환기")
        self.resizable(True, True)
        self.minsize(640, 520)
        self.configure(bg=self.BG)
        self.cfg = load_cfg()
        self._setup_style()
        self._build_ui()

    # ── 스타일 ───────────────────────────────────────────────────────────
    def _setup_style(self):
        st = ttk.Style(self)
        st.theme_use("clam")            # clam 이라야 색을 마음대로 지정할 수 있다
        C, K, M, L, A = self.CARD, self.INK, self.MUTED, self.LINE, self.ACCENT

        st.configure(".", background=self.BG, foreground=K, font=self.FONT)
        st.configure("TFrame", background=self.BG)
        st.configure("Card.TFrame", background=C)
        st.configure("TLabel", background=self.BG, foreground=K)
        st.configure("Card.TLabel", background=C, foreground=K)
        st.configure("Head.TLabel", background=C, foreground=K, font=self.FONT_B)
        st.configure("Muted.TLabel", background=C, foreground=M)
        st.configure("BarMuted.TLabel", background=self.BG, foreground=M)

        st.configure("TButton", background="#FBFCFD", foreground=K,
                     bordercolor=L, lightcolor="#FBFCFD", darkcolor="#FBFCFD",
                     focuscolor="", padding=(14, 7), relief="flat")
        st.map("TButton", background=[("active", "#F0F3F6"), ("pressed", "#E4E9EE")],
               bordercolor=[("active", "#B9C2CC")])
        st.configure("Accent.TButton", background=A, foreground="#FFFFFF",
                     bordercolor=A, lightcolor=A, darkcolor=A,
                     focuscolor="", padding=(18, 7), relief="flat", font=self.FONT_B)
        st.map("Accent.TButton",
               background=[("active", self.ACCENT_HI), ("pressed", self.ACCENT_LO),
                           ("disabled", "#A9BBD2")],
               bordercolor=[("active", self.ACCENT_HI), ("disabled", "#A9BBD2")],
               foreground=[("disabled", "#EDF2F8")])

        st.configure("TEntry", fieldbackground="#FFFFFF", foreground=K,
                     bordercolor=L, lightcolor=L, darkcolor=L, padding=5)
        st.map("TEntry", bordercolor=[("focus", A)])
        st.configure("TCombobox", fieldbackground="#FFFFFF", background="#FFFFFF",
                     bordercolor=L, lightcolor=L, darkcolor=L, arrowcolor=M, padding=4)
        st.map("TCombobox", bordercolor=[("focus", A)])

        st.configure("Card.TCheckbutton", background=C, foreground=K,
                     indicatorbackground="#FFFFFF", indicatorforeground=A,
                     bordercolor=L, focuscolor="")
        st.map("Card.TCheckbutton", background=[("active", C)],
               indicatorbackground=[("selected", A), ("disabled", "#F0F2F4")],
               foreground=[("disabled", "#AEB6BE")])
        st.configure("Card.TRadiobutton", background=C, foreground=K,
                     indicatorbackground="#FFFFFF", bordercolor=L, focuscolor="")
        st.map("Card.TRadiobutton", background=[("active", C)],
               indicatorbackground=[("selected", A)])

        st.configure("TNotebook", background=self.BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        st.configure("TNotebook.Tab", background=self.BG, foreground=M,
                     bordercolor=self.BG, lightcolor=self.BG, padding=(20, 9),
                     font=self.FONT)
        st.map("TNotebook.Tab",
               background=[("selected", C)], foreground=[("selected", K)],
               font=[("selected", self.FONT_B)],
               lightcolor=[("selected", C)], bordercolor=[("selected", L)])

        st.configure("TProgressbar", background=A, troughcolor="#E3E8ED",
                     bordercolor="#E3E8ED", lightcolor=A, darkcolor=A)
        st.configure("Vertical.TScrollbar", background="#D3DAE1", troughcolor=C,
                     bordercolor=C, arrowcolor=M, relief="flat")
        st.configure("TLabelframe", background=C, bordercolor=L, relief="solid",
                     borderwidth=1)
        st.configure("TLabelframe.Label", background=C, foreground=M, font=self.FONT)

    def _card(self, parent, title, desc=None):
        """흰 배경 + 1px 테두리 패널. 본문을 담을 프레임을 돌려준다.
        (ttk.LabelFrame 의 홈파인 테두리가 촘촘히 쌓이면 지저분해 보여 직접 만든다)"""
        outer = tk.Frame(parent, bg=self.CARD, highlightbackground=self.LINE,
                         highlightcolor=self.LINE, highlightthickness=1, bd=0)
        outer.pack(fill="x", padx=14, pady=(0, 10))
        ttk.Label(outer, text=title, style="Head.TLabel").pack(
            anchor="w", padx=14, pady=(11, 0))
        if desc:
            ttk.Label(outer, text=desc, style="Muted.TLabel").pack(
                anchor="w", padx=14, pady=(1, 0))
        body = ttk.Frame(outer, style="Card.TFrame")
        body.pack(fill="x", padx=14, pady=(8, 13))
        return body

    def _banner(self, parent, src, dst, note):
        """탭 맨 위에 '무엇을 넣으면 무엇이 나오는지' 를 한 줄로. 두 탭을 한눈에 구분시킨다."""
        f = tk.Frame(parent, bg=self.BG)
        f.pack(fill="x", padx=14, pady=(12, 10))
        row = tk.Frame(f, bg=self.BG)
        row.pack(anchor="w")
        tk.Label(row, text=src, bg=self.BG, fg=self.INK, font=self.FONT_B).pack(side="left")
        tk.Label(row, text="   →   ", bg=self.BG, fg=self.ACCENT,
                 font=self.FONT_B).pack(side="left")
        tk.Label(row, text=dst, bg=self.BG, fg=self.INK, font=self.FONT_B).pack(side="left")
        tk.Label(f, text=note, bg=self.BG, fg=self.MUTED, font=self.FONT).pack(
            anchor="w", pady=(3, 0))

    # ── UI 구성 ──────────────────────────────────────────────────────────
    #  두 기능(정변환 CAD→MAP / 역변환 MAP→CAD)은 입력도 설정도 겹치지 않아 탭으로 나눈다.
    #  로그는 탭 밖에 두어 어느 쪽을 돌리든 같은 자리에서 보이게 한다.
    def _build_ui(self):
        self._adv_win = None
        self._init_adv_vars()

        nb = self.nb = ttk.Notebook(self)
        nb.pack(fill="x", padx=14, pady=(4, 0))

        tab_fwd = ttk.Frame(nb, style="Card.TFrame")
        tab_rev = ttk.Frame(nb, style="Card.TFrame")
        nb.add(tab_fwd, text="CAD → MAP")
        nb.add(tab_rev, text="MAP → CAD")

        # 탭 안쪽 배경은 창 색으로 — 카드(흰 패널)가 떠 보이게
        for t in (tab_fwd, tab_rev):
            t.configure(style="TFrame")

        self._build_tab_forward(tab_fwd)
        self._build_tab_reverse(tab_rev)

        # 로그 (공통) — 콘솔처럼 어둡게 해서 설정 영역과 확실히 구분한다
        wrap = tk.Frame(self, bg=self.LINE, bd=0)
        wrap.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        self.log_box = scrolledtext.ScrolledText(
            wrap, height=11, width=78, state="disabled", font=("Consolas", 9),
            bg="#1B2027", fg="#CFD8E3", insertbackground="#CFD8E3",
            relief="flat", bd=0, padx=10, pady=8,
            selectbackground="#2F3A46", highlightthickness=0)
        self.log_box.pack(fill="both", expand=True, padx=1, pady=1)

        self._suggest_map(self.dxf_var.get())   # 시작 시 옆에 맵 있으면 채움

    # ── 탭 1: CAD → MAP ──────────────────────────────────────────────────
    def _build_tab_forward(self, parent):
        # 실행 바를 먼저 아래에 붙인다 (뒤에 pack 하는 카드가 그 위로 쌓이도록)
        bar = ttk.Frame(parent)
        bar.pack(side="bottom", fill="x", padx=14, pady=(2, 14))
        self.btn_run = ttk.Button(bar, text="변환 실행", style="Accent.TButton",
                                  command=self._run)
        self.btn_run.pack(side="right")
        ttk.Button(bar, text="고급 설정", command=self._open_adv).pack(
            side="right", padx=(0, 8))
        ttk.Label(bar, style="BarMuted.TLabel",
                  text="산출물   ori_<이름>.map  +  <이름>.map").pack(side="left", pady=8)

        self._banner(parent, "DXF 도면", "MAP 2개",
                     "도면의 선·호를 읽어 주행 그래프를 만듭니다")

        body = self._card(parent, "① 입력 DXF")
        self.dxf_var = tk.StringVar(value=self._default_dxf())
        ttk.Entry(body, textvariable=self.dxf_var).pack(side="left", fill="x", expand=True)
        ttk.Button(body, text="찾아보기", command=self._browse).pack(side="left", padx=(8, 0))

        body = self._card(parent, "② 주행 방향", "출력 그래프의 전체 진행 방향")
        self.dir_var = tk.StringVar(value=self.cfg["io"].get("direction", "CCW"))
        ttk.Combobox(body, textvariable=self.dir_var, values=["CCW", "CW"],
                     state="readonly", width=8).pack(side="left")

        body = self._card(parent, "③ 레일 / 포트 필터",
                          "도면을 스캔해 레일과 포트로 쓸 색·레이어를 고릅니다")
        self._color_counts: dict[int, int] = {}
        self._layer_counts: dict[str, int] = {}
        self._rail_color_var = tk.StringVar(value="")
        self._port_color_vars: dict[int, tk.BooleanVar] = {}
        self._rail_layer_vars: dict[str, tk.BooleanVar] = {}
        self._port_layer_vars: dict[str, tk.BooleanVar] = {}

        top_row = ttk.Frame(body, style="Card.TFrame")
        top_row.pack(fill="x")
        ttk.Button(top_row, text="DXF 스캔", command=self._scan_colors).pack(side="left")
        self._scan_status = ttk.Label(top_row, text="아직 스캔하지 않았습니다",
                                      style="Muted.TLabel")
        self._scan_status.pack(side="left", padx=10)
        # 스캔 진행바 — 평소 숨김. 스캔 시 표시(_scan_colors), 끝나면 숨김.
        self._scan_pb = ttk.Progressbar(top_row, mode="determinate", length=160, maximum=100)

        self._frm_color_body = ttk.Frame(body, style="Card.TFrame")
        self._frm_color_body.pack(fill="x")

        # 고급 설정은 항목이 23개라 본 창에 펼치면 창이 두 배가 된다 → 별도 창(_open_adv)

    # ── 탭 2: MAP → CAD ──────────────────────────────────────────────────
    def _build_tab_reverse(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(side="bottom", fill="x", padx=14, pady=(2, 14))
        self.btn_rev = ttk.Button(bar, text="DXF 생성", style="Accent.TButton",
                                  command=self._run_reverse)
        self.btn_rev.pack(side="right")
        ttk.Label(bar, style="BarMuted.TLabel",
                  text="산출물   <이름>_fromMap.dxf").pack(side="left", pady=8)

        self._banner(parent, "ori_*.map", "DXF 도면",
                     "맵의 노드·링크를 선과 호로 되돌립니다 (레이어·블록·장비는 복원 안 됨)")

        # clearance 이전 스냅샷이라 곡선이 순수한 호 → 현과 길이만으로 형상이 풀린다.
        # (최종 맵은 곡선이 양옆 직선을 흡수한 복합 형상이라 별도 처리가 필요 — final_to_cad.py)
        body = self._card(parent, "① 입력 MAP", "clearance 이전 스냅샷인 ori_*.map 을 넣으세요")
        self.map_var = tk.StringVar(value="")
        ttk.Entry(body, textvariable=self.map_var).pack(side="left", fill="x", expand=True)
        ttk.Button(body, text="찾아보기", command=self._browse_map).pack(side="left", padx=(8, 0))

        # 표준 호 반지름 R 은 고급 설정(rail_arc_radius_mm)을 그대로 쓴다.
        # 포트 마커는 레일 위 동그라미로 보여 혼동되기 쉬워 그리지 않는다.

    # ── 고급 설정 (별도 창) ───────────────────────────────────────────────
    #  StringVar 는 창을 닫아도 살아 있으므로, 변수는 시작할 때 한 번 만들고
    #  창을 열 때마다 위젯만 새로 붙인다. (_apply_adv_to_cfg 가 이 변수들을 읽는다)
    def _adv_sections(self):
        return [
            ("tolerance", [
                ("snap_tol",               "스냅 허용 오차 (mm)"),
                ("inter_merge_tol",        "세그먼트 병합 오차 (mm)"),
                ("clean_tol",              "영세그먼트 제거 오차 (mm)"),
                ("snap_decimals",          "좌표 소수점 자릿수"),
                ("short_straight_threshold","짧은 직선 기준 (mm)"),
            ]),
            ("branch_detection", [
                ("n_branch_min_arc_sweep_deg",    "N분기 최소 호 스윕각 (도)"),
                ("n_branch_diagonal_axis_tol_deg","N분기 대각선 판별 (도)"),
                ("scale_to_mm",                   "단위→mm 배율"),
            ]),
            ("clearance_nodes", [
                ("j1_downstream",        "J1 이동 거리 (mm)"),
                ("j3_arc_len",           "J3 이동 거리 (mm)"),
                ("lr_j2_upstream",       "L/R J2 거리 (mm)"),
                ("n_long_j2",            "N분기 J2 Long (mm)"),
                ("n_short_j2",           "N분기 J2 Short (mm)"),
                ("n_straight_threshold", "N분기 Long/Short 기준 (mm)"),
                ("u_j1",                 "U분기 J1 거리 (mm)"),
                ("small_x_j1",          "소형복합분기 J1 (mm)"),
                ("complex_lr_j1",       "복합분기 J1 (mm)"),
                ("complex_lr_point_a_x","복합분기 Point A 기준 X (mm)"),
                ("complex_lr_point_b2_x","복합분기 Point B2 기준 X (mm)"),
            ]),
            ("driving_nodes", [
                ("min_length",  "주행노드 삽입 최소 링크 길이 (mm)"),
                ("min_segment", "주행노드 최소 구간 길이 (mm)"),
            ]),
        ]

    def _init_adv_vars(self):
        self._adv_vars: dict[tuple, tk.StringVar] = {}
        for sec, fields in self._adv_sections():
            for key, _label in fields:
                self._adv_vars[(sec, key)] = tk.StringVar(
                    value=str(self.cfg.get(sec, {}).get(key, "")))

    def _open_adv(self):
        if getattr(self, "_adv_win", None) is not None and self._adv_win.winfo_exists():
            self._adv_win.lift()
            return
        win = tk.Toplevel(self)
        self._adv_win = win
        win.title("고급 설정")
        win.transient(self)
        win.resizable(False, False)
        win.configure(bg=self.BG)

        TITLES = {"tolerance": "허용 오차", "branch_detection": "분기 판정",
                  "clearance_nodes": "대기 노드", "driving_nodes": "주행 노드"}
        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=14, pady=(14, 0))
        # 두 칸으로 나눠 세로로 길어지는 것을 막는다
        cols = [ttk.Frame(body), ttk.Frame(body)]
        cols[0].pack(side="left", fill="y", anchor="n")
        cols[1].pack(side="left", fill="y", anchor="n", padx=(14, 0))
        for i, (sec, fields) in enumerate(self._adv_sections()):
            card = tk.Frame(cols[0 if i < 2 else 1], bg=self.CARD,
                            highlightbackground=self.LINE, highlightcolor=self.LINE,
                            highlightthickness=1, bd=0)
            card.pack(fill="x", pady=(0, 10))
            ttk.Label(card, text=TITLES.get(sec, sec), style="Head.TLabel").pack(
                anchor="w", padx=13, pady=(10, 6))
            for key, label in fields:
                row = ttk.Frame(card, style="Card.TFrame")
                row.pack(fill="x", padx=13, pady=(0, 5))
                ttk.Label(row, text=label, width=30, anchor="w",
                          style="Card.TLabel").pack(side="left")
                ttk.Entry(row, textvariable=self._adv_vars[(sec, key)],
                          width=9).pack(side="left")
            ttk.Frame(card, style="Card.TFrame").pack(pady=3)

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=14, pady=(4, 14))
        ttk.Button(bar, text="닫기", style="Accent.TButton",
                   command=win.destroy).pack(side="right")
        ttk.Button(bar, text="되돌리기",
                   command=self._reset_adv).pack(side="right", padx=(0, 8))
        ttk.Label(bar, style="BarMuted.TLabel",
                  text="변환 실행할 때 config.json 에 저장됩니다").pack(side="left", pady=8)

    def _reset_adv(self):
        """디스크의 config.json 값으로 되돌린다(저장 전 편집분만 취소)."""
        disk = load_cfg()
        for (sec, key), var in self._adv_vars.items():
            var.set(str(disk.get(sec, {}).get(key, "")))

    # ── 색상·레이어 스캔 ──────────────────────────────────────────────────
    def _scan_colors(self):
        dxf = self.dxf_var.get().strip()
        if not dxf or not Path(dxf).exists():
            messagebox.showerror("오류", "DXF 파일을 먼저 선택해주세요.")
            return

        self._log("색상·레이어 스캔 중...")
        self._scan_status.configure(text="DXF 읽는 중...")
        # 진행바 표시 (스캔 동안만). 읽기 단계는 측정 불가라 움직이는(indeterminate) 모드
        self._scan_pb.configure(mode="indeterminate")
        self._scan_pb.pack(side="right", padx=6)
        self._scan_pb.start(12)

        def worker():
            import traceback
            try:
                doc = ezdxf.readfile(dxf)

                # 읽기 끝 → 퍼센트(determinate) 모드로 전환
                def _to_determinate():
                    self._scan_pb.stop()
                    self._scan_pb.configure(mode="determinate", maximum=100, value=0)
                    self._scan_status.configure(text="스캔 중 0%")
                self.after(0, _to_determinate)

                def prog(d, t):
                    pct = int(d * 100 / t) if t else 100
                    def _upd():
                        self._scan_pb.configure(value=pct)
                        self._scan_status.configure(text=f"스캔 중 {pct}%")
                    self.after(0, _upd)

                color_counts, layer_counts = scan_colors_and_layers(doc, progress=prog)

                def done():
                    self._color_counts = color_counts
                    self._layer_counts = layer_counts
                    total = sum(color_counts.values())
                    self._scan_pb.stop()
                    self._scan_pb.pack_forget()   # 끝나면 숨김
                    self._scan_status.configure(
                        text=f"색상 {len(color_counts)}개 / 레이어 {len(layer_counts)}개, 총 {total}개 엔티티"
                    )
                    self._log(f"스캔 완료: 색상 {len(color_counts)}가지, 레이어 {len(layer_counts)}가지, 총 {total}개 엔티티")
                    self._build_color_ui()
                self.after(0, done)
            except Exception as e:
                tb = traceback.format_exc()
                def _fail():
                    self._scan_pb.stop()
                    self._scan_pb.pack_forget()   # 실패해도 숨김
                    self._scan_status.configure(text="스캔 실패")
                self.after(0, _fail)
                self.after(0, self._log, f"[오류] 스캔 실패: {e}\n{tb}")

        threading.Thread(target=worker, daemon=True).start()

    def _aci_hex(self, aci: int) -> str:
        try:
            from ezdxf.colors import aci2rgb
            r, g, b = aci2rgb(aci)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#cccccc"

    def _make_scroll_column(self, parent, title, max_h=240, width=160):
        """제목 LabelFrame + 세로 스크롤(Canvas) → 항목 담을 inner frame 반환.
        내용이 max_h를 넘칠 때만 스크롤바·휠 동작, 적으면 칸을 내용에 맞춰 줄이고 스크롤바 숨김."""
        lf = ttk.Frame(parent, style="Card.TFrame")
        lf.pack(side="left", fill="x", expand=True, anchor="n", padx=(0, 10))
        ttk.Label(lf, text=title, style="Muted.TLabel").pack(anchor="w", pady=(0, 3))
        canvas = tk.Canvas(lf, height=max_h, width=width, highlightthickness=0,
                           bg=self.CARD, bd=0)
        vsb = ttk.Scrollbar(lf, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)   # 스크롤바는 필요할 때만 pack
        inner = ttk.Frame(canvas, style="Card.TFrame")
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            req = inner.winfo_reqheight()
            if req > max_h:                      # 넘침 → 스크롤바 표시 + 높이 고정
                canvas.configure(height=max_h)
                if vsb.winfo_manager() != "pack":
                    vsb.pack(side="right", fill="y", before=canvas)
            else:                                # 다 들어감 → 스크롤바 숨김 + 내용에 맞춰 축소
                canvas.configure(height=max(req, 1))
                if vsb.winfo_manager() == "pack":
                    vsb.pack_forget()
        inner.bind("<Configure>", _on_inner)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))

        # 마우스휠: 내용이 넘칠 때만 (해당 칸 위에서)
        def _wheel(e):
            if inner.winfo_reqheight() > max_h:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _build_color_ui(self):
        for w in self._frm_color_body.winfo_children():
            w.destroy()
        self._port_color_vars.clear()
        self._rail_layer_vars.clear()
        self._port_layer_vars.clear()

        saved_cf = self.cfg.get("color_filter", {})
        saved_rail = saved_cf.get("rail_color")
        saved_ports = set(saved_cf.get("port_colors", []))
        saved_layers = set(saved_cf.get("rail_layers", []))
        saved_port_layers = set(saved_cf.get("port_layers", []))
        sorted_colors = sorted(self._color_counts.keys())
        sorted_layers = sorted(self._layer_counts.keys())

        cols = ttk.Frame(self._frm_color_body, style="Card.TFrame")
        cols.pack(fill="x", pady=(10, 0))

        # ── 레일 색상 (단일 선택) ──
        rail_frame = self._make_scroll_column(cols, "레일 색상 (1개)")
        self._rail_color_var.set(str(saved_rail) if saved_rail is not None else "")
        ttk.Radiobutton(rail_frame, text="없음 (전체)", variable=self._rail_color_var,
                        value="", style="Card.TRadiobutton").pack(anchor="w", pady=1)
        for aci in sorted_colors:
            cnt = self._color_counts[aci]; hex_c = self._aci_hex(aci)
            row = ttk.Frame(rail_frame, style="Card.TFrame"); row.pack(anchor="w", pady=1)
            swatch = tk.Canvas(row, width=11, height=11, highlightthickness=0, bg=self.CARD, bd=0)
            swatch.create_rectangle(0, 0, 11, 11, fill=hex_c, outline=self.LINE)
            swatch.pack(side="left", padx=(0, 5))
            ttk.Radiobutton(row, text=f"색{aci} ({cnt}개)", style="Card.TRadiobutton",
                            variable=self._rail_color_var, value=str(aci)).pack(side="left")

        # ── 레일 레이어 (복수 선택) ──
        layer_frame = self._make_scroll_column(cols, "레일 레이어 (복수)")
        for lname in sorted_layers:
            cnt = self._layer_counts[lname]
            var = tk.BooleanVar(value=(lname in saved_layers))
            self._rail_layer_vars[lname] = var
            ttk.Checkbutton(layer_frame, text=f"{lname} ({cnt}개)", variable=var,
                            style="Card.TCheckbutton").pack(anchor="w", pady=1)

        # ── 포트 색상 (복수 선택) ──
        port_frame = self._make_scroll_column(cols, "포트 색상 (복수)")
        for aci in sorted_colors:
            cnt = self._color_counts[aci]; hex_c = self._aci_hex(aci)
            var = tk.BooleanVar(value=(aci in saved_ports))
            self._port_color_vars[aci] = var
            row = ttk.Frame(port_frame, style="Card.TFrame"); row.pack(anchor="w", pady=1)
            swatch = tk.Canvas(row, width=11, height=11, highlightthickness=0, bg=self.CARD, bd=0)
            swatch.create_rectangle(0, 0, 11, 11, fill=hex_c, outline=self.LINE)
            swatch.pack(side="left", padx=(0, 5))
            ttk.Checkbutton(row, text=f"색{aci} ({cnt}개)", variable=var,
                            style="Card.TCheckbutton").pack(side="left")

        # ── 포트 레이어 (복수 선택) ──
        port_layer_frame = self._make_scroll_column(cols, "포트 레이어 (복수)")
        for lname in sorted_layers:
            cnt = self._layer_counts[lname]
            var = tk.BooleanVar(value=(lname in saved_port_layers))
            self._port_layer_vars[lname] = var
            ttk.Checkbutton(port_layer_frame, text=f"{lname} ({cnt}개)", variable=var,
                            style="Card.TCheckbutton").pack(anchor="w", pady=1)

    # ── 이벤트 ───────────────────────────────────────────────────────────
    def _default_dxf(self) -> str:
        # CAD 플러그인(리본 CAD→MAP 버튼 / CAD2MAP)이 현재 도면을 DXF 로 내보내 경로를 인자로 넘긴다 → 그 파일 우선
        for a in sys.argv[1:]:
            if a.lower().endswith(".dxf") and Path(a).is_file():
                return str(Path(a))
        raw = self.cfg["io"].get("dxf_path", "")
        p = Path(raw)
        if p.is_absolute():
            return str(p)
        candidate = _base / raw
        return str(candidate) if candidate.exists() else ""

    def _browse(self):
        path = filedialog.askopenfilename(
            title="DXF 파일 선택",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )
        if path:
            self.dxf_var.set(path)
            self._suggest_map(path)

    def _suggest_map(self, dxf_path: str):
        """DXF 옆에 ori_*.map 이 있으면 역변환 입력으로 미리 채운다."""
        p = Path(dxf_path)
        cand = p.with_name("ori_" + p.stem + ".map")
        if cand.exists() and not self.map_var.get().strip():
            self.map_var.set(str(cand))

    def _browse_map(self):
        path = filedialog.askopenfilename(
            title="MAP 파일 선택",
            filetypes=[("MAP files", "*.map"), ("All files", "*.*")],
        )
        if path:
            self.map_var.set(path)

    def _run_reverse(self):
        mp = self.map_var.get().strip()
        if not mp or not Path(mp).exists():
            messagebox.showerror("오류", "MAP 파일을 선택해주세요.")
            return

        _bd = self.cfg.get("branch_detection", {})
        radius = float(_bd.get("rail_arc_radius_mm", 480.0))
        radius_tol = float(_bd.get("rail_arc_radius_tol_mm", 5.0))
        draw_ports = False

        self.btn_rev.configure(state="disabled")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._log(f"MAP → CAD 역변환 시작 — R={radius:g}mm")

        def worker():
            import traceback
            try:
                log = lambda m: self.after(0, self._log, m)
                st = map_to_dxf(mp, None, radius_mm=radius, radius_tol_mm=radius_tol,
                                draw_ports=draw_ports, log=log)
                msg = (f"DXF 생성 완료\n\n{st['dxf']}\n\n"
                       f"LINE {st['lines']}개 / ARC {st['arcs']}개\n"
                       f"경고 {len(st['warnings'])}건")
                self.after(0, lambda: messagebox.showinfo("역변환 완료", msg))
            except Exception as e:
                tb = traceback.format_exc()
                self.after(0, self._log, f"[오류] {e}\n{tb}")
                self.after(0, lambda: messagebox.showerror("오류", str(e)))
            finally:
                self.after(0, lambda: self.btn_rev.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _apply_adv_to_cfg(self):
        for (sec, key), var in self._adv_vars.items():
            raw = var.get().strip()
            try:
                orig = self.cfg[sec][key]
                self.cfg[sec][key] = type(orig)(raw)
            except (ValueError, KeyError):
                pass

    def _run(self):
        dxf = self.dxf_var.get().strip()
        if not dxf or not Path(dxf).exists():
            messagebox.showerror("오류", "DXF 파일을 선택해주세요.")
            return

        direction = self.dir_var.get().strip().upper()
        if direction not in ("CCW", "CW"):
            messagebox.showerror("오류", "방향은 CCW 또는 CW만 입력 가능합니다.")
            return

        self._apply_adv_to_cfg()
        self.cfg["io"]["direction"] = direction

        rail_str = self._rail_color_var.get().strip()
        rail_color = int(rail_str) if rail_str else None
        port_colors = [aci for aci, var in self._port_color_vars.items() if var.get()]
        rail_layers = [lname for lname, var in self._rail_layer_vars.items() if var.get()]
        port_layers = [lname for lname, var in self._port_layer_vars.items() if var.get()]
        self.cfg["color_filter"] = {
            "rail_color": rail_color,
            "port_colors": port_colors,
            "rail_layers": rail_layers,
            "port_layers": port_layers,
        }
        save_cfg(self.cfg)

        self.btn_run.configure(state="disabled")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        def worker():
            import traceback
            try:
                run_pipeline(dxf, self.cfg, lambda m: self.after(0, self._log, m),
                             rail_color=rail_color, port_colors=port_colors,
                             rail_layers=rail_layers or None, port_layers=port_layers or None)
                # 방금 만든 ori 맵을 역변환 입력으로 채워준다
                _ori = Path(dxf).with_name("ori_" + Path(dxf).stem + ".map")
                if _ori.exists():
                    self.after(0, self.map_var.set, str(_ori))
            except Exception as e:
                tb = traceback.format_exc()
                self.after(0, self._log, f"[오류] {e}\n{tb}")
            finally:
                self.after(0, lambda: self.btn_run.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


def _cli_map2cad(argv: list[str]) -> int:
    """`DXFtoMAP.exe --map2cad <map> [out.dxf] [--ports]` — 창 없이 역변환만 수행(배치용).
    반지름은 exe 옆 config.json 의 branch_detection.rail_arc_radius_mm 을 쓴다.
    포트 마커는 GUI 체크박스와 같게 **기본 끔** — `--ports` 를 주면 그린다."""
    draw_ports = "--ports" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) < 1:
        print("사용법: --map2cad <map 경로> [출력 dxf] [--ports]")
        return 2
    cfg = load_cfg()
    _bd = cfg.get("branch_detection", {})
    try:
        st = map_to_dxf(args[0], args[1] if len(args) > 1 else None,
                        radius_mm=float(_bd.get("rail_arc_radius_mm", 480.0)),
                        radius_tol_mm=float(_bd.get("rail_arc_radius_tol_mm", 5.0)),
                        draw_ports=draw_ports)
    except Exception as e:
        print(f"[오류] {e}")
        return 1
    print(f"완료: {st['dxf']} (LINE {st['lines']} / ARC {st['arcs']} / 경고 {len(st['warnings'])})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--map2cad":
        sys.exit(_cli_map2cad(sys.argv[2:]))
    app = App()
    app.mainloop()
