"""Find middle chunk (801-1399) of app.html from Cursor transcript StrReplace chain."""
import json
import re
from pathlib import Path

TRANSCRIPT = Path(
    r"C:\Users\ganes\.cursor\projects\C-Users-ganes\agent-transcripts"
    r"\14947c77-e2d6-4808-b588-5c1f4a157579\14947c77-e2d6-4808-b588-5c1f4a157579.jsonl"
)

# Start from largest Write in transcript
best_write = ""
with TRANSCRIPT.open(encoding="utf-8") as f:
    for line in f:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", obj)
        content = msg.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for block in content:
            if block.get("type") != "tool_use":
                continue
            inp = block.get("input")
            if not isinstance(inp, dict):
                continue
            if "app/ui/app.html" not in inp.get("path", "").replace("\\", "/"):
                continue
            if inp.get("name") == "Write" or block.get("name") == "Write":
                s = inp.get("contents", "")
                if len(s) > len(best_write):
                    best_write = s

print("Base write:", len(best_write), "lines:", best_write.count(chr(10))+1)

# Apply all StrReplace operations in order
current = best_write
count = 0
with TRANSCRIPT.open(encoding="utf-8") as f:
    for line in f:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message", obj)
        content = msg.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for block in content:
            if block.get("type") != "tool_use":
                continue
            if block.get("name") not in ("StrReplace", None):
                continue
            inp = block.get("input")
            if not isinstance(inp, dict):
                continue
            if "app/ui/app.html" not in inp.get("path", "").replace("\\", "/"):
                continue
            old = inp.get("old_string", "")
            new = inp.get("new_string", "")
            if not old:
                continue
            if old in current:
                current = current.replace(old, new, 1)
                count += 1

print("Applied", count, "replacements")
print("Final size:", len(current), "lines:", current.count(chr(10))+1)
out = Path(__file__).resolve().parent.parent / "app" / "ui" / "app_rebuilt.html"
out.write_text(current, encoding="utf-8")
print("Wrote", out)
