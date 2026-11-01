# 主機通道選型評估（改進計劃 Phase C 第 14 項）

> open-emulator-platform 專案 ｜ 2026-11-01 ｜ v1.0
> 目的：ProtoBoard host 介面二選一 + 多板互連物理層評估。
> 星數/更新日為 2026-10-31 經 GitHub API 查得。背景見
> 《emulator-tools-landscape》§2/§4。

## 1. 主機通道：LitePCIe vs XDMA

| 維度 | LitePCIe (enjoy-digital/litepcie, 740★, 2026-10-29 更新) | Vivado XDMA IP（參考 WangXuan95 教學 867★） |
|---|---|---|
| 授權 | MIT，開源 core + Linux/Windows 驅動 | 商用 IP，隨 Vivado 授權 |
| Vivado 依賴 | 無（與 OpenXC7/無 Vivado 路線相容） | 必須 Vivado |
| 效能 | Gen3 x8 級（依板卡） | Gen3/Gen4（依版本與授權層級） |
| 驅動維護 | 開源社群 + 可自行修 | AMD 官方維護但黑箱 |
| 除錯觀測連動 | 與 litescope 同生態 | 與 fpgacapZero 無衝突 |

**建議：LitePCIe 為主**——硬條件是「無 Vivado 路線可生存」：
XDMA 一旦選定，整個工具鏈就被綁回 Vivado，Phase C 第 9 項
（OpenXC7）與 shell+patch 的 RapidWright 替代路線全部作廢。
效能差距對 emulator 控制面（下載 bitstream、讀寫少量暫存器、
回讀波形）不是瓶頸；若未來出現 DMA 頻寬瓶頸，退路是
alexforencich/verilog-pcie（1,677★，純 Verilog，同樣無 Vivado）。

**fallback 觸發條件**：AMD 板卡的 PCIe PHY 整合若繞不過
Vivado（某些 VP1902 官方板的 GTH 設定只有 Vivado 範例），
則控制面退回 XDMA、資料面仍優先評估 verilog-pcie。

## 2. 多板互連：liteiclink

ProtoPartition 切出多顆 FPGA 後，板間互連物理層評估
liteiclink（enjoy-digital/liteiclink，68★，2026-10-30 更新）：

- 提供 Inter-chip SerDes cores（SFP/光纖），與 LitePCIe 同
  LiteX 生態，整合成本低。
- 方法學對標 FireSim supernode 的 TDM 排程：板間 link 是
  emulator 分割後的稀缺資源，time-division multiplexing 決定
  可模擬的設計規模上限；efc 的 multi-FPGA partition
  （floorplan constraints 是其前置能力，見改進計劃第 7 項）
  應以「最小化板間 net 數」為目標函數之一。
- **誠實標記**：68★ 的成熟度低於 PCIe 側候選，上板前需要
  loopback 誤碼率驗收；若驗收不過，退路是商用 FMC/SFP 橋接板 +
  自有協議（成本高但風險可控）。

## 3. 啟動時機

不阻塞軟體主線。硬體就緒（ProtoBoard 板卡定案）時依序啟動：
LitePCIe 控制面 bring-up → fpgacapZero 觀測層（見
《debug-observation-eval》）→ liteiclink 板間互連驗收。
