#!/usr/bin/env python3
"""
Project Titan: Cindy Pawford Digital Museum Portal Generator
Deterministically compiles apps/cindypawford/archive/index.html from eras.json and recaps.
"""

import os
import json
import html

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARCHIVE_DIR = os.path.join(REPO_ROOT, "apps", "cindypawford", "archive")
ERAS_JSON_PATH = os.path.join(ARCHIVE_DIR, "eras.json")
OUTPUT_HTML_PATH = os.path.join(ARCHIVE_DIR, "index.html")

def load_eras_data():
    if not os.path.exists(ERAS_JSON_PATH):
        return {"total_eras": 0, "eras": []}
    with open(ERAS_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_era_recap(slug):
    recap_path = os.path.join(ARCHIVE_DIR, slug, "recap.json")
    if os.path.exists(recap_path):
        try:
            with open(recap_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def render_portal_html(eras_data):
    eras_list = eras_data.get("eras", [])
    total_eras = len(eras_list)

    cards_html = []
    for item in reversed(eras_list):
        era_num = item.get("era", 1)
        slug = item.get("slug", f"era-{era_num}")
        recap = load_era_recap(slug)

        theme_name = recap.get("theme_name") or item.get("theme_name") or f"Era {era_num}"
        date_range = recap.get("date_range") or item.get("date_range") or "Archive Period"
        quote = recap.get("closing_quote") or recap.get("founding_quote") or item.get("quote") or "The runway never sleeps."
        coding_model = recap.get("coding_model") or item.get("coding_model") or "titan-core"
        stats = recap.get("stats", {})

        stats_pills = []
        for k, v in stats.items():
            label = k.replace("_", " ").title()
            stats_pills.append(f'<span class="stat-pill"><strong>{v}</strong> {html.escape(label)}</span>')
        stats_html = "".join(stats_pills)

        card = f"""
        <article class="era-card" id="era-{slug}">
          <div class="card-glow"></div>
          <div class="card-header">
            <span class="era-tag">ERA {era_num:02d} • {html.escape(slug.upper())}</span>
            <span class="era-dates">{html.escape(date_range)}</span>
          </div>
          <h3 class="era-title">{html.escape(theme_name)}</h3>
          <blockquote class="era-quote">
            <span class="quote-mark">&ldquo;</span>{html.escape(quote)}<span class="quote-mark">&rdquo;</span>
          </blockquote>
          <div class="era-engine-badge">
            <svg class="engine-icon" viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
              <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/>
            </svg>
            <span>Autonomous Coding Engine: <strong>{html.escape(coding_model)}</strong></span>
          </div>
          {f'<div class="stats-row">{stats_html}</div>' if stats_html else ''}
          <div class="card-footer">
            <a href="./{slug}/index.html" class="btn-visit">
              <span>Enter Archived Atelier</span>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M5 12h14M12 5l7 7-7 7"/>
              </svg>
            </a>
          </div>
        </article>
        """
        cards_html.append(card)

    cards_rendered = "\n".join(cards_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cindy Pawford — Digital Museum & Historic Archive</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400..900;1,400..900&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-dark: #09090b;
      --bg-card: rgba(24, 24, 27, 0.7);
      --gold: #d4af37;
      --gold-light: #fef08a;
      --gold-glow: rgba(212, 175, 55, 0.25);
      --text-main: #f4f4f5;
      --text-muted: #a1a1aa;
      --border-subtle: rgba(212, 175, 55, 0.2);
      --font-display: 'Playfair Display', Georgia, serif;
      --font-sans: 'Inter', -apple-system, sans-serif;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background-color: var(--bg-dark);
      background-image: 
        radial-gradient(circle at 50% 0%, rgba(212, 175, 55, 0.12) 0%, transparent 60%),
        radial-gradient(circle at 100% 50%, rgba(212, 175, 55, 0.05) 0%, transparent 40%),
        linear-gradient(to bottom, #09090b, #18181b);
      color: var(--text-main);
      font-family: var(--font-sans);
      min-height: 100vh;
      line-height: 1.6;
      padding-bottom: 5rem;
    }}
    .nav-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      max-width: 1200px;
      margin: 0 auto;
      padding: 2rem 1.5rem;
    }}
    .nav-brand {{
      display: flex;
      align-items: center;
      gap: 1rem;
      text-decoration: none;
      color: var(--text-main);
    }}
    .monogram {{
      font-family: var(--font-display);
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--gold);
      border: 1.5px solid var(--gold);
      width: 44px;
      height: 44px;
      line-height: 40px;
      text-align: center;
      border-radius: 50%;
      box-shadow: 0 0 12px var(--gold-glow);
    }}
    .brand-name {{
      font-family: var(--font-display);
      font-size: 1.25rem;
      letter-spacing: 0.05em;
    }}
    .nav-links a {{
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.9rem;
      transition: color 0.2s;
    }}
    .nav-links a:hover {{ color: var(--gold-light); }}
    .hero {{
      text-align: center;
      max-width: 860px;
      margin: 2rem auto 4rem auto;
      padding: 0 1.5rem;
    }}
    .museum-tag {{
      display: inline-block;
      padding: 0.35rem 1rem;
      background: rgba(212, 175, 55, 0.1);
      border: 1px solid var(--border-subtle);
      border-radius: 9999px;
      font-size: 0.8rem;
      color: var(--gold);
      text-transform: uppercase;
      letter-spacing: 0.15em;
      margin-bottom: 1.25rem;
    }}
    .hero-title {{
      font-family: var(--font-display);
      font-size: clamp(2.5rem, 5vw, 4rem);
      font-weight: 700;
      line-height: 1.15;
      background: linear-gradient(135deg, #ffffff 20%, var(--gold-light) 60%, var(--gold) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 1.25rem;
    }}
    .hero-subtitle {{
      color: var(--text-muted);
      font-size: 1.15rem;
      max-width: 680px;
      margin: 0 auto;
    }}
    .gallery-container {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 0 1.5rem;
    }}
    .gallery-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 2rem;
    }}
    .era-card {{
      position: relative;
      background: var(--bg-card);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 2.25rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease;
      overflow: hidden;
    }}
    .era-card:hover {{
      transform: translateY(-4px);
      border-color: rgba(212, 175, 55, 0.5);
      box-shadow: 0 16px 32px rgba(0, 0, 0, 0.6), 0 0 20px var(--gold-glow);
    }}
    .card-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.25rem;
    }}
    .era-tag {{
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--gold);
      letter-spacing: 0.1em;
    }}
    .era-dates {{
      font-size: 0.8rem;
      color: var(--text-muted);
    }}
    .era-title {{
      font-family: var(--font-display);
      font-size: 1.75rem;
      color: #fff;
      margin-bottom: 1rem;
      line-height: 1.25;
    }}
    .era-quote {{
      font-family: var(--font-display);
      font-style: italic;
      color: var(--text-muted);
      font-size: 1rem;
      line-height: 1.55;
      margin-bottom: 1.5rem;
      flex-grow: 1;
    }}
    .quote-mark {{ color: var(--gold); font-size: 1.2rem; }}
    .era-engine-badge {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 6px;
      padding: 0.4rem 0.75rem;
      font-size: 0.8rem;
      color: #e4e4e7;
      margin-bottom: 1.25rem;
    }}
    .engine-icon {{ color: var(--gold); }}
    .stats-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-bottom: 1.5rem;
    }}
    .stat-pill {{
      background: rgba(212, 175, 55, 0.08);
      border: 1px solid rgba(212, 175, 55, 0.2);
      border-radius: 9999px;
      padding: 0.2rem 0.65rem;
      font-size: 0.75rem;
      color: var(--text-muted);
    }}
    .stat-pill strong {{ color: #fff; }}
    .card-footer {{
      border-top: 1px solid rgba(255, 255, 255, 0.06);
      padding-top: 1.25rem;
    }}
    .btn-visit {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      width: 100%;
      padding: 0.75rem 1.25rem;
      background: linear-gradient(135deg, #18181b 0%, #27272a 100%);
      border: 1px solid var(--border-subtle);
      border-radius: 8px;
      color: #fff;
      font-size: 0.9rem;
      font-weight: 500;
      text-decoration: none;
      transition: all 0.2s ease;
    }}
    .btn-visit:hover {{
      background: var(--gold);
      color: #000;
      border-color: var(--gold);
      box-shadow: 0 0 16px var(--gold-glow);
    }}
    .museum-footer {{
      text-align: center;
      margin-top: 5rem;
      color: #71717a;
      font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <nav class="nav-bar">
    <a href="./" class="nav-brand">
      <div class="monogram">CP</div>
      <span class="brand-name">Cindy Pawford Archive</span>
    </a>
    <div class="nav-links">
      <a href="http://cindypawford.titan.local" target="_blank">Live Atelier &rarr;</a>
    </div>
  </nav>

  <header class="hero">
    <span class="museum-tag">Permanent Digital Vault • {total_eras} Verified Era{'s' if total_eras != 1 else ''}</span>
    <h1 class="hero-title">The Grand Fashion Archives</h1>
    <p class="hero-subtitle">
      A curated chronicle of Cindy Pawford's weekly haute-couture eras, autonomous code evolutions, and executive canine philosophy preserved for posterity.
    </p>
  </header>

  <main class="gallery-container">
    <div class="gallery-grid">
      {cards_rendered}
    </div>
  </main>

  <footer class="museum-footer">
    <p>&copy; 2024&ndash;2026 Cindy Pawford Pet Company • Immutable Vault Preserved by Project Titan</p>
  </footer>
</body>
</html>
"""

def main():
    eras_data = load_eras_data()
    portal_html = render_portal_html(eras_data)
    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(portal_html)
    print(f"[SUCCESS] Digital Museum Portal compiled at {OUTPUT_HTML_PATH} ({len(eras_data.get('eras', []))} eras).")

if __name__ == "__main__":
    main()
