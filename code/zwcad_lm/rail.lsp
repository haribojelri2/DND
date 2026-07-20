;; ============================================================
;;  rail.lsp — ZWCAD LM 레일 플렉시블 블록 연동 (2/3/4차선 전 블록)
;;
;;  현재 블록 구성 (dist 폴더의 DWG 파일명 = 블록 이름)
;;    2차선 : 2rail1 ~ 2rail4    (4개)
;;    3차선 : 3rail1 ~ 3rail8    (8개)
;;    4차선 : 4rail1 ~ 4rail16   (16개)
;;
;;  명령
;;    DRAWRAIL   : 차선 → 번호 → 위치 로 블록 삽입
;;    DRAWRAIL2  : 2차선 블록 삽입 (번호 → 위치)
;;    DRAWRAIL3  : 3차선 블록 삽입
;;    DRAWRAIL4  : 4차선 블록 삽입
;;    RAILLEN    : 선택 레일의 길이(세로, 거리1) 변경
;;    RAILWID    : 선택 레일의 폭(가로, 거리2) 변경
;;    RAILPROPS  : (진단) 블록 이름 + 다이나믹 파라미터 이름/값 출력
;;    RAILLIST   : 사용 가능한 블록/DWG 파일 목록 확인
;;
;;  사용: APPLOAD 로 이 파일 로드 → 위 명령 실행
;;  ※ 거리1·거리2 는 기준점이 서로 반대라, 한 명령에서 둘 다 설정하면
;;    나중 값이 기준을 덮어써 거리2 가 이긴다(실측). 그래서 길이/폭 명령을
;;    분리해 한 번에 하나씩만 설정한다. 그립은 거리1/거리2 각각 그대로 동작.
;; ============================================================

(vl-load-com)

;; ===== 설정 (경로/구성 바뀌면 이 부분만 수정) =====
;; 블록 DWG 들이 있는 폴더 (끝에 / 포함). 지원 경로에 있으면 nil 로 둬도 findfile 이 찾음.
(setq *RAIL-DIR* "C:/Users/User/Desktop/dnd/code/zwcad_lm/dist/")

;; 차선별 블록 개수:  (차선 . 개수)  → 이름 규칙 = <차선>rail<번호>
(setq *RAIL-SETS* '((2 . 4) (3 . 8) (4 . 16)))

;; 파라미터 이름 후보 (도면에 따라 이름이 다를 수 있어 목록으로 매칭)
(setq *RAIL-LEN-PARAMS* '("거리1" "Distance1" "길이"))
(setq *RAIL-WID-PARAMS* '("거리2" "Distance2" "폭"))

;; 내부: 파일명 블록 → 실제(중첩) 다이나믹 블록 이름 캐시
(setq *RAIL-MAP* nil)

;; ---------- 내부 유틸 ----------

;; 다이나믹 파라미터 목록 (다이나믹 블록이 아니면 nil)
(defun rail:props (e / r)
  (if e
    (progn
      (setq r (vl-catch-all-apply
                '(lambda (en)
                   (vlax-safearray->list
                     (vlax-variant-value
                       (vla-getdynamicblockproperties (vlax-ename->vla-object en)))))
                (list e)))
      (if (vl-catch-all-error-p r) nil r))))

;; 블록 참조의 실제 이름 (익명 *U 처리 → EffectiveName)
(defun rail:effname (e / r)
  (setq r (vl-catch-all-apply
            '(lambda (en) (vla-get-effectivename (vlax-ename->vla-object en)))
            (list e)))
  (if (vl-catch-all-error-p r) (cdr (assoc 2 (entget e))) r))

;; 블록 정의가 "INSERT 하나만" 감싼 래퍼면 그 안쪽 블록 이름 반환, 아니면 nil
;;  (블록 참조를 WBLOCK 한 DWG 를 -INSERT 하면 이런 래퍼가 생겨 다이나믹 그립이 죽는다)
(defun rail:nested (bname / bh d cnt sub)
  (setq bh (tblobjname "BLOCK" bname) cnt 0 sub nil)
  (if bh
    (progn
      (setq bh (entnext bh))
      (while (and bh (setq d (entget bh)) (/= (cdr (assoc 0 d)) "ENDBLK"))
        (setq cnt (1+ cnt))
        (if (= (cdr (assoc 0 d)) "INSERT") (setq sub (rail:effname bh)))
        (setq bh (entnext bh)))))
  (if (and sub (= cnt 1) (/= (substr sub 1 1) "*")) sub))

;; 블록 이름 → DWG 경로 (없으면 nil)
(defun rail:file (name / p)
  (cond
    ((and *RAIL-DIR* (setq p (findfile (strcat *RAIL-DIR* name ".dwg")))) p)
    ((setq p (findfile (strcat name ".dwg"))) p)
    (t nil)))

;; -INSERT 인수용 경로 (공백 있으면 따옴표)
(defun rail:q (s)
  (if (vl-string-search " " s) (strcat "\"" s "\"") s))

;; 차선 번호 → 블록 이름 (범위 밖이면 nil)
(defun rail:name (lane idx / nmax)
  (setq nmax (cdr (assoc lane *RAIL-SETS*)))
  (if (and nmax (> idx 0) (<= idx nmax))
    (strcat (itoa lane) "rail" (itoa idx))))

;; 핵심: 블록 삽입 (도면에 있으면 이름으로, 없으면 DWG 에서 / 래퍼면 자동 해제)
(defun rail:insert (name pt / rname f e sub)
  (setq rname (cdr (assoc name *RAIL-MAP*)))      ; 이전에 해제한 적 있으면 실제 이름으로
  (if rname (setq name rname))
  (cond
    ((tblsearch "BLOCK" name)
     (command "_-INSERT" name pt 1 1 0))
    ((setq f (rail:file name))
     (command "_-INSERT" (rail:q f) pt 1 1 0))
    (t
     (princ (strcat "\n[!] '" name ".dwg' 못 찾음. *RAIL-DIR* 확인 또는 지원 경로에 추가."))
     (setq name nil)))
  (if name
    (progn
      (setq e (entlast))
      ;; 삽입 결과가 다이나믹이 아니고, 안에 INSERT 하나뿐이면 → 그 블록으로 다시 삽입
      (if (and e (null (rail:props e))
               (setq sub (rail:nested (cdr (assoc 2 (entget e))))))
        (progn
          (entdel e)
          (command "_-INSERT" sub pt 1 1 0)
          (setq *RAIL-MAP* (cons (cons name sub) *RAIL-MAP*))
          (setq e (entlast))
          (princ (strcat "\n(래퍼 해제: " name " → " sub ")"))))
      (princ (strcat "\n삽입: " (if e (rail:effname e) name)
                     (if (rail:props e) "  [플렉시블 OK]" "  [!] 다이나믹 파라미터 없음")))))
  (princ))

;; 파라미터 읽기 / 쓰기 (이름 후보 목록으로 매칭)
(defun rail:getval (e names / v p)
  (foreach p (rail:props e)
    (if (and (null v) (member (vla-get-propertyname p) names))
      (setq v (vlax-variant-value (vla-get-value p)))))
  v)

(defun rail:setval (e names val / n p)
  (setq n 0)
  (foreach p (rail:props e)
    (if (and (member (vla-get-propertyname p) names)
             (/= (vla-get-readonly p) :vlax-true))
      (progn
        (vla-put-value p (vlax-make-variant val vlax-vbdouble))
        (setq n (1+ n)))))
  n)

;; 길이/폭 변경 공통
(defun rail:resize (names label / e cur v n)
  (setq e (car (entsel (strcat "\n레일 선택 (" label " 변경): "))))
  (cond
    ((null e) (princ "\n선택 없음."))
    ((null (rail:props e))
     (princ "\n[!] 플렉시블(다이나믹) 블록이 아닙니다. RAILPROPS 로 확인하세요."))
    (t
     (setq cur (rail:getval e names))
     (setq v (getreal (strcat "\n새 " label
                              (if cur (strcat " <현재 " (rtos cur 2 1) ">") "") ": ")))
     (if v
       (progn
         (setq n (rail:setval e names v))
         (if (> n 0)
           (princ (strcat "\n" label " = " (rtos v 2 1)))
           (princ (strcat "\n[!] " label " 파라미터(" (car names)
                          ") 없음. RAILPROPS 로 이름 확인 후 설정 목록 수정.")))))))
  (princ))

;; ---------- 명령 ----------

(defun c:RAILLIST ( / nmax i name f s)
  (princ "\n=== 사용 가능한 레일 블록 ===")
  (foreach s *RAIL-SETS*
    (setq nmax (cdr s) i 1)
    (princ (strcat "\n[" (itoa (car s)) "차선] "))
    (while (<= i nmax)
      (setq name (strcat (itoa (car s)) "rail" (itoa i)))
      (setq f (rail:file name))
      (princ (strcat name
                     (cond ((tblsearch "BLOCK" name) "(도면) ")
                           (f "(파일) ")
                           (t "(없음!) "))))
      (setq i (1+ i))))
  (princ (strcat "\n폴더: " (if *RAIL-DIR* *RAIL-DIR* "(지원 경로)")))
  (princ))

(defun c:RAILPROPS ( / e ps p)
  (setq e (car (entsel "\n블록 선택: ")))
  (if e
    (progn
      (princ (strcat "\n블록: " (rail:effname e)))
      (setq ps (rail:props e))
      (if ps
        (progn
          (princ "\n--- 다이나믹 파라미터 ---")
          (foreach p ps
            (princ (strcat "\n  " (vla-get-propertyname p)
                           " = " (vl-princ-to-string (vlax-variant-value (vla-get-value p)))
                           (if (= (vla-get-readonly p) :vlax-true) "  [읽기전용]" "")))))
        (princ "\n[!] 다이나믹 파라미터 없음 (플렉시블 블록 아님 / 래퍼 블록).")))
    (princ "\n선택 없음."))
  (princ))

;; 차선 지정 삽입 (내부)
(defun rail:draw (lane / nmax idx name pt)
  (setq nmax (cdr (assoc lane *RAIL-SETS*)))
  (if (null nmax)
    (princ (strcat "\n[!] " (itoa lane) "차선 구성 없음."))
    (progn
      (initget 6)                                     ; 0·음수 금지
      (setq idx (getint (strcat "\n" (itoa lane) "차선 블록 번호 (1-"
                                (itoa nmax) ") <1>: ")))
      (if (null idx) (setq idx 1))
      (setq name (rail:name lane idx))
      (cond
        ((null name)
         (princ (strcat "\n[!] 번호는 1-" (itoa nmax) " 범위여야 합니다.")))
        ((setq pt (getpoint (strcat "\n" name " 삽입 위치: ")))
         (rail:insert name pt)))))
  (princ))

(defun c:DRAWRAIL ( / lane)
  (initget "2 3 4")
  (setq lane (getkword "\n차선 [2/3/4] <4>: "))
  (rail:draw (if lane (atoi lane) 4)))

(defun c:DRAWRAIL2 () (rail:draw 2))
(defun c:DRAWRAIL3 () (rail:draw 3))
(defun c:DRAWRAIL4 () (rail:draw 4))

(defun c:RAILLEN () (rail:resize *RAIL-LEN-PARAMS* "길이"))
(defun c:RAILWID () (rail:resize *RAIL-WID-PARAMS* "폭"))

(princ "\nrail.lsp 로드됨 (2rail1~4 / 3rail1~8 / 4rail1~16).")
(princ "\n  명령: DRAWRAIL  DRAWRAIL2  DRAWRAIL3  DRAWRAIL4  RAILLEN  RAILWID  RAILPROPS  RAILLIST")
(princ)
