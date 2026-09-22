# cc-token-audit

繁體中文 | [English](README.md)

**ccusage 告訴你花了多少錢。這個工具告訴你，錢是被什麼花掉的。**

這個領域現有的工具——[ccusage](https://github.com/ccusage/ccusage)，以及建構在它之上的
各種儀表板與選單列 app——都是把用量**按時間**分桶：今天、這週、這個 session。
那回答的是「多少」。它們回答不了「為什麼」，因為它們的資料模型裡根本沒有「成因」這個維度。

這個工具反過來追。它讀同一批 `~/.claude/projects/**/*.jsonl` log，
把你的快取讀取 token **逐一還原**到「當初是哪一個動作把東西塞進 context」——
某次讀檔、某條指令的輸出、某個搜尋不到東西的 grep——
再乘上它之後被扛了幾個 turn。

## 安裝

```bash
pip install git+https://github.com/dustynotesai/cc-token-audit.git
cc-token-audit audit
```

或者不安裝、直接跑：

```bash
git clone https://github.com/dustynotesai/cc-token-audit.git
cd cc-token-audit
python -m cc_token_audit audit
```

零相依套件。Python 3.9+。所有資料都留在你自己的機器上——
它只會讀 `~/.claude/projects/`，然後印到你的終端機。

輸出預設繁體中文，`--lang en` 可切換成英文。

<details>
<summary>如果安裝後找不到 <code>cc-token-audit</code> 指令</summary>

console script 會被放進 Python 的 `Scripts/`（Windows）或 `bin/` 目錄，
那個路徑不一定在你的 `PATH` 裡。
`python -m cc_token_audit audit` 永遠可用，也不需要動 PATH。
</details>

## 真正該理解的那件事

在 agentic coding 裡，你的 token 幾乎全部都是快取讀取。
以一份真實的 46 億 token 歷史來看，98.1% 是：

```
快取讀取        4,515,418,907   98.1%
快取寫入           72,576,883    1.6%
輸出               12,747,834    0.3%
輸入                   49,412    0.0%
```

這**不是**浪費。重讀對話正是模型有記憶的唯一方式，而且快取讀取只要全新輸入的十分之一。
任何人跟你說「你 98% 的 token 都浪費掉了」，都是在誤讀這個數字。

真正的重點是**乘數**。context 是**按每個 turn** 計費的。
在一個 900 turn 的 session 裡，第 5 個 turn 加進去的東西，之後還要再被收費 895 次。
所以一筆工具結果的成本，幾乎跟它的大小無關，而幾乎完全取決於它**什麼時候**進來：

```
      美元    tokens   被重讀  進來的時機
    $16.33    56,296      560  turn 0      <- 常駐 context
     $2.64     8,113      631  turn 820    <- 一條 bash 指令
```

那條 8k token 的指令，比同一個 session 裡多數 40k 的讀檔還貴，
純粹因為它落在什麼位置。這是其他工具給不了你的視角。

## 會計方法

```
ctx(i)   = input + cache_creation + cache_read     turn i 實際被計費的 context
delta(i) = ctx(i) - ctx(i-1)                       turn i 之前進來了什麼

總快取讀取  =  Σ  delta(i) × (它之後還有幾個 turn)
```

所有數字都從實際計費的 token 數推導而來，所以總量是**精確**的。
把單一筆 delta **拆分**給造成它的數個事件時，是按各自的實測大小等比例分配，
因此那一步是**估計**。工具每次執行都會印出**歸因保真度**，
讓你看見它重現了多少實際帳單——通常落在 99–101%。

三件天真的寫法會做錯、而這裡有處理的事：

- **assistant 記錄是重複的。** 一則邏輯上的訊息，會依 content block 數量被寫好幾次，
  每一份都重複同樣的 `usage`。逐行加總大約會讓帳單翻倍。這裡以 `message.id` 為準。
- **壓縮會結束一個區段。** context 崩落之後，先前的歷史就不再被計費。
  忽略這點會讓早期的量測值膨脹到 325%。
- **sidechain 是獨立的 context。** 子代理讀的東西不會進入主視窗，但它的 token 一樣要付錢。

## 指令

| | |
|---|---|
| `cc-token-audit audit` | 帳單、被扛著的 context 由什麼組成、哪些看起來可以省、以及怎麼做會比較省 |
| `cc-token-audit drill <session>` | 單一 session 的逐事件拆解，依攜帶成本排序。可傳路徑、session id，或任一片段 |
| `cc-token-audit baseline` | 常駐的 turn-0 那一包——system prompt、CLAUDE.md、MCP 工具 schema——以及扛著它的成本 |

選項：`--project`、`--since 7d`、`--top N`、`--json`、`--oversized N`、
`--rebuild N`、`--root`、`--lang`。放在子指令前後都可以。

## 它會標記什麼，以及它的認定方式

每一項發現都會說明自己的認定方式，因為「可以省」是一種判斷，你應該有辦法不同意它。

| 類別 | 計算方式 |
|---|---|
| `重複讀取` | 同一 session 內，同樣工具＋目標第二次以後的讀取。假設檔案沒有變動。Edit/Write 不算——反覆修改同一個檔案是正常工作 |
| `快取重寫` | 超出 context 成長所能解釋的快取寫入：快取項目過期後，同樣的內容以寫入價再買一次 |
| `過大的工具輸出` | 只計算工具結果超過 `--oversized`（預設 10k tokens）的那一部分，當作原本就該分頁或過濾 |
| `失敗的工具呼叫` | 非零結束碼、錯誤訊息、被中斷、搜尋無結果——什麼有用的都沒回傳，卻被扛了一整個 session |

## 節省模擬

`audit` 會拿你**真實的** context 成長，在不同工作習慣下重播一次。
這是重播，不是猜測：delta 序列是實測的，而且每次重開都要付重建 context 的成本，
所以沒有任何一項是免費的午餐。基準與各策略跑的是同一段程式碼，
因此差異來自策略本身，不是模型誤差。

結論**不是**「多清空 context」。在一份真實歷史上：

```
策略                                             會花       省下
context 到 300k 就開新 session               $1,698.95   $642.01    27%
context 到 500k 就開新 session               $1,832.35   $508.61    22%
context 到 200k 就開新 session               $2,102.67   $238.29    10%
context 到 150k 就開新 session               $2,935.63  $-591.98   -25%  <- 反而更貴
context 到 100k 就開新 session               $7,882.65 $-5,539.00  -236%  <- 反而更貴
```

**這裡有一個底。** 每次重開都要重寫常駐 context，而一次快取寫入是快取讀取的 **20 倍價**——
所以重開得太勤，比從不重開還糟。在這份歷史上，最佳點大約在 300k，而不是越早越好。

## 金額

金額是把用量換算成
[Claude API 牌價](https://platform.claude.com/docs/en/about-claude/pricing)
的結果（費率擷取於 2026-09-22），包含幾個容易漏掉的細節：
1 小時 TTL 的快取寫入是基礎輸入價的 **2 倍**（不是 1.25 倍），
而 Fable 5.1 的快取讀取是 **0.025 倍**（不是一般的 0.1 倍）。

**如果你用的是 Pro / Max 訂閱，你並沒有實際付出這些錢。**
請把它當成「做了多少工」的量尺，以及各項目之間的相對大小，而不是一張你欠的帳單。
費率定義在 `cc_token_audit/pricing.py`。

## 限制

- turn-0 那一包無法只靠 log 拆成 MCP schema / CLAUDE.md / system prompt——
  system prompt 不會被寫進 log。`baseline` 精確量測整包的大小並明講這條限制；
  想看出差別，可以比較連了不同 MCP server 的 session。
- 事件大小以字元數量測、以 4 字元／token 換算。因為只有事件之間的**比例**有意義，
  這個常數會相消，但單一事件被分到的那一份仍然是近似值。
- 節省模擬不模擬快取過期，因此它只重現了實測攜帶成本的約 90%。
  **請看它的百分比，不要看它的絕對金額。**

## 測試

```
python -m unittest discover -s tests
```

## 授權

MIT
