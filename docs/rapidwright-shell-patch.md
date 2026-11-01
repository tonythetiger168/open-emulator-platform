# RapidWright shell+patch 落地文件（改進計劃 Phase C 第 12 項）

> open-emulator-platform 專案 ｜ 2026-11-01 ｜ v1.0
> 對應 efc v0.14（`efc/shellpatch.py`）。本文是 efc 分區輸出 → RapidWright
> 實作流程的交接文件；RapidWright 側需要 Java + Vivado，在沙箱外執行。

## 1. 背景與對標

RapidWright（Xilinx 官方開源，395★）的 pre-implemented blocks /
stamped modules 路線：把固定不动的 *shell*（static logic、IO、host
介面）實作一次並保留 DCP，反覆迭代時只重作 *patch*（可重構區域），用
BlockStitcher 類 API 縫合。對本專案的意義：emulator bring-up 期間
DUT 天天變、shell 不變——正是 shell+patch 的最佳應用場景。

## 2. efc 側產出（已在 v0.14 落地）

```bash
python -m efc.cli <design>.v --grid N \
    --shell-patch x0,y0,x1,y1 --shell-patch-out sp.json
```

`sp.json` 內容（全部可由單元測試覆蓋的確定性輸出）：

| 欄位 | 意義 | RapidWright 消費方式 |
|---|---|---|
| `patch_rect` | patch 區域（CLB 矩形） | 對應 RP（reconfigurable partition）的 Pblock / CLOCKREGION 約束 |
| `patch_blocks` / `shell_blocks` | 每個 block 的來源 cell 名稱與擺放 slot | 轉成 EDIF 實例清單後，shell 實例走「保留 DCP」，patch 實例進入新一輪實作 |
| `boundary_nets` | 跨區 net + 兩側 terminal 數（含 IO pad 側） | 對應 partition pin 介面：每條 boundary net 在 RP 邊界需要一個 partition pin |

`boundary_nets` 是關鍵交付物：shell/patch 之間的每條跨界 net 都必須在
RP 介面上有 pin，漏一條縫合就會失敗。efc 的審計保證：回報的
boundary net 兩側 terminal 數與 netlist 逐條一致（測試
`test_boundary_nets_detected` / `test_internal_patch_net_not_boundary`）。

## 3. RapidWright 側流程（沙箱外）

1. **第一次完整實作**：設計（含 efc 產出 EDIF，見 `efc/edif.py`）+
   floorplan 約束（patch_rect → Pblock）走 Vivado synthesized DCP。
2. **保留 shell**：以 patch_rect 為界，匯出 shell 的 routed DCP
   （`write_checkpoint`）；記錄 boundary net 在 RP 邊界上的實體 pin 位置。
3. **迭代日**：DUT 更新 → 只對 patch 區塊重跑實作
   （`reset_run` / `route_design -reuse` 或 RapidWright 的
   `BlockStitcher`），套用保留的 shell DCP。
4. **縫合驗證**：`lec.py` 一貫的態度——沒有做 LEC 就不宣稱正確；
   Vivado 側至少跑 `report_route_status` 確認無 dangling net。

## 4. 誠實聲明與 fallback

- efc 的網格是**邏輯 CLB 網格**，不是 VP1902 的真實 tile 座標；
  `patch_rect` 換算到真實 Pblock 需要一層座標映射（座標比例 =
  邏輯網格邊長 / 裝置 CLB 列數），這層映射在第一次真機實作時校準。
- 若 RapidWright/Vivado 路線因授權或環境不可行，**已驗證退路**是
  Phase C 第 9 項的 OpenXC7 線（efc → nextpnr-xilinx → 真 bitstream），
  shell+patch 降級為完整重編譯，損失的是周轉時間不是正確性。
- carry8 分子（v0.11）跨 shell/patch 邊界時必須整鏈歸同一側——efc
  目前會原樣回報此種 boundary net，由 floorplan 約束階段攔截
  （整鏈歸 patch 是推薦預設）。
