# Emulator 容量與架構對標分析

> open-emulator-platform 專案設計文檔 ｜ 2026-10-23
> 以 AMD VP1902 為基底的 1/2/4/8 擴展規劃，與 Synopsys / Cadence / Siemens 商用平台對照。

## 一、摘要

本文件回答一個問題：用目前最大容量的 FPGA（AMD Versal Premium VP1902）搭建 1、2、4、8……顆規模的 emulator，各級配置能做到多大、跑多快，以及三大商用平台用同樣或更強的硬體做到了什麼程度。

- 單顆最大 FPGA 為 VP1902（18.5M system logic cells，2× 於 VU19P），且三大廠的 FPGA prototyping 線全部以它為基底——自研選型沒有站錯隊的風險。
- 以保守口徑 100M 等效閘/顆估算，1B 閘 MVP 約需 16 顆；以 Cadence 的 250M 可用閘/顆口徑則 4–8 顆即可——差距全部來自分割編譯器品質。
- 系統級容量天花板：Synopsys ZeBu Server 5 >60 BG（模組堆疊）；Cadence 與 Siemens 的簽核級 emulator 皆走自製晶片（5nm/7nm），48 BG / 40+ BG。
- 結論呼應可行性評估：硬體堆疊不難，80% 的價值與難度在分割編譯器與 debug 基礎設施。

## 二、最大容量 FPGA 與 1/2/4/8 擴展規劃

### 2.1 AMD VP1902 規格

VP1902 於 2023 年 6 月發表，至今仍是業界最大容量的 FPGA / adaptive SoC [^1]：

| 項目 | 規格 |
|---|---|
| System logic cells | 18.5M（2× VU19P） |
| LUT | 8.46M |
| DSP58 | 6,864 |
| 片上記憶體 | 858 Mb（239 Mb BRAM + 619 Mb UltraRAM） |
| SelectIO | 2,328 @ 最高 3.2 Gbps |
| 高速 SerDes | 最多 160 組，總頻寬 12.2 Tbps |
| 硬化 DDR 控制器 | 14 |

[^2]

### 2.2 1/2/4/8/16 顆容量擴展表

名目基準採 S2C Prodigy S8-100 官方換算：單顆 VP1902 ≈ 100M ASIC 等效閘（1/2/4 顆對應 100M/200M/400M）[^3]。

| 配置 | Logic Cells | 名目等效閘¹ | 務實可用² | 形態 / 互連 | 預期跑速³ | 適用場景 |
|---|---|---|---|---|---|---|
| 1 顆 | 18.5M | ~100M | 50–70M | 單板，無跨片切割 | 20–50 MHz | IP / 子系統驗證、軟體開發 |
| 2 顆 | 37M | ~200M | 100–130M | 同板直連（SelectIO + GT） | 10–30 MHz | 中型 SoC 子系統 |
| 4 顆 | 74M | ~400M | 200–260M | 板內 SERDES + TDM pin-mux | 5–15 MHz | 中大型 SoC（對標 S8-100 Quad） |
| 8 顆 | 148M | ~800M | 400–520M | 機箱 + 背板 | 3–10 MHz | 大型 SoC 全晶片、OS boot |
| 16 顆 | 296M | ~1.6B | 0.8–1.0B | 多機箱級聯 | 1–5 MHz | ≈ 自研 roadmap Phase 2 的 1B 閘目標 |

¹ 名目值 = 廠商換算（約 5.4 gates/LC），為資源全部用滿的理想值。
² 務實可用 = 乘上 50–65% 實裝率：跨片 cut net、TDM 時分多工與 debug 儀表都會消耗資源，顆數越多效率越低，容量呈次線性成長。
³ 速度隨 TDM ratio 上升而下降：跨片訊號需串行化（ratio 8–32），是 8 顆以上掉到個位數 MHz 的主因。

### 2.3 關鍵設計判斷

- **互連是瓶頸而非邏輯**：4 顆以內可靠直連加低倍 TDM 撐住；8 顆以上拓撲（ring/mesh/crossbar）與分割品質直接決定可用容量與速度。
- **模組化路線**：比照 S2C S/D/Q 做法，同一塊 FPGA module 板做 1→2→4 擴展，8 顆起進機箱——與自研 roadmap 的 Phase 1（multi-FPGA 原型板）→ Phase 2（1B 閘 MVP）完全吻合。
- **記憶體無虞**：每顆 858 Mb 片上 RAM + 14 個硬化 DDR 控制器，外接 DDR 是成熟做法。
- **真正的護城河在軟體**：自動分割編譯器、全可視性 debug、timing-driven partition。

## 三、三大商用平台對標

### 3.1 Synopsys：ZeBu Server 5 / ZeBu-200 / HAPS-200

| 系統 | 底層 FPGA | 容量 | 備註 |
|---|---|---|---|
| ZeBu Server 5（2023） | AMD VU19P（上一代） | 30 BG；2025 Modular HAV >60 BG；2026 software-defined 更新再 2× | 64 模組 × 每模組 240M 閘 + 80 GB 記憶體 [^4] |
| ZeBu-200（2025） | AMD VP1902 | 15.4 BG → 官網現標 23 BG | 2026/3 新增 12-FPGA 平台（Q3 2026 上市），較舊 6-FPGA 版容量 2× [^5] |
| HAPS-200（prototyping） | AMD VP1902 | 單顆桌面到 multi-rack 10.8 BG | EP-Ready 硬體可切換 emulation / prototyping |

### 3.2 Cadence：Palladium Z3 / Protium X3

2024 年 4 月 Dynamic Duo III：Palladium Z3 採自研仿真處理器（TSMC 5nm，單顆 >100B 電晶體），Protium X3 採 VP1902，兩台均 2× 容量、1.5× 速度，規模至 48 BG [^6]。

| | Palladium Z3（emulator） | Protium X3（prototyping） |
|---|---|---|
| 硬體基礎 | 自研仿真處理器，TSMC 5nm，>100B 電晶體 | AMD VP1902 |
| 容量 | 16M → 48 BG | 40M → 48 BG；System Studio 單機箱 250M 閘起跳 |
| 編譯 | Modular compile <8 小時，一天可轉 3 次 | <24 小時（≤20 BG） |
| 速度 | 基準（1×） | 比 Palladium 快 3–5× |
| 獨門功能 | 業界首個 4-state emulation、數模混合 emulation、95% 精度功耗簽核 [^8] | 每顆 250M 可用閘 + 1.1 GB 片上 RAM + 內建 64 GB DDR [^7]；與 Z3 共用編譯器 |
| 網路 | NVIDIA BlueField DPU + Quantum InfiniBand | 同左 |

### 3.3 Siemens（Mentor）：Veloce CS 家族

2024 年 2 月發表、同年夏季出貨，三機一體，全系 40M 閘至 40+ BG；Strato CS 採自研 CrystalX（Samsung 7nm 最大光罩），Primo CS / proFPGA CS 採 VP1902，三台共用編譯器與資料庫、硬體約 70% 重用 [^9][^10]。

| | Strato CS（emulation） | Primo CS（enterprise proto） | proFPGA CS（software proto） |
|---|---|---|---|
| 硬體 | 自研 CrystalX，Samsung 7nm | AMD VP1902 | AMD VP1902 |
| 單 blade | ~170M 閘 | ~500M 閘 | 單顆 FPGA 桌面板起跳 |
| 擴展階梯 | blade→模組→tower（~3B）→16 towers = 40+B、共 256 blades | tower ~8B → 6 towers = 40+B | 每機櫃 4B 閘、60 用戶並發 |
| 速度 | 基準（全可視性下 5× 前代） | 更快（prototyping 直連） | 最高 100 MHz |
| vs 前代（2021） | 4× 容量 / 5× 效能 / 5× debug | 4× / 5× / 50× debug | 2× / 2× / 50× |

proFPGA CS 的 VPS 軟體（自動 multi-FPGA 分割、timing-driven 優化、TDM pin-muxing）是業界公認標桿，也是自研分割編譯器最直接的參照。

### 3.4 三家對照總表

| | Synopsys | Cadence | Siemens（Mentor） |
|---|---|---|---|
| Emulator | ZeBu Server 5：>60 BG（VU19P 模組）；ZeBu-200：23 BG（VP1902） | Palladium Z3：48 BG（自研 5nm 處理器） | Strato CS：40+ BG（自研 7nm CrystalX） |
| FPGA prototyping | HAPS-200 / ZeBu-200（VP1902） | Protium X3：48 BG（VP1902） | Primo CS + proFPGA CS（VP1902） |
| 差異化 | software-defined 容量彈性、模組 HAV | 8h 編譯 TAT、4-state、功耗簽核 | 三機 congruency（70% 硬體重用）、blade 模組化 |

## 四、閘數口徑與架構槓桿

同樣一顆 VP1902，各家等效閘數相差達 2.5 倍以上。原因：一是架構差異——ZeBu 採編譯式排程（compiled scheduling），以時間多工換取更高映射密度；S2C/HAPS 為 prototyping 直接映射，密度低但速度快。二是 gate-equivalent 計數習慣不同。

| 口徑來源 | 每單位等效閘 | 底層 | 備註 |
|---|---|---|---|
| S2C Prodigy S8-100 | ~100M / 顆 | VP1902 | prototyping 直映射口徑，保守務實 |
| Cadence Protium X3 | ~250M 可用 / 顆 | VP1902 | System Studio 資料表明示 usable gates |
| Siemens Primo CS | ~500M / blade | VP1902（blade 內多顆） | 多顆合封後的系統級密度 |
| Synopsys ZeBu Server 5 | ~240M / 模組 | VU19P（9M LC） | ≈26.7 gates/LC，編譯式架構 + 計數習慣差異 |

規劃含義：以 S2C 100M/顆為下限、Cadence 250M/顆為上限做區間規劃。**編譯器品質本身就是容量**——這是架構槓桿的核心。

## 五、對自研路線的含義

- **硬體選型確認**：VP1902 是全產業共用的 prototyping 基底，自研硬體直接對標這一層。
- **雙軌架構獲三大廠驗證**：Cadence 與 Siemens 都以「自研晶片做簽核級 emulation、FPGA 做 prototyping」雙軌佈局，以共用編譯器打通——與本專案雙軌執行計劃一致。
- **容量目標校準**：Phase 2 的 1B 閘 MVP，保守口徑約需 16 顆 VP1902；分割編譯器達 Cadence 水準則 4–8 顆即可。軟體投資直接決定硬體成本。
- **速度預期管理**：單顆桌面級可達 20–100 MHz（proFPGA CS 標稱 100 MHz）；8 顆以上因 TDM 掉到個位數 MHz，須在規格書中明確告知使用者。
- **下一步**：把 1/2/4 顆模組的互連拓撲與 TDM ratio 預算展開為 ProtoBoard M2 硬體規格，並以 Siemens VPS 為分割編譯器功能基線。

## 資料來源

[^1]: AMD, "AMD Launches World's Largest FPGA-Based Adaptive SoC for Emulation and Prototyping", 2023-06. https://ir.amd.com/news-events/press-releases
[^2]: fpga.dev, "AMD Versal Premium VP1902: Key Specs and Pricing", 2025-10. https://fpga.dev/hardware/vp1902/
[^3]: S2C / PRNewswire, "S2C Unveils New Prodigy S8 Series Prototyping Solutions Powered by AMD Versal Premium VP1902 Adaptive SoC", 2025-06. https://www.prnewswire.com/news-releases/s2c-unveils-new-prodigy-s8-series-prototyping-solutions-powered-by-amd-versal-premium-vp1902-adaptive-soc-302296906.html
[^4]: Synopsys, "Synopsys Unveils Era's Most Scalable Emulation Systems", 2025-02-25. https://investor.synopsys.com/news/news-details/2025/；ZeBu Server 5 System Guide（64 模組 × 240M 閘/模組）
[^5]: SemiWiki, "Synopsys Introduces HAPS-200 12 FPGA and ZeBu-200 12 FPGA Systems", 2026-03. https://semiwiki.com/
[^6]: Design&Reuse / Cadence, "Cadence Unveils Palladium Z3 Emulation and Protium X3 Enterprise Prototyping Systems", 2024-04. https://www.designandreuse.com/news/57753/cadence-palladium-z3-protium-x3.html
[^7]: Cadence, "Protium X3 System Studio Datasheet", 2024. https://resources.pcb.cadence.com/
[^8]: Cadence, "Palladium Z3 Enterprise Emulation Platform" 產品頁. https://www.cadence.com/en_US/home/tools/system-design-and-verification/emulation/palladium-z3-enterprise-emulation-platform.html
[^9]: Siemens, "Siemens Veloce CS hardware assisted verification and validation system", 2024-02. https://newsroom.sw.siemens.com/en-US/siemens-veloce-cs-hardware-assisted-verification-and-validation-system/
[^10]: SemiWiki, "Siemens Veloce CS Set to Redefine Design Verification Productivity", 2024-04；engineering.com, "Siemens Announces Veloce CS Verification Suite", 2024-03
