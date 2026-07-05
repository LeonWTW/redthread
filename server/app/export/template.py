"""HTML rendering for report exports (M7 task 7.1).

Fully self-contained output: one document, inline CSS (screen + @media print),
no external requests. Two variants of the SAME template:
  - deliverable: footer "Prepared by RedThread — confidential" (PDF source).
  - public:      footer "Published with RedThread", citation anchors carry
                 rel="footnote" metadata, and the word "confidential" never
                 appears (GTM web variant).
In BOTH variants citation markers are internal anchors to the Evidence
appendix (#src-N).
"""

from __future__ import annotations

from jinja2 import Environment

_CSS = """
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  margin: 0;
  font-family: Georgia, "Times New Roman", "Songti SC", "Noto Serif CJK SC", serif;
  font-size: 16px;
  line-height: 1.65;
  color: #1c1a17;
  background: #fbfaf7;
}
.page { max-width: 70ch; margin: 0 auto; padding: 48px 24px 64px; }
h1, h2, h3, .wordmark, .week-of, .toc, .pill, .crossover, .decoder,
.source-num, .source-meta, .report-footer {
  font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
.zh {
  font-family: Georgia, "Songti SC", "Noto Serif CJK SC", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", serif;
}
a { color: inherit; }

/* Cover */
.cover { border-bottom: 2px solid #1c1a17; padding-bottom: 24px; margin-bottom: 40px; }
.wordmark {
  font-size: 13px; font-weight: 700; letter-spacing: 0.18em;
  text-transform: uppercase; color: #1c1a17;
}
.wordmark .red { color: #a02c2c; }
.report-title { font-size: 34px; line-height: 1.15; margin: 18px 0 6px; letter-spacing: -0.01em; }
.week-of { margin: 0 0 22px; color: #6f6759; font-size: 14px; letter-spacing: 0.02em; }
.toc-label {
  font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
  color: #8a8172; margin: 0 0 4px;
}
.toc ol { margin: 0; padding: 0; list-style: none; font-size: 13.5px; color: #4b463d; }
.toc li { display: flex; gap: 10px; padding: 2px 0; }
.toc-num { color: #a02c2c; font-weight: 600; min-width: 1.1em; }

/* Sections */
.section { margin: 36px 0; }
.section h2 {
  font-size: 15px; letter-spacing: 0.08em; text-transform: uppercase;
  border-top: 1px solid #d9d2c4; padding-top: 12px; margin: 0 0 14px;
  display: flex; gap: 10px;
}
.secnum { color: #a02c2c; }
.claim { margin: 0 0 12px; }
sup.cite { font-size: 0.68em; line-height: 0; }
sup.cite a {
  color: #a02c2c; text-decoration: none; font-weight: 600;
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
}
.empty { color: #8a8172; font-style: italic; font-size: 14px; margin: 0; }

/* Trend Radar */
.trend { margin: 0 0 30px; break-inside: avoid; page-break-inside: avoid; }
.trend h3 { font-size: 17px; margin: 0 0 6px; }
.trend-summary { margin: 0 0 12px; }
.crossover { width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 0 0 10px; }
.crossover caption {
  text-align: left; font-size: 11px; letter-spacing: 0.1em;
  text-transform: uppercase; color: #8a8172; padding: 0 0 6px;
}
.crossover th { text-align: left; width: 32%; font-weight: 600; }
.crossover th, .crossover td {
  border-top: 1px solid #e4ddcf; padding: 6px 12px 6px 0; vertical-align: top;
}
.verdict-line { margin: 0 0 12px; }
.pill {
  display: inline-block; font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 3px 12px; border-radius: 999px; border: 1px solid;
}
.pill-will_cross { color: #166534; background: #ecf7ef; border-color: #9fd6ad; }
.pill-wont_cross { color: #991b1b; background: #fbeeee; border-color: #e8b4b4; }
.pill-watch { color: #854d0e; background: #fdf6e3; border-color: #e5cf8f; }
.trend-claims { margin-left: 20px; padding-left: 14px; border-left: 2px solid #e4ddcf; }

/* Decoder */
.decoder { width: 100%; border-collapse: collapse; font-size: 14px; }
.decoder th {
  text-align: left; font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.08em; color: #8a8172;
  border-bottom: 1px solid #1c1a17; padding: 0 14px 6px 0;
}
.decoder td { border-bottom: 1px solid #e4ddcf; padding: 8px 14px 8px 0; vertical-align: top; }
.decoder td.zh { font-size: 15px; white-space: nowrap; }
.decoder td.muted { color: #6f6759; }

/* Evidence appendix */
.appendix { margin-top: 48px; border-top: 2px solid #1c1a17; padding-top: 16px; }
.appendix h2 {
  font-size: 15px; text-transform: uppercase; letter-spacing: 0.08em; margin: 0 0 16px;
}
.sources { list-style: none; margin: 0; padding: 0; }
.source {
  display: grid; grid-template-columns: 2.4em 1fr; column-gap: 6px;
  margin: 0 0 20px; break-inside: avoid; page-break-inside: avoid;
}
.source-num { color: #a02c2c; font-weight: 700; font-size: 13px; padding-top: 4px; }
.source .zh {
  grid-column: 2; margin: 0 0 6px; padding: 8px 12px;
  background: #f4f0e7; border-left: 3px solid #d9d2c4;
  line-height: 1.9; font-size: 15px;
}
.source .en { grid-column: 2; margin: 0 0 4px; font-size: 14px; color: #3d382f; }
.source-meta { grid-column: 2; margin: 0; font-size: 12px; color: #8a8172; }

/* Footer */
.report-footer {
  margin-top: 56px; padding-top: 14px; border-top: 1px solid #d9d2c4;
  font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; color: #8a8172;
}

/* Print */
@page { size: A4; margin: 18mm 16mm 20mm; }
@media print {
  body { background: #fff; color: #000; font-size: 11pt; }
  .page { max-width: none; margin: 0; padding: 0; }
  .section h2 { break-after: avoid; page-break-after: avoid; }
  .trend, .source, .decoder tr { break-inside: avoid; page-break-inside: avoid; }
  .appendix { break-before: page; page-break-before: always; }
  sup.cite a { color: #000; }
  .source .zh { background: #f4f0e7; }
}
"""

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{%- if public %}
<meta name="generator" content="RedThread">
{%- endif %}
<title>{{ report.title }}</title>
<style>{{ css }}</style>
</head>
<body>
<article class="page">
  <header class="cover">
    <div class="wordmark"><span class="red">Red</span>Thread</div>
    <h1 class="report-title">{{ report.title }}</h1>
    {%- if report.week_of_label %}
    <p class="week-of">{{ report.week_of_label }}</p>
    {%- endif %}
    <nav class="toc">
      <p class="toc-label">Contents</p>
      <ol>
      {%- for section in sections %}
        <li><span class="toc-num">{{ section.number }}</span> {{ section.title }}</li>
      {%- endfor %}
      </ol>
    </nav>
  </header>

  {%- for section in sections %}
  <section class="section" id="section-{{ section.key }}">
    <h2><span class="secnum">{{ section.number }}</span> {{ section.title }}</h2>
    {%- if section.key == "decoder" %}
    {%- if glossary %}
    <table class="decoder">
      <thead>
        <tr><th>中文 term</th><th>English rendering</th><th>Note</th></tr>
      </thead>
      <tbody>
      {%- for term in glossary %}
        <tr>
          <td class="zh">{{ term.term_zh }}</td>
          <td>{{ term.term_en }}</td>
          <td class="muted">{{ term.note or "" }}</td>
        </tr>
      {%- endfor %}
      </tbody>
    </table>
    {%- else %}
    <p class="empty">No glossary terms.</p>
    {%- endif %}
    {%- elif not section.blocks %}
    <p class="empty">No entries this week.</p>
    {%- else %}
    {%- for block in section.blocks %}
    {%- if block.type == "claim" %}
    <p class="claim">{{ block.text }}{{ block.cites_html|safe }}</p>
    {%- else %}
    <div class="trend">
      <h3>{{ block.title }}{{ block.title_cites_html|safe }}</h3>
      {%- if block.summary %}
      <p class="trend-summary">{{ block.summary }}{{ block.summary_cites_html|safe }}</p>
      {%- endif %}
      {%- if block.crossover %}
      <table class="crossover">
        <caption>Crossover Screen</caption>
        <tbody>
        {%- for row in block.crossover %}
          <tr><th>{{ row.label }}</th><td>{{ row.value }}</td></tr>
        {%- endfor %}
        </tbody>
      </table>
      {%- endif %}
      {%- if block.verdict %}
      <p class="verdict-line"><span class="pill pill-{{ block.verdict.key }}">{{ block.verdict.label }}</span></p>
      {%- endif %}
      {%- if block.children %}
      <div class="trend-claims">
        {%- for child in block.children %}
        <p class="claim">{{ child.text }}{{ child.cites_html|safe }}</p>
        {%- endfor %}
      </div>
      {%- endif %}
    </div>
    {%- endif %}
    {%- endfor %}
    {%- endif %}
  </section>
  {%- endfor %}

  <section class="appendix" id="evidence">
    <h2>Evidence</h2>
    {%- if sources %}
    <ol class="sources">
    {%- for source in sources %}
      <li id="src-{{ source.number }}" class="source">
        <div class="source-num">{{ source.number }}</div>
        {%- if source.zh %}
        <blockquote class="zh">{{ source.zh }}</blockquote>
        {%- endif %}
        {%- if source.en %}
        <p class="en">{{ source.en }}</p>
        {%- endif %}
        <p class="source-meta">
          {%- if source.captured_label %}Captured {{ source.captured_label }}{% endif %}
          {%- if source.note_id %} · XHS note {{ source.note_id }}{% endif -%}
        </p>
      </li>
    {%- endfor %}
    </ol>
    {%- else %}
    <p class="empty">No sources cited.</p>
    {%- endif %}
  </section>

  <footer class="report-footer">
    {%- if public %}
    Published with RedThread
    {%- else %}
    Prepared by RedThread — confidential
    {%- endif %}
  </footer>
</article>
</body>
</html>
"""

_env = Environment(autoescape=True)
_template = _env.from_string(_TEMPLATE)

VARIANTS = ("deliverable", "public")


def _cites_html(numbers: list[int], public: bool) -> str:
    """Superscript citation markers; consecutive markers comma-separated.

    Built in Python from integers only (injection-safe), marked |safe in the
    template so the anchor markup survives autoescaping. Numbering itself
    comes from queries.load_export_data — never recomputed here.
    """
    if not numbers:
        return ""
    rel = ' rel="footnote"' if public else ""
    links = ",".join(f'<a href="#src-{n}"{rel}>{n}</a>' for n in numbers)
    return f'<sup class="cite">{links}</sup>'


def render_report_html(data: dict, variant: str = "deliverable") -> str:
    if variant not in VARIANTS:
        raise ValueError(f"unknown export variant '{variant}'")
    public = variant == "public"

    def decorate_claim(block: dict) -> None:
        block["cites_html"] = _cites_html(block["cites"], public)

    for section in data["sections"]:
        for block in section.get("blocks", []):
            if block["type"] == "claim":
                decorate_claim(block)
                continue
            # Trend markers attach to the summary paragraph when there is
            # one, otherwise to the trend title line.
            markers = _cites_html(block["cites"], public)
            block["summary_cites_html"] = markers if block["summary"] else ""
            block["title_cites_html"] = "" if block["summary"] else markers
            for child in block["children"]:
                decorate_claim(child)

    return _template.render(
        report=data["report"],
        sections=data["sections"],
        glossary=data["glossary"],
        sources=data["sources"],
        public=public,
        css=_CSS,
    )
