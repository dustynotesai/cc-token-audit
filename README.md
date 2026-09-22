# cc-token-audit

繁體中文 | [English](README.en.md)

> **ccusage 告訴你花了多少錢。**
> **這個工具告訴你，錢是被什麼花掉的。**

分析你自己的 Claude Code 使用紀錄，找出哪些 token 花在不必要的東西上。
零相依套件，資料不離開你的電腦。

📐 想知道每一步怎麼算、為什麼這樣算 → **[完整方法論](METHODOLOGY.md)**

---

## 安裝

```bash
pip install git+https://github.com/dustynotesai/cc-token-audit.git
cc-token-audit audit
```

不想安裝也可以直接跑：

```bash
git clone https://github.com/dustynotesai/cc-token-audit.git
cd cc-token-audit
python -m cc_token_audit audit
```

Python 3.9+。輸出預設繁體中文，加 `--lang en` 切英文。

<details>
<summary>裝完說「找不到指令」？</summary>

console script 會被放進 Python 的 `Scripts/`（Windows）或 `bin/` 目錄，
那個路徑不一定在你的 `PATH` 裡。改用 `python -m cc_token_audit audit`，
永遠可用，也不用動 PATH。
</details>

---

## 三個指令

```bash
cc-token-audit audit       # 總覽：帳單、浪費排行、怎麼做會比較省
cc-token-audit baseline    # 每個 session 開場就背著的那包東西，花了你多少
cc-token-audit drill <id>  # 單一 session，逐筆看是什麼把 context 撐大的
cc-token-audit verify      # 自我驗證：跟 ccusage 對帳，不用相信我
```

常用選項：`--project` `--since 7d` `--top 20` `--json` `--lang en`

---

## 先講清楚：一個 turn 是什麼

這份文件到處都在講 **turn**，它是整件事的計價單位，值得先搞懂。

**一個 turn = 模型被呼叫一次。** 不是你講一句話。

差別在哪？在 agentic coding 裡，你打**一則**訊息，Claude 可能會：

```
你：「幫我修好這個 bug」          ← 你只打了 1 則訊息
  │
  ├─ 讀檔案            → turn 1   ← 模型被呼叫，整個 context 讀一次
  ├─ 搜尋相關程式碼     → turn 2   ← 又一次，context 又大了一點
  ├─ 讀另一個檔案       → turn 3   ← 又一次
  ├─ 改程式碼          → turn 4   ← 又一次
  ├─ 跑測試            → turn 5   ← 又一次
  └─ 回報結果          → turn 6   ← 又一次
```

**每一個箭頭，都是一次完整的 API 呼叫，都要把當下整包 context 重讀一遍。**

### 這個落差有多大

實測你自己的紀錄：

| | |
|---|---:|
| 你實際打的訊息 | 2,419 則 |
| 模型實際被呼叫 | **10,666 次** |
| 平均每則訊息 | **4.4 個 turn** |
| 最誇張的 session | 16 個 turn / 訊息 |

所以當你覺得「我今天沒跟 Claude 講幾句話」，帳單看到的其實是
**四倍以上**的模型呼叫次數。

### 為什麼這件事是重點

因為 context 是**按 turn 計費**的，不是按你打了幾個字。

一個檔案在第 5 個 turn 被讀進來、session 總共跑了 900 個 turn，
那份內容就被收費了 895 次。而那 900 個 turn，可能只來自你打的 200 則訊息。

**這就是為什麼「攜帶成本」會這麼可怕**——乘數比你以為的大得多。

### 其他幾個詞

| 詞 | 意思 |
|---|---|
| **context** | 模型這一輪「看得到」的全部內容：system prompt、CLAUDE.md、對話歷史、工具結果 |
| **session** | 一次 Claude Code 對話，從開啟到 `/clear`。對應一個 `.jsonl` 檔 |
| **快取讀取** | context 裡已經算過的部分，便宜（基礎價 1/10） |
| **快取寫入** | 新東西第一次進 context，貴（1h TTL 是基礎價 2 倍，等於讀取的 20 倍） |
| **攜帶成本** | 一筆內容的**真正**成本 = 它的大小 × 它之後還被重讀幾次 |

---

## 在 session 裡即時知道「該不該 /compact 或 /clear」

上面三個指令都是**事後**分析。如果你想在寫程式的當下就知道，
把它掛成 Claude Code 的狀態列：

**步驟一**：先確認指令能跑（沒裝的話回到上面的安裝段落）

```bash
cc-token-audit statusline --help
```

**步驟二**：打開 `~/.claude/settings.json`，加上 `statusLine` 這一段。
**注意是加進去，不是整個檔案覆蓋掉**——你原本的設定要留著：

```json
{
  "model": "opus[1m]",
  "theme": "dark",

  "statusLine": {
    "type": "command",
    "command": "cc-token-audit statusline",
    "refreshInterval": 60
  }
}
```

`refreshInterval: 60` 讓它每分鐘自己更新一次，
這樣「快取還剩幾分鐘過期」的倒數才會跟著跳，不會停在你上次送訊息的那一刻。

**步驟三**：重開 Claude Code（或按一次 `/hooks` 讓它重讀設定）。

底部就會一直顯示：

```
Opus 5  ■■■□□□□□□□ 32%  320k  每輪 $0.160  ⚠ 重開撐 4 輪回本
Opus 5  ■■■■■■■■□□ 75%  750k  每輪 $0.375  ⚠ 重開撐 2 輪回本  快取 6 分後過期，屆時重付 $3.82
```

### 它在告訴你什麼

| 欄位 | 意思 |
|---|---|
| `每輪 $0.160` | **下一個 turn 光是重讀 context 就要花這麼多**，還沒開始做事 |
| `重開撐 4 輪回本` | 現在重開，只要之後還會用超過 4 個 turn，就比繼續扛划算 |
| `快取 N 分後過期` | 再不動作，整包 context 要以**寫入價**重買一次 |

**不用背任何門檻數字。** 看到「回本輪數」小於你接下來還要做的事，就該動了。

<details>
<summary>狀態列沒出現 / 顯示空白？</summary>

- 狀態列腳本壞掉時 Claude Code 只會顯示空白，不會報錯。先手動測：
  ```bash
  echo '{"model":{"id":"claude-opus-5","display_name":"Opus 5"},"context_window":{"total_input_tokens":300000,"used_percentage":30,"context_window_size":1000000}}' | cc-token-audit statusline
  ```
  應該要印出一行。沒有的話代表指令不在 PATH 上。
- PATH 找不到 `cc-token-audit` 的話，改用完整寫法：
  ```json
  { "statusLine": { "type": "command", "command": "python -m cc_token_audit statusline" } }
  ```
- 改完設定要重開 Claude Code 才會生效。
</details>

### /compact 還是 /clear？

| 情況 | 用哪個 | 為什麼 |
|---|---|---|
| 要換一件不相干的事 | **`/clear`** | 最便宜。舊歷史完全不用留，只重付開場那包 |
| 同一件事還要接著做 | **`/compact`** | 摘要會保留脈絡，但摘要本身也要付寫入費，所以別太頻繁 |
| 回本輪數還很大（>25） | **都不用** | 現在動反而虧 |

---

## 為什麼需要這個工具

現有工具（[ccusage](https://github.com/ccusage/ccusage) 和建構在它上面的那些
儀表板、選單列 app）都是把用量**按時間**分桶：今天、這週、這個 session。

那回答的是「**多少**」。

它們回答不了「**為什麼**」——因為它們的資料模型裡沒有「成因」這個維度。

這個工具反過來追：把每一個快取讀取 token，還原到「當初是哪個動作把東西塞進
context」，再乘上它之後被扛了幾個 turn。

---

## 一個你可能不知道的事

在 agentic coding 裡，你的 token 幾乎全部是**快取讀取**。
以一份真實的 46 億 token 紀錄為例：

| 項目 | tokens | 佔比 |
|---|---:|---:|
| 快取讀取 | 4,515,418,907 | **98.1%** |
| 快取寫入 | 72,576,883 | 1.6% |
| 輸出 | 12,747,834 | 0.3% |
| 輸入 | 49,412 | 0.0% |

### 但這不是浪費

重讀對話正是模型有記憶的唯一方式，而且快取讀取只要全新輸入的十分之一。

**任何人跟你說「你 98% 的 token 都浪費掉了」，都是在誤讀這個數字。**

### 真正的重點是「乘數」

context 是**按每個 turn** 計費的。
在一個 900 turn 的 session 裡，第 5 個 turn 塞進去的東西，之後還要再被收費 895 次。

所以一筆工具結果的成本，**幾乎跟它的大小無關**，
而幾乎完全取決於它**什麼時候**進來：

```
      美元    tokens   被重讀  進來的時機
    $16.33    56,296      560  turn 0      <- 開場那包常駐 context
     $2.64     8,113      631  turn 820    <- 一條 bash 指令
```

那條 8k token 的指令，比同一個 session 裡多數 40k 的讀檔還貴。
純粹因為它落在什麼位置。

---

## 它會幫你抓出什麼

| 類別 | 它在算什麼 |
|---|---|
| **重複讀取** | 同一 session 內，同樣的東西讀了第二次以後。Edit/Write 不算——反覆改同一個檔案是正常工作 |
| **快取重寫** | 快取過期後，同樣的內容以「寫入價」再買一次 |
| **過大的工具輸出** | 只算超過 10k tokens 的那一部分，當作原本就該分頁或過濾 |
| **失敗的工具呼叫** | 錯誤、被中斷、搜尋不到東西——什麼都沒回傳，卻被扛了一整個 session |

每一項都會印出**它自己的認定方式**，因為「可以省」是一種判斷，
你應該有辦法不同意它。

---

## 怎麼做會比較省

`audit` 會拿你**真實的** context 成長，在不同工作習慣下重播一次。
這是重播，不是猜測——而且每次重開 session 都要付「重建 context」的成本，
所以沒有任何一項是免費的午餐。

結論**不是**「多清空 context」：

```
策略                                             會花       省下
context 到 300k 就開新 session               $1,698.95   $642.01    27%
context 到 500k 就開新 session               $1,832.35   $508.61    22%
context 到 200k 就開新 session               $2,102.67   $238.29    10%
context 到 150k 就開新 session               $2,935.63  $-591.98   -25%  <- 反而更貴
context 到 100k 就開新 session               $7,882.65 $-5,539.00  -236%  <- 反而更貴
```

**這裡有一個底。**

每次重開都要重寫常駐 context，而一次快取寫入是快取讀取的 **20 倍價**。
所以重開得太勤，比從不重開還糟。最佳點大約在 **300k**，而不是越早越好。

---

## 這些數字有多可信（不用相信我，自己驗）

```bash
cc-token-audit verify
```

它會做兩種**互相獨立**的檢查：

```
內部檢查
                        cc-token-audit  ccusage / actual     drift
  carry identity         4,586,250,703     4,540,328,954    +1.01%  通過
  per-session sums       4,540,328,954     4,540,328,954    +0.00%  通過

跟 ccusage 對帳（獨立的第三方工具，讀同一批 log）
  cache read             4,540,328,954     4,536,430,862    +0.09%  通過
  cache write               72,818,624        72,794,665    +0.03%  通過
  input                         49,568            49,544    +0.05%  通過
  output                    14,180,855        14,180,954    -0.00%  通過
```

- **內部**：攜帶成本是個恆等式，重新加總必須還原出實際計費的快取讀取量。
- **外部**：跟 [ccusage](https://github.com/ccusage/ccusage)（18.7k stars）對帳。
  它讀同一批 log。**原始總數對得上，才有資格談上面疊的那層歸因。**

> 這個對帳實際上抓到過我的一個 bug：assistant 的重複記錄是串流快照，
> `output_tokens` 會隨著生成長大，而我原本讀的是第一張快照，
> 導致輸出少算 9.5%。ccusage 比對後才發現並修掉。
> （context 那三欄不受影響，所以核心分析一直是對的。）

**總量是精確的**，**單筆拆分是估計的**——所以每次執行都會印出**歸因保真度**。

完整推導、每一步的取捨、以及我算錯過的四個地方，
都寫在 **[METHODOLOGY.md](METHODOLOGY.md)**。

---

## 關於金額

金額是換算成 [Claude API 牌價](https://platform.claude.com/docs/en/about-claude/pricing)
的結果（費率擷取於 2026-09-22），包含兩個容易漏掉的細節：

- 1 小時 TTL 的快取寫入是基礎輸入價的 **2 倍**（不是 1.25 倍）
- Fable 5.1 的快取讀取是 **0.025 倍**（不是一般的 0.1 倍）

> **如果你用的是 Pro / Max 訂閱，你並沒有實際付出這些錢。**
> 請把它當成「做了多少工」的量尺，以及各項目之間的相對大小，
> 而不是一張你欠的帳單。

費率定義在 `cc_token_audit/pricing.py`，可以自己改。

---

## 已知限制

- **turn-0 那包拆不開。** 無法只靠 log 分出 MCP schema / CLAUDE.md / system prompt
  各佔多少——system prompt 不會被寫進 log。`baseline` 精確量測整包大小並明講這點。
- **事件大小是近似的。** 以字元數量測、4 字元／token 換算。只有事件之間的**比例**
  有意義，這個常數會相消，但單一事件被分到的那一份仍是近似值。
- **節省模擬不模擬快取過期**，只重現了實測攜帶成本的約 90%。
  **請看它的百分比，不要看它的絕對金額。**

---

## 測試

```bash
python -m unittest discover -s tests
```

## 授權

MIT
