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
```

常用選項：`--project` `--since 7d` `--top 20` `--json` `--lang en`

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

## 這些數字有多可信

**總量是精確的**——全部從實際計費的 token 數推導而來。

**單筆拆分是估計的**——按各事件的實測大小等比例分配。

所以工具每次執行都會印出**歸因保真度**，讓你看見它重現了多少實際帳單。
通常落在 99–101%。

完整的推導、每一步的取捨、以及我一開始算錯的三個地方，
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
