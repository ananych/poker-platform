# Open decisions / assumptions register（SDD §16）

狀態：**Proposed** = 依 SDD 建議預設實作、尚待產品負責人確認；**Implemented** = 已有程式碼。

| ID | 項目 | 目前做法 | 狀態 |
|---|---|---|---|
| A-01 | Post-BB / missed-blind 規則 | **隨時可以進**：新坐下或暫離回來的玩家直接加入下一手（進行中的那手不能插入），不需要等大盲、不用補盲、沒有 dead SB。BB 每手在參與者之間順時針前進一位，Button/SB 由 BB 往回推 | **Confirmed** (2026-10-10) |
| A-02 | Show/Muck/all-in 揭露 | **攤牌時全部亮牌**：打到攤牌的每一手都公開（不能 muck），回放中也看得到；棄牌者的手牌永遠不公開。亮牌順序：河牌最後進攻者先，否則按鈕左側順時針 | **Confirmed** (2026-10-10) |
| A-03 | 關房／被封鎖後的存取 | 前成員（含關房後）可看歷史與回放；被封鎖者不能看歷史、只能看自己的籌碼紀錄，不能重新加入 | Implemented |
| A-04 | 改盲注後的買入上限 | 上限只套用到核准的補碼（套用當下的 max_buyin）；既有較大籌碼保留 | Implemented |
| A-05 | 恢復期間房主不在 | 連續斷線 60 秒轉移給最早加入（joined_at, member_id）且在線的未封鎖成員；原房主重連不會自動收回 | Implemented |
| A-06 | 牌組加密／金鑰輪替 | AES-256-GCM（AAD 綁定 hand/seq），金鑰來自 secrets manager；密文含 key id 以便日後輪替。輪替流程尚未自動化：有進行中牌局時不可換金鑰 | Implemented (rotation manual) |
| A-07 | Session 壽命 | 30 天滑動過期；剩餘不到一半時延長；敏感轉換時輪替 token | Implemented |
| A-08 | 回放／保留政策 | 牌局與 ledger 保留；聊天預設 30 天、過期 session 每小時清除 | Implemented |
| A-09 | ½-pot 等非整數預設 | raise_to = current_bet + floor((pot + to_call) × 比例)，夾在 server 給的 min/max；server 一律驗證 | Implemented |
| A-10 | 無合格房主時的完整恢復 | 無限期暫停直到授權操作者處理；空房 24h 關閉時若仍有未結束牌局，改設 PAUSED_RECOVERY 而不關房、不動底池 | Implemented (operator tooling 待 Phase 5) |

## Phase 2 實作上的補充決定

| 項目 | 做法 |
|---|---|
| 沒有牌局進行時 | 改設定（盲注/買入上下限）與已核准的補碼**立即**生效（本來就是「兩手之間」）；牌局中則等下一次 Start Hand |
| 補碼請求上限 | 申請時就檢查 `stack + 待處理補碼 + amount <= max_buyin`，套用時再檢查一次 |
| Presence | 連線狀態不增加 `room_version`，避免他人重連造成 STALE_VERSION |
| 密碼猜測限制 | 只有失敗的嘗試會扣額度（每 guest+房間、每 IP+房間，各 5 次／5 分鐘）；同一 NAT 的朋友正常加入不受影響 |
| 踢人 vs 封鎖 | `kick` 只移出座位（可繼續觀戰）；`ban` 移出座位＋封鎖＋斷線 |
| 空房關閉 | 24h 後關房時把所有座位 cash out 寫入 ledger（歸檔，不刪除牌局） |
| REST 動作端點 | `POST /rooms/{id}/actions` 走與 WS 完全相同的序列化流程，供工具/測試用 |

## Phase 3–5 補充

| 項目 | 做法 |
|---|---|
| 邀請連結 | 伺服器只存雜湊，連結只在建立／重新產生時顯示一次；房主可「產生新連結」使舊的失效 |
| 密碼驗證 | Argon2 驗證在房間鎖外執行（不阻塞牌局），通過後才進入序列化交易 |
| 部署 | 同源反向代理（Caddy），`/api` `/ws` `/health` 到 API；`/metrics` 只在內網用 token 存取 |
| 重新部署 | SIGTERM：拒絕新牌局、readiness 503、WebSocket 以 1012 關閉讓客戶端重連；新程序把進行中牌局設為 PAUSED_RECOVERY |
| 背景隱藏手牌 | 切到背景時模糊自己的手牌（僅 UX，非安全邊界） |

## 試玩回饋修正（2026-10）

| 編號 | 項目 | 決定 | 狀態 |
|---|---|---|---|
| B-01 | 逾時處理 | **逾時一律棄牌**（即使可以過牌），並在這手結束後進入「暫離」；按「回到牌局」恢復（等同 A-01 隨時可進）。取代 SDD §2 的 Check-or-Fold（engine 仍保留 `check_if_possible` 選項） | Implemented |
| B-02 | 逾時計時器 | 不再綁 `room_version`：只驗證「同一手、deadline 已過」。他人入座、改選房主、補碼申請等無關變動不會再讓計時器失效。背景 sweeper 每 5 秒補處理過期的 deadline（計時器只是加速） | Implemented |
| B-03 | 自動發牌 | 每手結束 5 秒後自動開下一手（`rooms.next_hand_at`），房主可按「立即發下一手」提早，或在房主面板暫停／恢復自動發牌。第一手仍由房主開始。房主不在也會繼續發牌 | Implemented |
| B-04 | 暫離太久 | 暫離超過 10 分鐘自動離座，籌碼寫入 ledger 結帳（不是封鎖，可重新入座） | Implemented |
| B-05 | 結果顯示 | 結束後自己的手牌一律顯示給自己（含棄牌）；贏家座位發光＋👑＋「🏆 +X」；自己贏時畫面中央「你贏了 +X」 | Implemented |
| B-06 | 水上水下 | 每個座位顯示淨輸贏（目前籌碼＋本手已下注＋已結帳−買入−補碼）；「戰績」分頁＋每 5 手自動跳出排行榜 | Implemented |
| B-07 | 預選動作 | 等待時可勾選：過牌/棄牌、過牌、跟注 X（金額變動自動取消）、跟任何注、預選加注（½/¾/1 池／全下）。只對勾選當下那條街有效；送出仍走一般 action 流程 | Implemented |
| B-08 | 提醒 | 輪到你：音效＋震動＋分頁標題閃爍＋（可選）背景通知；新訊息：座位泡泡、頂部提示、未讀數、音效 | Implemented |
| B-09 | 音樂／音效 | 全部以 Web Audio 即時合成（無音檔、無授權問題）；音樂預設關、音效預設開，在 ⚙ 設定 | Implemented |
| B-10 | 語言 | 中文／English，預設跟瀏覽器語言，⚙ 或大廳右上角切換 | Implemented |
