"""Build a tiny five-turn session with round numbers, for teaching and demos.

Real logs are the wrong place to learn the model from: the numbers are huge and
nothing lines up by hand. This writes a session small enough to verify on paper,
so the carry identity can be checked rather than believed.

    python examples/make_demo.py
    cc-token-audit audit --root examples/demo

The shape:

    turn 0   ctx 10,000   the standing context every turn will re-read
    turn 1   ctx 15,000   a 5,000-token file read
    turn 2   ctx 20,000   another 5,000
    turn 3   ctx 25,000   another 5,000
    turn 4   ctx 30,000   another 5,000 -- the last one, carried by nothing

Total cache reads: 0 + 10,000 + 15,000 + 20,000 + 25,000 = 70,000

And the identity reproduces exactly that, from the other direction:

    10,000 x 4 = 40,000     the standing context, re-read on all four later turns
     5,000 x 3 = 15,000     the turn-1 read
     5,000 x 2 = 10,000     the turn-2 read
     5,000 x 1 =  5,000     the turn-3 read
     5,000 x 0 =      0     the turn-4 read -- nothing follows it
                 -------
                  70,000

Same five thousand tokens, read at turn 1, costs fifteen thousand. Read at
turn 4, costs nothing. That is the whole idea.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "demo", "C--demo-project")

BASE = 10_000
STEP = 5_000
TURNS = 5
MODEL = "claude-opus-5"


def assistant(i, read, write, blocks):
    return {
        "type": "assistant",
        "timestamp": f"2026-09-20T10:{i:02d}:00Z",
        "isSidechain": False,
        "sessionId": "demo0001",
        "cwd": "/demo/project",
        "gitBranch": "main",
        "requestId": f"req_{i}",
        "message": {
            "id": f"msg_{i}",
            "model": MODEL,
            "role": "assistant",
            "content": blocks,
            "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": write,
                "cache_read_input_tokens": read,
                "output_tokens": 100,
                "output_tokens_details": {"thinking_tokens": 40},
                "cache_creation": {
                    "ephemeral_1h_input_tokens": write,
                    "ephemeral_5m_input_tokens": 0,
                },
            },
        },
    }


def tool_result(i, text):
    return {
        "type": "user",
        "timestamp": f"2026-09-20T10:{i:02d}:30Z",
        "isSidechain": False,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": text}]},
        "toolUseResult": {"stdout": text, "stderr": "", "interrupted": False},
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "demo0001.jsonl")
    records = []
    ctx = 0

    for i in range(TURNS):
        write = BASE if i == 0 else STEP
        read = ctx
        ctx += write
        blocks = [{"type": "tool_use", "id": f"t{i}", "name": "Read",
                   "input": {"file_path": f"/demo/project/file_{i}.py"}}]
        records.append(assistant(i, read, write, blocks))
        if i < TURNS - 1:
            # This result is what pushes the NEXT turn's context up by STEP, and
            # it has to carry the id of the call that was just made -- that is
            # how the tool and its target get attached to the cost.
            records.append(tool_result(i, "x" * (STEP * 4)))

    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    reads = sum(r["message"]["usage"]["cache_read_input_tokens"]
                for r in records if r["type"] == "assistant")
    print(f"wrote {path}")
    print(f"{TURNS} turns, context {BASE:,} -> {ctx:,}")
    print(f"total cache reads: {reads:,}")
    print()
    print("now run:  cc-token-audit audit --root examples/demo")


if __name__ == "__main__":
    main()
