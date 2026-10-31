# efc — Emulator FPGA Compiler（單顆 FPGA，目標 VP1902）

參考 Synplify Pro 架構的單顆 FPGA 編譯器，含**自研 P&R**
（smart-centroid + SA placement、A* timing-driven PathFinder routing、
cut-enumeration LUT mapping、SAT-based LEC 等價驗證），並可輸出
**EDIF 2.0.0 網表 + XDC 約束**接 Vivado 跑真機（xcvp1902），或輸出
**7-series primitives Verilog** 走 OpenXC7/nextpnr-xilinx 無 Vivado 迴路
（靶機 Kintex-7 xc7k325t）。
目標元件由 **data-driven 架構描述檔**（`arch/vp1902.json`、`arch/xc7k325t.json`）定義，
換元件不必改演算法。設計書見 `docs/single-fpga-compiler-architecture.md`；
改進計劃見 `docs/compiler-improvement-plan.md`。

## Pipeline 與 Synplify Pro 對照

| 階段 | efc 模組 | Synplify Pro 對應 |
|---|---|---|
| HDL 前端（parse） | `efc/verilog.py` | HDL Compiler（語言前端） |
| 展開 / bit-blast | `efc/netlist.py` | HDL Analyst（RTL view，generic netlist） |
| 技術映射 gates→LUT6 + INIT | `efc/techmap.py` + `efc/cutmap.py` | Technology Mapper（Technology view） |
| LEC 等價驗證（generic vs mapped netlist） | `efc/lec.py` | Formality/LEC（Yosys equiv_make/simple/induct） |
| 架構描述（JSON，data-driven） | `efc/arch.py` + `arch/vp1902.json` | —（VPR architecture XML 對應） |
| Prepack molecules（lutff/carry8） | `efc/prepack.py` | —（VPR prepacker 對應） |
| CLB 打包（8×LUT6+16FF） | `efc/pack.py` | —（VP1902 slice 結構，BLE packing） |
| Placement（smart-centroid seed + SA） | `efc/place.py` | —（自研 P&R，VPR 式） |
| Routing（A* timing-driven PathFinder） | `efc/route.py` | 同上 |
| STA（Elmore + slack/criticality） | `efc/timing.py` | Timing Analyst |
| EDIF/XDC 輸出 | `efc/edif.py` | Synplify 的 EDIF+SDC 出貨格式 |
| 7-series primitives 輸出（`--xc7`） | `efc/xc7out.py` | —（OpenXC7/nextpnr-xilinx 無 Vivado 路徑） |
| QoR golden 回歸（`benchmarks/`） | `efc/qor.py` | —（VTR golden-QoR 追蹤） |

## VP1902 目標

- 原生 LUT6 映射（CLB = 8×LUT6 + 16×FF 打包）。
- 容量對照真機 envelope：8.46M LUT6 / 16.92M FF / 6,864 DSP58 /
  239 Mb BRAM / 619 Mb URAM / 2,328 SelectIO，報表給出利用率。
- 架構描述檔（`arch/vp1902.json`）攜帶 CLB 結構、routing segment
  （長度/頻率/R/C）、switch block（wilton, Fs=3）、IO 擺放策略；
  timing 與 segment 資料供後續 timing-driven pass 使用。
- P&R 在邏輯 CLB 格陣上進行（bitstream 未公開，見「已知限制」）。

## 用法

```bash
cd compiler
python3 -m efc.cli examples/alu4.v --grid 8 --tracks 8 \
    --arch vp1902 --clock 10 --edif out/alu4.edif --xdc out/alu4.xdc
python3 -m unittest discover tests -v
```

`--arch` 接受 `arch/` 下的名稱或任一 JSON 描述檔路徑；`--clock` 設定
STA 與 XDC 的時脈週期（ns），違例時 CLI 以 exit 1 回報。
`--mapper {cut,greedy}` 切換 LUT mapper（預設 cut-enumeration，greedy 供 A/B）。
`--lec` 對 mapping 結果跑 SAT 等價驗證（需 yosys；proven/failed/skipped
三態，無 yosys 時誠實報 skipped 不偽造通過，failed/error 時 CLI exit 1）。
編譯報表的 `molecules` 行顯示 prepack 分子統計
（single/lutff/carry8，v0.11 起，QoR golden 追蹤項之一）。
`--xc7 out.v` 輸出 7-series primitives Verilog（LUT1–6/FDRE/IBUF/OBUF，
搭配 `--arch xc7k325t`），接續指令：

```bash
yosys -p "read_verilog -lib +/xilinx/cells_sim.v; read_verilog out.v; \
    hierarchy -top <top> -purge_lib; proc; write_json out.json"
nextpnr-xilinx --chipdb <xc7k325t chipdb> --json out.json  # 需 OpenXC7 chipdb
```

QoR 回歸（v0.10）：`benchmarks/` 語料庫（alu4/maj4/mixer8/regpipe8/sel4）
跑完整 flow，`golden.json` 鎖定確定性指標（LUTs/DFF/CLB/logic depth/CP/
HPWL/wirelength/channel 用量/LEC 狀態），runtime 只記錄漂移不斷言：

```bash
python3 -m efc.qor --update   # 在已知良好樹上記錄 golden（建議帶 yosys）
python3 -m efc.qor --check    # 比對 golden，有任何確定性漂移即 exit 1
```

## Verilog 子集（MVP）

- `module/input/output/wire/reg`、`assign`（`~ & | ^`、括號、常數）
- `always @(posedge clk)`：`y <= expr;` 與 `if (c) y<=e1; else y<=e0;`
- 不支援：concat/切片、case、for-generate、記憶體/DSP 推斷、multi-clock

## 已知限制（誠實清單）

1. **VP1902 bitstream 格式未公開**——自研 P&R 以邏輯 CLB 格陣為目標；
   真機路徑為 EDIF/XDC → Vivado。EDIF 遵循 Synplify 的 `hdi_primitives`
   外部庫慣例（LUT1–6/FDRE + INIT property），**尚未在真 Vivado 上驗證**，
   第一次上機前需用 Vivado `link_design` 檢查。
2. 時序為 STA（Elmore wire delay 依 placement HPWL 估算 + t_lut/t_clkq/t_setup
   來自 arch 描述檔），但尚未依真實 routing 拓撲回填延遲。
3. LUT mapper 已換 cut-enumeration（v0.7，ABC/FlowMap 式，`--mapper greedy`
   可 A/B 對照舊版）；v0.8 起 `--lec` 對 netlist→LUT mapping 做 SAT 等價
   驗證（Yosys equiv，覆蓋 techmap 一級）；未來可加 priority cuts 截斷、
   timing-driven mapping，並把 LEC 擴展到 pack/EDIF 之後。
4. Routing 已換 A* directed search + lookahead 並消費 STA criticality（v0.5），但仍為最簡 4 鄰格圖，未消費 arch 的 switch block / segment 長度。
5. `arch/vp1902.json` 的 timing 與 R/C 為邏輯模型估計值，非矽真值
   （VP1902 詳細 timing 未公開）。
6. Placement 的 centroid seeding 之 legalization 是 greedy nearest-free-slot
   （O(nb×slots)）；設計規模變大後換 Hungarian/auction 求解器。
7. `--xc7` 輸出已驗證可被 stock Yosys 讀取並轉出 nextpnr-xilinx 用的 JSON
   （cell 集合限 LUT1–6/FDRE/IBUF/OBUF）；**bitstream 段需 nextpnr-xilinx +
   xc7k325t chipdb（Project X-Ray 資料），在本沙箱外執行，尚未上板**。
8. QoR golden（`benchmarks/golden.json`）鎖的是**當前演算法行為**而非
   品質上界——允許故意改進時以 `--update` 重記（應在 commit message 說明
   哪些指標變動、為何可接受）；runtime 欄位永不斷言，僅供漂移參考。
9. prepack 的 **carry8 分子框架已落地（v0.11）但尚無端到端來源**：
   Verilog 子集無 `+` 算子，CARRY8 chain 目前經 `LutNet.carry_chains`
   標註注入（單元測試覆蓋）；BRAM/DSP58 分子同理，待前端推斷落地後啟用。

## Roadmap

- [ ] concat/切片/case、FSM extraction（對齊 Synplify FSM Compiler）
- [x] cut-enumeration LUT mapping（v0.7，FlowMap 式 depth label + area flow）
- [x] LEC 驗證迴圈（v0.8，Yosys equiv_make/simple/induct，`--lec`）
- [ ] BRAM/DSP58 推斷、CARRY8
- [x] STA：Elmore RC + arrival/required/slack/criticality（v0.4）
- [x] Router BFS → A* + lookahead，消費 criticality（v0.5）
- [x] Placement smart-centroid 初始解 + SA refine（v0.6）
- [ ] switch block 建模 + routing 拓撲延遲回填（消費 arch segment/R-C 表）
- [x] Arch 描述檔化（v0.3；`arch/vp1902.json` + `efc/arch.py`）
- [x] EDIF/XDC 輸出接 Vivado（v0.2；真機驗證待跑）
- [x] OpenXC7 靶機後端（v0.9：`arch/xc7k325t.json` + `--xc7` 7-series primitives
      輸出，Yosys→JSON 段已驗證；bitstream 段待 nextpnr-xilinx chipdb 環境）
- [x] QoR golden 回歸系統（v0.10：`efc/qor.py` + `benchmarks/` 5 設計語料，
      確定性指標精確比對、runtime 僅記錄漂移，LEC 納入 golden）
- [x] Prepacking molecules（v0.11：`efc/prepack.py`，lutff 強制配對框架化 +
      carry8 鏈分子（容量/歸屬校驗，atomic 打包）；BRAM/DSP 待前端推斷）
- [ ] 固定 shell + runtime patch（overlay/PR）評估：迭代編譯去 Vivado 化；
      注意 overlay 面積 overhead 約 2–10×，僅適合中小設計快速迭代
- [ ] multi-FPGA partition（對齊 roadmap Phase 2，參考 Siemens VPS）
