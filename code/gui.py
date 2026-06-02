from __future__ import annotations
import json, sys, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import ezdxf
from core import *
from dxf_parser import (collect_entities_recursive, build_edges_raw_no_split_no_unify,
                        clean_edges, scan_entity_colors, scan_entity_layers)
from geometry import (split_edges_at_intersections, glue_arc_endpoints_to_lines,
                      snap_segments, reproject_arcs_to_circle,
                      merge_line_segments_at_degree2_nodes)
from topology import unify_edge_directions, insert_clearance_nodes
from map_exporter import (export_map_from_unified_edges,
                          find_un_branch_merge_groups,
                          find_un_branch_merge_groups_by_x, save_map)
from port_extractor import extract_stb_ports, collect_port_nodes_by_color


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


# ── 파이프라인 (별도 스레드에서 실행) ──────────────────────────────────────
def run_pipeline(dxf_path: str, cfg: dict, log,
                 rail_color: int | None = None,
                 port_colors: list | None = None,
                 rail_layers: list | None = None):
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

    log("DXF 읽는 중...")
    doc = ezdxf.readfile(str(DXF_PATH))
    _rl = rail_layers if rail_layers else None
    if rail_color is not None:
        log(f"레일 색상 필터링 중... (색상 {rail_color})")
    if _rl:
        log(f"레일 레이어 필터링 중... ({', '.join(_rl)})")
    lines, arcs = collect_entities_recursive(doc, rail_color=rail_color, rail_layers=_rl)
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
    )
    _extra_ori = collect_port_nodes_by_color(doc, port_colors or [])
    stb_ports, new_t_nodes, _ = extract_stb_ports(doc, nodes, links, next_node_id=len(nodes) + 1,
                                                   extra_port_nodes=_extra_ori)
    nodes.extend(new_t_nodes)
    save_map(str(ORI_MAP_OUT), nodes, links, header="#LSL - Jcolab", ports=stb_ports)
    log(f"원본 저장됨: {ORI_MAP_OUT}")
    if DIRECTION.upper() == "CW":
        unified_edges = list(reversed(unified_edges))
        for e in unified_edges:
            e.reverse()

    log("대기 노드 삽입 중...")
    merge_groups = find_un_branch_merge_groups(
        unified_edges, INTER_MERGE_TOL, SHORT_STRAIGHT_THRESHOLD,
        scale_to_mm=SCALE_TO_MM,
        n_branch_min_arc_sweep_deg=N_BRANCH_MIN_ARC_SWEEP_DEG,
        n_branch_diagonal_axis_tol_deg=N_BRANCH_DIAGONAL_AXIS_TOL_DEG,
    )
    n_arc_pairs = [idx for idx, bt in merge_groups if bt == "N"]
    u_arc_pairs = [idx for idx, bt in merge_groups if bt == "U"]

    unified_edges, intra_arm_u_idx, complex_lr_flat, plain_arc_flat, graph_scan_u_pair_objs = insert_clearance_nodes(
        unified_edges, tol=SNAP_TOL,
        n_arc_indices=n_arc_pairs, u_arc_indices=u_arc_pairs,
        cfg=cfg,
    )

    merge_groups_x = find_un_branch_merge_groups_by_x(
        unified_edges, INTER_MERGE_TOL, SHORT_STRAIGHT_THRESHOLD,
        scale_to_mm=SCALE_TO_MM,
        n_branch_min_arc_sweep_deg=N_BRANCH_MIN_ARC_SWEEP_DEG,
        n_branch_diagonal_axis_tol_deg=N_BRANCH_DIAGONAL_AXIS_TOL_DEG,
    )
    merge_groups_x = [
        (idx, bt) for idx, bt in merge_groups_x
        if not any(i in complex_lr_flat for i in idx)
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
        if any(idx in complex_lr_flat or idx in plain_arc_flat for idx in _idxs):
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

    log("최종 맵 내보내는 중...")
    nodes, links = export_map_from_unified_edges(
        unified_edges, MAP_OUT,
        tol=INTER_MERGE_TOL, scale_to_mm=SCALE_TO_MM,
        short_straight_threshold=SHORT_STRAIGHT_THRESHOLD,
        precomputed_merge_groups=merge_groups_x,
        header="#LSL - Jcolab",
    )
    _extra_final = collect_port_nodes_by_color(doc, port_colors or [])
    if _extra_final:
        log(f"포트 색상 필터링 완료: {len(_extra_final)}개 포트 위치 검출")
    stb_ports, new_t_nodes, _ = extract_stb_ports(doc, nodes, links, next_node_id=len(nodes) + 1,
                                                   extra_port_nodes=_extra_final)
    nodes.extend(new_t_nodes)
    save_map(str(MAP_OUT), nodes, links, header="#LSL - Jcolab", ports=stb_ports)

    log(f"완료: NODE {len(nodes)}개  LINK {len(links)}개  STB포트 {len(stb_ports)}개")
    log(f"저장됨: {MAP_OUT}")


# ── GUI ────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DXF → MAP 변환기")
        self.resizable(False, False)
        self.cfg = load_cfg()
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────────────────────
    def _build_ui(self):
        pad = dict(padx=10, pady=6)

        # DXF 파일 선택
        frm_file = ttk.LabelFrame(self, text="입력 파일")
        frm_file.pack(fill="x", **pad)

        self.dxf_var = tk.StringVar(value=self._default_dxf())
        ttk.Entry(frm_file, textvariable=self.dxf_var, width=52).pack(side="left", padx=6, pady=6)
        ttk.Button(frm_file, text="찾아보기", command=self._browse).pack(side="left", padx=(0, 6), pady=6)

        # 방향
        frm_dir = ttk.LabelFrame(self, text="주행 방향")
        frm_dir.pack(fill="x", **pad)

        self.dir_var = tk.StringVar(value=self.cfg["io"].get("direction", "CCW"))
        ttk.Label(frm_dir, text="주행 방향:").pack(side="left", padx=6, pady=6)
        ttk.Combobox(frm_dir, textvariable=self.dir_var, values=["CCW", "CW"],
                     state="readonly", width=6).pack(side="left", pady=6)

        # 색상·레이어 필터
        frm_color = ttk.LabelFrame(self, text="레일/포트 필터")
        frm_color.pack(fill="x", **pad)

        self._color_counts: dict[int, int] = {}
        self._layer_counts: dict[str, int] = {}
        self._rail_color_var = tk.StringVar(value="")
        self._port_color_vars: dict[int, tk.BooleanVar] = {}
        self._rail_layer_vars: dict[str, tk.BooleanVar] = {}

        top_row = ttk.Frame(frm_color)
        top_row.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Button(top_row, text="DXF 스캔", command=self._scan_colors).pack(side="left")
        self._scan_status = ttk.Label(top_row, text="(DXF를 먼저 스캔하세요)")
        self._scan_status.pack(side="left", padx=8)

        self._frm_color_body = ttk.Frame(frm_color)
        self._frm_color_body.pack(fill="x", padx=6, pady=(0, 6))

        # 고급 설정 (접기/펼치기)
        self.adv_open = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="고급 설정 보기", variable=self.adv_open,
                        command=self._toggle_adv).pack(anchor="w", padx=10)

        self.frm_adv = ttk.LabelFrame(self, text="고급 설정")
        self._build_adv(self.frm_adv)

        # 실행 버튼
        self.btn_run = ttk.Button(self, text="변환 실행", command=self._run)
        self.btn_run.pack(pady=(4, 2))

        # 로그 창
        frm_log = ttk.LabelFrame(self, text="로그")
        frm_log.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self.log_box = scrolledtext.ScrolledText(frm_log, height=10, width=70,
                                                 state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_adv(self, parent):
        sections = [
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

        self._adv_vars: dict[tuple, tk.StringVar] = {}
        for sec, fields in sections:
            lf = ttk.LabelFrame(parent, text=sec)
            lf.pack(fill="x", padx=6, pady=3)
            for key, label in fields:
                row = ttk.Frame(lf)
                row.pack(fill="x", padx=4, pady=1)
                ttk.Label(row, text=label, width=30, anchor="w").pack(side="left")
                var = tk.StringVar(value=str(self.cfg[sec].get(key, "")))
                self._adv_vars[(sec, key)] = var
                ttk.Entry(row, textvariable=var, width=12).pack(side="left")

    def _toggle_adv(self):
        if self.adv_open.get():
            self.frm_adv.pack(fill="x", padx=10, pady=(0, 4))
        else:
            self.frm_adv.pack_forget()

    # ── 색상·레이어 스캔 ──────────────────────────────────────────────────
    def _scan_colors(self):
        dxf = self.dxf_var.get().strip()
        if not dxf or not Path(dxf).exists():
            messagebox.showerror("오류", "DXF 파일을 먼저 선택해주세요.")
            return

        self._log("색상·레이어 스캔 중...")
        self._scan_status.configure(text="스캔 중...")

        def worker():
            import traceback
            try:
                doc = ezdxf.readfile(dxf)
                color_counts = scan_entity_colors(doc)
                layer_counts = scan_entity_layers(doc)
                def done():
                    self._color_counts = color_counts
                    self._layer_counts = layer_counts
                    total = sum(color_counts.values())
                    self._scan_status.configure(
                        text=f"색상 {len(color_counts)}개 / 레이어 {len(layer_counts)}개, 총 {total}개 엔티티"
                    )
                    self._log(f"스캔 완료: 색상 {len(color_counts)}가지, 레이어 {len(layer_counts)}가지, 총 {total}개 엔티티")
                    self._build_color_ui()
                self.after(0, done)
            except Exception as e:
                tb = traceback.format_exc()
                self.after(0, self._scan_status.configure, {"text": "스캔 실패"})
                self.after(0, self._log, f"[오류] 스캔 실패: {e}\n{tb}")

        threading.Thread(target=worker, daemon=True).start()

    def _aci_hex(self, aci: int) -> str:
        try:
            from ezdxf.colors import aci2rgb
            r, g, b = aci2rgb(aci)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#cccccc"

    def _build_color_ui(self):
        for w in self._frm_color_body.winfo_children():
            w.destroy()
        self._port_color_vars.clear()
        self._rail_layer_vars.clear()

        saved_cf = self.cfg.get("color_filter", {})
        saved_rail = saved_cf.get("rail_color")
        saved_ports = set(saved_cf.get("port_colors", []))
        saved_layers = set(saved_cf.get("rail_layers", []))
        sorted_colors = sorted(self._color_counts.keys())
        sorted_layers = sorted(self._layer_counts.keys())

        cols = ttk.Frame(self._frm_color_body)
        cols.pack(fill="x")

        # ── 레일 색상 (단일 선택) ──
        rail_frame = ttk.LabelFrame(cols, text="레일 색상 (1개)")
        rail_frame.pack(side="left", fill="both", expand=True, padx=(0, 4), pady=2)
        self._rail_color_var.set(str(saved_rail) if saved_rail is not None else "")
        ttk.Radiobutton(rail_frame, text="없음 (전체)", variable=self._rail_color_var,
                        value="").pack(anchor="w", padx=6, pady=1)
        for aci in sorted_colors:
            cnt = self._color_counts[aci]
            hex_c = self._aci_hex(aci)
            row = ttk.Frame(rail_frame)
            row.pack(anchor="w", padx=6, pady=1)
            swatch = tk.Canvas(row, width=12, height=12, highlightthickness=0)
            swatch.create_rectangle(0, 0, 12, 12, fill=hex_c, outline="gray")
            swatch.pack(side="left", padx=(0, 3))
            ttk.Radiobutton(row, text=f"색{aci} ({cnt}개)",
                            variable=self._rail_color_var, value=str(aci)).pack(side="left")

        # ── 레일 레이어 (복수 선택) ──
        layer_frame = ttk.LabelFrame(cols, text="레일 레이어 (복수 선택)")
        layer_frame.pack(side="left", fill="both", expand=True, padx=(0, 4), pady=2)
        for lname in sorted_layers:
            cnt = self._layer_counts[lname]
            var = tk.BooleanVar(value=(lname in saved_layers))
            self._rail_layer_vars[lname] = var
            ttk.Checkbutton(layer_frame, text=f"{lname} ({cnt}개)", variable=var).pack(
                anchor="w", padx=6, pady=1)

        # ── 포트 색상 (복수 선택) ──
        port_frame = ttk.LabelFrame(cols, text="포트 색상 (복수 선택)")
        port_frame.pack(side="left", fill="both", expand=True, pady=2)
        for aci in sorted_colors:
            cnt = self._color_counts[aci]
            hex_c = self._aci_hex(aci)
            var = tk.BooleanVar(value=(aci in saved_ports))
            self._port_color_vars[aci] = var
            row = ttk.Frame(port_frame)
            row.pack(anchor="w", padx=6, pady=1)
            swatch = tk.Canvas(row, width=12, height=12, highlightthickness=0)
            swatch.create_rectangle(0, 0, 12, 12, fill=hex_c, outline="gray")
            swatch.pack(side="left", padx=(0, 3))
            ttk.Checkbutton(row, text=f"색{aci} ({cnt}개)", variable=var).pack(side="left")

    # ── 이벤트 ───────────────────────────────────────────────────────────
    def _default_dxf(self) -> str:
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
        self.cfg["color_filter"] = {
            "rail_color": rail_color,
            "port_colors": port_colors,
            "rail_layers": rail_layers,
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
                             rail_layers=rail_layers or None)
            except Exception as e:
                tb = traceback.format_exc()
                self.after(0, self._log, f"[오류] {e}\n{tb}")
            finally:
                self.after(0, lambda: self.btn_run.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    app = App()
    app.mainloop()
