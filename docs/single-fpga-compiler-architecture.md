# 單顆 FPGA Compiler 架構設計書

> open-emulator-platform 專案 ｜ 2026-10-23 ｜ v0.2（VP1902 目標 + Vivado 路徑）
> 參考 Synplify Pro 架構，含自研 P&R。程式碼：`compiler/`（Python，`examples/alu4.v` 端到端可跑）。

## 1. 目標與範圍

為自研 emulator 建立編譯器的第一塊基石：**單顆 FPGA 的完整編譯流程**——
從 Verilog 子集到 LUT6/FF 網表、CLB 打包、自研 placement/routing，
並可輸出 EDIF/XDC 走 Vivado 真機路徑（xcvp1902）。
單顆流程跑通後，multi-FPGA partition（roadmap Phase 2）才有所依附。

- 參考藍本：**Synplify Pro**（compile → elaborate → map → optimize）。
- P&R：**自研**（Synplify 本身不含 P&R；此部分參考學術界 VPR 架構）。
- 目標元件：**AMD Versal Premium VP1902**（18.5M SLC / 8.46M LUT6 / 16.92M FF）。

## 2. Synplify Pro 架構回顧（我們參考什麼）

1. **HDL Compiler（語言前端）**：Verilog/VHDL → AST → generic 網表。
2. **HDL Analyst**：RTL view / Technology view 兩級檢視。
3. **高階優化**：常數傳播、resource sharing、**FSM Compiler**、**retiming**。
4. **Technology Mapper**：generic gates → 目標元件 primitives（LUT mapping、
   carry chain、記憶體與 DSP 推斷）。
5. **輸出**：EDIF netlist + 約束，交給廠商 P&R（Vivado）——Synplify 到這層為止。

## 3. efc pipeline 對照（v0.2）

```
verilog.py   語言前端（lexer/parser/AST）            ~ HDL Compiler
netlist.py   展開 + bit-blast → generic gates        ~ HDL Analyst (RTL view)
               AND2/OR2/XOR2/NOT/MUX2/DFF
techmap.py   gates → LUT6（greedy cone-merge）
               + cone 追蹤 + INIT 真值表計算         ~ Technology Mapper (Tech view)
pack.py      CLB 打包（8×LUT6+16FF，LUT→DFF 配對）   ~ VP1902 slice 結構
place.py     SA placement（block 級，HPWL）          ← 自研 P&R（VPR 式）
route.py     PathFinder negotiated-congestion        ← 自研 P&R
timing.py    logic depth 估算                        ~ Timing Analyst（簡化）
edif.py      EDIF 2.0.0 + XDC 輸出                   ~ Synplify 出貨格式 → Vivado
```

資料結構主線：`AST → Netlist(gates) → LutNet(LUT6+DFF+INIT) →
blocks(CLB) → placement → routes → EDIF/XDC`。
每一級都是純資料，pass 之間無隱含狀態——為日後 partition pass
（插在 techmap 與 pack 之間）預留結構。

## 4. VP1902 目標與自研 P&R

### 4.1 元件 envelope（真機資源表）

| 資源 | VP1902 |
|---|---|
| System logic cells | 18.5M |
| LUT6 / FF | 8.46M / 16.92M |
| CLB（8×LUT6+16FF） | ~1.06M |
| DSP58 | 6,864 |
| BRAM / URAM | 239 Mb / 619 Mb |
| SelectIO | 2,328 |

編譯報表直接給出對真機的利用率（LUT6/FF/CLB %）。

### 4.2 CLB packing（pack.py）

- LUT→DFF 獨佔配對放同一 CLB（經典 BLE 模式），剩餘 cell 以共享 net
  最多的 first-fit 裝箱；容量上限 8 LUT6 + 16 FF / CLB。
- packing 後產生 block 級外部網表，供 block-level placement/routing。

### 4.3 P&R

- Placement：VPR 式模擬退火，成本 = 全網表 HPWL；動作為 block 交換/移位。
- Routing：PathFinder negotiated congestion，rip-up & re-route 全網表迭代，
  history penalty 收斂；邏輯格陣 N×N、通道容量 = tracks。
- 後續：timing-driven 成本項、switch block 建模、wire segment 長度。

### 4.4 Vivado 真機路徑（edif.py）

- EDIF 2 0 0：外部庫 `hdi_primitives`（LUT1–6/FDRE，同 Synplify 慣例），
  instance 帶 `INIT` property（由 cone 真值表計算）；bus port 打平為純量
  並以 `rename` 還原 `name[i]`。
- XDC：`create_clock` + 佔位 PACKAGE_PIN（真實 pinout 待 ProtoBoard 板檔）。
- **誠實標記**：EDIF 尚未在真 Vivado 上驗證，首次上機前需 `link_design` 檢查。

### 4.5 誠實限制

**VP1902 bitstream 格式未公開**，任何第三方都無法直接產生可燒錄檔案。
自研 P&R 的價值：① partition 前的演算法練兵場；② placement/routing 決策
可作 Vivado 約束引導；③ 若用開放 bitstream 元件（iCE40/ECP5）做教學板可
直接出真 bitstream。真機主流路徑 = 自研前端 + EDIF → Vivado。

## 5. 驗證結果（v0.2，examples/alu4.v，8×8 邏輯格、8 tracks）

| 指標 | 值 |
|---|---|
| generic gates | 24 |
| LUT6 / DFF | 12 / 4（LUT6 比 v0.1 LUT4 的 16 顆少 25%） |
| CLB used | 4 |
| VP1902 LUT6 利用率 | 0.000142% |
| placement HPWL | 56 |
| routing | 無壅塞（max channel 4/8） |
| logic depth | 2 |
| EDIF/XDC | 產出 OK，結構含 LUTn INIT 與 FDRE |

`tests/test_smoke.py` 4 項：端到端不變量、AND2→LUT2 INIT=0x8、
MUX cone→LUT3 INIT 寬度、EDIF/XDC 內容標記。

## 6. Roadmap（對齊專案 Phase 1→2）

1. 語言子集擴充：concat/切片/case、FSM extraction（對齊 Synplify FSM Compiler）。
2. LUT mapping 換 cut-enumeration（FlowMap 式）；BRAM/DSP58/CARRY8 推斷。
3. switch block 建模 + timing-driven P&R + 佈線延遲回填。
4. EDIF 在真 Vivado 上驗證（link_design → bitstream 全流程）。
5. multi-FPGA partition pass（TDM pin-muxing，參考 Siemens VPS）——
   對齊《Emulator 容量與架構對標分析》的 1→2→4→8 擴展路線。

## 版本紀錄

- v0.1（2026-10-23）：MVP pipeline，LUT4，抽象 fabric。
- v0.2（2026-10-23）：目標 VP1902——LUT6 原生映射 + INIT、CLB packing、
  block 級 P&R、真機資源利用率、EDIF/XDC 輸出。
