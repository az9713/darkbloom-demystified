"""Convert each .md under docs/ to a matching .html next to it (dark mode)."""
import pathlib
import re

import markdown

DOCS = pathlib.Path(__file__).resolve().parent / "docs"

# Simon's standard dark palette (global CLAUDE.md, 2026-08-13).
CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #0f172a; color: #cbd5e1;
  font: 16px/1.65 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 40px 24px 80px; }
h1, h2, h3 { color: #e2e8f0; line-height: 1.25; }
h1 { font-size: 1.9rem; border-bottom: 2px solid #334155; padding-bottom: 12px; }
h2 { font-size: 1.4rem; margin-top: 2.2em; border-bottom: 1px solid #1e293b; padding-bottom: 6px; }
h3 { font-size: 1.15rem; margin-top: 1.8em; }
a { color: #2dd4bf; text-decoration: none; }
a:hover { text-decoration: underline; }
strong { color: #e2e8f0; }
code { background: #1e293b; color: #fb923c; padding: 2px 6px; border-radius: 4px;
  font: 0.875em ui-monospace, "Cascadia Code", Consolas, monospace; }
pre { background: #1e293b; border: 1px solid #334155; border-radius: 8px;
  padding: 14px 16px; overflow-x: auto; }
pre code { background: none; padding: 0; color: #e2e8f0; }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; margin: 1.2em 0; font-size: 0.925rem; }
th, td { border: 1px solid #334155; padding: 8px 12px; text-align: left; vertical-align: top; }
th { background: #1e293b; color: #e2e8f0; }
tr:nth-child(even) td { background: rgba(30, 41, 59, 0.45); }
blockquote { border-left: 3px solid #fb923c; margin: 1em 0; padding: 4px 18px;
  color: #94a3b8; background: #1e293b; border-radius: 0 8px 8px 0; }
li { margin: 4px 0; }
hr { border: none; border-top: 1px solid #334155; margin: 2em 0; }
footer { margin-top: 60px; color: #94a3b8; font-size: 0.85rem;
  border-top: 1px solid #1e293b; padding-top: 16px; }
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<main>
{body}
<footer>Darkbloom explainer docs &middot; generated from <code>{src}</code> &middot; 2026-08-27</footer>
</main>
</body>
</html>
"""

md = markdown.Markdown(extensions=["tables", "fenced_code"])

count = 0
for src in sorted(DOCS.rglob("*.md")):
    text = src.read_text(encoding="utf-8")
    # Point relative doc links at the .html twin; leave externals alone.
    text = re.sub(r"\((?!https?://)([^)\s]+)\.md\)", r"(\1.html)", text)
    m = re.search(r"^# (.+)$", text, re.M)
    title = m.group(1) if m else src.stem
    md.reset()
    body = md.convert(text)
    # Wide tables scroll inside their own container, not the page.
    body = body.replace("<table>", '<div class="tablewrap"><table>')
    body = body.replace("</table>", "</table></div>")
    out = src.with_suffix(".html")
    out.write_text(
        TEMPLATE.format(title=title, css=CSS, body=body, src=src.name),
        encoding="utf-8",
    )
    count += 1
    print(f"{out.relative_to(DOCS)}  <-  {src.relative_to(DOCS)}")

print(f"{count} files converted")
assert count == 13, f"expected 13 md files, found {count}"
