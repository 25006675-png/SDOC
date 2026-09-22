"""Build the SDOC architecture diagram: a self-contained HTML page and a PNG.

    python docs/architecture/build.py

Brand logos come from Simple Icons (logos/*.svg) and the landing page's
mail and file icons; everything is embedded so the HTML opens anywhere.
"""
import base64
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ICONS = ROOT / "sdoc-landing" / "assets" / "icons"

BRAND = {  # Simple Icons slug -> brand colour
    "render": "#000000", "fastapi": "#009688", "supabase": "#3FCF8E",
    "googlegemini": "#8E75B2", "docker": "#2496ED", "postgresql": "#4169E1", "python": "#3776AB",
}


def svg_logo(slug, size=22):
    path = re.search(r'<path d="([^"]+)"', (HERE / "logos" / f"{slug}.svg").read_text(encoding="utf-8")).group(1)
    return (f'<svg class="logo" width="{size}" height="{size}" viewBox="0 0 24 24" aria-hidden="true">'
            f'<path fill="{BRAND[slug]}" d="{path}"/></svg>')


def img_logo(name, size=22):
    data = (ICONS / name).read_bytes()
    kind = "webp" if name.endswith(".webp") else "png"
    return (f'<img class="logo" width="{size}" height="{size}" alt="" '
            f'src="data:image/{kind};base64,{base64.b64encode(data).decode()}">')


def file_logo(name, size=28):
    from io import BytesIO
    from PIL import Image
    im = Image.open(ICONS / name).convert("RGBA")
    im.thumbnail((size * 4, size * 4), Image.LANCZOS)
    buf = BytesIO(); im.save(buf, "PNG")
    return (f'<img class="logo" width="{size}" height="{size}" alt="" style="object-fit:contain;border-radius:6px" '
            f'src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}">')


SDOC_MARK = ('<svg class="logo" width="26" height="26" viewBox="0 0 64 64" aria-hidden="true"><rect width="64" height="64" rx="16" fill="#e8892a"/>'
             '<path d="M15 15h15v15H15zM34 15h15v15H34zM15 34h15v15H15zM34 34h15v15H34z" stroke="#fff" fill="none" stroke-width="4"/>'
             '<path d="M25 25h14v14H25z" fill="#fff"/></svg>')

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>SDOC architecture</title>
<style>
  :root { --navy: #1f3864; --blue: #2f5597; --blue-soft: #eef3fb; --grey: #f2f2f2; --grey-line: #b7b7b7;
          --orange: #ed7d31; --ink: #1c2433; --muted: #5d6675; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #fff; font-family: "Segoe UI", Inter, Arial, sans-serif; color: var(--ink); }
  .canvas { position: relative; width: 1920px; height: 1080px; padding: 104px 56px; }
  svg.wires { position: absolute; inset: 0; z-index: 5; width: 100%; height: 100%; pointer-events: none; overflow: visible; }
  header { display: flex; align-items: center; gap: 14px; margin-bottom: 26px; }
  header h1 { margin: 0; font-size: 34px; font-weight: 800; font-style: italic; letter-spacing: -.02em; }
  header p { margin: 0 0 0 18px; padding-left: 18px; border-left: 2px solid #dde3ec; color: var(--muted); font-size: 17px; }
  .layout { display: grid; grid-template-columns: 300px 1fr 360px; gap: 64px; align-items: start; }
  .col-title { margin: 0 0 12px; color: var(--muted); font-size: 13px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
  .card { position: relative; display: flex; align-items: center; gap: 12px; padding: 17px 18px; border-radius: 10px; font-size: 17px; font-weight: 600; }
  .card small { display: block; margin-top: 2px; font-size: 13px; font-weight: 500; opacity: .8; }
  .logo { flex: none; display: block; }
  .source { background: var(--grey); border: 1.5px solid var(--grey-line); color: #444; margin-bottom: 18px; }
  .source .logo-tile { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 9px; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.08); }
  .step { background: var(--blue); color: #fff; }
  .step.dark { background: var(--navy); }
  .step.ai { background: #fff; color: var(--navy); border: 2px solid var(--orange); }
  .step .num { display: grid; place-items: center; flex: none; width: 26px; height: 26px; border-radius: 50%; background: rgba(255,255,255,.18); font-size: 13px; font-weight: 800; }
  .step.ai .num { background: #fdeee3; color: #b4561a; }
  .render { position: relative; padding: 18px 22px 22px; border: 2px dashed #9fb3d6; border-radius: 16px; background: linear-gradient(180deg, #f7f9fd, #fff 40%); }
  .render-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; color: var(--navy); font-size: 15px; font-weight: 700; }
  .render-head .tag { margin-left: auto; display: flex; align-items: center; gap: 8px; padding: 5px 12px; border-radius: 999px; background: #fff; border: 1px solid #d6dfee; font-size: 13px; font-weight: 600; color: var(--muted); }
  .api { margin-bottom: 32px; justify-content: center; font-size: 19px; }
  .api .logo-tile { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 8px; background: #fff; }
  .pipeline { display: grid; grid-template-columns: 1fr 1fr; column-gap: 70px; row-gap: 34px; }
  .pipeline > div { display: grid; row-gap: 34px; align-content: start; }
  .sandbox { padding: 12px; border: 2px dashed var(--orange); border-radius: 12px; background: #fffaf6; }
  .sandbox-label { display: flex; align-items: center; justify-content: space-between; margin: 0 2px 10px; color: #b4561a; font-size: 12.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
  .filetypes { display: flex; gap: 6px; margin-left: auto; }
  .filetypes span { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 7px; background: #fff; }
  .states { display: flex; flex-wrap: nowrap; gap: 5px; margin-top: 8px; }
  .states i { font-style: normal; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; background: #fff; }
  .s-ok { color: #26734a; } .s-diff { color: #99511a; } .s-rev { color: #69509c; } .s-stall { color: #a2362e; } .s-wait { color: #54626a; }
  .apps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 34px; padding-top: 24px; border-top: 1px solid #dde3ec; }
  .apps .card { justify-content: center; text-align: center; }
  .apps-label { grid-column: 1 / -1; margin: -6px 0 0; color: var(--muted); font-size: 13px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
  .ext { margin-bottom: 22px; }
  .ext .logo-tile { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 10px; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.1); }
  .gemini { background: #fff; color: var(--navy); border: 2px solid var(--orange); }
  .supabase { background: var(--navy); color: #fff; }
  .people { background: var(--blue-soft); color: var(--navy); border: 1.5px solid #c9d6ec; }
  .legend { position: absolute; left: 56px; bottom: 34px; display: flex; gap: 28px; color: var(--muted); font-size: 13.5px; }
  .legend span { display: inline-flex; align-items: center; gap: 8px; }
  .legend b { display: inline-block; width: 26px; height: 14px; border-radius: 4px; }
</style></head>
<body><div class="canvas" id="canvas">
  <svg class="wires" id="wires">
    <defs>
      <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="#2f5597"/></marker>
      <marker id="arrow-ai" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="#ed7d31"/></marker>
    </defs>
  </svg>
  <div class="layout">
    <section>
      <p class="col-title">Mail sources</p>
      <div class="card source" id="gmail"><span class="logo-tile">__GMAIL__</span><span>Gmail<small>Gmail API · OAuth</small></span></div>
      <div class="card source" id="outlook"><span class="logo-tile">__OUTLOOK__</span><span>Outlook<small>Microsoft Graph · OAuth</small></span></div>
      <div class="card source" id="dataset"><span class="logo-tile">__PYTHON__</span><span>Organizer dataset<small>Hackathon bundle / Docker server</small></span></div>
      <p class="col-title" style="margin-top:34px">People</p>
      <div class="card people" id="people"><span>Documentation team<small>Workers review · admins monitor</small></span></div>
    </section>

    <section class="render" id="render">
      <div class="render-head">__RENDER__ Render web service <span class="tag">__DOCKER__ Docker · Python 3.12 · Tesseract OCR</span></div>
      <div class="card step dark api" id="api"><span class="logo-tile">__FASTAPI__</span>FastAPI backend</div>
      <div class="pipeline">
        <div>
          <div class="card step" id="s1"><span class="num">1</span><span>Mailbox sync<small>Every 60 s · new mail with attachments</small></span></div>
          <div class="card step ai" id="s2"><span class="num">2</span><span>Classification + case engine<small>Rules + Gemini · grouped by shipment reference</small></span></div>
          <div class="card step" id="s3"><span class="num">3</span><span>Security gate<small>Type, size, encryption, pages · before any parsing</small></span></div>
          <div class="sandbox" id="s4">
            <div class="sandbox-label">Isolated reader processes <span class="filetypes"><span>__PDF__</span><span>__WORD__</span><span>__EXCEL__</span></span></div>
            <div class="card step"><span class="num">4</span><span>Document processing<small>PDF · DOCX · XLSX · OCR fallback · timeout per file</small></span></div>
          </div>
        </div>
        <div>
          <div class="card step" id="s5"><span class="num">5</span><span>Validation + targeted retry<small>Structure check · one bounded recovery</small></span></div>
          <div class="card step ai" id="s6"><span class="num">6</span><span>Independent verification<small>DeepSeek second read · blind to pass 1</small></span></div>
          <div class="card step" id="s7"><span class="num">7</span><span>Deterministic comparison<small>7 fields · business rules and tolerances</small></span></div>
          <div class="card step dark" id="s8"><span class="num">8</span><span>Case decision + evidence
            <span class="states"><i class="s-ok">Verified</i><i class="s-diff">Discrepancy</i><i class="s-rev">Needs review</i><i class="s-stall">Blocked</i><i class="s-wait">Waiting</i></span></span></div>
        </div>
      </div>
      <div class="apps">
        <p class="apps-label">Served from the same service</p>
        <div class="card step" id="landing">Landing page</div>
        <div class="card step dark" id="worker">Worker dashboard</div>
        <div class="card step dark" id="admin">Admin dashboard</div>
      </div>
    </section>

    <section>
      <p class="col-title">External services</p>
      <div class="card ext gemini" id="gemini"><span class="logo-tile">__GEMINI__</span><span>Google Gemini API<small>Email classification · daily spend cap</small></span></div>
      <div class="card ext gemini" id="deepseek"><span class="logo-tile">__DEEPSEEK__</span><span>DeepSeek API<small>Independent verification read</small></span></div>
      <div class="card ext supabase" id="supabase"><span class="logo-tile">__SUPABASE__</span><span>Supabase<small>PostgreSQL · cases, evidence, audit log, mailbox tokens</small></span></div>
    </section>
  </div>
  <div class="legend">
    <span><b style="background:#2f5597"></b>Deterministic step</span>
    <span><b style="background:#fff;border:2px solid #ed7d31"></b>AI-assisted step</span>
    <span><b style="background:#fffaf6;border:2px dashed #ed7d31"></b>Isolated process</span>
    <span><b style="background:#f2f2f2;border:1.5px solid #b7b7b7"></b>Source</span>
  </div>
</div>
<script>
  // Orthogonal connectors drawn from the laid-out boxes, so edits to the
  // labels never leave an arrow pointing at the wrong place.
  const svg = document.getElementById('wires');
  const canvas = document.getElementById('canvas').getBoundingClientRect();
  const box = id => { const r = document.getElementById(id).getBoundingClientRect();
    return { l: r.left - canvas.left, r: r.right - canvas.left, t: r.top - canvas.top, b: r.bottom - canvas.top,
             cx: (r.left + r.right) / 2 - canvas.left, cy: (r.top + r.bottom) / 2 - canvas.top }; };
  function wire(points, ai, dashed) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', 'M' + points.map(([x, y]) => x + ' ' + y).join(' L'));
    p.setAttribute('fill', 'none'); p.setAttribute('stroke', ai ? '#ed7d31' : '#2f5597');
    p.setAttribute('stroke-width', '2.5'); p.setAttribute('stroke-linejoin', 'round');
    if (dashed) p.setAttribute('stroke-dasharray', '7 6');
    p.setAttribute('marker-end', ai ? 'url(#arrow-ai)' : 'url(#arrow)');
    svg.append(p);
  }
  const down = (a, b) => { const A = box(a), B = box(b); wire([[A.cx, A.b], [B.cx, B.t - 2]]); };
  // Sources into the backend.
  const api = box('api'), bus = api.l - 34;
  ['gmail', 'outlook', 'dataset'].forEach(id => { const S = box(id); wire([[S.r, S.cy], [bus, S.cy], [bus, api.cy], [api.l - 2, api.cy]]); });
  // Backend into the pipeline, then down each column and across.
  const s1 = box('s1'); wire([[s1.cx, api.b], [s1.cx, s1.t - 2]]);
  down('s1', 's2'); down('s2', 's3'); down('s3', 's4');
  const s4 = box('s4'), s5 = box('s5'), mid = (s4.r + s5.l) / 2;
  wire([[s4.r, s4.cy], [mid, s4.cy], [mid, s5.cy], [s5.l - 2, s5.cy]]);
  down('s5', 's6'); down('s6', 's7'); down('s7', 's8');
  // AI steps call Gemini.
  const gem = box('gemini'), render = box('render'), lane = render.r + 30;
  // Step 2 leaves through the column gap and runs under the FastAPI bar, so
  // no arrow crosses a box; step 6 leaves straight out of the right side.
  const s2 = box('s2'), s6 = box('s6'), gapX = s2.r + 16, under = (api.b + s1.t) / 2;
  wire([[s2.r, s2.cy], [gapX, s2.cy], [gapX, under], [lane, under], [lane, gem.cy], [gem.l - 2, gem.cy]], true, true);
  const deep = box('deepseek');
  wire([[s6.r, s6.cy], [lane - 14, s6.cy], [lane - 14, deep.cy], [deep.l - 2, deep.cy]], true, true);
  // Decisions persist to Supabase; the dashboards read them back.
  const s8 = box('s8'), sup = box('supabase');
  wire([[s8.r, s8.cy], [lane + 10, s8.cy], [lane + 10, sup.cy], [sup.l - 2, sup.cy]]);
  const worker = box('worker'), admin = box('admin');
  wire([[sup.cx, sup.b], [sup.cx, admin.cy], [admin.r + 2, admin.cy]]);
  // People use the dashboards.
  const people = box('people'), landing = box('landing'), y = render.b + 26;
  wire([[people.cx, people.b], [people.cx, y], [worker.cx, y], [worker.cx, worker.b + 2]]);
</script>
</body></html>
"""

html = (HTML
        .replace("__GMAIL__", img_logo("gmail.webp", 26))
        .replace("__OUTLOOK__", img_logo("outlook.webp", 26))
        .replace("__PDF__", img_logo("pdf.png", 20))
        .replace("__WORD__", img_logo("word.png", 20))
        .replace("__EXCEL__", img_logo("excel.webp", 20))
        .replace("__PYTHON__", svg_logo("python", 24))
        .replace("__RENDER__", file_logo("render-icon-filled-256.png", 22))
        .replace("__DEEPSEEK__", file_logo("DeepSeek-icon.svg.webp", 30))
        .replace("__DOCKER__", svg_logo("docker", 16))
        .replace("__FASTAPI__", svg_logo("fastapi", 24))
        .replace("__GEMINI__", file_logo("Google_Gemini_icon_2025.svg.webp", 30))
        .replace("__SUPABASE__", file_logo("supabase.jpg", 30)))
out = HERE / "architecture.html"
out.write_text(html, encoding="utf-8")
print("wrote", out)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
    page.goto(out.as_uri())
    page.wait_for_timeout(300)
    page.screenshot(path=str(HERE / "architecture.png"), clip={"x": 0, "y": 0, "width": 1920, "height": 1080})
    browser.close()
print("wrote", HERE / "architecture.png")
