"""
PDF export of a report summary (Phase 11). Stateless: structured data in, PDF bytes out.

Contents: the results exactly as printed (value, unit, the lab's range and flag), AyuMitra's
comparison with that range, any evidence-backed explanations with their numbered sources, and the
disclaimer. Nothing new is generated here; it only lays out what was already validated.
"""

from __future__ import annotations

import html
from datetime import datetime

CSS = """
body { font-family: sans-serif; font-size: 10pt; color: #141c3d; }
h1 { font-size: 17pt; margin: 0 0 2pt 0; color: #0f6f75; }
h2 { font-size: 12pt; margin: 14pt 0 4pt 0; color: #141c3d; }
p { margin: 2pt 0; }
.muted { color: #5b6378; font-size: 8.5pt; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; font-size: 8.5pt; color: #5b6378; border-bottom: 1px solid #c9cfdc; padding: 3pt; }
td { border-bottom: 1px solid #e4e7ef; padding: 3pt; font-size: 9pt; }
.out { font-weight: bold; }
.cite { font-size: 8.5pt; color: #5b6378; margin-left: 8pt; }
.box { border: 1px solid #c9cfdc; padding: 6pt; margin-top: 6pt; }
"""

STATUS = {"above": "Above lab range", "below": "Below lab range", "within": "Within lab range",
          "matches": "Matches reference", "differs": "Differs from reference", "unknown": "Not compared"}


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""))


def build_html(data: dict) -> str:
    rows = []
    for p in data.get("parameters", []):
        status = p.get("range_status", "unknown")
        cls = ' class="out"' if status in ("above", "below") else ""
        rows.append(
            f"<tr><td{cls}>{_e(p.get('name_as_printed'))}</td><td{cls}>{_e(p.get('value_text'))} {_e(p.get('unit'))}</td>"
            f"<td>{_e(p.get('reference_range_text') or '-')}</td><td>{_e(p.get('lab_flag') or '-')}</td>"
            f"<td{cls}>{_e(STATUS.get(status, status))}</td></tr>"
        )
    parts = [
        f"<h1>AyuMitra AI: report summary</h1>",
        f"<p><b>{_e(data.get('title', 'Lab report'))}</b></p>",
        f"<p class='muted'>Report date: {_e(data.get('report_date') or 'not printed')} &nbsp;·&nbsp; "
        f"Exported: {datetime.now():%d %b %Y %H:%M}</p>",
        "<h2>Results (as printed by the laboratory)</h2>",
        "<table><tr><th>Test</th><th>Result</th><th>Lab reference range</th><th>Lab flag</th><th>Compared with lab range</th></tr>",
        *rows, "</table>",
        "<p class='muted'>'Lab flag' is what the laboratory printed. 'Compared with lab range' is AyuMitra's comparison "
        "with the laboratory's own printed range.</p>",
    ]
    for title, items in (("Explanations of results outside the range", data.get("explanations") or []),
                         ("Diet and lifestyle education", (data.get("education") or {}).get("items") or [])):
        answered = [i for i in items if (i.get("answer") or {}).get("status") == "answered"]
        if not answered:
            continue
        parts.append(f"<h2>{_e(title)}</h2>")
        for item in answered:
            ans = item["answer"]
            parts.append(f"<div class='box'><p><b>{_e(item.get('parameter'))}</b></p><p>{_e(ans.get('answer'))}</p>")
            for c in ans.get("citations", []):
                parts.append(f"<p class='cite'>[{_e(c.get('id'))}] {_e(c.get('title'))}, {_e(c.get('section'))}. "
                             f"{_e(c.get('url') or '')}</p>")
            parts.append("</div>")
    parts.append(
        "<h2>Important</h2><p class='muted'>AyuMitra AI provides general health information from trusted sources. "
        "It is not a diagnosis or a substitute for advice from your doctor or pharmacist. Values were read "
        "automatically from your document; check them against the original report.</p>"
    )
    return "\n".join(parts)


def render_report_pdf(data: dict) -> bytes:
    import io

    import fitz  # PyMuPDF

    story = fitz.Story(html=build_html(data), user_css=CSS)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    mediabox = fitz.paper_rect("a4")
    content = mediabox + (40, 40, -40, -40)
    more = True
    while more:  # flow the HTML across as many A4 pages as needed
        device = writer.begin_page(mediabox)
        more, _ = story.place(content)
        story.draw(device)
        writer.end_page()
    writer.close()
    doc = fitz.open(stream=buf.getvalue(), filetype="pdf")
    doc.set_metadata({"title": f"AyuMitra report summary: {data.get('title', '')}", "creator": "AyuMitra AI"})
    return doc.tobytes()
