# efc — Emulator FPGA Compiler（單顆 FPGA，目標 VP1902）

參考 Synplify Pro 架構的單顆 FPGA 編譯器，含**自研 P&R**
（VPR 式模擬退火 placement + PathFinder routing），並可輸出
**EDIF 2.0.0 網表 + XDC 約束**接 Vivado 跑真機（xcvp1902）。
設計書見 `docs/single-fpga-compiler-architecture.md`。

## Pipeline 與 Synplify Pro 對照

| 階段 | efc 模組 | Synplify Pro 對應 |
|---|---|---|
| HDL 前端（parse） | `efc/verilog.py` | HDL Compiler（語言前端） |
| 展開 / bit-blast | `efc/netlist.py` | HDL Analyst（RTL view，generic netlist） |
| 技術映射 gates→LUT6 + INIT | `efc/techmap.py` | Technology Mapper（Technology view） |
| CLB 打包（8×LUT6+16FF） | `efc/pack.py` | —（VP1902 slice 結構，BLE packing） |
| Placement（SA，block 級） | `efc/place.py` | —（自研 P&R，VPR 式） |
| Routing（PathFinder） | `efc/route.py` | 同上 |
| 時序估算（logic depth） | `efc/timing.py` | Timing Analyst（簡化版） |
| EDIF/XDC 輸出 | `efc/edif.py` | Synplify 的 EDIF+SDC 出貨格式 |

## VP1902 目標

- 原生 LUT6 映射（CLB = 8×LUT6 + 16×FF 打包）。
- 容量對照真機 envelope：8.46M LUT6 / 16.92M FF / 6,864 DSP58 /
  239 Mb BRAM / 619 Mb URAM / 2,328 SelectIO，報表給出利用率。
- P&R 在邏輯 CLB 格陣上進行（bitstream 未公開，見「已知限制」）。

## 用法

```bash
cd compiler
python3 -m efc.cli examples/alu4.v --grid 8 --tracks 8 \
    --edif out/alu4.edif --xdc out/alu4.xdc
python3 -m unittest discover tests -v
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
2. 時序僅邏輯深度估算，未做 RC / 佈線延遲回填。
3. LUT mapper 為貪婪 cone-merge，非最優（後續換 cut-enumeration）。
4. Routing 為最簡 4 鄰格圖，未建模 switch block / wire segment 長度。

## Roadmap

- [ ] concat/切片/case、FSM extraction（對齊 Synplify FSM Compiler）
- [ ] cut-enumeration LUT mapping（FlowMap 式）、BRAM/DSP58 推斷、CARRY8
- [ ] switch block + timing-driven P&R
- [x] EDIF/XDC 輸出接 Vivado（v0.2；真機驗證待跑）
- [ ] multi-FPGA partition（對齊 roadmap Phase 2，參考 Siemens VPS）
