"""Interface strings, and CJK-aware column padding.

Chinese output is the default because the tool's audience is Chinese-speaking;
`--lang en` switches back. Code, identifiers and comments stay in English so
that the source is still readable to outside contributors.

The padding helpers matter more than they look: a CJK glyph occupies two
terminal cells but counts as one character, so plain f-string padding silently
skews every table that mixes scripts.
"""
import unicodedata

DEFAULT_LANG = "zh-TW"
LANGS = ("zh-TW", "en")

_WIDE = ("W", "F")


def width(s):
    """Display width of a string in terminal cells."""
    return sum(2 if unicodedata.east_asian_width(c) in _WIDE else 1 for c in s)


def pad(s, n, align="<"):
    """Pad to `n` display cells, counting CJK glyphs as two."""
    s = str(s)
    gap = max(0, n - width(s))
    if align == ">":
        return " " * gap + s
    if align == "^":
        left = gap // 2
        return " " * left + s + " " * (gap - left)
    return s + " " * gap


def clip(s, n):
    """Truncate to at most `n` display cells."""
    s = str(s)
    if width(s) <= n:
        return s
    out, used = [], 0
    for c in s:
        w = 2 if unicodedata.east_asian_width(c) in _WIDE else 1
        if used + w > n:
            break
        out.append(c)
        used += w
    return "".join(out)


STRINGS = {
    "zh-TW": {
        "title": "CLAUDE CODE TOKEN 稽核",
        "scanned": "{sessions:,} 個 session | {turns:,} 個 assistant turn | {span}",
        "fidelity": "歸因保真度 {pct:.1f}%  （這份報告能解釋掉多少實際的快取讀取帳單）",

        "bill_head": "帳單",
        "col_tokens": "tokens",
        "col_usd": "美元",
        "col_share": "佔比",
        "cache read": "快取讀取",
        "cache write": "快取寫入",
        "output": "輸出",
        "input": "輸入",
        "total": "總計",
        "bill_note": [
            "你有 {pct:.1f}% 的 token 是快取讀取。這是正常的，本身不是浪費——",
            "重讀 context 正是模型有記憶的方式，而快取讀取只要全新輸入的十分之一。",
            "真正該問的是：那裡面有多少，是在扛著早就沒用的東西。",
        ],

        "attr_head": "被扛著的 context 是由什麼組成的",
        "kind.assistant_output": "Claude 自己的回覆（含思考）",
        "kind.tool_result": "工具結果",
        "kind.base": "常駐 context（system + CLAUDE.md + MCP schema）",
        "kind.context_rebuild": "壓縮後重建的 context",
        "kind.attachment": "附件 / 注入的提醒",
        "kind.user_message": "你的訊息",
        "kind.system": "系統通知",
        "kind.unattributed": "無法歸因的成長",

        "waste_head": "看起來可以省掉的部分",
        "waste_none": "沒有超過回報門檻的項目。",
        "share_of_bill": "佔帳單 {pct:.1f}%",
        "assumes": "認定方式：",
        "carried_turns": "被扛了 {n} 個 turn",

        "cat.duplicate-read": "重複讀取",
        "cat.cache-churn": "快取重寫",
        "cat.oversized-result": "過大的工具輸出",
        "cat.failed-tool": "失敗的工具呼叫",

        "detail.duplicate-read": "{n} 次重複讀取已經在 context 裡的內容",
        "detail.cache-churn": "快取項目過期後，context 被重新寫入一次",
        "detail.oversized-result": "{n} 筆超過 {limit:,} tokens 的工具結果",
        "detail.failed-tool": "{n} 筆失敗／空結果的工具呼叫仍留在 context 裡",

        "assume.duplicate-read": "同一個 session 內，同樣的工具＋目標第二次以後的讀取；"
                                 "並假設檔案沒有變動",
        "assume.cache-churn": "超出 context 成長所能解釋的快取寫入；通常發生在 session "
                              "閒置超過 TTL 後又繼續使用",
        "assume.oversized-result": "只計算超過 {limit:,} tokens 的那一部分，"
                                   "當作原本就該分頁、過濾或加上 limit",
        "assume.failed-tool": "非零結束碼、錯誤訊息、被中斷、或搜尋無結果；"
                              "其全部攜帶成本都計入",

        "save_head": "怎麼做會比較省",
        "save_none": "測試過的策略都沒有比你現在的做法更省。",
        "save_scope": "本次模擬的攜帶成本：{usd}，涵蓋 {turns:,} 個主執行緒 turn。",
        "save_excluded": [
            "（輸出 token 與子代理執行緒不受這些策略影響，因此不計入下方基準。）",
        ],
        "save_accuracy": [
            "重播重現了實際攜帶成本 {usd} 的 {pct:.0f}%；差額來自它不模擬的快取重寫。",
            "請看百分比，不要看絕對金額。",
        ],
        "col_policy": "策略",
        "col_would_cost": "會花",
        "col_saves": "省下",
        "costs_more": "  <- 反而更貴",
        "policy.cap": "context 到 {k}k 就開新 session",
        "policy.slim": "把常駐 context 砍掉{name}",
        "slim.half": "一半",
        "slim.quarter": " 25%",
        "note.restarts": "總共重開 {n} 次，每次都要付重建最近 {turns} 個 turn 的成本",
        "note.slim": "少接幾個 MCP server，或把 CLAUDE.md 寫短一點",
        "save_method": [
            "以上是拿你真實的 context 成長、用同一套費率重播出來的，",
            "而且每次重開都已計入重建 context 的成本。",
            "基準與各策略跑的是同一段程式，所以差異來自策略本身，不是模型誤差。",
        ],
        "save_floor": [
            "重開得太勤反而更貴：每次重開都要重寫常駐 context，",
            "而一次快取寫入是快取讀取的 20 倍價。這裡有一個底，表格顯示了它在哪。",
        ],

        "top_head": "最貴的 session",
        "col_turns": "turns",
        "col_peak": "context 峰值",
        "col_project": "專案 / session",

        "drill_summary": "{main} 個主 turn，{side} 個子代理 turn",
        "drill_bill": "帳單 {usd}  |  保真度 {pct:.1f}%  |  {resets} 次 context 重置",
        "drill_peak": "context 峰值 {peak:,} tokens",
        "drill_head": "這個 context 裡最貴的東西",
        "col_reread": "被重讀",
        "col_entered": "進來的時機",
        "col_what": "是什麼",
        "turn_at": "turn {n}",

        "base_head": "常駐 CONTEXT（turn 0）",
        "base_intro": [
            "每個 session 一開場就扛著 system prompt、你的 CLAUDE.md，",
            "以及每一個已連線 MCP server 的工具 schema。這整包會在每一個 turn 被",
            "重讀一次，所以它的成本 = 它的大小 x 你的 turn 數。",
        ],
        "base_median": "turn-0 context 中位數",
        "base_range": "範圍",
        "base_total": "所有 session 扛著它的總成本",
        "base_half": "砍掉一半原本可以省下 {usd}",
        "col_base_cost": "這包的成本",
        "col_base_tok": "base tokens",
        "base_note": [
            "註：這裡精確量測了整包的大小。但要拆成 MCP schema、CLAUDE.md、",
            "system prompt 各佔多少，光靠 log 做不到——system prompt 不會寫進 log。",
            "想看出差別，可以比較連了不同 MCP server 的 session。",
        ],

        "footer_note": [
            "金額是這些用量換算成 Claude API 牌價的結果。",
            "如果你用的是 Pro / Max 訂閱，你並沒有實際付出這些錢——",
            "請把它當成「做了多少工」的量尺，以及各項目之間的相對大小，",
            "而不是一張你欠的帳單。",
        ],
        "footer_rates": "費率來源：platform.claude.com/docs/en/about-claude/pricing（2026-09-22）",

        "cli.desc": "把你的 Claude Code 快取讀取帳單，追回到究竟是什麼造成的。",
        "cli.epilog": (
            "ccusage 那類工具告訴你花了多少錢、什麼時候花的。\n"
            "這個工具問的是另一個問題：佔帳單絕大部分的快取讀取 token 裡，\n"
            "有哪些是在扛著早就沒用的東西。每個數字都能追回到實際計費的 token 數。\n"
        ),
        "cli.audit": "全歷史診斷與浪費排行",
        "cli.drill": "單一 session 的逐事件拆解",
        "cli.baseline": "每個 session 開場就背著的那包 context 的成本",
        "cli.session_arg": "路徑、session id，或兩者的任一片段",
        "cli.root": "log 目錄（預設 {default}）",
        "cli.project": "只看資料夾名稱含有這段文字的專案",
        "cli.since": "只看比這個時間新的 session，例如 7d、4w、12h",
        "cli.top": "每個表格顯示幾列（預設 12）",
        "cli.oversized": "工具結果超過這個大小，超出的部分會被標記",
        "cli.rebuild": "重開 session 時需要重建幾個 turn 的 context",
        "cli.json": "輸出機器可讀的 JSON",
        "cli.lang": "輸出語言：zh-TW（預設）或 en",
        "err.no_sessions": "在 {root} 底下找不到任何 session",
        "err.no_match": "找不到符合 {q} 的 session",
        "err.bad_since": "--since {spec} 格式錯誤；請用 7d、4w、12h 這種寫法",

        "cli.statusline": "給 Claude Code 狀態列用：即時顯示下一輪要花多少、何時該重開",
        "live.per_turn": "每輪 {usd}",
        "live.restart_now": "⚠ 重開撐 {n} 輪回本",
        "live.restart_soon": "重開撐 {n} 輪回本",
        "live.cache_cold": "快取 {mins} 分後過期，屆時重付 {usd}",
    },

    "en": {
        "title": "CLAUDE CODE TOKEN AUDIT",
        "scanned": "{sessions:,} sessions | {turns:,} assistant turns | {span}",
        "fidelity": "attribution fidelity {pct:.1f}%  "
                    "(how much of the real cache-read bill this explains)",

        "bill_head": "THE BILL",
        "col_tokens": "tokens",
        "col_usd": "USD",
        "col_share": "share",
        "cache read": "cache read",
        "cache write": "cache write",
        "output": "output",
        "input": "input",
        "total": "TOTAL",
        "bill_note": [
            "{pct:.1f}% of your tokens are cache reads. That is normal and not",
            "itself waste -- re-reading context is how an agent has memory, and",
            "a read costs a tenth of fresh input. The question is how much of it",
            "was carrying things that stopped being useful.",
        ],

        "attr_head": "WHAT THE CARRIED CONTEXT WAS MADE OF",
        "kind.assistant_output": "Claude's own replies (incl. thinking)",
        "kind.tool_result": "tool results",
        "kind.base": "standing context (system + CLAUDE.md + MCP schemas)",
        "kind.context_rebuild": "context rebuilt after compaction",
        "kind.attachment": "attachments / injected reminders",
        "kind.user_message": "your messages",
        "kind.system": "system notices",
        "kind.unattributed": "unattributed growth",

        "waste_head": "WHAT LOOKS AVOIDABLE",
        "waste_none": "Nothing above the reporting thresholds.",
        "share_of_bill": "{pct:.1f}% of bill",
        "assumes": "assumes:",
        "carried_turns": "carried {n} turns",

        "cat.duplicate-read": "duplicate-read",
        "cat.cache-churn": "cache-churn",
        "cat.oversized-result": "oversized-result",
        "cat.failed-tool": "failed-tool",

        "detail.duplicate-read": "{n} repeat reads of content already in context",
        "detail.cache-churn": "context re-written after cache entries expired",
        "detail.oversized-result": "{n} tool results over {limit:,} tokens",
        "detail.failed-tool": "{n} failed / empty tool results kept in context",

        "assume.duplicate-read": "counts every read after the first of the same "
                                 "tool+target in one conversation; assumes the "
                                 "file had not changed",
        "assume.cache-churn": "cache writes beyond what context growth explains; "
                              "happens when a session idles past its TTL and is "
                              "then resumed",
        "assume.oversized-result": "counts only the portion above {limit:,} tokens, "
                                   "as if the command had been paged, filtered or "
                                   "given a limit",
        "assume.failed-tool": "a non-zero exit, an error string, an interruption or "
                              "an empty search result; all of its carry cost is counted",

        "save_head": "WHAT WOULD HAVE SAVED MONEY",
        "save_none": "No policy tested beats what you already did.",
        "save_scope": "Carried-context cost being modelled: {usd} across "
                      "{turns:,} main-thread turns.",
        "save_excluded": [
            "(Output tokens and subagent threads are unaffected by these",
            " policies, so they are excluded from the baseline below.)",
        ],
        "save_accuracy": [
            "The replay reproduces {pct:.0f}% of the {usd} actually billed for",
            "carried context; the remainder is cache churn, which it does not",
            "simulate. Read the percentages, not the absolute dollars.",
        ],
        "col_policy": "policy",
        "col_would_cost": "would cost",
        "col_saves": "saves",
        "costs_more": "  <- costs more",
        "policy.cap": "start a fresh session at {k}k context",
        "policy.slim": "cut the standing turn-0 context by {name}",
        "slim.half": "half",
        "slim.quarter": "25%",
        "note.restarts": "{n} restarts in total, each paying to rebuild the "
                         "last {turns} turns",
        "note.slim": "fewer MCP servers connected, or a shorter CLAUDE.md",
        "save_method": [
            "These are replays of your real context growth at the same rates,",
            "including what it costs to rebuild context after each restart.",
            "Baseline and scenarios run through the same replay, so the",
            "difference is the policy and not the model's error.",
        ],
        "save_floor": [
            "Restarting too eagerly costs more than it saves: each restart",
            "rewrites the standing context, and a cache write is 20x the",
            "price of a read. There is a floor, and the table shows it.",
        ],

        "top_head": "MOST EXPENSIVE SESSIONS",
        "col_turns": "turns",
        "col_peak": "peak ctx",
        "col_project": "project / session",

        "drill_summary": "{main} main turns, {side} sidechain",
        "drill_bill": "bill {usd}  |  fidelity {pct:.1f}%  |  {resets} context resets",
        "drill_peak": "context peaked at {peak:,} tokens",
        "drill_head": "MOST EXPENSIVE THINGS PUT INTO THIS CONTEXT",
        "col_reread": "re-read",
        "col_entered": "entered at",
        "col_what": "what",
        "turn_at": "turn {n}",

        "base_head": "STANDING CONTEXT (turn 0)",
        "base_intro": [
            "Every session opens carrying the system prompt, your CLAUDE.md, and",
            "the tool schemas of every connected MCP server. That block is re-read",
            "on every single turn, so its cost is its size times your turn count.",
        ],
        "base_median": "median turn-0 context",
        "base_range": "range",
        "base_total": "carried across all sessions",
        "base_half": "cutting it in half would have saved {usd}",
        "col_base_cost": "cost of base",
        "col_base_tok": "base tok",
        "base_note": [
            "Note: this measures the block exactly. Splitting it into MCP schemas",
            "vs CLAUDE.md vs system prompt is not possible from the logs alone --",
            "compare sessions run with different MCP servers connected to see it.",
        ],

        "footer_note": [
            "Dollar figures are what this usage would cost at Claude API list",
            "rates. On a Pro/Max subscription you did not pay these amounts --",
            "read them as a measure of how much work was done, and of the",
            "relative size of each line, not as a bill you owe.",
        ],
        "footer_rates": "Rates: platform.claude.com/docs/en/about-claude/pricing "
                        "(2026-09-22)",

        "cli.desc": "Trace your Claude Code cache-read bill back to what caused it.",
        "cli.epilog": (
            "ccusage and the tools around it report how much you spent, bucketed\n"
            "by time. This one asks a different question: of the cache-read tokens\n"
            "that make up almost all of that bill, which were carrying something\n"
            "that had stopped being useful.\n"
        ),
        "cli.audit": "whole-history diagnosis and waste ranking",
        "cli.drill": "per-event breakdown of one session",
        "cli.baseline": "cost of the context every session starts with",
        "cli.session_arg": "path, session id, or any substring of either",
        "cli.root": "log directory (default {default})",
        "cli.project": "only projects whose folder name contains this",
        "cli.since": "only sessions newer than e.g. 7d, 4w, 12h",
        "cli.top": "rows per table (default 12)",
        "cli.oversized": "tool result size above which the excess is flagged",
        "cli.rebuild": "turns of context a restarted session must rebuild",
        "cli.json": "machine-readable output",
        "cli.lang": "output language: zh-TW (default) or en",
        "err.no_sessions": "no sessions found under {root}",
        "err.no_match": "no session matching {q}",
        "err.bad_since": "bad --since {spec}; use forms like 7d, 4w, 12h",

        "cli.statusline": "for the Claude Code status line: live cost per turn "
                          "and when restarting pays off",
        "live.per_turn": "{usd}/turn",
        "live.restart_now": "⚠ restart pays back in {n} turns",
        "live.restart_soon": "restart pays back in {n} turns",
        "live.cache_cold": "cache cold in {mins}m, then {usd} to rebuild",
    },
}

_lang = DEFAULT_LANG


def set_lang(lang):
    global _lang
    _lang = lang if lang in STRINGS else DEFAULT_LANG


def lang():
    return _lang


def join_label(label, text):
    """Join a label to its text. A full-width colon already carries its own
    trailing space, so adding another leaves a visible gap."""
    return label + ("" if label.endswith("：") else " ") + text


def t(key, **kw):
    """One line. Falls back to English, then to the key itself."""
    s = STRINGS[_lang].get(key)
    if s is None:
        s = STRINGS["en"].get(key, key)
    return s.format(**kw) if kw else s


def lines(key, **kw):
    """A block of lines."""
    block = STRINGS[_lang].get(key) or STRINGS["en"].get(key, [])
    return [ln.format(**kw) if kw else ln for ln in block]
