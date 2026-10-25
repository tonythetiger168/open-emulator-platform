# 單顆 FPGA Compiler 架構設計書

> open-emulator-platform 專案 ｜ 2026-10-25 ｜ v0.5（A* timing-driven router）
> 參考 Synplify Pro 架構，含自研 P&R。程式碼：`compiler/`（Python，`examples/alu4.v` 端到端可跑）。

## 1. 目標與範圍

為自研 emulator 建立編譯器的第一塊基石：**單顆 FPGA 的完整編譯流程**——
從 Verilog 子集到 LUT6/FF 網表、CLB 打包、自研 placement/routing，
並可輸出 EDIF/XDC 走 Vivado 真機路徑（xcvp1902）。
單顆流程跑通後，multi-FPGA partition（roadmap Phase 2）才有所依附。

- 參考藍本：**Synplify Pro**（compile → elaborate → map → optimize）。
- P&R：**自研**（Synplify 本身不含 P&R；此部分參考學術界 VPR 架構）。
- 目標元件：**AMD Versal Premium VP1902**（18.5M SLC / 8.46M LUT6 / 16.92M FF），
  以 **data-driven 架構描述檔**（`compiler/arch/vp1902.json`）定義。

## 2. Synplify Pro 架構回顧（我們參考什麼）

1. **HDL Compiler（語言前端）**：Verilog/VHDL → AST → generic 網表。
2. **HDL Analyst**：RTL view / Technology view 兩級檢視。
3. **高階優化**：常數傳播、resource sharing、**FSM Compiler**、**retiming**。
4. **Technology Mapper**：generic gates → 目標元件 primitives（LUT mapping、
   carry chain、記憶體與 DSP 推斷）。
5. **輸出**：EDIF netlist + 約束，交給廠商 P&R（Vivado）——Synplify 到這層為止。

## 3. efc pipeline 對照（v0.5）

```
verilog.py   語言前端（lexer/parser/AST）            ~ HDL Compiler
netlist.py   展開 + bit-blast → generic gates        ~ HDL Analyst (RTL view)
               AND2/OR2/XOR2/NOT/MUX2/DFF
techmap.py   gates → LUT6（greedy cone-merge）
               + cone 追蹤 + INIT 真值表計算         ~ Technology Mapper (Tech view)
arch.py      架構描述檔 loader（JSON）               ~ VPR architecture XML
               CLB 結構 / segment 長度+RC / switch block / IO 策略
pack.py      CLB 打包（8×LUT6+16FF，LUT→DFF 配對）   ~ VP1902 slice 結構
place.py     SA placement（block 級，HPWL）          ← 自研 P&R（VPR 式）
route.py     A* timing-driven PathFinder             ← 自研 P&R
timing.py    STA：Elmore RC + slack/criticality      ~ Timing Analyst
edif.py      EDIF 2.0.0 + XDC 輸出                   ~ Synplify 出貨格式 → Vivado
```

資料結構主線：`AST → Netlist(gates) → LutNet(LUT6+DFF+INIT) →
blocks(CLB) → placement → routes → EDIF/XDC`，arch spec 由 `arch.py`
載入後貫穿 fabric/pack/cli。每一級都是純資料，pass 之間無隱含狀態——
為日後 partition pass（插在 techmap 與 pack 之間）預留結構。

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
envelope 數字自 v0.3 起存於 `arch/vp1902.json`，不再硬編碼。

### 4.2 架構描述檔（arch.py + arch/vp1902.json，v0.3 新增）

對標 VPR architecture XML，把目標元件從程式碼中抽離為資料：

- **clb**：LUT/FF 數、LUT K、block timing（t_lut / t_clkq / t_setup 估計值）。
- **routing.segments**：wire segment 型別表——長度（L1/L2/L6）、通道佔比、
  R/C（供 Elmore 延遲模型，`Segment.elmore_ns()` 已備）。
- **routing.switch_block**：拓撲型別（wilton）與 Fs。
- **io**：perimeter 擺放策略（input→west/north，output→east/south）。
- `--arch` 可指定 `arch/` 下的名稱或任一 JSON 路徑——**換元件不改演算法**，
  這也是 OpenXC7 靶機（Kintex-7）與 timing-driven P&R 的前置開關。

誠實標記：timing 與 R/C 是邏輯模型估計值，非矽真值（VP1902 詳細 timing
未公開）；v0.3 的 grid P&R 仍為 unit-length 邊，segment 表供後續 pass 消費。

### 4.3 CLB packing（pack.py）

- LUT→DFF 獨佔配對放同一 CLB（經典 BLE 模式），剩餘 cell 以共享 net
  最多的 first-fit 裝箱；容量上限 8 LUT6 + 16 FF / CLB。
- packing 後產生 block 級外部網表，供 block-level placement/routing。

### 4.4 STA（v0.4，timing.py）

- 延遲模型：LUT = arch `t_lut_ns`；DFF = `t_ff_clkq_ns` / `t_setup_ns`；
  wire = 依 placement 的 per-net HPWL（tile 數）經 `arch.segment_for()`
  選 segment，Elmore 估算 `elmore_ns × ⌈hpwl/len⌉`；CLB 內部 net 記 0。
- 前向 arrival → 端點（DFF d：T−t_setup；PO：T）→ 反向 required →
  per-net slack 與 **criticality（VPR 式：1 − slack/T）**。
- 報表：critical_path_ns / est_fmax_mhz / worst_slack_ns / violated；
  `--clock` 控制目標週期，違例時 CLI exit 1。criticality 供 Phase A
  第 3–4 項 timing-driven router/placer 直接消費。
- 誠實標記：wire delay 依 HPWL 估算，尚未依真實 routing 拓撲回填。

### 4.5 P&R

- Placement：VPR 式模擬退火，成本 = 全網表 HPWL；動作為 block 交換/移位。
- Routing（v0.5）：**A\* directed search + lookahead** 的 timing-driven
  PathFinder。邊成本 = `crit×delay + (1−crit)×congestion`（VPR 式），
  crit 來自 STA 的 per-net criticality——關鍵 net 走最短徑不讓路，
  非關鍵 net 繞開壅塞；lookahead = Manhattan×最小單跳成本（admissible，不高估真實成本），
  搜尋有方向、不再 BFS 攤平（VTR 8 已證明 BFS router 是死路並整個移除）。
  保留 negotiated congestion：rip-up & re-route 全網表迭代 + history penalty。
  alu4 實測：wirelength/通道佔用與 BFS 版完全一致，節點展開數降 2.56×。
- 後續：switch block 消費、wire segment 長度、routing 拓撲延遲回填
  （arch 描述檔已備好資料，見改進計劃 Phase A 第 4–5 項與 Phase B）。

### 4.6 Vivado 真機路徑（edif.py）

- EDIF 2 0 0：外部庫 `hdi_primitives`（LUT1–6/FDRE，同 Synplify 慣例），
  instance 帶 `INIT` property（由 cone 真值表計算）；bus port 打平為純量
  並以 `rename` 還原 `name[i]`。
- XDC：`create_clock` + 佔位 PACKAGE_PIN（真實 pinout 待 ProtoBoard 板檔）。
- **誠實標記**：EDIF 尚未在真 Vivado 上驗證，首次上機前需 `link_design` 檢查。

### 4.7 誠實限制

**VP1902 bitstream 格式未公開**，任何第三方都無法直接產生可燒錄檔案
（開源逆向版圖：Project X-Ray = 7-series；Project U-Ray = UltraScale/+
部分文件；Versal 為零，且配置走 PDI 封裝 + PMC/PLM 開機韌體，難度更高）。
自研 P&R 的價值：① partition 前的演算法練兵場；② placement/routing 決策
可作 Vivado 約束引導；③ 若用開放 bitstream 元件（iCE40/ECP5/UltraScale+）
做教學板可直接出真 bitstream。真機主流路徑 = 自研前端 + EDIF → Vivado。

## 5. 驗證結果（v0.5，examples/alu4.v，8×8 邏輯格、8 tracks、10 ns clock）

| 指標 | 值 |
|---|---|
| generic gates | 24 |
| LUT6 / DFF | 12 / 4（LUT6 比 v0.1 LUT4 的 16 顆少 25%） |
| CLB used | 4 |
| VP1902 LUT6 利用率 | 0.000142% |
| placement HPWL | 56 |
| routing | 無壅塞（max channel 4/8，wirelength 57） |
| router 節點展開數 | 292（BFS 版同條件 466，A* 降 2.56×，QoR 不變） |
| logic depth | 2 |
| critical path / est. Fmax | 0.1299 ns / ~7.7 GHz（邏輯模型估計） |
| worst slack @10ns | +9.86 ns（--clock 0.05 正確報違例並 exit 1） |
| EDIF/XDC | 產出 OK，結構含 LUTn INIT 與 FDRE |

v0.2 → v0.3 迴歸：面積/佈局/佈線數字**完全一致**（arch 檔化為純重構）。
v0.3 → v0.4：新增 STA 報表，QoR 數字不變。
v0.4 → v0.5：router 換 A*，wirelength / max channel / 時序數字**完全一致**。

`tests/test_smoke.py` 4 項：端到端不變量、AND2→LUT2 INIT=0x8、
MUX cone→LUT3 INIT 寬度、EDIF/XDC 內容標記。
`tests/test_arch.py` 6 項（v0.3）：預設/路徑載入、未知 arch 報錯、
segment 排序與覆蓋、利用率公式迴歸、IO 策略生效。
`tests/test_timing.py` 6 項（v0.4）：wire delay 模型、單 LUT 路徑
CP 下界、criticality 範圍與最關鍵 net、緊時脈違例偵測、CP ≥ depth×t_lut
下界、CLI 時序報表。
`tests/test_route.py` 6 項（v0.5 新增）：空格陣最短徑與有向展開上界、
multi-source tree 接附、關鍵 net 無視壅塞走最短徑、非關鍵 net 繞開
懲罰邊、PathFinder 收斂且 crit 可缺省、CLI 報表含 expanded_nodes。

## 6. Roadmap（對齊專案 Phase 1→2）

1. 語言子集擴充：concat/切片/case、FSM extraction（對齊 Synplify FSM Compiler）。
2. LUT mapping 換 cut-enumeration（FlowMap 式）；BRAM/DSP58/CARRY8 推斷。
3. ~~STA~~（v0.4）、~~A* router~~（v0.5）完成；下一步：解析式/smart-centroid
   初始佈局消費 criticality（《改進計劃》Phase A 第 4 項），switch block
   建模與 routing 拓撲回填。
4. EDIF 在真 Vivado 上驗證（link_design → bitstream 全流程）。
5. multi-FPGA partition pass（TDM pin-muxing，參考 Siemens VPS）——
   對齊《Emulator 容量與架構對標分析》的 1→2→4→8 擴展路線。
6. **OpenXC7（UltraScale+）後端（驗證線）**：efc → OpenXC7
   （Yosys / nextpnr-xilinx / prjuray）出真 bitstream，全程無 Vivado。
   元件容量小（Zynq UltraScale+ 級），價值在於給 compiler 一個
   可上真機的端到端正確性靶機。
7. **固定 shell + runtime patch 評估（加速線）**：Vivado 僅跑一次產生
   shell bitstream，後續設計編譯只出 patch data（參考 Nexus 的固定
   bitstream + 指令編譯、PRflow/HiPR 的 partial reconfiguration 分頁、
   學術界 overlay 做法）。預期把迭代編譯從小時級降到秒~分鐘級；
   代價是 overlay 面積 overhead 約 2–10×，故僅適合中小設計快速迭代，
   不作為 100M 閘級 emulator 主線。

逐項展開與優先序見 `docs/compiler-improvement-plan.md`。

## 版本紀錄

- v0.1（2026-10-23）：MVP pipeline，LUT4，抽象 fabric。
- v0.2（2026-10-23）：目標 VP1902——LUT6 原生映射 + INIT、CLB packing、
  block 級 P&R、真機資源利用率、EDIF/XDC 輸出。
- roadmap 增補（2026-10-23）：§4.5 補開源 bitstream 版圖說明；
  新增第 6 項（OpenXC7 驗證線）與第 7 項（shell+patch 加速線）。
- v0.3（2026-10-25）：**arch 描述檔化**（改進計劃 Phase A 第 1 項）——
  `arch/vp1902.json` + `efc/arch.py`；envelope/CLB/segment/switch block/IO
  策略全部改為資料驅動，`--arch` 可切換目標元件；行為零迴歸，
  新增 `tests/test_arch.py` 6 項。
- v0.4（2026-10-25）：**STA 引擎**（改進計劃 Phase A 第 2 項）——Elmore wire
  delay（placement HPWL × arch segment R/C）+ arrival/required/slack +
  per-net criticality；CLI 新增 `--clock`、critical_path/Fmax/slack 報表與
  違例 exit 1；新增 `tests/test_timing.py` 6 項（共 16 項全過）。
- v0.5（2026-10-25）：**A\* timing-driven router**（改進計劃 Phase A 第 3 項）——
  BFS 換 A\* directed search + Manhattan lookahead；邊成本
  `crit×delay + (1−crit)×congestion` 消費 STA criticality；報表新增
  route_expanded_nodes；alu4 展開數降 2.56× 且 QoR 零迴歸；新增
  `tests/test_route.py` 6 項（共 22 項全過）。
