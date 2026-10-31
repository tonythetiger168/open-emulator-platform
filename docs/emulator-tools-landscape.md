# Emulator 工具生態掃描（GitHub OSS 版圖）

> open-emulator-platform 專案 ｜ 2026-10-30 ｜ v1.0
> 目的：掃描 GitHub 上可支援本 emulator 平台（efc compiler、ProtoBoard、
> ProtoPartition、runtime）的開源工具，按需求面分類，標示硬識別碼
> （repo、星數、最近更新），並給出整合建議。星數與更新時間為 2026-10-30
> 經 GitHub API 查得之值。編譯器/P&R 對標（VTR、nextpnr、OpenFPGA、
> OpenXC7、RapidWright 等）已收於《改進計劃》§1，本文不重複。

## 1. 模擬／驗證方法學（emulator 軟體面對標）

| 專案 | ★ | 最近更新 | 對專案的意義 |
|---|---|---|---|
| [firesim/firesim](https://github.com/firesim/firesim) | 1,057 | 2026-10-29 | **最接近的開源對標**：FPGA-accelerated 硬體模擬全棧——Golden Gate compiler 把 RTL 轉成 FAME1 decoupled 模型、supernode 做多 FPGA 分割排程、FireMarshal 管 workload（93★）。ProtoPartition 與 efc 的方法學參照 |
| [verilator/verilator](https://github.com/verilator/verilator) | 4,041 | 2026-10-30 | 上機前的 golden 模擬器；亦可做 efc 輸出網表的行為級對照 |
| [cocotb/cocotb](https://github.com/cocotb/cocotb) | 2,559 | 2026-10-29 | Python 驗證框架；配 cocotbext-axi（368★）/ cocotbext-pcie（213★）/ cocotb-coverage（129★）可建 emulator 的 host-side 測試台 |
| [euphoric-hardware/rtl-simulation-reading](https://github.com/euphoric-hardware/rtl-simulation-reading) | 20 | 2026-10-02 | RTL 模擬／emulation 論文書單，調研用 |

## 2. 主機介面 / Runtime（emulator 與 host 的通道）

| 專案 | ★ | 最近更新 | 說明 |
|---|---|---|---|
| [enjoy-digital/litepcie](https://github.com/enjoy-digital/litepcie) | 740 | 2026-10-29 | 小尺寸 PCIe core + Linux/Windows 驅動，LiteX 生態；ProtoBoard 主機通道的現成選項 |
| [enjoy-digital/litex](https://github.com/enjoy-digital/litex) | 4,182 | 2026-10-30 | SoC 建構框架，快速拉起 support infrastructure（UART/ETH/PCIe/DDR 控制面） |
| [alexforencich/verilog-pcie](https://github.com/alexforencich/verilog-pcie) | 1,677 | 2026-10-28 | 純 Verilog PCIe 元件庫（不進 LiteX/Python 流程時的選項） |
| [WangXuan95/Xilinx-FPGA-PCIe-XDMA-Tutorial](https://github.com/WangXuan95/Xilinx-FPGA-PCIe-XDMA-Tutorial) | 867 | 2026-10-28 | XDMA 保姆級教學，走 Vivado XDMA IP 路線時參考 |

## 3. 除錯可觀測性（emulator 上版的眼睛）

| 專案 | ★ | 最近更新 | 說明 |
|---|---|---|---|
| [enjoy-digital/litescope](https://github.com/enjoy-digital/litescope) | 212 | 2026-10-20 | 嵌入式 FPGA logic analyzer（ILA 開源對應），可參數化、走 LiteX 匯流排 |
| [lcapossio/fpgacapZero](https://github.com/lcapossio/fpgacapZero) | 136 | 2026-10-29 | vendor-agnostic 除錯 cores：embedded LA + embedded IO + JTAG-AXI，不依賴 Vivado ILA——**與無 Vivado 路線相容** |
| [gtkwave/gtkwave](https://github.com/gtkwave/gtkwave) | 1,041 | 2026-10-30 | 波形查看（VCD/FST），回讀除錯資料的後端 |

## 4. 多 FPGA 互連（ProtoPartition 的物理層）

| 專案 | ★ | 最近更新 | 說明 |
|---|---|---|---|
| [enjoy-digital/liteiclink](https://github.com/enjoy-digital/liteiclink) | 68 | 2026-10-29 | 小尺寸 inter-chip SerDes 通訊 cores（SFP/光纖）——多板卡互連 fabric 的開源起點 |
| [alexforencich/verilog-ethernet](https://github.com/alexforencich/verilog-ethernet) | 3,142 | 2026-10-30 | 1G–100G Ethernet 元件，板間互連備案 |
| firesim supernode | — | — | 多 FPGA 分割 + TDM 排程的唯一開源實作範例（firesim repo 內） |

## 5. Gap 分析（誠實版）

1. **ZeBu/Palladium 等級的完整 emulator compiler 在開源世界不存在**：
   「multi-FPGA partition + TDM pin-muxing 編譯器」的針對性搜尋
   （`multi-FPGA partition`、`ASIC emulation FPGA compiler TDM` 等）
   近乎零命中。這正是本專案（efc + ProtoPartition）填的空缺。
2. **方法學最接近的是 FireSim**（Golden Gate/FAME 模型、supernode 分割），
   但它是 simulation-acceleration 取向（decoupled model、非全速
   cycle-accurate in-circuit），與硬體 emulator 設計點不同——適合借鑑
   分割排程與 host 通訊協定，不適合直接當編譯流程。
3. **除錯與主機介面已有成熟開源件**（LiteScope、fpgacapZero、LitePCIe），
   這兩塊不必自研，列為整合評估項（《改進計劃》第 13、14 項）。

## 6. 建議

- **短期（整合評估）**：LiteScope / fpgacapZero 擇一做 emulator 除錯
  觀測層；LitePCIe vs XDMA 做主機通道選型——見《改進計劃》Phase C
  第 13、14 項。
- **中期（方法學）**：ProtoPartition 設計時研讀 FireSim supernode 的
  TDM 排程與分割粒度決策，取其分配演算法、捨其 decoupled 模型。
- **長期（驗證）**：上機流程以 cocotb + cocotbext-pcie 建 host-side
  回歸測試台；GTKWave 作回讀波形後端。

相關文件：《單顆 FPGA Compiler 架構設計書》《改進計劃》
（`docs/compiler-improvement-plan.md`）。
