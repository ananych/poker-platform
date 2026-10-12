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
