# efc — Emulator FPGA Compiler（單顆 FPGA，目標 VP1902）

參考 Synplify Pro 架構的單顆 FPGA 編譯器，含**自研 P&R**
（VPR 式模擬退火 placement + PathFinder routing），並可輸出
**EDIF 2.0.0 網表 + XDC 約束**接 Vivado 跑真機（xcvp1902）。
目標元件由 **data-driven 架構描述檔**（`arch/vp1902.json`）定義，
換元件不必改演算法。設計書見 `docs/single-fpga-compiler-architecture.md`；
改進計劃見 `docs/compiler-improvement-plan.md`。

## Pipeline 與 Synplify Pro 對照

| 階段 | efc 模組 | Synplify Pro 對應 |
|---|---|---|
| HDL 前端（parse） | `efc/verilog.py` | HDL Compiler（語言前端） |
| 展開 / bit-blast | `efc/netlist.py` | HDL Analyst（RTL view，generic netlist） |
| 技術映射 gates→LUT6 + INIT | `efc/techmap.py` | Technology Mapper（Technology view） |
| 架構描述（JSON，data-driven） | `efc/arch.py` + `arch/vp1902.json` | —（VPR architecture XML 對應） |
| CLB 打包（8×LUT6+16FF） | `efc/pack.py` | —（VP1902 slice 結構，BLE packing） |
| Placement（SA，block 級） | `efc/place.py` | —（自研 P&R，VPR 式） |
| Routing（A* timing-driven PathFinder） | `efc/route.py` | 同上 |
| STA（Elmore + slack/criticality） | `efc/timing.py` | Timing Analyst |
| EDIF/XDC 輸出 | `efc/edif.py` | Synplify 的 EDIF+SDC 出貨格式 |

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
3. LUT mapper 為貪婪 cone-merge，非最優（後續換 cut-enumeration）。
4. Routing 已換 A* directed search + lookahead 並消費 STA criticality（v0.5），但仍為最簡 4 鄰格圖，未消費 arch 的 switch block / segment 長度。
5. `arch/vp1902.json` 的 timing 與 R/C 為邏輯模型估計值，非矽真值
   （VP1902 詳細 timing 未公開）。

## Roadmap

- [ ] concat/切片/case、FSM extraction（對齊 Synplify FSM Compiler）
- [ ] cut-enumeration LUT mapping（FlowMap 式）、BRAM/DSP58 推斷、CARRY8
- [x] STA：Elmore RC + arrival/required/slack/criticality（v0.4）
- [x] Router BFS → A* + lookahead，消費 criticality（v0.5）
- [ ] switch block 建模 + routing 拓撲延遲回填（消費 arch segment/R-C 表）
- [x] Arch 描述檔化（v0.3；`arch/vp1902.json` + `efc/arch.py`）
- [x] EDIF/XDC 輸出接 Vivado（v0.2；真機驗證待跑）
- [ ] OpenXC7（UltraScale+）目標後端：不需 Vivado 的端到端真 bitstream 驗證靶機
- [ ] 固定 shell + runtime patch（overlay/PR）評估：迭代編譯去 Vivado 化；
      注意 overlay 面積 overhead 約 2–10×，僅適合中小設計快速迭代
- [ ] multi-FPGA partition（對齊 roadmap Phase 2，參考 Siemens VPS）
