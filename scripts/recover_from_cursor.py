"""Extract full app.html from Cursor agent transcript."""
import json
import re
from pathlib import Path

TRANSCRIPT = Path(
    r"C:\Users\ganes\.cursor\projects\C-Users-ganes\agent-transcripts"
    r"\14947c77-e2d6-4808-b588-5c1f4a157579\14947c77-e2d6-4808-b588-5c1f4a157579.jsonl"
)
OUT = Path(__file__).resolve().parent.parent / "app" / "ui" / "app_from_cursor.html"

TARGET = "revrecover-ui-version"
MARKERS = ("loadCharts", "loadIntelligencePanels", "0.8.3")


def main() -> None:
    best = ("", 0, "")
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
                p = inp.get("path", "")
                if "app/ui/app.html" not in p.replace("\\", "/"):
                    continue
                for key in ("contents", "new_string"):
                    s = inp.get(key, "")
                    if not s or len(s) < 5000:
                        continue
                    if not s.lstrip().startswith("<!DOCTYPE") and not s.lstrip().startswith("<html"):
                        continue
                    score = len(s)
                    if all(m in s for m in MARKERS):
                        score += 100000
                    if TARGET in s:
                        score += 10000
                    if score > best[1]:
                        best = (key, score, s)

    print("best source:", best[0], "score:", best[1], "len:", len(best[2]))
    if best[2]:
        OUT.write_text(best[2], encoding="utf-8")
        lines = best[2].count("\n") + 1
        print(f"Wrote {OUT} ({len(best[2])} bytes, ~{lines} lines)")


if __name__ == "__main__":
    main()
