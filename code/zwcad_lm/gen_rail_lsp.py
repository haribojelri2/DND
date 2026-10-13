# -*- coding: utf-8 -*-
"""
rail.lsp / rail_gen.lsp 생성기.
실행하면 이 스크립트와 같은 폴더에 두 LISP 파일을 쓴다.

    python gen_rail_lsp.py

  - rail.lsp     : 플렉시블 블록 연동 (삽입 + vlax 길이변경 + 진단). 그립 사용 시.
  - rail_gen.lsp : 순수 LISP 레일 (entmake 생성 + 재생성 길이변경). 그립 없이, 명령어만.
"""
import os

# ── rail.lsp (플렉시블 블록 연동) ─────────────────────────────
RAIL_LSP = r'''
;; ============================================================
;;  rail.lsp — ZWCAD LM 레일 플렉시블 블록 연동
;;    DRAWRAIL2 : 플렉시블 블록 삽입 (리본 버튼: ^C^CDRAWRAIL2)
;;    RAILLEN   : 선택한 레일 길이를 명령어로 변경 (vlax로 파라미터 설정)
;;    RAILPROPS : (진단) 블록의 다이나믹 파라미터 이름/값 출력
;;  사용: APPLOAD 로 로드 → DRAWRAIL2 / RAILLEN / RAILPROPS
;; ============================================================

(vl-load-com)

;; ===== 설정 (블록/경로 바뀌면 이 3줄만 수정) =====
(setq *RAIL-DWG*      "RAIL2.dwg")             ; 블록 DWG 파일명. 지원 경로/도면 폴더에 두면 findfile 이 찾음(절대경로도 가능)
(setq *RAIL-BLOCK*    "RAIL2")                 ; 블록 이름
(setq *RAIL-LENPARAMS* '("거리1"))            ; 명령어 리사이즈용 파라미터 = 거리1 (실측: RAILLEN 은 거리1 가 효과 있음).
;; (거리1·거리2 는 기준점 반대. 명령어로 둘 다 설정하면 나중 값이 기준을 덮어써서 거리2 가 이김.
;;  그래서 명령어는 거리1 하나만 설정. 그립은 거리1/거리2 각각 그대로 양방향 동작.)

;; ----- 내부: 블록의 다이나믹 파라미터 목록(vla-object 리스트) -----
(defun rail:getprops (obj)
  (vlax-safearray->list
    (vlax-variant-value (vla-getdynamicblockproperties obj))))

;; ----- 진단: 파라미터 이름/값 출력 -----
(defun c:RAILPROPS ( / e obj)
  (setq e (car (entsel "\n플렉시블 블록 선택: ")))
  (if e
    (progn
      (setq obj (vlax-ename->vla-object e))
      (princ "\n--- 다이나믹 파라미터 ---")
      (foreach p (rail:getprops obj)
        (princ (strcat "\n  " (vla-get-propertyname p)
                       " = " (vl-princ-to-string (vlax-variant-value (vla-get-value p)))
                       (if (= (vla-get-readonly p) :vlax-true) "  [읽기전용]" "")))))
    (princ "\n선택 없음."))
  (princ))

;; ----- 삽입 (도면에 블록 있으면 이름으로, 없으면 지원경로의 DWG 파일에서) -----
(defun c:DRAWRAIL2 ( / pt dwg)
  (setq pt (getpoint "\n레일 삽입 위치: "))
  (if pt
    (if (tblsearch "BLOCK" *RAIL-BLOCK*)
      (command "_-INSERT" *RAIL-BLOCK* pt 1 1 0)   ; 이미 도면에 있으면 이름으로 (재정의 프롬프트 회피)
      (progn
        (setq dwg (findfile *RAIL-DWG*))           ; 지원 경로/도면 폴더에서 RAIL2.dwg 찾기
        (if dwg
          (command "_-INSERT" dwg pt 1 1 0)
          (princ (strcat "\n[!] '" *RAIL-DWG* "' 못 찾음. 지원 경로에 넣거나 도면에 블록을 먼저 삽입하세요."))))))
  (princ))

;; ----- 길이 변경 (vlax로 파라미터 설정) -----
(defun c:RAILLEN ( / e obj newlen n)
  (setq e (car (entsel "\n레일 선택: ")))
  (if e
    (progn
      (setq newlen (getreal "\n새 길이: "))
      (if newlen
        (progn
          (setq obj (vlax-ename->vla-object e) n 0)
          (foreach p (rail:getprops obj)
            (if (member (vla-get-propertyname p) *RAIL-LENPARAMS*)
              (progn
                (vla-put-value p (vlax-make-variant newlen vlax-vbdouble))
                (setq n (1+ n)))))
          (if (> n 0)
            (princ (strcat "\nRAILLEN: 길이 = " (rtos newlen 2 1) "  (" (itoa n) "개 파라미터 설정)"))
            (princ "\n[!] 길이 파라미터 못 찾음. RAILPROPS 로 이름 확인 후 *RAIL-LENPARAMS* 수정."))))))
  (princ))

(princ "\nrail.lsp 로드됨.  명령: DRAWRAIL2 / RAILLEN / RAILPROPS")
(princ)
'''

# ── rail_gen.lsp (순수 LISP 재생성) ─────────────────────────────
RAIL_GEN_LSP = r'''
;; ============================================================
;;  rail_gen.lsp — 순수 LISP 2차선 레일 (플렉시블 블록 불필요)
;;    DRAWRAIL2 : 지정 위치에 레일 생성 (entmake, 기본 길이 30000)
;;    RAILLEN   : 레일 선택 → 새 길이 → 지우고 정확히 재생성
;;  조인트 위치를 코드가 매번 (길이×비율) 로 계산 → 비례 항상 정확.
;;  (그립 없음. 리사이즈는 명령어로 길이 입력.)
;; ============================================================

;; ── 상수 (gen_rail2_base.py 와 동일) ──
(setq RA:HALF_W 960.0)
(setq RA:R 450.0)
(setq RA:BAR_DY 325.0)
(setq RA:THROAT_BAR_DY 680.0)
(setq RA:MINLEN 12000.0)  ; 이보다 짧으면 양 끝 throat·조인트가 겹쳐 이상해짐 → 하한
(setq RA:NECK (- RA:HALF_W RA:R))                 ; 510  (호가 edge 에 맞물림)
(setq RA:ARC_DY (+ RA:R RA:BAR_DY))               ; 775  (호가 바에 맞물림)
(setq RA:THROAT_ARC_DY (+ RA:R RA:THROAT_BAR_DY)) ; 1130
(setq RA:JOINT_FRACS (list 0.25 0.75))            ; 조인트 2개: 1/4, 3/4
(setq RA:APP "RAILPLUGIN")
(if (null RA:CTR) (setq RA:CTR 0))

(defun ra:d2r (d) (* pi (/ d 180.0)))

(defun ra:xd (id len bx by)
  (list -3 (list RA:APP (cons 1070 id) (cons 1040 len) (cons 1040 bx) (cons 1040 by))))

(defun ra:line (bx by x0 y0 x1 y1 xd)
  (entmake (list '(0 . "LINE")
                 (list 10 (+ bx x0) (+ by y0) 0.0)
                 (list 11 (+ bx x1) (+ by y1) 0.0)
                 xd)))

(defun ra:arc (bx by cx cy a0 a1 xd)
  (entmake (list '(0 . "ARC")
                 (list 10 (+ bx cx) (+ by cy) 0.0)
                 (cons 40 RA:R)
                 (cons 50 (ra:d2r a0))
                 (cons 51 (ra:d2r a1))
                 xd)))

(defun ra:draw (bx by len id / cxo xd frac yc)
  (if (< len RA:MINLEN) (setq len RA:MINLEN))
  (regapp RA:APP)
  (setq xd (ra:xd id len bx by))
  (ra:line bx by (- RA:HALF_W) 0.0 (- RA:HALF_W) len xd)
  (ra:line bx by RA:HALF_W 0.0 RA:HALF_W len xd)
  (setq cxo (+ RA:HALF_W RA:R))
  (ra:arc bx by (- cxo) 0.0 270 360 xd)
  (ra:arc bx by cxo 0.0 180 270 xd)
  (ra:arc bx by (- cxo) len 0 90 xd)
  (ra:arc bx by cxo len 90 180 xd)
  (ra:line bx by (- RA:NECK) RA:THROAT_BAR_DY RA:NECK RA:THROAT_BAR_DY xd)
  (ra:arc bx by (- RA:NECK) RA:THROAT_ARC_DY 180 270 xd)
  (ra:arc bx by RA:NECK RA:THROAT_ARC_DY 270 360 xd)
  (ra:line bx by (- RA:NECK) (- len RA:THROAT_BAR_DY) RA:NECK (- len RA:THROAT_BAR_DY) xd)
  (ra:arc bx by (- RA:NECK) (- len RA:THROAT_ARC_DY) 90 180 xd)
  (ra:arc bx by RA:NECK (- len RA:THROAT_ARC_DY) 0 90 xd)
  (foreach frac RA:JOINT_FRACS
    (setq yc (* len frac))
    (ra:line bx by (- RA:NECK) (- yc RA:BAR_DY) RA:NECK (- yc RA:BAR_DY) xd)
    (ra:line bx by (- RA:NECK) (+ yc RA:BAR_DY) RA:NECK (+ yc RA:BAR_DY) xd)
    (ra:arc bx by (- RA:NECK) (- yc RA:ARC_DY) 90 180 xd)
    (ra:arc bx by RA:NECK (- yc RA:ARC_DY) 0 90 xd)
    (ra:arc bx by (- RA:NECK) (+ yc RA:ARC_DY) 180 270 xd)
    (ra:arc bx by RA:NECK (+ yc RA:ARC_DY) 270 360 xd))
  len)

(defun ra:get (e / x)
  (setq x (assoc -3 (entget e (list RA:APP))))
  (if x (cdr (car (cdr x)))))

(defun c:DRAWRAIL2 ( / pt)
  (setq pt (getpoint "\n레일 삽입 위치: "))
  (if pt
    (progn
      (setq RA:CTR (1+ RA:CTR))
      (ra:draw (car pt) (cadr pt) 30000.0 RA:CTR)
      (princ (strcat "\nDRAWRAIL2: 레일 생성 (id=" (itoa RA:CTR) ", 길이 30000)"))))
  (princ))

(defun c:RAILLEN ( / e items id bx by newlen ss i en2 it2)
  (setq e (car (entsel "\n레일 선택: ")))
  (if e
    (progn
      (setq items (ra:get e))
      (if items
        (progn
          (setq id (cdr (nth 0 items)))
          (setq bx (cdr (nth 2 items)))
          (setq by (cdr (nth 3 items)))
          (setq newlen (getreal "\n새 길이: "))
          (if newlen
            (progn
              (setq ss (ssget "X" (list (list -3 (list RA:APP)))))
              (if ss
                (progn
                  (setq i 0)
                  (repeat (sslength ss)
                    (setq en2 (ssname ss i))
                    (setq i (1+ i))
                    (setq it2 (ra:get en2))
                    (if (and it2 (= id (cdr (nth 0 it2))))
                      (entdel en2)))))
              (ra:draw bx by newlen id)
              (princ (strcat "\nRAILLEN: 길이=" (rtos newlen 2 1))))))
        (princ "\n[!] 레일이 아님 (RAILPLUGIN XData 없음).")))
    (princ "\n선택 없음."))
  (princ))

(princ "\nrail_gen.lsp 로드됨.  명령: DRAWRAIL2 (생성) / RAILLEN (길이변경)")
(princ)
'''


def main():
    print("start")
    here = os.path.dirname(os.path.abspath(__file__))
    for name, content in (("rail.lsp", RAIL_LSP), ("rail_gen.lsp", RAIL_GEN_LSP)):
        path = os.path.join(here, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.lstrip("\n"))
        print("wrote %s (%d bytes)" % (path, len(content)))


if __name__ == "__main__":
    main()
