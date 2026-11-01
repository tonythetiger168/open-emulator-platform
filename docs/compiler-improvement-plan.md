# efc 改進計劃：對標 GitHub 開源 FPGA / P&R 專案

> open-emulator-platform 專案 ｜ 2026-11-01 ｜ v1.11
> 目的：掃描 GitHub 上主流開源 FPGA 綜合與 P&R 專案，萃取可落地的演算法與架構設計，
> 排定 efc（`compiler/`）的改進優先序。本文是《單顆 FPGA Compiler 架構設計書》
> roadmap 的展開與具體化。

## 1. 對標專案盤點

| 專案 | 定位 | 對 efc 的核心啟發 |
|---|---|---|
| [verilog-to-routing (VTR/VPR)](https://github.com/verilog-to-routing/vtr-verilog-to-routing) | 學術界 P&R 金標準 | v9 的 RLPlace（RL agent 動態選擇 SA move 類型）、smart centroid 初始佈局、AIR router 的 flat routing 與空間分割平行化、floorplanning constraints；placement / routing 分別比 VTR 8 快 4× / 2.2× 且 QoR 更佳 |
| [nextpnr](https://github.com/YosysHQ/nextpnr) | 開源商用級 P&R（1.8k★） | HeAP 解析式佈局：二次 wirelength 求解 + bound2bound 權重（criticality 驅動）+ 迭代 spreading / legalization，再 SA refine；router2 用 directed search；timing criticality（0.0=don't care～1.0=關鍵路徑）貫穿 place/route |
| [ABC](https://github.com/berkeley-abc/abc) / [Yosys](https://github.com/YosysHQ/yosys) | 邏輯綜合（VTR 的前端） | AIG 優化 + cut-enumeration（priority cuts）LUT mapping——替換 efc 貪婪 cone-merge 的正解 |
| [OpenFPGA](https://github.com/lnis-uofu/OpenFPGA) | FPGA fabric 生成框架（1.2k★） | bitstream 對輸入 netlist 的 formal verification、自動產生全級 testbench——compiler 正確性驗證的範本 |
| [RapidWright](https://github.com/Xilinx/RapidWright) | AMD 官方 Vivado 快速組裝框架（395★） | pre-implemented blocks / stamped modules + RWRoute——shell+patch 加速線的現成載體 |
| [OpenXC7](https://github.com/openXC7) / [prjuray](https://github.com/f4pga/prjuray) | 7-series 開放 bitstream；UltraScale/+ 文件化中 | 驗證線落點：efc → nextpnr-xilinx → 真 bitstream 的無 Vivado 迴路 |
| VPR-Evolve（2026，arXiv:2602.13594） | LLM 多 agent 演化 P&R 程式碼 | 前瞻方向：對 P&R 原始碼做 per-design 演化，CPD 最多降 9.8%、runtime 最多降 79.3% |

## 2. 改進計劃（依優先序）

### Phase A：timing-driven 地基

1. **Arch 描述檔化**（學 VPR architecture XML）—— ✅ **已完成（v0.3，2026-10-25）**
   原況 `fabric.py` 為硬編碼 dict。改為 data-driven 架構描述：CLB 內部結構、
   switch block 類型（subset/Wilton/universal）、wire segment 長度、delay/RC 表。
   是所有 timing-driven 工作的地基，也是日後切換目標元件（含 OpenXC7 靶機）的開關。
   落地：`compiler/arch/vp1902.json` + `efc/arch.py`；envelope/CLB/segment/
   switch block/IO 策略全部資料驅動，`--arch` 可切換元件；alu4 迴歸數字不變，
   新增 `tests/test_arch.py` 6 項。

2. **Timing 引擎升級** —— ✅ **已完成（v0.4，2026-10-25）**：Elmore RC +
   STA，產出 per-net arrival/required/slack/**criticality**（VPR 式 1−slack/T）。
   落地：`efc/timing.py::sta()`；CLI 報 critical_path/Fmax/worst_slack，
   `--clock` 違例 exit 1；`tests/test_timing.py` 6 項。下一步第 3–4 項直接
   消費 criticality。

3. **Router 換 directed search** —— ✅ **已完成（v0.5，2026-10-25）**：
   純 BFS → A* + Manhattan lookahead（VPR timing-driven PathFinder /
   nextpnr router2 路線）。邊成本 `crit×delay + (1−crit)×congestion`，
   crit 由 `timing.sta()` 的 per-net criticality 直接餵入；關鍵 net 走
   最短徑不讓路、非關鍵 net 繞開壅塞。落地：`efc/route.py` 改寫 +
   cli 先 STA 後 route；alu4 QoR 零迴歸（wirelength 57 / max channel 4/8
   / CP 0.1299 ns 全同），節點展開數 466→182（2.56×）；
   新增 `tests/test_route.py` 6 項（共 22 項全過）。

4. **Placer 初始解** —— ✅ **已完成（v0.6，2026-10-27）**：採 smart centroid
   （VTR 9）路線——星型連接加權質心迭代出種子（IO 固定錨點、無 RNG、
   決定性）→ 貪婪最近空槽合法化 → 原 VPR 式 SA refine。落地：
   `efc/place.py::initial_placement()` + `place(init="centroid")` 預設啟用、
   `init="random"` 保留 v0.5 行為供 A/B；alu4 QoR 零迴歸（HPWL 56 /
   wirelength 57 / CP 0.1299 ns 全同）；新增 `tests/test_place.py` 6 項
   （共 28 項全過）。後續微調：placement 成本項消費 criticality
   （bound2bound 式加權）留作下一步增強。

5. **LUT mapping 換 cut-enumeration** —— ✅ **已完成（v0.7，2026-10-27）**：
   K-feasible cut 列舉（dominated cut 剔除）+ FlowMap 式 depth label +
   area flow 面積回收（不破壞 depth label）。落地：新增 `efc/cutmap.py`，
   `techmap.py` 改 dispatcher（`--mapper greedy` 保留舊版供 A/B）；
   alu4 **LUT6 12→4（−67%）、logic depth 2→1、CP 0.1299→0.1198 ns**；
   reconvergent fanout 測試證明 cut 以複製換面積（3→2 LUT），dead logic
   自動移除；新增 `tests/test_cutmap.py` 6 項（共 34 項全過）。
   Phase A 五項至此全數完成。

### Phase B：結構對齊商用流程

6. **Prepacking molecules**（VPR prepacker）—— ✅ **已完成（v0.11，2026-10-30）**：
   CARRY8 chain、LUT-FF 強制配對作為不可拆分子進 packer。落地：新增
   `efc/prepack.py`——Molecule（single/lutff/carry8）+ `prepack()` +
   `molecule_stats()`；lutff 把 v0.1 起隱含的 LUT→DFF 獨佔配對提升為顯式
   分子；carry8 為有序鏈分子（≤8 bit 對齊 VP1902 CARRY8 一 CLB 容量，
   越界/陌生 cell/重複入鏈皆 ValueError）；`pack.py` 改為分子 atomic
   裝箱（lutff/carry8 自開 CLB，singles first-fit），無 carry chain 時
   與 v0.10 **bit-identical**——qor golden 5/5 零漂移（golden 首次實戰
   守門）。CLI 報表新增 `molecules` 行並納入 QoR 確定性追蹤；新增
   `tests/test_prepack.py` 9 項（共 71 項全過）。**誠實標記**：Verilog
   子集尚無 `+` 算子，carry8 端到端待前端算術推斷（目前由
   `LutNet.carry_chains` 標註注入、單元測試覆蓋）；BRAM/DSP58 分子
   框架已可容納，待記憶體/DSP 推斷落地後啟用。

7. **Floorplanning constraints** —— ✅ **已完成（v0.12，2026-11-01）**：
   落地 `efc/floorplan.py`——JSON 約束（regions：`rect` + cell 名選擇器 +
   `exclusive` 保留區；`fixed`：精確鎖定 slot）；resolve 階段即做
   可行性檢查（rect 越界/雙重區域/雙重鎖定/容量不足一律
   FloorplanError，不放行到 placement）；placer 全程強制——centroid
   種子鉗制在 rect 內、legalization 只搜區內空槽、fixed block 免於
   SA、SA 只提議合法 move；post-place `verify_floorplan()` 複審，
   違例即 fail build（絕不靜默降級）。`--floorplan` CLI 接入；
   floorplan=None 時與 v0.11 **bit-identical**（QoR golden 5/5 零漂移
   守門）；新增 `tests/test_floorplan.py` 11 項（共 82 項全過）。
   multi-FPGA partition（Phase 2）前置能力就此鋪通。

8. **平行 / flat routing** —— ✅ **框架已完成（v0.13，2026-11-01）**：
   VTR 9 AIR router 路線——空間分割（垂直 strip）把 net 分為 global
   （跨 strip，序列先繞，佔有 cut edge）與 local（strip 內，
   multiprocessing 平行，worker 以 global nets 佔用 occ0 為種子繞開），
   合併後 any overuse → 自動退回完整序列 PathFinder（結果與 route()
   逐位相同，文件化 fallback）。`route()` 加 `occ0/hist0`（預設
   None 行為不變）；`--route-par`/`--workers` CLI 接入。**誠實標記**：
   benchmark 級距（grid 8–15）無 speedup 宣稱——本項價值是規模化
   時不再需要新程式碼（原計劃「設計規模上來後再做」的框架提前落地）；
   平行模式 5/5 benchmark wirelength 與序列模式一致、expanded_nodes
   偏差 <0.2%、重複執行 bit-identical（測試斷言）。
   新增 `tests/test_routepar.py` 7 項（共 89 項全過）。

### Phase C：正確性驗證與生態落地

9. **OpenXC7 驗證線落地**（原 roadmap 第 6 項具體化）—— ✅ **efc 端已完成
   （v0.9，2026-10-30）**：落地 `arch/xc7k325t.json`（Kintex-7 FFG900，
   envelope = DS180 真值：203,800 LUT6 / 407,600 FF / 840 DSP48E1；
   CLB 同形 8×LUT6+16FF，P&R 零改動）+ `efc/xc7out.py`——mapped LutNet
   輸出 LUT1–6/FDRE/IBUF/OBUF flat Verilog（`--xc7`），即 `synth_xilinx`
   產出、nextpnr-xilinx 消費的 cell 集合；Yosys 0.23 parse/stat/
   write_json 段沙箱內驗證通過（cell 型別全合法）；新增
   `tests/test_xc7out.py` 7 項（共 49 項全過）。**誠實標記**：真
   bitstream 段（nextpnr-xilinx + xc7k325t chipdb → 上板）需 OpenXC7
   工具鏈環境，在沙箱外執行。

10. **LEC 驗證迴圈**（學 OpenFPGA / VTR flow）—— ✅ **已完成（v0.8，2026-10-30）**：
    每級 pass 後做 SAT-based equivalence check。落地：新增 `efc/lec.py`——
    golden（generic gates）與 mapped（LUT+DFF）各發 flat Verilog（LUT =
    INIT 真值表索引、DFF 兩側同名同結構），Yosys `equiv_make` /
    `equiv_simple` / `equiv_induct` 一條腳本收口（induct 的 k-step SAT
    歸納負責 DFF 狀態位對）；CLI `--lec` 開關，proven/failed/error/skipped
    四態——**無 yosys 報 skipped 絕不偽造通過**，failed/error 時 exit 1。
    實測：alu4 proven 12/12 $equiv cells，cut 與 greedy 兩 mapper 皆過；
    INIT 翻轉負面測試正確判 failed；新增 `tests/test_lec.py` 8 項
    （共 42 項全過）。目前覆蓋 techmap 一級，日後可對 EDIF 輸出再跑一級。

11. **QoR 回歸系統**（學 VTR golden QoR tracking）—— ✅ **已完成（v0.10，2026-10-30）**：
    建立 benchmark corpus 與 golden 追蹤，防止改 A 壞 B。落地：新增
    `efc/qor.py` + `benchmarks/` 5 設計語料（alu4/maj4/mixer8/regpipe8/sel4，
    全在 Verilog 子集內、覆蓋純組合/時序/多分支）；**確定性指標精確比對**
    （LUTs/DFF/PI/PO/CLB/logic depth/CP ±1e-12/HPWL/wirelength/channel
    用量/展開節點數/LEC 狀態），**runtime 只記錄漂移 % 永不斷言**
    （機器相關）；LEC 納入 golden，--check 端無 yosys 時 skipped 視中立
    （不偽造通過也不誤報）；grid 依 PI/PO 自動定尺寸
    （`max(8, ceil(max(PI,PO)/2)+2)`，因 fabric IO 容量 = 2×grid）並寫入
    golden 保證 --update/--check 一致。首版 golden：5/5 LEC proven；
    `--check` 重跑零漂移、回歸即 exit 1。新增 `tests/test_qor.py` 13 項
    （共 62 項全過）。**誠實標記**：golden 鎖的是當前演算法行為而非品質
    上界，故意改進時以 `--update` 重記並在 commit message 說明；語料規模
    仍為自製小設計（MCNC/Koios 級語料待 Verilog 子集擴充後引入）。

12. **shell+patch 線用 RapidWright 落地** —— ✅ **efc 端已完成
    （v0.14，2026-11-01）**：落地 `efc/shellpatch.py` +
    `--shell-patch x0,y0,x1,y1 [--shell-patch-out sp.json]`——依擺放位置
    把 packed blocks 分為 shell/patch（rect 越界即 ValueError），並審計
    boundary nets（跨區 net 逐條回報兩側 terminal 數，含 IO pad 側——
    正是 RP partition pin 介面的輸入）。交接文件
    `docs/rapidwright-shell-patch.md`：partition JSON → RapidWright
    BlockStitcher/stamped modules 映射、保留 shell DCP→迭代只重作
    patch 的流程、邏輯網格→真實 Pblock 座標映射校準點、fallback
    （OpenXC7 線降級為全量重編譯）。**誠實標記**：Java + Vivado 側在
    沙箱外執行，efc 不偽造該段；carry8 分子跨邊界須整鏈歸同一側
    （推薦歸 patch）。新增 `tests/test_shellpatch.py` 7 項。

13. **除錯觀測層整合評估** —— ✅ **評估完成（2026-11-01）**：
    交付 `docs/debug-observation-eval.md`——litescope（212★）vs
    fpgacapZero（136★，2026-10-31 仍活躍）逐維度比較，**建議 fpgacapZero
    為主**（JTAG-AXI 獨立除錯通道，不搶 host 頻寬、不污染 timing
    量測；vendor-agnostic 與無 Vivado 路線一致），litescope 為備
    （support SoC 定案 LiteX 且除錯走系統匯流排可接受時）。整合本身
    （訊號清單自 efc ext_nets/floorplan 產生、GTKWave/FST 收尾、對
    Verilator golden 逐週期驗收）待硬體就緒啟動，不阻塞軟體主線。

14. **主機通道選型評估** —— ✅ **評估完成（2026-11-01）**：
    交付 `docs/host-channel-eval.md`——**建議 LitePCIe 為主**（MIT、
    無 Vivado 依賴是硬條件；XDMA 會把工具鏈綁回 Vivado，使 OpenXC7 與
    shell+patch 替代路線作廢；頻寬瓶頸時退路 verilog-pcie 1,677★）；
    板間互連評估 liteiclink（68★）+ FireSim supernode TDM 方法學，
    **誠實標記**成熟度較低、上板前需 loopback BER 驗收。上板整合待
    ProtoBoard 硬體定案。

## 3. 執行順序

```
1 ✅ → 2 ✅（v0.4）→ 3 ✅（v0.5）→ 4 ✅（v0.6）    （P&R 從「能跑」到「timing-driven」）
→ 5 ✅（v0.7）   （mapping 收口，Phase A 完成）
→ 10 ✅（v0.8）→ 9 ✅（v0.9）  （正確性驗證與靶機後端收口）
→ 11 ✅（v0.10） （QoR 回歸系統： benchmark corpus + golden 追蹤）
→ 6 ✅（v0.11）  （prepacking molecules： lutff 框架化 + carry8 鏈）
→ 7 ✅（v0.12）  （floorplanning constraints： multi-FPGA partition 的路鋪通）
→ 8 ✅（v0.13）  （空間分割平行 routing 框架： 規模化不再需要新程式碼）
→ 12 ✅（v0.14） （shell+patch 分區 + RapidWright 交接文件）
→ 13, 14 ✅      （除錯觀測層、主機通道選型評估交付——
                  上板整合待硬體就緒，不阻塞軟體主線）
```

**Phase A/B/C 十四項至此全數收口**（完成 1–14；13/14 為評估交付，
實體整合待 ProtoBoard 硬體就緒）。後續主線：BRAM/DSP58 推斷與
Verilog 子集擴充（解放 carry8 端到端與 MCNC/Koios 級語料）、
multi-FPGA partition（Phase 2）、RL/ML move selection（前瞻）。

RL / ML move selection（RLPlace、VPR-Evolve 路線）留作前瞻：benchmark
corpus 已於 v0.10 建立（前置條件滿足），可考慮用 RL agent 或 LLM-driven
evolution 對自家 codebase 做 QoR 演化，以 `--check` 為適應度閘門。

## 4. 誠實聲明

efc 目前約 1,500 行 Python；對標專案為 10 萬～百萬行 C++。本計劃的取徑是
**萃取演算法與架構設計，不是重寫**。當 runtime 成為瓶頸時，選項是將核心
pass 下沉到 C++，或直接利用 nextpnr 的架構 API，而非在 Python 層硬扛效能。

## 版本紀錄

- v1.0（2026-10-25）：初版。對標 VTR/VPR 9、nextpnr、ABC/Yosys、OpenFPGA、
  RapidWright、OpenXC7/prjuray、VPR-Evolve；排定 Phase A/B/C 共 12 項改進。
- v1.1（2026-10-25）：Phase A 第 1 項（arch 描述檔化）標記完成（efc v0.3）。
- v1.2（2026-10-25）：Phase A 第 2 項（STA/criticality）標記完成（efc v0.4）。
- v1.3（2026-10-25）：Phase A 第 3 項（A* timing-driven router）標記完成（efc v0.5）。
- v1.4（2026-10-27）：Phase A 第 4 項（smart-centroid 初始佈局）標記完成（efc v0.6）。
  備註：v0.6 程式碼由每小時自動接續 session 完成，本版同步補齊設計書/計劃文件。
- v1.5（2026-10-27）：Phase A 第 5 項（cut-enumeration mapping）標記完成（efc v0.7），
  Phase A 全數完成；下一步進入 10（LEC 迴圈）‖ 9（OpenXC7 靶機）。
- v1.6（2026-10-30）：Phase C 第 10 項（LEC 驗證迴圈）標記完成（efc v0.8）；
  下一步進入 9（OpenXC7 靶機 xc7k325t）。
- v1.7（2026-10-30）：Phase C 第 9 項（OpenXC7 靶機後端）efc 端標記完成
  （efc v0.9）；bitstream 段待 OpenXC7 工具鏈環境。下一步進入 11
  （QoR 回歸系統）或 6/7（商用結構對齊）。
- v1.8（2026-10-30）：Phase C 第 11 項（QoR 回歸系統）標記完成
  （efc v0.10：`efc/qor.py` + `benchmarks/` 5 設計語料 + golden.json，
  確定性指標精確比對、runtime 僅記漂移、LEC 納入 golden）；RL/ML 前瞻
  的前置條件（corpus）已滿足。下一步進入 6/7（商用結構對齊：
  prepacking molecules、floorplanning constraints）。
- v1.9（2026-10-30）：新增 GitHub emulator 工具生態掃描
  （`docs/emulator-tools-landscape.md` v1.0）——確認 ZeBu/Palladium 級
  emulator compiler 無開源對應（本專案差異化明確），FireSim 為方法學
  最近對標；據此新增 Phase C 第 13 項（除錯觀測層：LiteScope /
  fpgacapZero 評估）與第 14 項（主機通道：LitePCIe vs XDMA、
  liteiclink 板間互連評估），硬體就緒時啟動、不阻塞軟體主線。
- v1.10（2026-10-30）：Phase B 第 6 項（prepacking molecules）標記完成
  （efc v0.11：`efc/prepack.py` 分子框架 + pack.py atomic 裝箱，QoR
  golden 零漂移守門）；carry8 端到端待前端算術推斷。下一步進入 7
  （floorplanning constraints）。
- v1.11（2026-11-01）：Phase B 第 7/8 項、Phase C 第 12/13/14 項標記完成
  （efc v0.12 floorplanning constraints——regions/fixed/exclusive + 全程
  強制 + post-place 驗證；v0.13 空間分割平行 routing——global 序列 +
  per-strip locals 多行程式平行 + overuse 自動退回序列；v0.14
  shell+patch 分區 + boundary net 審計 + RapidWright 交接文件；
  `docs/debug-observation-eval.md` 建議 fpgacapZero 為主、
  `docs/host-channel-eval.md` 建議 LitePCIe 為主 + liteiclink 板間互連）。
  **十四項全數收口**（剩餘為硬體就緒後的實體整合）。全程 QoR golden
  5/5 零漂移守門（runtime 僅漂移不斷言），96 項單元測試全過。
