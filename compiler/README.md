# efc — Emulator FPGA Compiler（單顆 FPGA MVP）

參考 Synplify Pro 架構的單顆 FPGA 編譯器最小可行版本，含**自研 P&R**
（VPR 式模擬退火 placement + PathFinder negotiated-congestion routing）。
設計書見 `docs/single-fpga-compiler-architecture.md`。

## Pipeline 與 Synplify Pro 對照

| 階段 | efc 模組 | Synplify Pro 對應 |
|---|---|---|
| HDL 前端（parse） | `efc/verilog.py` | HDL Compiler（語言前端） |
| 展開 / bit-blast | `efc/netlist.py` | HDL Analyst（RTL view，generic netlist） |
| 技術映射 gates→LUTK | `efc/techmap.py` | Technology Mapper（Technology view） |
| Placement（SA） | `efc/place.py` | —（Synplify 交給後端；此為自研 P&R，VPR 式） |
| Routing（PathFinder） | `efc/route.py` | 同上 |
| 時序估算（logic depth） | `efc/timing.py` | Timing Analyst（簡化版） |

## 用法

```bash
cd compiler
python3 -m efc.cli examples/alu4.v --lut-k 4 --grid 10 --tracks 8
python3 -m unittest discover tests -v
```

## Verilog 子集（MVP）

- `module/input/output/wire/reg`、`assign`（`~ & | ^`、括號、常數）
- `always @(posedge clk)`：`y <= expr;` 與 `if (c) y<=e1; else y<=e0;`
- 不支援：concat/切片、case、for-generate、記憶體/DSP 推斷、multi-clock

## 已知限制（誠實清單）

1. **VP1902 bitstream 格式未公開**——自研 P&R 的 MVP 以抽象 CLB grid fabric
   為目標；綁定真機仍需輸出 netlist 給 Vivado（或等待 UltraScale+/Versal
   的 bitstream 逆向進展）。此限制也適用於所有第三方流程。
2. 時序僅邏輯深度估算，未做 RC / 佈線延遲回填。
3. LUT mapper 為貪婪 cone-merge，非最優（後續可換 cut-enumeration）。
4. Routing 圖為最簡 4 鄰 CLB 格，未建模 switch block / wire segment 長度。

## Roadmap

- [ ] concat/切片/case、FSM extraction（對齊 Synplify FSM Compiler）
- [ ] cut-enumeration LUT mapping（FlowMap 式）
- [ ] switch block + timing-driven placement/routing
- [ ] 輸出 Vivado 可吃的 EDIF/XDC（真機路徑）
- [ ] multi-FPGA partition（對齊 roadmap Phase 2，參考 Siemens VPS）
