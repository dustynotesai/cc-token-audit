# cc-token-audit

[繁體中文](README.zh-TW.md) | English

**ccusage tells you how much you spent. This tells you what spent it.**

Every tool in this space — [ccusage](https://github.com/ccusage/ccusage) and the
dashboards and menubar apps built on it — buckets your usage by time: today,
this week, this session. That answers *how much*. It cannot answer *why*, because
its data model has no notion of cause.

This one traces the bill backwards. It reads the same `~/.claude/projects/**/*.jsonl`
logs and decomposes your cache-read tokens back onto the individual moments when
something entered the context — a file read, a command's output, a failed grep —
then multiplies each by how many turns it was then carried for.

## Install

```bash
pip install git+https://github.com/dustynotesai/cc-token-audit.git
cc-token-audit audit
```

Or run it without installing anything:

```bash
git clone https://github.com/dustynotesai/cc-token-audit.git
cd cc-token-audit
python -m cc_token_audit audit
```

No dependencies. Python 3.9+. Nothing leaves your machine — it only reads
`~/.claude/projects/` and prints to your terminal.

Output defaults to Traditional Chinese; pass `--lang en` for English.

<details>
<summary>If <code>cc-token-audit</code> is not found after installing</summary>

The console script goes into your Python `Scripts/` (Windows) or `bin/`
directory, which may not be on `PATH`. `python -m cc_token_audit audit` always
works and needs no PATH change.
</details>

## The thing worth understanding

In agentic coding, almost all your tokens are cache reads. On a real 4.6-billion-token
history, 98.1% were:

```
cache read     4,507,338,257   98.1%
cache write       72,491,170    1.6%
output            12,700,490    0.3%
input                 49,352    0.0%
```

That is **not** waste. Re-reading the conversation is how the model has memory at
all, and a cached read costs a tenth of fresh input. Anyone telling you "98% of
your tokens are wasted" is misreading the number.

The real point is the multiplier. Context is billed *per turn*. Something added at
turn 5 of a 900-turn session gets paid for 895 more times. So the cost of a tool
result has almost nothing to do with its size and almost everything to do with
**when** it arrived:

```
       USD    tokens  re-read  entered at
    $16.33    56,296      560  turn 0      <- standing context
     $2.64     8,113      631  turn 820    <- a single bash command
```

That 8k-token command cost more than most 40k-token reads in the same session,
purely because of where it landed. This is the view no other tool gives you.

## The accounting

```
ctx(i)   = input + cache_creation + cache_read     billed context at turn i
delta(i) = ctx(i) - ctx(i-1)                       what entered before turn i

total cache_read  =  SUM  delta(i) x (turns that follow i)
```

Every number is derived from billed token counts, so the totals are exact. The
*split* of one delta across the several events that caused it is proportional to
their measured sizes, and therefore an estimate. The tool prints an **attribution
fidelity** figure on every run so you can see how much of the real bill it
reproduced — typically 99–101%.

Three things this gets right that a naive reading does not:

- **Assistant records are duplicated.** One logical message is written once per
  content block, every copy repeating the same `usage`. Summing per line roughly
  doubles the bill. Turns are keyed on `message.id`.
- **Compaction ends a segment.** After the context collapses, earlier history
  stops being billed. Ignoring this inflated an early measurement to 325%.
- **Sidechains are a separate context.** A subagent's reading never enters the
  main window, but its tokens are still billed.

## Commands

| | |
|---|---|
| `cc-token-audit audit` | the bill, what the carried context was made of, what looks avoidable, and what would have saved money |
| `cc-token-audit drill <session>` | one session, event by event, ranked by carry cost. Takes a path, a session id, or any substring |
| `cc-token-audit baseline` | the standing turn-0 block — system prompt, CLAUDE.md, MCP tool schemas — and what carrying it cost |

Options: `--project`, `--since 7d`, `--top N`, `--json`, `--oversized N`,
`--rebuild N`, `--root`, `--lang`. They work on either side of the subcommand.

## What it flags, and what it assumes

Every finding states its assumption, because "avoidable" is a judgement you
should be able to disagree with.

| category | what it counts |
|---|---|
| `duplicate-read` | reads after the first of the same tool+target in one conversation. Assumes the file had not changed. Edit/Write are excluded — touching a file repeatedly is normal work |
| `cache-churn` | cache writes beyond what context growth explains: content bought a second time after an entry expired, at the write rate |
| `oversized-result` | only the portion of a tool result above `--oversized` (default 10k tokens), as if the command had been paged or filtered |
| `failed-tool` | non-zero exits, error strings, interruptions, empty searches — nothing usable returned, then carried for the rest of the session |

## The savings model

`audit` replays your real context growth under different working habits. These
are replays, not guesses: the delta sequence is measured, and each restart is
charged for rebuilding context, so nothing is a free win. Baseline and scenarios
run through the same code path, so the difference is the policy and not the
model's error.

The result is not "clear your context more often". On one real history:

```
policy                                     would cost      saves
start a fresh session at 300k context       $1,697.88    $642.01    27%
start a fresh session at 500k context       $1,831.28    $508.61    22%
start a fresh session at 200k context       $2,101.89    $238.00    10%
start a fresh session at 150k context       $2,931.37   $-591.48   -25%  <- costs more
start a fresh session at 100k context       $7,856.83  $-5,516.94  -236%  <- costs more
```

There is a floor. Every restart rewrites the standing context, and a cache write
costs 20x a read — so restarting too eagerly is worse than never restarting. The
optimum on this history was around 300k, not as early as possible.

## Dollars

Figures are what the usage would cost at
[Claude API list rates](https://platform.claude.com/docs/en/about-claude/pricing)
(fetched 2026-09-22), including the details that are easy to miss: 1-hour cache
writes cost 2x base input rather than 1.25x, and Fable 5.1 reads at 0.025x
instead of the usual 0.1x.

**On a Pro/Max subscription you did not pay these amounts.** Read them as a
measure of how much work was done and of the relative size of each line, not as
a bill you owe. Rates live in `cc_token_audit/pricing.py`.

## Limits

- Splitting the turn-0 block into MCP schemas vs CLAUDE.md vs system prompt is
  not possible from the logs alone — the system prompt is not recorded. `baseline`
  measures the block exactly and says so; compare sessions run with different MCP
  servers connected to see the split.
- Event sizes are measured in characters and converted at 4 chars/token. Only the
  ratio between events matters, so the constant cancels, but a single event's
  attributed share is approximate.
- The savings replay does not simulate cache expiry, so it reproduces roughly 90%
  of the measured carried cost. Read its percentages, not its absolute dollars.

## Tests

```
python -m unittest discover -s tests
```

## Licence

MIT
