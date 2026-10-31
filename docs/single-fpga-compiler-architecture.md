# 單顆 FPGA Compiler 架構設計書

> open-emulator-platform 專案 ｜ 2026-10-30 ｜ v0.11（prepacking molecules）
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

## 3. efc pipeline 對照（v0.11）

```
verilog.py   語言前端（lexer/parser/AST）            ~ HDL Compiler
netlist.py   展開 + bit-blast → generic gates        ~ HDL Analyst (RTL view)
               AND2/OR2/XOR2/NOT/MUX2/DFF
techmap.py   mapper dispatcher + INIT 真值表計算    ~ Technology Mapper (Tech view)
cutmap.py    gates → LUT6：cut-enumeration          ~ ABC/FlowMap 式 mapping
               （K-feasible cuts + depth label + area flow；--mapper greedy 可 A/B）
lec.py       netlist vs LUT 網表 SAT 等價驗證        ~ Formality/LEC
               （Yosys equiv_make/simple/induct；--lec；無 yosys 報 skipped）
arch.py      架構描述檔 loader（JSON）               ~ VPR architecture XML
               CLB 結構 / segment 長度+RC / switch block / IO 策略
prepack.py   分子分組（lutff 強制配對 / carry8 鏈）   ~ VPR prepacker
pack.py      CLB 打包（8×LUT6+16FF，分子 atomic 裝箱） ~ VP1902 slice 結構
place.py     SA placement（block 級，HPWL）          ← 自研 P&R（VPR 式）
route.py     A* timing-driven PathFinder             ← 自研 P&R
timing.py    STA：Elmore RC + slack/criticality      ~ Timing Analyst
edif.py      EDIF 2.0.0 + XDC 輸出                   ~ Synplify 出貨格式 → Vivado
xc7out.py    7-series primitives Verilog 輸出        ~ OpenXC7/nextpnr-xilinx
               （LUT1-6/FDRE/IBUF/OBUF；--xc7；靶機 arch/xc7k325t.json）
qor.py       QoR golden 回歸（benchmarks/ 語料）     ~ VTR golden-QoR 追蹤
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

### 4.3 Prepack + CLB packing（prepack.py / pack.py，v0.11 重構）

- **Prepack molecules**（v0.11，改進計劃 Phase B 第 6 項）：packing 前先把
  cell 組成不可拆分子（VPR prepacker 對應）——
  - `lutff`：LUT→DFF 獨佔強制配對（經典 BLE 模式；把 v0.1 起隱含在
    pack.py 的配對規則提升為顯式、可檢視的分子）。
  - `carry8`：有序進位鏈，≤8 LUT/分子（VP1902 CARRY8 恰好佔一個 CLB），
    容量越界、cell 不在網表內、cell 重複入鏈皆以 ValueError 拒絕。
    **誠實標記**：鏈目前由 `LutNet.carry_chains` 標註注入（單元測試
    覆蓋）；Verilog 子集尚無 `+` 算子，端到端啟用待前端算術推斷，
    BRAM/DSP58 分子同理。
  - `single`：其餘 cell。
- **Packing**：分子 atomic 裝箱——lutff/carry8 自開 CLB seed block，
  single LUT 以共享 net 最多 first-fit、single FF first-fit；
  容量上限 8 LUT6 + 16 FF / CLB。分子順序（carry8 → lutff 依 DFF 序 →
  singles 依網表序）與 v0.10 逐相位一致，**無 carry chain 的設計 packing
  結果與 v0.10 bit-identical**（由 qor golden 守門，5/5 零漂移）。
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

- Placement（v0.6）：**smart-centroid 初始解 + SA refine**（VTR 9 路線）。
  先做星型連接加權質心迭代（IO 為固定錨點，全程無 RNG、結果決定性），
  再以貪婪最近空槽合法化，最後進 VPR 式 SA（HPWL）refine——VTR 9 證明
  「高品質初始解 + 有方向的 move」是 runtime 與 QoR 雙贏。`init="random"`
  保留 v0.5 的隨機種子入口供 A/B 量測。
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

### 4.7 LEC 驗證迴圈（v0.8，lec.py）

- 動機（改進計劃 Phase C 第 10 項）：對自研 compiler，每級 pass 後的
  等價驗證比任何單項 QoR 改進都重要（OpenFPGA/VTR 皆以 formal
  verification 收口 mapping）。
- 做法：golden（generic gates）與 gate（mapped LUT+DFF）各發成 flat
  Verilog——LUT 寫成 `assign o = INIT[{in...}];` 真值表、DFF 兩側同名
  同結構；Yosys 一條腳本收口：`equiv_make`（按名配對 state bits）→
  `equiv_simple`（組合 $equiv cells）→ `equiv_induct`（k-step SAT
  歸納證 DFF 狀態位對）→ `equiv_status -assert`。
- 四態語義：`proven` / `failed`（真不等價，exit 1）/ `error`（工具
  崩潰或逾時）/ `skipped`（無 yosys——**誠實回報，絕不偽造通過**）。
  CLI `--lec` 開關，failed/error 時 exit 1，skipped 不影響乾淨編譯的
  結束碼。
- 實測：alu4 cut mapping proven 12/12 $equiv cells；greedy 同過；
  負面測試翻轉 INIT bit0 正確判 failed。
- 覆蓋範圍：netlist→LUT mapping 一級（DFF 1:1 存活故時序元素可按名
  配對）；pack/place/route 不改功能，日後可對 EDIF 輸出再跑一級 LEC。

### 4.8 OpenXC7 靶機後端（v0.9，xc7out.py + arch/xc7k325t.json）

- 動機（改進計劃 Phase C 第 9 項）：VP1902 bitstream 未公開（§4.10），
  需要一個**無 Vivado 的端到端真 bitstream 靶機**來驗證 compiler 正確性。
  靶機選 Kintex-7 XC7K325T（FFG900，KC705 級）——OpenXC7 demo 最成熟、
  Project X-Ray bitstream 文件最完整的元件。
- 架構描述檔 `arch/xc7k325t.json`：envelope 用 datasheet（DS180）真值——
  203,800 LUT6（50,950 slices×4）/ 407,600 FF / 840 DSP48E1 / 445 BRAM36 /
  500 SelectIO；7-series CLB = 2 slices ×（4 LUT6 + 8 FF）= 8 LUT6 + 16 FF，
  與 vp1902 邏輯模型同形，**pack/fabric/place/route 零改動直跑**，
  `--arch xc7k325t` 一鍵切換（v0.3 arch 檔化的紅利）。
- `xc7out.py`：mapped LutNet → flat Verilog，cell 集合恰為
  `yosys synth_xilinx` 產出、nextpnr-xilinx 消費的 LUT1–6（.INIT）/FDRE/
  IBUF/OBUF；PI/PO 經 IBUF/OBUF buffer（alias wire 慣例同 synth_xilinx），
  port 保留 pin 名（`_Names` 新增 priority 參數讓 port 先取乾淨名）。
- 無 Vivado 迴路：`efc --arch xc7k325t --xc7 out.v` → `yosys read_verilog
  -lib +/xilinx/cells_sim.v … write_json` → `nextpnr-xilinx --chipdb …`。
  沙箱內已驗證前兩段（Yosys 0.23 parse/stat/write_json，cell 型別全在
  合法集合內）；**bitstream 段需 nextpnr-xilinx chipdb，沙箱外執行**。
- 正確性鏈：golden netlist ≡（v0.8 LEC）mapped LutNet →（純格式轉換）
  xc7 Verilog——格式層由 yosys parse/stat/JSON 煙霧測試把關。

### 4.9 QoR golden 回歸系統（v0.10，qor.py + benchmarks/）

- 動機（改進計劃 Phase C 第 11 項）：VTR 的 golden-QoR 做法——每次演算法
  改動，用固定語料庫的**確定性指標快照**守住「修了 A 卻弄壞 B」。
  efc 的 unittest 只驗證功能正確性；QoR 回歸驗證的是品質指標不漂移。
- 語料庫 `benchmarks/`：alu4（既有 example）、maj4（多數決邏輯 +
  reconvergent）、mixer8（2:1 mux 陣列）、regpipe8（兩級 pipeline）、
  sel4（if-else 分支）——覆蓋純組合/時序/多分支，全在 Verilog 子集內。
- 指標分兩類：**確定性指標精確比對**（LUTs/DFF/PI/PO/CLB_used/
  logic_depth_LUT/critical_path_ns（±1e-12 容忍 repr 雜訊）/placement_hpwl/
  route_wirelength/route_max_channel/route_overused_channels/
  route_expanded_nodes/lec 狀態）；**runtime_s 只記錄、永不斷言**
  （機器相關），以漂移 % 列報。
- Grid 自動定尺寸：fabric IO 容量 = 2×grid（每方向類別），故
  `grid = max(8, ceil(max(PI,PO)/2) + 2)`——決定性、寫入 golden，
  --update 與 --check 一致（mixer8/regpipe8 有 25 個 PI，8×8 放不下）。
- LEC 納入 golden：--update 時建議帶 yosys（記錄 proven）；--check 端
  若無 yosys，current 為 skipped 視為**中立**（不偽造通過也不誤報回歸），
  與 v0.8 的誠實語義一致。
- 用法：`python3 -m efc.qor --update`（已知良好樹上記錄）/
  `--check`（預設，漂移即 exit 1）/`--json out.json`（匯出當前指標）。
  故意改進導致指標變動時，以 --update 重記並在 commit message 說明
  哪些指標變動、為何可接受（golden 鎖的是當前行為，非品質上界）。

### 4.10 誠實限制

**VP1902 bitstream 格式未公開**，任何第三方都無法直接產生可燒錄檔案
（開源逆向版圖：Project X-Ray = 7-series；Project U-Ray = UltraScale/+
部分文件；Versal 為零，且配置走 PDI 封裝 + PMC/PLM 開機韌體，難度更高）。
自研 P&R 的價值：① partition 前的演算法練兵場；② placement/routing 決策
可作 Vivado 約束引導；③ 若用開放 bitstream 元件（iCE40/ECP5/UltraScale+）
做教學板可直接出真 bitstream。真機主流路徑 = 自研前端 + EDIF → Vivado。

## 5. 驗證結果（v0.11，examples/alu4.v，8×8 邏輯格、8 tracks、10 ns clock）

| 指標 | 值 |
|---|---|
| generic gates | 24 |
| LUT6 / DFF | 4 / 4（cut mapping；greedy 為 12，v0.1 LUT4 為 16） |
| CLB used | 4 |
| VP1902 LUT6 利用率 | 0.000047% |
| placement HPWL | 56 |
| routing | 無壅塞（max channel 4/8，wirelength 57） |
| router 節點展開數 | 280（v0.5 基準 292；BFS 版同條件 466，A* 展開數更少） |
| logic depth | 1（greedy 版為 2） |
| critical path / est. Fmax | 0.1198 ns / ~8.3 GHz（邏輯模型估計） |
| worst slack @10ns | +9.88 ns（--clock 0.05 正確報違例並 exit 1） |
| EDIF/XDC | 產出 OK，結構含 LUTn INIT 與 FDRE |
| LEC（--lec） | proven（12/12 $equiv cells；cut 與 greedy mapper 皆過） |

v0.2 → v0.3 迴歸：面積/佈局/佈線數字**完全一致**（arch 檔化為純重構）。
v0.3 → v0.4：新增 STA 報表，QoR 數字不變。
v0.4 → v0.5：router 換 A*，wirelength / max channel / 時序數字**完全一致**。
v0.5 → v0.6：placer 換 smart-centroid 種子，alu4 QoR 數字**完全一致**；
chain 測試中種子 HPWL ≤ 隨機種子中位數，且 SA refine 不劣化種子。
v0.6 → v0.7：mapper 換 cut-enumeration——**LUT6 12→4（−67%）、logic depth
2→1、CP 0.1299→0.1198 ns**；reconvergent fanout 測試 3→2 LUT（greedy
無法合併多扇出共享邏輯，cut 以複製換面積）；dead logic 自動移除；
`--mapper greedy` 可一鍵 A/B。
v0.7 → v0.8：新增 LEC 迴圈（不改 QoR 數字）——alu4 `--lec` proven
12/12 $equiv cells，greedy/cut 兩 mapper 皆與 golden netlist 等價；
INIT 翻轉的負面測試正確判 failed，無 yosys 環境誠實報 skipped。
v0.8 → v0.9：新增 OpenXC7 靶機後端——`--arch xc7k325t --lec --xc7` 端到端
實測：LUT6/FF 4/4、HPWL 56、wirelength 57 與 vp1902 全同（同形 CLB 結構），
LEC proven 12/12；`--xc7` 輸出經 Yosys 0.23 parse/stat/write_json 驗證，
cell 型別全在 LUT1–6/FDRE/IBUF/OBUF 合法集合（timing 數字依 xc7k325t
估計值而異：CP 0.2446 ns @ t_lut=0.10 ns，屬預期的 per-arch 差異）。
v0.9 → v0.10：新增 QoR 回歸系統（不改任何演算法行為）——`benchmarks/`
5 設計語料首版 golden：alu4/sel4 4 LUT/4 DFF（depth 1，CP 0.1198 ns）、
maj4 4 LUT（grid 11）、mixer8 8 LUT（grid 15）、regpipe8 16 LUT
（depth 1，CP 0.1898 ns，grid 15），5/5 LEC proven；`--check` 重跑
全部指標零漂移。
v0.10 → v0.11：pack 重構為 prepack 分子 + atomic 裝箱——**全部確定性
QoR 指標零漂移**（golden 首個實戰驗證：重構前後 `--check` 皆過），
golden 以 --update 僅新增 `molecules` 追蹤欄位（commit message 已載明）；
語料 5 設計全為暫存器輸出故 lutff 全配對（single=0），synthetic
carry8 鏈 4-bit 打包進單一 CLB、8-bit 合法 / 9-bit 拒絕。

`tests/test_smoke.py` 4 項：端到端不變量、AND2→LUT2 INIT=0x8、
MUX cone→LUT3 INIT 寬度、EDIF/XDC 內容標記。
`tests/test_arch.py` 6 項（v0.3）：預設/路徑載入、未知 arch 報錯、
segment 排序與覆蓋、利用率公式迴歸、IO 策略生效。
`tests/test_timing.py` 6 項（v0.4）：wire delay 模型、單 LUT 路徑
CP 下界、criticality 範圍與最關鍵 net、緊時脈違例偵測、CP ≥ depth×t_lut
下界、CLI 時序報表。
`tests/test_route.py` 6 項（v0.5）：空格陣最短徑與有向展開上界、
multi-source tree 接附、關鍵 net 無視壅塞走最短徑、非關鍵 net 繞開
懲罰邊、PathFinder 收斂且 crit 可缺省、CLI 報表含 expanded_nodes。
`tests/test_place.py` 6 項（v0.6 新增）：種子合法且決定性、種子 HPWL ≤
隨機種子中位數、線性鏈種子緊湊、SA refine 不劣化種子、alu4 迴歸窗、
init="random" 相容 v0.5。
`tests/test_cutmap.py` 6 項（v0.7 新增）：reconvergent fanout 勝 greedy、
XOR3 單 LUT（INIT=0x96）、K=4 深度受限切兩顆、dead logic 移除、
alu4 cut ≤ greedy、CLI 預設 mapper=cut。
`tests/test_lec.py` 8 項（v0.8 新增）：名稱消毒與 INIT 表格式、
alu4 cut/greedy proven、reconvergent 設計兩 mapper proven、INIT 翻轉
必判 failed、無 yosys 報 skipped 不偽造通過、CLI --lec 報表。
`tests/test_xc7out.py` 7 項（v0.9 新增）：xc7k325t arch 載入與 envelope
真值、LUTk INIT 位寬、名稱消毒、IBUF/OBUF 配線、Yosys parse/stat 煙霧、
write_json cell 型別合法集合、CLI --xc7 報表。
`tests/test_qor.py` 13 項（v0.10 新增）：語料存在且全數可編譯、
auto_grid 對齊 fabric IO 容量、golden 鍵完整、相同輸入零違例、
注入 LUTs+1 與 CP 漂移必被捕獲、runtime×10 不觸發違例（僅列漂移）、
新增/缺失 benchmark 必被標記、LEC skipped 中立與 failed 必報、
golden 與當前重跑一致、逐 bench LEC proven、main --check exit 0。
`tests/test_prepack.py` 9 項（v0.11 新增）：alu4 全 lutff 配對且 cell
守恆、fanout-2 net 不配對、PI 直驅 DFF 保持 single、carry8 鏈成單一
分子且位序保持、鏈 atomic 入單一 CLB、9-bit 越界/陌生 cell/重複入鏈
皆拒絕、alu4 packing 與 v0.10 一致（4 CLB、每塊 1+1、14 條外部網）、
CLI 報表含 molecules 行（共 71 項全過）。

## 6. Roadmap（對齊專案 Phase 1→2）

1. 語言子集擴充：concat/切片/case、FSM extraction（對齊 Synplify FSM Compiler）。
2. ~~LUT mapping 換 cut-enumeration~~（v0.7 完成）；BRAM/DSP58/CARRY8 推斷。
3. ~~STA~~（v0.4）、~~A* router~~（v0.5）、~~smart-centroid 初始佈局~~（v0.6）、
   ~~cut-enumeration mapping~~（v0.7）——《改進計劃》Phase A 全數完成；
   ~~LEC 驗證迴圈~~（v0.8）、~~OpenXC7 靶機後端~~（v0.9，Phase C 第 10、9 項）、
   ~~QoR 回歸系統~~（v0.10，Phase C 第 11 項）、~~prepacking molecules~~
   （v0.11，Phase B 第 6 項）；
   下一步：placement 成本項消費 criticality（bound2bound 式加權）、
   switch block 建模與 routing 拓撲回填、floorplanning constraints（Phase B）。
4. EDIF 在真 Vivado 上驗證（link_design → bitstream 全流程）。
5. multi-FPGA partition pass（TDM pin-muxing，參考 Siemens VPS）——
   對齊《Emulator 容量與架構對標分析》的 1→2→4→8 擴展路線。
6. **OpenXC7 後端（驗證線）**：~~efc 端落地~~（v0.9：`arch/xc7k325t.json`
   + `xc7out.py`，Yosys→JSON 段沙箱內已驗證）；剩 bitstream 段——
   nextpnr-xilinx + xc7k325t chipdb → 真 bitstream 上板，全程無 Vivado，
   需具備 OpenXC7 工具鏈的機器執行。
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
- v0.6（2026-10-27）：**smart-centroid 初始佈局**（改進計劃 Phase A 第 4 項）——
  星型加權質心迭代種子（無 RNG、決定性）+ 貪婪合法化 + SA refine；
  `place(init="random")` 保留 v0.5 行為供 A/B；alu4 QoR 零迴歸；
  新增 `tests/test_place.py` 6 項（共 28 項全過）。
- v0.7（2026-10-27）：**cut-enumeration LUT mapping**（改進計劃 Phase A 第 5 項）——
  K-feasible cut 列舉 + FlowMap 式 depth label + area flow 面積回收；
  新增 `efc/cutmap.py`，`techmap.py` 改為 dispatcher（`--mapper greedy` A/B）；
  alu4 LUT6 12→4、depth 2→1、CP 0.1299→0.1198 ns；新增
  `tests/test_cutmap.py` 6 項（共 34 項全過）。
- v0.8（2026-10-30）：**LEC 驗證迴圈**（改進計劃 Phase C 第 10 項）——
  新增 `efc/lec.py`：golden/mapped 雙側 flat Verilog 發射 + Yosys
  equiv_make/simple/induct SAT 證明；`--lec` CLI 開關，proven/failed/
  error/skipped 四態（無 yosys 誠實報 skipped）；alu4 proven 12/12
  $equiv cells，INIT 翻轉負面測試正確判 failed；新增
  `tests/test_lec.py` 8 項（共 42 項全過）。
- v0.9（2026-10-30）：**OpenXC7 靶機後端**（改進計劃 Phase C 第 9 項）——
  新增 `arch/xc7k325t.json`（Kintex-7，envelope 為 DS180 真值）與
  `efc/xc7out.py`（LUT1–6/FDRE/IBUF/OBUF flat Verilog，`--xc7` 開關）；
  `_Names` 加 priority 參數讓 port 取乾淨名；Yosys parse/stat/write_json
  段沙箱內驗證通過，bitstream 段待 nextpnr-xilinx chipdb 環境；新增
  `tests/test_xc7out.py` 7 項（共 49 項全過）。
- v0.10（2026-10-30）：**QoR golden 回歸系統**（改進計劃 Phase C 第 11 項）——
  新增 `efc/qor.py` 與 `benchmarks/` 5 設計語料（alu4/maj4/mixer8/
  regpipe8/sel4）：12 項確定性指標精確比對（CP ±1e-12）、runtime 只記錄
  漂移不斷言、LEC 納入 golden（skipped 中立）；grid 依 PI/PO 自動定尺寸
  並寫入 golden；`--update/--check/--json` CLI，回歸即 exit 1；新增
  `tests/test_qor.py` 13 項（共 62 項全過）。
- v0.11（2026-10-30）：**prepacking molecules**（改進計劃 Phase B 第 6 項）——
  新增 `efc/prepack.py`（VPR prepacker 對應）：lutff 強制配對提升為顯式
  分子、carry8 有序鏈分子（≤8 bit 對齊 VP1902 CARRY8，容量/歸屬/重複
  校驗）、single 預設；`pack.py` 改為分子 atomic 裝箱，無 carry chain 的
  設計與 v0.10 **bit-identical**（qor golden 5/5 零漂移——golden 首次
  實戰守門成功）；CLI 報表新增 `molecules` 行並納入 QoR 追蹤；
  新增 `tests/test_prepack.py` 9 項（共 71 項全過）。誠實標記：carry8
  端到端啟用待前端 `+` 推斷，BRAM/DSP58 分子待記憶體/算術推斷。
