"""Generate FINAL_PITCH_SCRIPT.pdf from FINAL_PITCH_SCRIPT.md"""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "FINAL_PITCH_SCRIPT.md"
PDF_PATH = ROOT / "FINAL_PITCH_SCRIPT.pdf"
FONT_REG = Path(r"C:\Windows\Fonts\segoeui.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\segoeuib.ttf")


class PitchPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Segoe", "", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"RevRecover Pitch Script  |  Page {self.page_no()}", align="C")


def clean_inline(text: str) -> str:
    text = text.replace("**", "").replace("*", "")
    text = text.replace("`", "")
    text = text.replace("→", "->")
    text = text.replace("…", "...")
    text = text.replace("—", "-")
    text = text.replace("⚡", "").replace("◎", "").replace("◉", "")
    return text.strip()


def write_pdf() -> Path:
    md = MD_PATH.read_text(encoding="utf-8")
    pdf = PitchPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    if FONT_REG.exists() and FONT_BOLD.exists():
        pdf.add_font("Segoe", "", str(FONT_REG))
        pdf.add_font("Segoe", "B", str(FONT_BOLD))
        body_font = "Segoe"
    else:
        body_font = "Helvetica"

    def write_block(text: str, *, size: int = 10, bold: bool = False, color=(60, 60, 60), indent: int = 0) -> None:
        text = clean_inline(text)
        if not text:
            return
        pdf.set_x(pdf.l_margin + indent)
        pdf.set_font(body_font, "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.multi_cell(pdf.epw - indent, 5, text)

    write_block("RevRecover - Final 5-Minute Pitch Script", size=18, bold=True, color=(20, 30, 50))
    pdf.ln(2)
    write_block("Deck: RevRecover_Beautiful_Pitch_Deck.pptx  |  Simple story format  |  ~5 minutes", size=10, color=(80, 90, 110))
    pdf.ln(4)

    in_code = False
    for raw in md.splitlines():
        line = raw.rstrip()

        if line.strip() == "---":
            pdf.ln(2)
            continue

        if line.strip().startswith("```"):
            in_code = not in_code
            continue

        if in_code:
            write_block(line, size=9, color=(40, 40, 40), indent=2)
            continue

        if not line.strip():
            pdf.ln(2)
            continue

        if line.startswith("# "):
            pdf.ln(3)
            write_block(line[2:], size=15, bold=True, color=(0, 120, 140))
            pdf.ln(1)
            continue

        if line.startswith("## "):
            pdf.ln(2)
            write_block(line[3:], size=12, bold=True, color=(30, 40, 60))
            pdf.ln(1)
            continue

        if line.startswith("> "):
            write_block(line[2:], size=11, color=(30, 30, 30), indent=4)
            continue

        if line.startswith("|") and "---" in line:
            continue

        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            write_block("  |  ".join(c for c in cells if c), size=9)
            continue

        if line.startswith("*Practice"):
            continue

        write_block(line, size=10)

    pdf.output(str(PDF_PATH))
    return PDF_PATH


if __name__ == "__main__":
    out = write_pdf()
    print(f"Created: {out} ({out.stat().st_size // 1024} KB)")
