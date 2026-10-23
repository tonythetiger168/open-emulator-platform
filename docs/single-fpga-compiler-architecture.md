# 單顆 FPGA Compiler 架構設計書

> open-emulator-platform 專案 ｜ 2026-10-23 ｜ v0.1（MVP）
> 參考 Synplify Pro 架構，含自研 P&R。程式碼骨架：`compiler/`（Python，可跑 `examples/alu4.v` 端到端）。

## 1. 目標與範圍

為自研 emulator 建立編譯器的第一塊基石：**單顆 FPGA 的完整編譯流程**——
從 Verilog 子集到可佈局的 LUT/FF 網表，再做自研 placement 與 routing。
單顆流程跑通後，multi-FPGA partition（roadmap Phase 2）才有所依附。

- 參考藍本：**Synplify Pro**（compile → elaborate → map → optimize 的經典 FPGA synthesis 流程）。
- P&R：**自研**（Synplify 本身不含 P&R；此部分參考學術界 VPR 架構）。
- MVP 語言子集：見 `compiler/README.md`。

## 2. Synplify Pro 架構回顧（我們參考什麼）

Synplify Pro 的經典流水線：

1. **HDL Compiler（語言前端）**：Verilog/VHDL → AST → generic 網表。
2. **HDL Analyst**：RTL view / Technology view 兩級檢視——前者是架構無關的
   暫存器傳輸級結構，後者是映射到 LUT/FF/BRAM/DSP 的結果。
3. **高階優化**：常數傳播、resource sharing、**FSM Compiler**（狀態機抽取與
   重編碼）、**retiming**（pipeline 平衡）。
4. **Technology Mapper**：generic gates → 目標元件 primitives（LUT mapping、
   carry chain、記憶體與 DSP 推斷）。
5. **輸出**：EDIF/netlist + SDC 約束，交給廠商 P&R（Vivado/Quartus）——
   Synplify 到這層為止，**不碰 placement/routing**。

## 3. efc pipeline 對照

```
verilog.py   語言前端（lexer/parser/AST）          ~ HDL Compiler
netlist.py   展開 + bit-blast → generic gates      ~ HDL Analyst (RTL view)
               AND2/OR2/XOR2/NOT/MUX2/DFF
techmap.py   gates → LUTK（greedy cone-merge）     ~ Technology Mapper (Tech view)
place.py     SA placement（HPWL 成本，VPR 式）     ← 自研 P&R 起點
route.py     PathFinder negotiated-congestion      ← 自研 P&R
timing.py    logic depth 估算                      ~ Timing Analyst（簡化）
```

資料結構主線：`AST → Netlist(gate cells) → LutNet(LUTK + DFF) →
placement(cells→CLB coords) → routes(net→channel edges)`。
每一級都是不可變的純資料，pass 之間無隱含狀態——這是為日後多顆分割
（partition pass 插在 techmap 與 place 之間）預留的結構。

## 4. 自研 P&R 設計

### 4.1 Fabric 模型（抽象，bitstream-agnostic）

- N×N CLB 格陣（MVP 每 CLB 放 1 個 LUT 或 DFF；VP1902 真實 CLB 為
  8×LUT6+16×FF，後續細化）。
- IO pad 固定於周邊（input 西/北、output 東/南）。
- 相鄰 CLB 間通道容量 = tracks 數（MVP 用最簡 4 鄰格圖，未建模
  switch block 與 wire segment 長度）。

### 4.2 Placement：VPR 式模擬退火

- 成本函數：全網表 HPWL（half-perimeter wirelength）總和。
- 動作：兩 cell 交換 / cell 移至空 CLB；幾何降溫。
- 後續：timing-driven 成本項（criticality × delay）、BLE 打包（LUT+FF 同 CLB）。

### 4.3 Routing：PathFinder negotiated congestion

- 每輪對所有 net 做 rip-up & re-route（BFS 最短路徑 + 擁擠懲罰），
  超用通道累積 history penalty，直至無超用或達迭代上限。
- 多 pin net 以「依距離逐一接入既有樹」的遞增樹方式佈線。

### 4.4 誠實限制

**VP1902（Versal）bitstream 格式未公開**，任何第三方都無法直接產生可燒錄
檔案。自研 P&R 的價值在於：① 演算法與資料結構的練兵場（partition 前的
必經之路）；② 輸出 placement/routing 決策可作為 Vivado 的約束引導；
③ 若未來採開放 bitstream 元件（如 iCE40/ECP5 級）做教學板，本 pipeline
可直接出真 bitstream。真機路徑：增加 EDIF/XDC 輸出 pass 接 Vivado。

## 5. MVP 驗證結果

`examples/alu4.v`（4-bit 暫存式邏輯）在 10×10 CLB、8 tracks/ch 下：

| 指標 | 值 |
|---|---|
| generic gates | 24 |
| LUT4 / DFF | 16 / 4 |
| placement HPWL | 97 |
| routing | 無壅塞（max channel 4/8），總線長 102 |
| logic depth | 2 |

`tests/test_smoke.py` 固定了端到端不變量（LUT 數不劣於 1:1 映射、
無超用通道、LUT6 不劣於 LUT4）。

## 6. Roadmap（對齊專案 Phase 1→2）

1. 語言子集擴充：concat/切片/case、FSM extraction（對齊 Synplify FSM Compiler）。
2. LUT mapping 換 cut-enumeration（FlowMap 式），加入 BRAM/DSP 推斷。
3. switch block 建模 + timing-driven P&R + 佈線延遲回填。
4. EDIF/XDC 輸出，接 Vivado 跑真 VP1902（混合模式：自研前端 + 廠商後端）。
5. multi-FPGA partition pass（TDM pin-muxing，參考 Siemens VPS）——
   對齊《Emulator 容量與架構對標分析》的 1→2→4→8 擴展路線。
