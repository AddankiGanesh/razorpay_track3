"""Recover pre-Antigravity app.html (v0.8.3, 1684 lines) from Antigravity VIEW_FILE logs."""
import json
import re
from pathlib import Path

TRANSCRIPT = Path(
    r"C:\Users\ganes\.gemini\antigravity\brain"
    r"\ff02c478-cb44-4720-8fcf-d2fbfbf531a7"
    r"\.system_generated\logs\transcript.jsonl"
)
OUT = Path(__file__).resolve().parent.parent / "app" / "ui" / "app.html"

LINE_RE = re.compile(r"^(\d+):\s?(.*)$")


def extract_numbered_lines(content: str) -> dict[int, str]:
    lines: dict[int, str] = {}
    # Only parse the actual code block (after preamble line)
    marker = "The following code has been modified"
    idx = content.find(marker)
    if idx == -1:
        return lines
    block = content[idx:]
    for raw in block.splitlines():
        m = LINE_RE.match(raw.strip())
        if m:
            lines[int(m.group(1))] = m.group(2)
    return lines


def load_view(step_index: int) -> dict[int, str]:
    with TRANSCRIPT.open(encoding="utf-8") as f:
        for row in f:
            obj = json.loads(row)
            if obj.get("step_index") != step_index:
                continue
            if obj.get("type") != "VIEW_FILE":
                continue
            content = obj.get("content", "")
            if "app/ui/app.html" not in content:
                continue
            if "Total Lines: 1684" not in content:
                continue
            return extract_numbered_lines(content)
    return {}


def main() -> None:
    chunk1 = load_view(30)   # lines 1-800
    chunk2 = load_view(38)   # lines 1400-1684
    merged = {**chunk1, **chunk2}

    print(f"Chunk1: {len(chunk1)} lines ({min(chunk1) if chunk1 else 0}-{max(chunk1) if chunk1 else 0})")
    print(f"Chunk2: {len(chunk2)} lines ({min(chunk2) if chunk2 else 0}-{max(chunk2) if chunk2 else 0})")

    missing = [i for i in range(1, 1685) if i not in merged]
    print(f"Missing: {len(missing)} lines")
    if missing:
        print(f"  gap: {missing[0]}-{missing[-1]}")

    if len(merged) < 1600:
        raise SystemExit("Recovery incomplete — need middle chunk from Cursor transcript")

    text = "\n".join(merged[i] for i in sorted(merged)) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT} ({len(text)} bytes, {len(merged)} lines)")


if __name__ == "__main__":
    main()
