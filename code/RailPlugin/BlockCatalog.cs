using System;
using System.Collections.Generic;
using Autodesk.AutoCAD.Geometry;

namespace RailPlugin
{
    // 부품 블록 카탈로그 — "분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf" 실측값.
    //  전 블록 base_point=(0,0)이고 지오메트리는 도면 절대좌표에 있음 → 삽입점 = 목표점 − RefOffset.
    //  RefOffset = 각 블록의 기준 포트(레일 접점)의 블록 내 절대좌표.
    //  공통 규격: 호 r=450, 레일=단일선, 접속 스텁=200, 크로스오버 레일간격=900, U턴브릿지 간격=1350.
    public static class BlockCatalog
    {
        public const string SourceDxfName = "분기 레일 형상 세트 정리 (레이아웃 설계) v0_260721.dxf";
        public const double R = 450.0;          // 표준 호 반경
        public const double STUB = 200.0;       // 접속 스텁 길이
        public const double XOVER_GAP = 900.0;  // BRANCH N/BY PASS 내부 레일 간격
        public const double UBRIDGE_GAP = 1350.0; // DOUBLE BRANCH 2CH/4CH 레일 간격

        public sealed class Part
        {
            public string Name;                 // 블록명 (원본 DXF 정의명)
            public Point3d RefOffset;           // 기준 포트(레일 접점)의 블록 내 좌표
            public double RailLen;              // 블록에 포함된 수직 레일 조각 길이 (0=없음)
            public double SpanX;                // 좌우 레일 점유 폭 (0=단일 레일)
            public Part(string name, double rx, double ry, double railLen, double spanX)
            { Name = name; RefOffset = new Point3d(rx, ry, 0); RailLen = railLen; SpanX = spanX; }
        }

        // 기준 포트 = 블록 내 "수직 레일 조각의 하단" (실측 절대좌표)
        public static readonly Dictionary<string, Part> Parts = new Dictionary<string, Part>
        {
            // 코너(아치 반쪽): 레일조각 1035 + 호 r450 + 수평스텁 200
            //  BRANCH LEFT  : 레일 우측, 스텁이 왼쪽(−650,650) — 아치 '우측' 코너로 사용
            //  BRANCH RIGHT : 레일 좌측, 스텁이 오른쪽(+650,650) — 아치 '좌측' 코너로 사용
            ["BRANCH LEFT"]  = new Part("BRANCH LEFT",  51980.7, 35377.1, 1035, 0),
            ["BRANCH RIGHT"] = new Part("BRANCH RIGHT", 51980.7, 33255.2, 1035, 0),

            // 크로스오버(N분기, 관통): 45° 대각 + 호 2 + 레일조각. 900/650.
            //  ★레일조각 = 도면 기입 치수 1670 (_650 파생은 1420). 2026-07-28 수정:
            //   N 1502(접점 114.6)·BY PASS 1672.8(접점 200) → 호 접점을 전 계열 198.6 으로 통일.
            //   호·대각선은 불변 → 조립 앵커(대각 중심) 영향 없음. 스크립트=fix_branch_n_1670.py
            ["BRANCH N LEFT"]       = new Part("BRANCH N LEFT",       42092.6, 49566.9, 1670, 900),
            ["BRANCH N RIGHT"]      = new Part("BRANCH N RIGHT",      44168.9, 49816.9, 1670, 900),
            ["BRANCH N LEFT_650"]   = new Part("BRANCH N LEFT_650",   0, -84, 1420, 650),
            ["BRANCH N RIGHT_650"]  = new Part("BRANCH N RIGHT_650",  0, -84, 1420, 650),
            // 바이패스(터미널, 합류): 45°. 900/650.
            ["BRANCH BY PASS LEFT"] = new Part("BRANCH BY PASS LEFT", 42092.6, 46524.6, 1670, 900),
            ["BRANCH BY PASS RIGHT"]= new Part("BRANCH BY PASS RIGHT",43918.9, 46524.6, 1670, 900),
            ["BRANCH BY PASS LEFT_650"]  = new Part("BRANCH BY PASS LEFT_650",  0, 1.4, 1420, 650),
            ["BRANCH BY PASS RIGHT_650"] = new Part("BRANCH BY PASS RIGHT_650", 0, 1.4, 1420, 650),

            // U턴 브릿지: 좌우 레일조각 1035 + 호 2개 + 바 450. 레일간격 1350 고정.
            ["DOUBLE BRANCH 2CH"] = new Part("DOUBLE BRANCH 2CH", 27592.0, 60273.1, 1035, 1350),
            ["DOUBLE BRANCH 4CH"] = new Part("DOUBLE BRANCH 4CH", 49839.1, 27000.5, 2000, 1350),
            // U턴 브릿지 900폭: 반원(같은 중심 호쌍), 바 없음. 0-기반.
            ["DOUBLE BRANCH 2CH_900"] = new Part("DOUBLE BRANCH 2CH_900", 0, 0, 1035, 900),
            ["DOUBLE BRANCH 4CH_900"] = new Part("DOUBLE BRANCH 4CH_900", 0, 0, 2000, 900),

            // 완성형 아치(고정 변형): 바 + 호 2개 + 하향 스텁 200×2 (스텁 간격 650/700/1000)
            ["DOUBLE BRANCH"]      = new Part("DOUBLE BRANCH",      33644.4, 44120.4, 0, 650),
            ["DOUBLE BRANCH_700"]  = new Part("DOUBLE BRANCH_700",  50157.1, 31348.3, 0, 700),
            ["DOUBLE BRANCH_1000"] = new Part("DOUBLE BRANCH_1000", 50157.1, 29529.2, 0, 1000),

            // 코너+분기 복합(VEER)
            ["DOUBLE BRANCH VEER LEFT"]  = new Part("DOUBLE BRANCH VEER LEFT",  53187.7, 41575.5, 0, 0),
            ["DOUBLE BRANCH VEER RIGHT"] = new Part("DOUBLE BRANCH VEER RIGHT", 51549.4, 40847.3, 0, 0),
            ["DOUBLE BRANCH VEER 4CH"]   = new Part("DOUBLE BRANCH VEER 4CH",     -809.9, 65447.7, 0, 1350),
        };

        // 수량 집계 키 — 폭 변형(_900/_650)을 본체 이름 + 폭 으로 통합.
        //  [사용자 규칙] 고정폭 집합(900·1020·1270·1350)을 DOUBLE BRANCH 4CH 하나의 단위로 인식.
        //  변환기 part_counter.py 의 CANON_NAME/NATIVE_WIDTH 와 같은 규칙.
        public static string CountKey(string blockName)
        {
            string n = (blockName ?? "").Trim();
            double w = 0;
            switch (n)
            {
                case "DOUBLE BRANCH 2CH": w = 1350; break;
                case "DOUBLE BRANCH 4CH": w = 1350; break;
                case "DOUBLE BRANCH 2CH_900": n = "DOUBLE BRANCH 2CH"; w = 900; break;
                case "DOUBLE BRANCH 4CH_900": n = "DOUBLE BRANCH 4CH"; w = 900; break;
                case "DOUBLE BRANCH": w = 650; break;
                case "DOUBLE BRANCH_700": w = 700; break;
                case "DOUBLE BRANCH_1000": w = 1000; break;
                case "BRANCH N LEFT": case "BRANCH N RIGHT":
                case "BRANCH BY PASS LEFT": case "BRANCH BY PASS RIGHT": w = 900; break;
                case "BRANCH N LEFT_650": n = "BRANCH N LEFT"; w = 650; break;
                case "BRANCH N RIGHT_650": n = "BRANCH N RIGHT"; w = 650; break;
                case "BRANCH BY PASS LEFT_650": n = "BRANCH BY PASS LEFT"; w = 650; break;
                case "BRANCH BY PASS RIGHT_650": n = "BRANCH BY PASS RIGHT"; w = 650; break;
            }
            return n + "|" + w.ToString("0");
        }

        // ── BAY 1 실측 조립 공식 (레퍼런스 레이아웃) ──
        //  레일 간격 W(기본 2520), 길이 L.
        //  U아치: 코너 호 중심 = (레일x ± 450 안쪽, 레일끝 y), 바 y = 레일끝 ± 450, 바 길이 = W − 900.
        //  보타이 스테이션: 바 2개(간격 700, 각 W−900) + 호 4개(중심 = 바에서 ∓450).
        //  외부 출입 스텁: 레일 바깥쪽 400mm 수평선 (레일±200 중심).
        public const double BAY_W_DEFAULT = 2520.0;
        public const double BOWTIE_BAR_GAP = 700.0;   // 보타이 바 간격
        public const double ARCH_BAR_INSET = 450.0;   // 바 y = 레일끝에서 450
    }
}
