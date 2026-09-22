"""Read Claude Code session logs into Sessions of Turns carrying Events.

Two things here are easy to get wrong and are the reason this module exists:

1. Assistant records are duplicated. One logical assistant message is written
   once per content block as the stream progresses, every copy carrying the
   same `message.usage`. Summing usage per line roughly doubles the bill.
   Turns are keyed on `message.id`.

2. What a turn is billed for is the whole context, not what just arrived. An
   Event is anything that entered context before a given turn; the carry
   engine is what turns those into money.
"""
import json
import os
from dataclasses import dataclass, field

DEFAULT_ROOT = os.path.join(os.path.expanduser("~"), ".claude", "projects")

# Rough chars-per-token for non-CJK text. CJK characters are counted as one
# token each: a Chinese message is ~1 token per character, code is ~4 chars per
# token, and sessions here mix both -- a flat divisor would blame code for
# tokens that Chinese text actually consumed. The split is proportional, so
# what matters is that the ratio between events is right, not the constant.
CHARS_PER_TOKEN = 4

_EMPTY_RESULT_MARKERS = (
    "no matches found", "no files found", "no content", "(no output)",
)


@dataclass
class Event:
    kind: str                 # tool_result | assistant_output | user_message | attachment | system
    approx: int               # estimated tokens, used only for proportional splitting
    tool: str = ""
    target: str = ""          # short handle for display (basename, clipped command)
    ok: bool = True
    key: str = ""             # full identifier for de-duplication (full path, full command)

    @property
    def label(self):
        if self.kind == "tool_result":
            return f"{self.tool}({self.target})" if self.target else self.tool
        return self.kind


@dataclass
class Turn:
    mid: str
    idx: int = 0
    ts: str = ""
    model: str = ""
    inp: int = 0
    write_5m: int = 0
    write_1h: int = 0
    read: int = 0
    out: int = 0
    thinking: int = 0
    sidechain: bool = False
    events: list = field(default_factory=list)
    out_chars: int = 0        # raw characters of assistant output
    out_est: int = 0          # estimated tokens of assistant output (CJK-aware)

    @property
    def ctx(self):
        """Context actually billed for this turn."""
        return self.inp + self.write_5m + self.write_1h + self.read

    @property
    def write(self):
        return self.write_5m + self.write_1h


@dataclass
class Session:
    path: str
    project: str
    session_id: str = ""
    cwd: str = ""
    branch: str = ""
    turns: list = field(default_factory=list)

    @property
    def main(self):
        return [t for t in self.turns if not t.sidechain]

    @property
    def side(self):
        return [t for t in self.turns if t.sidechain]

    @property
    def start(self):
        return self.turns[0].ts if self.turns else ""

    @property
    def end(self):
        return self.turns[-1].ts if self.turns else ""


def _is_cjk(ch):
    o = ord(ch)
    return (0x3000 <= o <= 0x9FFF or 0xAC00 <= o <= 0xD7AF
            or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF)


def _text(obj):
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


def _approx(obj):
    """Estimated tokens: CJK chars count 1 each, everything else ~4 chars/token."""
    text = _text(obj)
    cjk = sum(1 for ch in text if _is_cjk(ch))
    return cjk + (len(text) - cjk) // CHARS_PER_TOKEN


def _key(name, inp):
    """Full identifier of what a tool acted on, for de-duplication. Two files
    that share a basename in different directories must not collide."""
    if not isinstance(inp, dict):
        return ""
    for key in ("file_path", "notebook_path", "path"):
        if inp.get(key):
            return os.path.normcase(os.path.normpath(str(inp[key])))
    if inp.get("command"):
        return " ".join(str(inp["command"]).split())
    if inp.get("pattern"):
        scope = inp.get("path") or inp.get("glob") or ""
        return str(inp["pattern"]) + "@" + str(scope)
    if inp.get("url"):
        return str(inp["url"])
    return ""


def _target(name, inp):
    """A short human handle for what a tool acted on (display only)."""
    if not isinstance(inp, dict):
        return ""
    for key in ("file_path", "notebook_path", "path"):
        if inp.get(key):
            return os.path.basename(str(inp[key])) or str(inp[key])
    if inp.get("command"):
        return " ".join(str(inp["command"]).split())[:60]
    if inp.get("pattern"):
        return str(inp["pattern"])[:40]
    if inp.get("url"):
        return str(inp["url"])[:60]
    return ""


def _result_ok(block, tur):
    """False when a tool result carries no usable value: an error, an
    interruption, or an empty search. Such a result still occupies context for
    the rest of the session, which is what makes it worth counting."""
    if isinstance(block, dict) and block.get("is_error"):
        return False
    if isinstance(tur, dict):
        if tur.get("interrupted"):
            return False
        code = tur.get("returnCode", tur.get("exit_code"))
        if isinstance(code, int) and code != 0:
            return False
        if tur.get("stderr") and not tur.get("stdout"):
            return False
    text = ""
    if isinstance(tur, str):
        text = tur
    elif isinstance(block, dict):
        c = block.get("content")
        if isinstance(c, str):
            text = c
        elif c:
            text = json.dumps(c, ensure_ascii=False)
    head = text[:200].strip().lower()
    if not head:
        return True
    if head.startswith("error") or "<tool_use_error>" in head:
        return False
    return not any(m in head for m in _EMPTY_RESULT_MARKERS)


def parse_session(path, project=""):
    """Parse one .jsonl into a Session. Streams; never holds the whole file."""
    sess = Session(path=path,
                   project=project or os.path.basename(os.path.dirname(path)))
    tools = {}          # tool_use_id -> (name, target)
    pending = []        # events entering context before the next assistant turn
    cur = None

    def flush(turn):
        if turn is not None and turn.out_est:
            pending.append(Event("assistant_output", turn.out_est))

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            kind = rec.get("type")

            if kind == "assistant":
                msg = rec.get("message") or {}
                mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
                if cur is None or cur.mid != mid:
                    flush(cur)
                    u = msg.get("usage") or {}
                    cc = u.get("cache_creation") or {}
                    created = u.get("cache_creation_input_tokens", 0) or 0
                    w1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
                    w5m = cc.get("ephemeral_5m_input_tokens", 0) or 0
                    if not (w1h or w5m):        # older logs lack the breakdown
                        w5m = created
                    cur = Turn(
                        mid=mid, idx=len(sess.turns), ts=rec.get("timestamp", ""),
                        model=msg.get("model", ""),
                        inp=u.get("input_tokens", 0) or 0,
                        write_5m=w5m, write_1h=w1h,
                        read=u.get("cache_read_input_tokens", 0) or 0,
                        out=u.get("output_tokens", 0) or 0,
                        thinking=(u.get("output_tokens_details") or {}).get(
                            "thinking_tokens", 0) or 0,
                        sidechain=bool(rec.get("isSidechain")),
                        events=pending,
                    )
                    pending = []
                    sess.turns.append(cur)
                    sess.session_id = sess.session_id or rec.get("sessionId", "")
                    sess.cwd = sess.cwd or rec.get("cwd", "")
                    sess.branch = sess.branch or rec.get("gitBranch", "")
                else:
                    # The duplicate records are streaming snapshots, and
                    # `output_tokens` grows as generation proceeds -- the first
                    # copy reports only what had been produced when that block
                    # was written. The input side is fixed at request time and
                    # is identical in every copy, so only the output figures
                    # need to advance. Reading the first snapshot understated
                    # output by ~9.5% against ccusage.
                    u = msg.get("usage") or {}
                    cur.out = max(cur.out, u.get("output_tokens", 0) or 0)
                    cur.thinking = max(cur.thinking, (
                        u.get("output_tokens_details") or {}
                    ).get("thinking_tokens", 0) or 0)

                for blk in msg.get("content") or []:
                    if not isinstance(blk, dict):
                        continue
                    cur.out_chars += len(_text(blk))
                    cur.out_est += _approx(blk)
                    if blk.get("type") == "tool_use":
                        tools[blk.get("id")] = (
                            blk.get("name", "?"),
                            _target(blk.get("name"), blk.get("input")),
                            _key(blk.get("name"), blk.get("input")),
                        )
                continue

            if kind == "user":
                msg = rec.get("message") or {}
                tur = rec.get("toolUseResult")
                content = msg.get("content")
                if isinstance(content, list):
                    for blk in content:
                        if not isinstance(blk, dict):
                            continue
                        if blk.get("type") == "tool_result":
                            name, target, key = tools.pop(
                                blk.get("tool_use_id"), ("?", "", ""))
                            size = max(_approx(blk), _approx(tur))
                            pending.append(Event("tool_result", size, tool=name,
                                                 target=target, key=key,
                                                 ok=_result_ok(blk, tur)))
                        else:
                            pending.append(Event("user_message", _approx(blk)))
                elif content:
                    pending.append(Event("user_message", _approx(content)))
                continue

            if kind == "attachment":
                pending.append(Event("attachment", _approx(rec.get("attachment"))))
            elif kind == "system":
                pending.append(Event("system", _approx(rec.get("content"))))

    flush(cur)
    return sess


def walk(root=None, project=None, since=None):
    """Yield parsed Sessions under root, newest file first."""
    root = root or DEFAULT_ROOT
    found = []
    for base, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(base, fn)
            proj = os.path.basename(base)
            if project and project.lower() not in proj.lower():
                continue
            try:
                found.append((os.path.getmtime(path), path, proj))
            except OSError:
                continue
    for mtime, path, proj in sorted(found, reverse=True):
        if since is not None and mtime < since:
            continue
        sess = parse_session(path, proj)
        if sess.turns:
            yield sess
