# 除錯觀測層整合評估（改進計劃 Phase C 第 13 項）

> open-emulator-platform 專案 ｜ 2026-11-01 ｜ v1.0
> 目的：emulator 上版後的內部訊號觀測不自研，從開源方案擇一整合。
> 星數/更新日為 2026-10-31 經 GitHub API 查得。背景見
> 《emulator-tools-landscape》§3。

## 1. 候選比較

| 維度 | litescope (enjoy-digital/litescope, 212★) | fpgacapZero (lcapossio/fpgacapZero, 136★) |
|---|---|---|
| 最後更新 | 2026-10-20 | 2026-10-31（非常活躍，2026-03 才建立） |
| 定位 | 嵌入式 logic analyzer（ILA 開源對應） | vendor-agnostic 全套除錯 cores：LA + embedded IO + JTAG-AXI |
| 匯流排 | Wishbone / LiteX 生態 | AXI（JTAG-AXI 直達，不必經系統匯流排） |
| Vivado 依賴 | 無（純 Verilog + Python 前端） | 無（明確標榜 vendor-agnostic） |
| 波形後端 | 自帶 dump（VCD）→ GTKWave | VCD/FST → GTKWave |
| 本專案相容性 | 與 LiteX support SoC 天然搭配 | 與路線無關，對「無 Vivado 流程」最保守 |

兩者都滿足硬條件（開源、無 Vivado 依賴、GTKWave 收尾）。分歧在生態：
litescope 綁 LiteX/Wishbone；fpgacapZero 綁 AXI 但匯流排依賴更鬆
（JTAG-AXI 可獨立使用）。

## 2. 建議：**fpgacapZero 為主，litescope 為備**

理由：

1. **觀測通道獨立性**：emulator 的 host 通道（見《host-channel-eval》）
   本身就是 scarce resource；JTAG-AXI 走獨立除錯通道，不和
   DUT/主機資料流搶頻寬。litescope 走系統匯流排，除錯流量會
   污染 emulator 的 timing 量測——對一個以「量時序」為賣点的
   平台是扣分项。
2. **供應商中立承諾**：fpgacapZero 明確把 vendor-agnostic 寫進
   repo 描述，與本專案 OpenXC7/無 Vivado 路線的策略一致；
   litescope 雖也是純 Verilog，但整個工具鏈（litex_boards、
   Python 前端）實質綁定 LiteX 生態版本節奏。
3. **活躍度**：fpgacapZero 建立於 2026-03、2026-10-31 仍有提交，
   issue 回應快；litescope 功能穩定但功能增量趨緩（對成熟工具
   中性，對新需求偏負）。

反向條件（什麼情況改選 litescope）：若 ProtoBoard 的 support
SoC 確定用 LiteX 且除錯走系統匯流排可接受（例如只做功能除錯、
不做全速 timing 量測），litescope 與 LiteX 整合的現成度更高，
且 212★ 的社群驗證更足。

## 3. 整合路線（硬體就緒時啟動）

1. 選定觀測通道：JTAG-AXI（fpgacapZero）vs PCIe 直連——與
   《host-channel-eval》的選型連動。
2. 訊號清單由 efc 的 `ext_nets` 與 floorplan 區域產生
   （觀測點優先放 boundary net，正是 shell+patch 的跨界線）。
3. 波形回讀統一走 GTKWave；檔案格式統一 FST（體積小於 VCD）。
4. 驗收：在 alu4 級設計上觀測一條 known-critical net，
   波形與 Verilator golden 逐週期一致（方法學同 efc LEC 的
   誠實標準：對不上就是觀測層 bug，不圓場）。
