#!/usr/bin/env python3
"""
Project Titan: Cindy Pawford Digital Museum & Declassified Logbook Portal Generator
Protocol 1984.7 — Retro Phosphor Terminal & Historic Archival Ledger Aesthetic.
Compiles apps/cindypawford/archive/index.html deterministically from logbook.json and eras.json.
"""

import os
import json
import html

def find_repo_root():
    d = os.path.abspath(os.path.dirname(__file__))
    while d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, "config", "agents.yaml")) or os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

REPO_ROOT = find_repo_root()
ARCHIVE_DIR = os.path.join(REPO_ROOT, "apps", "cindypawford", "archive")
LOGBOOK_JSON_PATH = os.path.join(ARCHIVE_DIR, "logbook.json")
ERAS_JSON_PATH = os.path.join(ARCHIVE_DIR, "eras.json")
OUTPUT_HTML_PATH = os.path.join(ARCHIVE_DIR, "index.html")

def load_json_file(path, default=None):
    if not os.path.exists(path):
        return default or {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Error reading {path}: {e}")
        return default or {}

def render_timeline_entry(entry):
    cat = html.escape(entry.get("category", "new-era"))
    date_disp = html.escape(entry.get("date_display", "UNDATED"))
    time_disp = html.escape(entry.get("time_display", "00:00:00 UTC"))
    badge = html.escape(entry.get("badge", "[LOG ENTRY]"))
    subbadge = html.escape(entry.get("subbadge", ""))
    block = html.escape(entry.get("block", ""))
    title = html.escape(entry.get("title", "Untitled Chronicle"))
    desc = html.escape(entry.get("description", ""))
    badge_type = entry.get("badge_type", "primary")

    # Date badge styling based on badge type
    date_border_class = "border-primary-container/40"
    date_text_class = "text-primary font-bold"
    track_dot_class = "bg-primary-container"
    card_hover_class = "hover:border-primary-container/50"
    badge_pill_class = "bg-primary-container text-on-primary-container font-bold"

    if badge_type == "error":
        date_border_class = "border-error/40"
        date_text_class = "text-error font-bold"
        track_dot_class = "bg-error"
        card_hover_class = "hover:border-error/50"
        badge_pill_class = "bg-error/20 text-error font-bold border border-error/40"
    elif badge_type == "secondary":
        date_border_class = "border-secondary/40"
        date_text_class = "text-secondary font-bold"
        track_dot_class = "bg-secondary"
        card_hover_class = "hover:border-secondary/50"
        badge_pill_class = "bg-secondary text-on-secondary font-bold"
    elif badge_type == "tertiary":
        date_border_class = "border-tertiary/40"
        date_text_class = "text-tertiary font-bold"
        track_dot_class = "bg-tertiary"
        card_hover_class = "hover:border-tertiary/50"
        badge_pill_class = "bg-tertiary text-surface-container-lowest font-bold"

    body_extra = ""

    # 1. Telemetry / Hex Dump Entry
    if "telemetry" in entry:
        telem = entry["telemetry"]
        sig = html.escape(telem.get("sig", "SIG: MERKLE_ROOT"))
        system_tag = html.escape(telem.get("system_tag", "SYSTEM_TELEMETRY // VERIFIED"))
        hex_raw = telem.get("hex_dump", "")
        hash_val = html.escape(telem.get("hash", "0x0000"))
        status = html.escape(telem.get("status", "ACTIVE"))

        hex_lines = "<br/>".join([html.escape(line) for line in hex_raw.splitlines()]) if hex_raw else ""
        hex_box = ""
        if hex_lines:
            hex_box = f"""
            <div class="bg-surface-container-lowest border border-outline-variant/30 p-space-sm rounded-lg font-body-sm text-body-sm text-primary-fixed-dim/90 overflow-x-auto shadow-inner">
              <div class="flex justify-between items-center pb-1 text-outline font-label-sm text-label-sm">
                <span>{sig}</span>
                <span class="text-tertiary">{system_tag}</span>
              </div>
              <code>{hex_lines}</code>
            </div>
            """

        body_extra = f"""
        {hex_box}
        <div class="flex items-center justify-between pt-space-xs flex-wrap gap-2 font-label-sm text-label-sm">
          <div class="flex items-center gap-space-xs text-outline">
            <span>{sig if not hex_box else 'ROOT HASH:'}</span>
            <span class="text-tertiary font-mono">{hash_val}</span>
          </div>
          <span class="text-primary-container bg-surface-container-highest px-2 py-0.5 rounded-DEFAULT font-bold">{status}</span>
        </div>
        """

    # 2. Incident Metrics Grid Entry
    elif "incident_metrics" in entry:
        m = entry["incident_metrics"]
        peak = html.escape(str(m.get("peak_players", "0")))
        jitter = html.escape(str(m.get("packet_jitter", "0 ms")))
        failover = html.escape(str(m.get("failover_time", "0 s")))
        footer = entry.get("footer", {})
        snapshot = html.escape(footer.get("snapshot", "SYS_DUMP.TAR"))
        status = html.escape(footer.get("status", "STATUS: RESOLVED"))

        body_extra = f"""
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-space-xs bg-surface-container-lowest border border-outline-variant/30 p-space-sm rounded-lg text-center">
          <div class="flex flex-col p-2 bg-surface-container rounded-DEFAULT">
            <span class="font-label-sm text-label-sm text-outline">PEAK PLAYERS</span>
            <span class="font-headline-md text-headline-md text-primary font-bold">{peak}</span>
          </div>
          <div class="flex flex-col p-2 bg-surface-container rounded-DEFAULT">
            <span class="font-label-sm text-label-sm text-outline">PACKET JITTER</span>
            <span class="font-headline-md text-headline-md text-error font-bold">{jitter}</span>
          </div>
          <div class="flex flex-col p-2 bg-surface-container rounded-DEFAULT">
            <span class="font-label-sm text-label-sm text-outline">FAILOVER TIME</span>
            <span class="font-headline-md text-headline-md text-tertiary font-bold">{failover}</span>
          </div>
        </div>
        <div class="flex items-center justify-between pt-space-xs flex-wrap gap-2 font-label-sm text-label-sm">
          <div class="flex items-center gap-space-xs text-outline">
            <span>SNAPSHOT:</span>
            <span class="text-tertiary font-mono">{snapshot}</span>
          </div>
          <span class="text-primary-fixed-dim bg-surface-container-highest px-2 py-0.5 rounded-DEFAULT">{status}</span>
        </div>
        """

    # 3. Governance Proposal Entry
    elif "proposal" in entry:
        prop = entry["proposal"]
        lineage = html.escape(prop.get("weights_lineage", "RETRO_AVANT_GARDE"))
        consensus = html.escape(prop.get("consensus", "RATIFIED"))
        bars = prop.get("bars", [])
        bars_html = "".join([
            f'<div class="h-full" style="width:{b.get("pct", 0)}%;background-color:{b.get("color", "#00ff66")};"></div>'
            for b in bars
        ])
        footer = entry.get("footer", {})
        contract = html.escape(footer.get("contract", "0x0000"))
        status = html.escape(footer.get("status", "[SYSTEM_TELEMETRY] LOCKED"))

        body_extra = f"""
        <div class="p-space-sm bg-surface-container-lowest border border-outline-variant/30 rounded-lg flex flex-col gap-2">
          <div class="flex justify-between font-label-sm text-label-sm text-outline">
            <span>WEIGHTS LINEAGE: {lineage}</span>
            <span class="text-secondary font-bold">CONSENSUS: {consensus}</span>
          </div>
          <div class="w-full bg-surface-container h-2 rounded-full overflow-hidden flex">
            {bars_html}
          </div>
        </div>
        <div class="flex items-center justify-between pt-space-xs flex-wrap gap-2 font-label-sm text-label-sm">
          <div class="flex items-center gap-space-xs text-outline">
            <span>CONTRACT:</span>
            <span class="text-tertiary font-mono">{contract}</span>
          </div>
          <span class="text-tertiary bg-surface-container-highest px-2 py-0.5 rounded-DEFAULT">{status}</span>
        </div>
        """

    # 4. Audio Soundboard Entry
    elif "audio_preview" in entry:
        audio = entry["audio_preview"]
        stem = html.escape(audio.get("chip_stem", "TELEPHONE_RING_84.WAV"))
        footer = entry.get("footer", {})
        commit = html.escape(footer.get("commit", "cindy-audio-v0.8.2"))
        status = html.escape(footer.get("status", "CHIP STACK ONLINE"))

        body_extra = f"""
        <div class="bg-surface-container-lowest border border-outline-variant/30 p-space-sm rounded-lg flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <span class="font-label-sm text-label-sm text-outline">CHIP STEM: {stem}</span>
            <span class="font-label-sm text-label-sm text-primary-fixed-dim font-bold" id="sound-status">STATUS: STANDBY</span>
          </div>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <button class="px-2 py-1.5 bg-surface-container border border-outline-variant/40 text-primary-fixed-dim hover:bg-surface-container-high font-label-sm text-label-sm rounded-DEFAULT text-left cursor-pointer transition-colors" onclick="triggerChiptune(440, 'DIAL TONE')">[▶] 440Hz DIAL</button>
            <button class="px-2 py-1.5 bg-surface-container border border-outline-variant/40 text-secondary hover:bg-surface-container-high font-label-sm text-label-sm rounded-DEFAULT text-left cursor-pointer transition-colors" onclick="triggerChiptune(880, 'PAW TAP')">[▶] 880Hz TAP</button>
            <button class="px-2 py-1.5 bg-surface-container border border-outline-variant/40 text-tertiary hover:bg-surface-container-high font-label-sm text-label-sm rounded-DEFAULT text-left cursor-pointer transition-colors" onclick="triggerChiptune(330, 'BERLIN CARRIER')">[▶] 330Hz CARRIER</button>
            <button class="px-2 py-1.5 bg-surface-container border border-outline-variant/40 text-primary hover:bg-surface-container-high font-label-sm text-label-sm rounded-DEFAULT text-left cursor-pointer transition-colors" onclick="triggerChiptune(1200, 'CHOPPER SYNTH')">[▶] 1.2kHz BELL</button>
          </div>
        </div>
        <div class="flex items-center justify-between pt-space-xs flex-wrap gap-2 font-label-sm text-label-sm">
          <div class="flex items-center gap-space-xs text-outline">
            <span>COMMIT:</span>
            <span class="text-tertiary font-mono">{commit}</span>
          </div>
          <span class="text-secondary bg-surface-container-highest px-2 py-0.5 rounded-DEFAULT">{status}</span>
        </div>
        """

    pr_meta = entry.get("pr_metadata", {})
    pr_num = pr_meta.get("pr_number")
    pr_url = f"https://github.com/patternsatscale/CindyPawford-Online/pull/{pr_num}" if pr_num else None

    if block:
        if pr_url:
            block_html = f'<a href="{pr_url}" target="_blank" rel="noopener noreferrer" class="font-label-sm text-label-sm text-secondary hover:text-primary font-mono flex items-center gap-1 transition-colors"><span>{block}</span><span class="material-symbols-outlined text-[12px]">open_in_new</span></a>'
        else:
            block_html = f'<span class="font-label-sm text-label-sm text-secondary font-mono">{block}</span>'
    else:
        block_html = ""

    pr_footer = ""
    if pr_url:
        pr_author = html.escape(str(pr_meta.get("author", "cindy-pawford")))
        sha = html.escape(str(pr_meta.get("commit_sha", "HEAD"))[:8])
        pr_footer = f"""
        <div class="flex items-center justify-between pt-space-xs mt-1 border-t border-outline-variant/20 flex-wrap gap-2 font-label-sm text-label-sm">
          <div class="flex items-center gap-2 text-outline">
            <span class="text-on-surface-variant font-bold">SOURCE:</span>
            <a href="{pr_url}" target="_blank" rel="noopener noreferrer" class="text-primary hover:underline font-bold flex items-center gap-1">
              <span>PR #{pr_num}</span>
              <span class="material-symbols-outlined text-[12px]">open_in_new</span>
            </a>
            <span>•</span>
            <span>@{pr_author}</span>
            {f'<span>•</span><span>COMMIT: <span class="text-tertiary font-mono">{sha}</span></span>' if sha else ''}
          </div>
          <a href="{pr_url}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-0.5 bg-primary-container/20 hover:bg-primary-container text-primary hover:text-on-primary-container border border-primary/40 rounded-DEFAULT font-bold flex items-center gap-1 transition-all">
            <span>VIEW ON GITHUB</span>
            <span class="material-symbols-outlined text-[12px]">open_in_new</span>
          </a>
        </div>
        """

    return f"""
    <!-- TIMELINE ENTRY: {date_disp} -->
    <div class="timeline-entry flex flex-col sm:flex-row items-start gap-space-md relative" data-cat="{cat}">
      <!-- Date Stamp Pill -->
      <div class="sm:w-32 flex-shrink-0 flex sm:flex-col sm:items-end items-center gap-1 sm:pr-space-md z-10">
        <div class="px-2 py-1 bg-surface-container-high border {date_border_class} rounded text-center shadow-md">
          <div class="font-label-sm text-label-sm {date_text_class}">{date_disp}</div>
          <div class="font-label-sm text-[9px] text-outline">{time_disp}</div>
        </div>
      </div>
      <!-- Track Node -->
      <div class="absolute left-28 sm:left-32 -ml-[5px] top-3 hidden sm:block w-3 h-3 rounded-full {track_dot_class} ring-4 ring-surface-container-lowest z-20"></div>
      <!-- Entry Card -->
      <article class="flex-1 bg-surface-container border border-outline-variant/40 p-space-md rounded-xl shadow-lg {card_hover_class} transition-all">
        <div class="flex flex-col gap-space-xs">
          <div class="flex items-center justify-between flex-wrap gap-2 pb-1 border-b border-outline-variant/20">
            <div class="flex items-center gap-space-xs">
              <span class="font-label-sm text-label-sm px-2 py-0.5 rounded-DEFAULT {badge_pill_class}">{badge}</span>
              {f'<span class="font-label-sm text-label-sm text-tertiary font-mono">{subbadge}</span>' if subbadge else ''}
            </div>
            {block_html}
          </div>
          <div class="font-headline-md text-headline-md text-on-surface font-bold">{title}</div>
          <p class="font-body-md text-body-md text-on-surface-variant">
            {desc}
          </p>
          {body_extra}
          {pr_footer}
        </div>
      </article>
    </div>
    """

def render_era_tile(era):
    num = era.get("era", 1)
    tag = html.escape(era.get("era_tag", f"ERA-{num:02d}"))
    title = html.escape(era.get("theme_name", f"Era {num}"))
    range_str = html.escape(era.get("date_range", "Historical Archive Period"))
    blocks = html.escape(era.get("blocks", "#00000001 - #00000094"))
    hash_str = html.escape(era.get("hash", "0x0000...0000"))
    status_tag = html.escape(era.get("status_tag", "100% MERKLE VERIFIED"))
    color_theme = era.get("color_theme", "primary")
    slug = era.get("slug", "2024-genesis")
    emblem_src = era.get("emblem", "")

    theme_border = "hover:border-primary-container/60"
    tag_bg = "bg-primary-container text-on-primary-container"
    status_text = "text-primary-fixed-dim"

    if color_theme == "secondary":
        theme_border = "hover:border-secondary/60"
        tag_bg = "bg-secondary text-on-secondary"
        status_text = "text-secondary"
    elif color_theme == "tertiary":
        theme_border = "hover:border-tertiary/60"
        tag_bg = "bg-tertiary text-surface-container-lowest"
        status_text = "text-tertiary"
    elif color_theme == "primary-container":
        theme_border = "hover:border-primary/60"
        tag_bg = "bg-surface-variant text-primary-fixed-dim border border-outline-variant/40"
        status_text = "text-primary-container"

    badge_visual = ""
    if emblem_src:
        badge_visual = f"""
        <div class="w-14 h-14 rounded-lg bg-surface-container-lowest border border-primary/40 overflow-hidden flex-shrink-0 flex items-center justify-center p-1">
          <img alt="{title} Emblem" class="w-full h-full object-cover rounded" src="{emblem_src}" onerror="this.src='/assets/cindy_desk_support.jpg'"/>
        </div>
        """
    else:
        num_color = "text-secondary" if color_theme == "secondary" else ("text-tertiary" if color_theme == "tertiary" else "text-primary")
        bg_num = "bg-secondary/10" if color_theme == "secondary" else ("bg-tertiary/10" if color_theme == "tertiary" else "bg-primary/10")
        badge_visual = f"""
        <div class="w-14 h-14 rounded-lg bg-surface-container-lowest border border-outline-variant/40 overflow-hidden flex-shrink-0 flex items-center justify-center p-1">
          <div class="w-full h-full {bg_num} rounded flex items-center justify-center {num_color} text-xl font-bold font-mono">{num:02d}</div>
        </div>
        """

    return f"""
    <!-- ERA TILE {num:02d} -->
    <div class="w-full bg-surface-container border border-outline-variant/40 {theme_border} p-space-md rounded-xl shadow-lg transition-all flex flex-col md:flex-row md:items-center justify-between gap-space-md">
      <div class="flex items-center gap-space-md min-w-0">
        {badge_visual}
        <div class="flex flex-col min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-label-sm text-label-sm px-2 py-0.5 font-bold rounded-DEFAULT {tag_bg}">{tag}</span>
            <span class="font-headline-md text-base text-on-surface font-bold truncate">{title}</span>
          </div>
          <div class="flex items-center gap-3 text-outline font-label-sm text-label-sm mt-0.5 flex-wrap">
            <span>RANGE: <span class="text-on-surface">{range_str}</span></span>
            <span>•</span>
            <span>BLOCKS: <span class="text-secondary">{blocks}</span></span>
            <span>•</span>
            <span>HASH: <span class="text-tertiary font-mono">{hash_str}</span></span>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-space-md justify-between md:justify-end flex-shrink-0">
        <span class="font-label-sm text-label-sm px-2 py-1 bg-surface-container-high {status_text} rounded border border-outline-variant/30">{status_tag}</span>
        <a href="{"https://cindypawford.com" if "ACTIVE" in status_tag.upper() else f"./{slug}/index.html"}" class="px-4 py-2 bg-surface-container-high hover:bg-surface-bright text-on-surface hover:text-primary font-bold text-label-sm rounded-DEFAULT border border-outline-variant/40 transition-colors flex items-center gap-1 cursor-pointer">
          <span>{"LIVE CANVAS ➔" if "ACTIVE" in status_tag.upper() else "EXPLORE ERA ➔"}</span>
        </a>
      </div>
    </div>
    """

def render_scoreboard(eras, entries):
    era_rows = []
    for era in eras:
        num = era.get("era", 1)
        tag = html.escape(era.get("era_tag", f"ERA-{num:02d}"))
        name = html.escape(era.get("theme_name", f"Era {num}"))
        dates = html.escape(era.get("date_range", ""))
        status = html.escape(era.get("status_tag", "RECORDED"))
        color = era.get("color_theme", "primary")
        dot_color = "bg-primary-container" if color == "primary" else ("bg-secondary" if color == "secondary" else "bg-tertiary")
        pill_bg = "bg-primary-container/20 text-primary border border-primary/40" if color == "primary" else "bg-secondary/20 text-secondary border border-secondary/40"
        era_url = "https://cindypawford.com" if "ACTIVE" in status.upper() else f"./{era.get('slug', '2024-genesis')}/index.html"

        era_rows.append(f"""
        <a href="{era_url}" class="group flex items-center justify-between p-2.5 bg-surface-container-lowest border border-outline-variant/30 rounded-lg hover:border-primary hover:bg-surface-container transition-all cursor-pointer">
          <div class="flex items-center gap-2 min-w-0">
            <span class="font-mono text-xs text-primary font-bold w-5">{num:02d}</span>
            <div class="flex flex-col truncate">
              <div class="flex items-center gap-1.5">
                <span class="font-label-sm text-label-sm text-on-surface group-hover:text-primary transition-colors truncate font-bold">{name}</span>
              </div>
              <span class="font-label-sm text-[9px] text-outline">{tag} • {dates}</span>
            </div>
          </div>
          <div class="flex items-center gap-2 flex-shrink-0">
            <span class="font-label-sm text-[10px] px-1.5 py-0.5 rounded {pill_bg}">{status}</span>
            <span class="w-1.5 h-1.5 rounded-full {dot_color} {'animate-pulse' if 'ACTIVE' in status else ''}"></span>
          </div>
        </a>
        """)

    pr_rows = []
    for idx, e in enumerate(entries):
        rank_str = f"{idx + 1:02d}"
        title = html.escape(e.get("title", "Pull Request"))
        date = html.escape(e.get("date_display", ""))
        b_type = e.get("badge_type", "primary")
        pr_meta = e.get("pr_metadata", {})
        pr_num = pr_meta.get("pr_number")
        pr_url = f"https://github.com/patternsatscale/CindyPawford-Online/pull/{pr_num}" if pr_num else "https://github.com/patternsatscale/CindyPawford-Online/pulls"
        tag_str = f"PR #{pr_num} • {date}" if pr_num else date

        dot_class = "bg-primary-container"
        text_rank = "text-primary"
        if b_type == "error":
            dot_class = "bg-error"
            text_rank = "text-error"
        elif b_type == "secondary":
            dot_class = "bg-secondary"
            text_rank = "text-secondary"
        elif b_type == "tertiary":
            dot_class = "bg-tertiary"
            text_rank = "text-tertiary"

        pr_rows.append(f"""
        <a href="{pr_url}" target="_blank" rel="noopener noreferrer" class="group flex items-center justify-between p-2 bg-surface-container-lowest border border-outline-variant/30 rounded-lg hover:border-primary hover:bg-surface-container transition-all cursor-pointer">
          <div class="flex items-center gap-2 min-w-0">
            <span class="font-mono text-xs {text_rank} font-bold w-5">{rank_str}</span>
            <div class="flex flex-col truncate">
              <span class="font-label-sm text-label-sm text-on-surface group-hover:text-primary transition-colors truncate font-bold">{title}</span>
              <span class="font-label-sm text-[9px] text-outline">{tag_str}</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5 flex-shrink-0">
            <span class="font-mono text-[11px] font-bold text-primary px-1.5 py-0.5 rounded bg-surface-container-high border border-outline-variant/30 group-hover:border-primary group-hover:bg-primary/10 transition-colors flex items-center gap-1">
              <span>#{pr_num if pr_num else 'PR'}</span>
              <span class="material-symbols-outlined text-[12px]">open_in_new</span>
            </span>
            <span class="w-1.5 h-1.5 rounded-full {dot_class}"></span>
          </div>
        </a>
        """)

    era_rows_html = "\n".join(era_rows)
    pr_rows_html = "\n".join(pr_rows)

    return f"""
    <!-- CANONICAL ERAS & RECENT ACTIVITY SCOREBOARD -->
    <div class="bg-surface-container border border-outline-variant/40 p-space-md rounded-xl shadow-xl flex flex-col gap-space-sm">
      <div class="flex items-center justify-between pb-space-xs border-b border-outline-variant/20">
        <div class="flex items-center gap-space-xs">
          <span class="material-symbols-outlined text-secondary text-base">leaderboard</span>
          <span class="font-label-md text-label-md text-secondary font-bold">CANONICAL ERAS &amp; ACTIVITY</span>
        </div>
        <span class="font-label-sm text-label-sm px-2 py-0.5 bg-primary-container text-on-primary-container font-bold rounded-DEFAULT">LIVE • {len(eras)} ERAS</span>
      </div>

      <!-- CANONICAL ERAS SUBSECTION -->
      <div class="flex flex-col gap-1.5">
        <div class="font-label-sm text-[10px] text-outline tracking-wider uppercase pt-0.5">CANONICAL ERAS ({len(eras)} RECORDED)</div>
        {era_rows_html}
      </div>

      <!-- RECENT PULL REQUESTS SUBSECTION -->
      <div class="flex flex-col gap-1.5 pt-1 border-t border-outline-variant/20">
        <div class="flex items-center justify-between pt-1">
          <span class="font-label-sm text-[10px] text-outline tracking-wider uppercase">RECENT PULL REQUESTS ({len(entries)} MERGED)</span>
          <a href="https://github.com/patternsatscale/CindyPawford-Online/pulls" target="_blank" rel="noopener noreferrer" class="font-label-sm text-[10px] text-primary hover:underline flex items-center gap-0.5">
            <span>VIEW ALL</span>
            <span class="material-symbols-outlined text-[10px]">open_in_new</span>
          </a>
        </div>
        {pr_rows_html}
      </div>
    </div>
    """

def build_portal():
    logbook_data = load_json_file(LOGBOOK_JSON_PATH, {"entries": []})
    entries = logbook_data.get("entries", [])

    eras_data = load_json_file(ERAS_JSON_PATH, {"eras": []})
    eras = eras_data.get("eras", [])

    # Ensure logbook entries are sorted reverse-chronologically (latest at the top)
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    # Render entries
    timeline_html = "\n".join([render_timeline_entry(entry) for entry in entries])

    # Render era tiles
    era_tiles_html = "\n".join([render_era_tile(era) for era in eras])

    # Render scoreboard
    scoreboard_html = render_scoreboard(eras, entries)

    full_html = f"""<!DOCTYPE html>
<html class="dark" lang="en">
<head>
  <meta charset="utf-8"/>
  <meta content="width=device-width, initial-scale=1.0" name="viewport"/>
  <title>Cindy Pawford — Digital Museum & Declassified Logbook Archive</title>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet"/>
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>
  <style>
    @layer base {{
      html, body {{
        margin: 0;
        padding: 0;
      }}
      body {{
        overscroll-behavior: none;
      }}
      main > :first-child {{
        margin-top: 0 !important;
      }}
      main > :last-child {{
        margin-bottom: 0 !important;
      }}
    }}
    ::-webkit-scrollbar {{
      width: 6px;
      height: 6px;
    }}
    ::-webkit-scrollbar-track {{
      background: #0d0a08;
    }}
    ::-webkit-scrollbar-thumb {{
      background: #241f1a;
      border-radius: 3px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
      background: #3e3833;
    }}
    @keyframes blink {{
      0%, 49% {{ opacity: 1; }}
      50%, 100% {{ opacity: 0; }}
    }}
    .animate-crt-blink {{
      animation: blink 1s step-end infinite;
    }}
    .crt-scanlines {{
      background: repeating-linear-gradient(
        to bottom,
        rgba(0, 0, 0, 0) 0px,
        rgba(0, 0, 0, 0) 2px,
        rgba(0, 0, 0, 0.28) 2px,
        rgba(0, 0, 0, 0.28) 4px
      );
      pointer-events: none;
    }}
  </style>
  <script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
  <script id="tailwind-config">
    tailwind.config = {{
      darkMode: "class",
      theme: {{
        extend: {{
          colors: {{
            "background": "#0d0a08",
            "surface": "#17120e",
            "surface-dim": "#17120e",
            "surface-bright": "#3e3833",
            "surface-container-lowest": "#120d09",
            "surface-container-low": "#201b16",
            "surface-container": "#241f1a",
            "surface-container-high": "#2f2924",
            "surface-container-highest": "#3a342f",
            "surface-variant": "#3a342f",
            "on-surface": "#ece0d9",
            "on-surface-variant": "#b9ccb5",
            "outline": "#849581",
            "outline-variant": "#3b4b3a",
            "primary": "#00ff66",
            "primary-container": "#00ff66",
            "primary-fixed": "#6bff83",
            "primary-fixed-dim": "#00e55b",
            "on-primary": "#003911",
            "on-primary-container": "#007128",
            "secondary": "#ffb000",
            "secondary-container": "#ed9000",
            "secondary-fixed": "#ffdcbc",
            "secondary-fixed-dim": "#ffb86c",
            "on-secondary": "#492900",
            "tertiary": "#00e5ff",
            "tertiary-container": "#00e5ff",
            "tertiary-fixed": "#d5eba4",
            "error": "#ffb4ab",
            "error-container": "#93000a"
          }},
          borderRadius: {{
            DEFAULT: "0.125rem",
            lg: "0.25rem",
            xl: "0.5rem",
            full: "0.75rem"
          }},
          spacing: {{
            gutter: "1rem",
            "space-md": "1rem",
            margin: "1rem",
            "space-lg": "1.5rem",
            "space-xs": "0.25rem",
            "space-sm": "0.5rem",
            "space-xl": "2.5rem",
            "gutter-desktop": "1.5rem"
          }},
          fontFamily: {{
            "headline-xl": ["Space Mono", "monospace"],
            "body-md": ["Space Mono", "monospace"],
            "label-sm": ["Space Mono", "monospace"],
            "body-lg": ["Space Mono", "monospace"],
            "body-sm": ["Space Mono", "monospace"],
            "headline-lg": ["Space Mono", "monospace"],
            "headline-md": ["Space Mono", "monospace"],
            "label-md": ["Space Mono", "monospace"]
          }},
          fontSize: {{
            "headline-xl": ["38px", {{ lineHeight: "46px", letterSpacing: "-0.03em", fontWeight: "700" }}],
            "body-md": ["13px", {{ lineHeight: "20px", letterSpacing: "0em", fontWeight: "400" }}],
            "label-sm": ["10px", {{ lineHeight: "14px", letterSpacing: "0.1em", fontWeight: "700" }}],
            "body-lg": ["15px", {{ lineHeight: "22px", letterSpacing: "0em", fontWeight: "400" }}],
            "body-sm": ["11px", {{ lineHeight: "16px", letterSpacing: "0.02em", fontWeight: "400" }}],
            "headline-lg": ["28px", {{ lineHeight: "36px", letterSpacing: "-0.02em", fontWeight: "700" }}],
            "headline-md": ["18px", {{ lineHeight: "24px", letterSpacing: "-0.01em", fontWeight: "700" }}],
            "label-md": ["11px", {{ lineHeight: "15px", letterSpacing: "0.08em", fontWeight: "700" }}]
          }}
        }}
      }}
    }};
  </script>
</head>
<body class="bg-[#0d0a08] font-body-md text-on-surface select-none relative min-h-screen">
  <div class="fixed inset-0 crt-scanlines z-50 pointer-events-none"></div>

  <!-- HEADER NAVIGATION -->
  <header class="fixed top-0 w-full z-40 bg-surface-container-lowest/95 backdrop-blur-md border-b border-outline-variant/40 shadow-[0_4px_20px_rgba(0,0,0,0.8)]">
    <div class="h-20 w-full px-4 sm:px-gutter-desktop flex items-center justify-between gap-space-md">
      <!-- Expanded Cindy-OS Title -->
      <div class="flex items-center gap-space-md flex-1 min-w-0">
        <img alt="Cindy Pawford Emblem" class="h-10 w-10 rounded-full ring-2 ring-primary-container object-cover flex-shrink-0" src="/assets/cindy_desk_support.jpg" onerror="this.src='https://lh3.googleusercontent.com/aida-public/AB6AXuDIa3GJJMLB4rPYqh2xR0q4cl5CdoMkrFclKcXJzMnB_jcGTOgMB1rr9J7AaWEJiq8Ap6OJacwbX3ySW4lf3L7YPjtxCTpIZxRilX0_dSxyiIQ1Ht6VZheJvF6avwaLbvF8l42NFWzEGwyvg8nLWrePlFsI18A71gyLcSIXNzW11T1Ihag5aYPVJ23MbxxyifSlol4K7-LMhEQhQHrEZhWT5PEKIS_hoK0jBqDP6UH_9HDmvcyx2OLKWqVeQP-Igaah'"/>
        <div class="flex flex-col min-w-0">
          <div class="flex items-center gap-space-xs flex-wrap">
            <span class="font-headline-md text-xl sm:text-2xl text-primary-fixed-dim font-bold tracking-tight">CINDY-OS</span>
            <span class="font-label-sm text-label-sm text-secondary bg-surface-container-high px-space-xs py-0.5 rounded-DEFAULT">v2.4.9</span>
            <span class="font-label-sm text-label-sm text-tertiary-container">[PHOSPHOR KERNEL]</span>
            <span class="inline-block w-2 h-4 bg-primary-fixed-dim animate-crt-blink ml-1"></span>
          </div>
          <span class="font-label-sm text-xs text-outline tracking-wider truncate">CANINE ESPIONAGE TERMINAL // AUTONOMOUS AGENT ACTIVE</span>
        </div>
      </div>

      <!-- Telemetry badges (xl:flex, hidden on smaller screens) -->
      <div class="hidden xl:flex items-center gap-space-sm flex-shrink-0">
        <div class="flex items-center gap-space-xs px-space-sm py-1 bg-surface-container border border-outline-variant/30 rounded-full">
          <span class="inline-block w-1.5 h-1.5 rounded-full bg-primary-container animate-pulse"></span>
          <span class="font-label-sm text-label-sm text-primary">EDGE SILICON: 98.4% EFF</span>
        </div>
        <div class="flex items-center gap-space-xs px-space-sm py-1 bg-surface-container border border-outline-variant/30 rounded-full">
          <span class="inline-block w-1.5 h-1.5 rounded-full bg-secondary"></span>
          <span class="font-label-sm text-label-sm text-secondary">TG: @CindyPawford_bot LINKED</span>
        </div>
        <div class="flex items-center gap-space-xs px-space-sm py-1 bg-surface-container border border-outline-variant/30 rounded-full">
          <span class="inline-block w-1.5 h-1.5 rounded-full bg-tertiary-container"></span>
          <span class="font-label-sm text-label-sm text-tertiary-container">SANDBOX: ZERO-TRUST LOCK</span>
        </div>
      </div>

      <!-- Right profile avatar -->
      <div class="flex items-center gap-space-sm pl-space-xs flex-shrink-0">
        <div class="w-8 h-8 rounded-full overflow-hidden ring-2 ring-primary-fixed-dim/40">
          <img alt="Avatar" class="w-full h-full object-cover" src="/assets/cindy_desk_support.jpg" onerror="this.src='https://lh3.googleusercontent.com/aida-public/AB6AXuB653GqPRH-6BHq_b4PrQBfE33OM5OTMNLjyyuzCwVk2thLznnxNhRWd3-PKOlGZQdHsfaevcBtsa_uHWd1zptaYT4_Gd-Sx_NO2ordh6JlaSbCUxXoDIroSCrxGmDa6Y-IP2-iIe7ehrDZCh5Cb3dM_sOih7ZY3jjbbJbpvectyl3WhGjJE7ivCulVRyqjcr7KxpYCnQy0-kBX7kIat42uceozAJCmz--jMHF81ek2P7eKbP8R2Mlqes4SdoNeOsop'"/>
        </div>
      </div>
    </div>
  </header>

  <!-- LEFT TELEMETRY SIDEBAR (Responsive: hidden on mobile/tablet < xl, visible on xl) -->
  <aside class="hidden xl:flex fixed left-0 top-20 bottom-0 w-72 bg-surface-container-lowest/95 border-r border-outline-variant/40 backdrop-blur-lg z-30 flex-col justify-between p-space-md shadow-[4px_0_24px_rgba(0,0,0,0.6)]">
    <div class="flex flex-col gap-space-lg">
      <div class="p-space-sm bg-surface-container border border-outline-variant/30 rounded-lg">
        <div class="font-label-sm text-label-sm text-secondary uppercase tracking-wider mb-space-xs flex items-center justify-between">
          <span>OPERATIVE TELEMETRY</span>
          <span class="w-2 h-2 rounded-full bg-primary animate-ping"></span>
        </div>
        <div class="font-body-sm text-body-sm text-on-surface-variant flex justify-between py-0.5">
          <span>CALLSIGN:</span>
          <span class="text-primary font-bold">CINDY-07</span>
        </div>
        <div class="font-body-sm text-body-sm text-on-surface-variant flex justify-between py-0.5">
          <span>CORE FREQ:</span>
          <span class="text-secondary">44.1 MHz</span>
        </div>
        <div class="font-body-sm text-body-sm text-on-surface-variant flex justify-between py-0.5">
          <span>STATION:</span>
          <span class="text-on-surface">BERLIN-MAIN</span>
        </div>
        <div class="font-body-sm text-body-sm text-on-surface-variant flex justify-between py-0.5">
          <span>ARCHIVE LEDGER:</span>
          <span class="text-tertiary font-bold">WORM-VERIFIED</span>
        </div>
      </div>

      <div class="flex flex-col gap-space-xs">
        <div class="font-label-sm text-label-sm text-outline uppercase px-space-sm py-1">SYSTEM ROUTING</div>
        <nav class="flex flex-col gap-space-xs">
          <a class="flex items-center gap-space-sm px-space-sm py-2 rounded-lg text-on-surface-variant hover:bg-surface-container hover:text-on-surface font-body-sm text-body-sm transition-all" href="https://cindypawford.com">
            <span class="text-secondary">❖</span>
            <span>Terminal Prompt Deck</span>
          </a>
          <a aria-current="page" class="flex items-center gap-space-sm px-space-sm py-2 transition-all bg-surface-container-high text-primary-fixed-dim font-bold rounded-lg border border-primary-container/30 shadow-[inset_0_0_8px_rgba(0,255,102,0.15)]" href="#">
            <span class="text-secondary">▲</span>
            <span>Immutable Vault Records</span>
          </a>
          <a class="flex items-center gap-space-sm px-space-sm py-2 rounded-lg text-on-surface-variant hover:bg-surface-container hover:text-on-surface font-body-sm text-body-sm transition-all" href="https://info.cindypawford.com">
            <span class="text-secondary">::</span>
            <span>Project Information</span>
          </a>
          <a class="flex items-center gap-space-sm px-space-sm py-2 rounded-lg text-on-surface-variant hover:bg-surface-container hover:text-on-surface font-body-sm text-body-sm transition-all" href="https://t.me/CindyPawford_bot" target="_blank" rel="noopener noreferrer">
            <span class="text-secondary">➔</span>
            <span>Telegram Intercept Stream</span>
          </a>
          <a class="flex items-center gap-space-sm px-space-sm py-2 rounded-lg text-on-surface-variant hover:bg-surface-container hover:text-on-surface font-body-sm text-body-sm transition-all" href="https://cindypawford.com">
            <span class="text-secondary">[✕]</span>
            <span>Zero-Trust Sandbox Pod</span>
          </a>
        </nav>
      </div>
    </div>

    <div class="flex flex-col gap-space-sm p-space-sm bg-surface-container-low border border-outline-variant/30 rounded-lg">
      <div class="flex items-center justify-between font-label-sm text-label-sm text-outline">
        <span>CHASSIS TEMP</span>
        <span class="text-primary font-mono">41.8°C</span>
      </div>
      <div class="w-full bg-surface-container h-1.5 rounded-full overflow-hidden">
        <div class="bg-primary-container h-full w-[42%]"></div>
      </div>
      <div class="font-label-sm text-label-sm text-outline flex justify-between pt-space-xs">
        <span>CRYPTO REFS:</span>
        <span class="text-secondary font-mono">{len(eras)} ERAS / 100% OK</span>
      </div>
      <div class="font-label-sm text-label-sm text-on-surface-variant/70 text-center tracking-widest pt-1">CANINE TELECOMM v2.4</div>
    </div>
  </aside>

  <!-- MAIN CONTENT WRAPPER (Responsive padding: pl-0 on mobile/tablet, pl-72 on xl screens) -->
  <div class="pl-0 xl:pl-72">
    <main class="relative pt-20 min-h-screen bg-[#0d0a08] w-full px-4 sm:px-gutter-desktop pb-space-xl">
      <div class="flex flex-col w-full">
        <!-- AMBIENT GLOW BACKDROPS -->
        <div class="relative w-full">
          <div class="absolute top-10 left-1/4 w-96 h-96 bg-primary-container/5 rounded-full blur-3xl pointer-events-none -z-10"></div>
          <div class="absolute top-80 right-1/4 w-96 h-96 bg-secondary/5 rounded-full blur-3xl pointer-events-none -z-10"></div>

          <!-- TOP TELEMETRY BREADCRUMB & CONSOLE HEADER -->
          <section class="flex flex-col md:flex-row md:items-center justify-between gap-space-md p-space-md bg-surface-container-lowest border border-outline-variant/30 rounded-xl shadow-xl mt-space-md mb-space-lg">
            <div class="flex flex-col gap-space-xs">
              <div class="flex items-center gap-space-xs text-primary-fixed-dim">
                <span class="material-symbols-outlined text-base">terminal</span>
                <span class="font-label-sm text-label-sm tracking-widest text-primary-fixed-dim">ARCHIVE ROOT</span>
                <span class="text-secondary">&gt;</span>
                <span class="font-label-sm text-label-sm tracking-widest text-secondary">COMMAND_DECK</span>
                <span class="text-secondary">&gt;</span>
                <span class="font-label-sm text-label-sm tracking-widest text-on-surface">FILTER_MATRIX</span>
                <span class="inline-block w-1.5 h-3 bg-primary-container animate-crt-blink ml-1"></span>
              </div>
              <div class="flex items-baseline gap-space-sm flex-wrap">
                <h1 class="font-headline-md text-headline-md text-on-surface tracking-tighter">IMMUTABLE VAULT ARCHIVE // CHRONOLOGICAL EVENT LOGBOOK</h1>
                <span class="font-label-sm text-label-sm px-2 py-0.5 bg-surface-variant text-tertiary-container border border-outline-variant/40 rounded-DEFAULT" id="logbook-sync-status">LEDGER: logbook.json ({len(entries)} ENTRIES VERIFIED)</span>
              </div>
            </div>

            <!-- LIVE SYSTEM STATUS TAPE -->
            <div class="flex items-center gap-space-xs bg-surface-container px-space-sm py-1.5 rounded-lg border border-outline-variant/40 flex-shrink-0">
              <span class="material-symbols-outlined text-primary text-base">verified</span>
              <div class="flex flex-col">
                <span class="font-label-sm text-label-sm text-outline">CANONICAL LEDGER</span>
                <span class="font-label-sm text-label-sm text-primary font-bold">2024 - 2026 CANONICAL</span>
              </div>
            </div>
          </section>

          <!-- MAIN COCKPIT GRID: 12 COLUMNS (8 TIMELINE BAY + 4 ARTIFACT & SCOREBOARD BAY) -->
          <div class="grid grid-cols-1 lg:grid-cols-12 gap-space-lg">
            <!-- LEFT BAY: TIMELINE & FILTER MATRIX (8 COLS) -->
            <div class="lg:col-span-8 flex flex-col gap-space-md">
              <!-- PROMINENT EVENT-TYPE FILTER BAR MATRIX -->
              <div class="p-space-sm bg-surface-container-lowest border border-outline-variant/40 rounded-xl shadow-md flex flex-col gap-2">
                <div class="flex items-center justify-between pb-1 border-b border-outline-variant/20 flex-wrap gap-1">
                  <div class="flex items-center gap-space-xs">
                    <span class="material-symbols-outlined text-secondary text-base">tune</span>
                    <span class="font-label-sm text-label-sm text-secondary tracking-widest uppercase font-bold">EVENT-TYPE FILTER MATRIX</span>
                  </div>
                  <span class="font-label-sm text-label-sm text-outline">DISPLAYING FILTERED LOGS</span>
                </div>
                <div class="flex items-center gap-2 flex-wrap" id="archive-filter-deck">
                  <button class="filter-btn active font-label-sm text-label-sm px-3 py-1.5 bg-primary-container text-on-primary-container font-bold rounded-DEFAULT shadow-md transition-all cursor-pointer" data-category="all">[ALL EVENTS]</button>
                  <button class="filter-btn font-label-sm text-label-sm px-3 py-1.5 bg-surface-container text-on-surface-variant hover:text-primary hover:bg-surface-bright rounded-DEFAULT transition-all cursor-pointer border border-outline-variant/30" data-category="new-era">[★ NEW ERAS]</button>
                  <button class="filter-btn font-label-sm text-label-sm px-3 py-1.5 bg-surface-container text-on-surface-variant hover:text-secondary hover:bg-surface-bright rounded-DEFAULT transition-all cursor-pointer border border-outline-variant/30" data-category="protocol">[⚡ PROTOCOL &amp; CIPS]</button>
                  <button class="filter-btn font-label-sm text-label-sm px-3 py-1.5 bg-surface-container text-on-surface-variant hover:text-error hover:bg-surface-bright rounded-DEFAULT transition-all cursor-pointer border border-outline-variant/30" data-category="anomaly">[⚠ ANOMALIES &amp; INCIDENTS]</button>
                  <button class="filter-btn font-label-sm text-label-sm px-3 py-1.5 bg-surface-container text-on-surface-variant hover:text-tertiary hover:bg-surface-bright rounded-DEFAULT transition-all cursor-pointer border border-outline-variant/30" data-category="media">[♬ AUDIO &amp; MEDIA]</button>
                </div>
              </div>

              <!-- TRUE VERTICAL CHRONOLOGICAL TIMELINE -->
              <div class="relative flex flex-col gap-space-lg pt-space-xs pb-space-md">
                <!-- Connecting Vertical Phosphor Bus Track -->
                <div class="absolute left-28 sm:left-32 top-3 bottom-6 w-0.5 bg-primary-container/30 border-l border-dashed border-primary-container/60 hidden sm:block"></div>

                {timeline_html}
              </div>
            </div>

            <!-- RIGHT BAY: ARTIFACT VIEWER + TOP 10 SCOREBOARD (4 COLS) -->
            <aside class="lg:col-span-4 flex flex-col gap-space-lg">
              <!-- ARTIFACT VIEWER MODULE -->
              <div class="bg-surface-container border border-outline-variant/40 p-space-md rounded-xl shadow-xl flex flex-col gap-space-md relative overflow-hidden">
                <div class="flex items-center justify-between pb-space-xs border-b border-outline-variant/20">
                  <div class="flex items-center gap-space-xs">
                    <span class="text-secondary text-base">🏛️</span>
                    <span class="font-label-md text-label-md text-secondary font-bold">ARTIFACT VIEWER // #001</span>
                  </div>
                  <span class="font-label-sm text-label-sm px-2 py-0.5 bg-surface-container-high text-primary-fixed-dim rounded-DEFAULT border border-outline-variant/30">ORIGINAL ICON</span>
                </div>

                <!-- ARTIFACT BADGE SHOWCASE USING DATASTORE IMAGE -->
                <div class="relative bg-surface-container-lowest border border-outline-variant/30 p-space-sm rounded-lg flex flex-col items-center justify-center">
                  <div class="relative w-48 h-48 sm:w-56 sm:h-56 rounded-full overflow-hidden shadow-2xl p-1 bg-gradient-to-br from-secondary via-primary-container/30 to-tertiary">
                    <img alt="Official Cindy Pawford Badge" class="w-full h-full object-cover rounded-full" src="/assets/cindy_desk_support.jpg" onerror="this.src='https://lh3.googleusercontent.com/aida-public/AB6AXuDu8CjTwbjhvrjgGqhsp1pO12NiAlYRajR1p8a79VzlmFgcEF8UdY65lpwDSdxXUFmOitpVNIJQQ1a07sRaqx2E9q49DEdJgyKXlEi5oWM-YPBO2DrY7bCsZZTba4AcKTJgHshc_qqedG1QTnW4L-30ttcgPhhnrjk45UXpkbKVkDOXI_q7CqsaMrRSyEGMjw_el5Ea-ndhtGaoEganilTX1Rp4Aq9QLqFFhIX5TIolzxzM0nWw-136UX72p0mfMnL-'"/>
                  </div>
                  <div class="mt-space-sm text-center">
                    <div class="font-label-md text-label-md text-primary font-bold">CINDY PAWFORD (ORIGINAL EMBLEM)</div>
                    <div class="font-label-sm text-label-sm text-outline">SERIES: 1984 AGENT TELECOM PORTRAIT</div>
                  </div>
                </div>

                <!-- TECHNICAL SPEC CARD -->
                <div class="bg-surface-container-low border border-outline-variant/30 p-space-sm rounded-lg flex flex-col gap-1 font-body-sm text-body-sm">
                  <div class="flex justify-between">
                    <span class="text-outline">MEDIUM:</span>
                    <span class="text-on-surface">Screenprint Dot Halftone</span>
                  </div>
                  <div class="flex justify-between">
                    <span class="text-outline">PALETTE:</span>
                    <span class="text-secondary">Avocado / Ochre / Sepia</span>
                  </div>
                  <div class="flex justify-between">
                    <span class="text-outline">HARDWARE:</span>
                    <span class="text-primary-fixed-dim">Bell 103 Rotary Acoustic Receiver</span>
                  </div>
                  <div class="flex justify-between">
                    <span class="text-outline">OPTICS:</span>
                    <span class="text-on-surface">70s Aviator Amber Tint</span>
                  </div>
                  <div class="flex justify-between">
                    <span class="text-outline">STATUS:</span>
                    <span class="text-primary font-bold">PERMANENT ENCRYPTION</span>
                  </div>
                </div>
              </div>

              {scoreboard_html}
            </aside>
          </div>

          <!-- FULL-WIDTH HORIZONTAL ERA TILES ('ALL ARCHIVED ERAS // IMMUTABLE LEDGER') -->
          <section class="mt-space-xl flex flex-col gap-space-md">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-outline-variant/30">
              <div class="flex items-center gap-space-sm">
                <span class="material-symbols-outlined text-primary text-xl">database</span>
                <h2 class="font-headline-md text-headline-md text-primary font-bold">ALL ARCHIVED ERAS // IMMUTABLE LEDGER</h2>
                <span class="font-label-sm text-label-sm text-outline">[WORM RECORD TILES]</span>
              </div>
              <div class="font-label-sm text-label-sm text-secondary">TOTAL ERAS RECORDED: {len(eras):02d} // MERKLE ROOT SYNCHRONIZED</div>
            </div>

            <!-- Stacked Full-Width Rows -->
            <div class="flex flex-col gap-space-sm">
              {era_tiles_html}
            </div>
          </section>

          <!-- FOOTER TELECOMM TERMINAL DIAGNOSTIC STRIP -->
          <footer class="mt-space-xl p-space-md bg-surface-container-lowest border border-outline-variant/40 rounded-xl shadow-lg flex flex-col md:flex-row items-center justify-between gap-space-md">
            <div class="flex items-center gap-space-sm flex-wrap">
              <span class="inline-block w-2.5 h-2.5 rounded-full bg-secondary animate-pulse"></span>
              <span class="font-label-sm text-label-sm text-on-surface tracking-widest uppercase">STATION: BERLIN-MAIN // COMMAND DECK MATRIX ACTIVE</span>
              <span class="text-outline hidden sm:inline">•</span>
              <a href="https://info.cindypawford.com" class="font-label-sm text-label-sm text-primary hover:text-primary-fixed hover:underline font-bold flex items-center gap-1 transition-colors">
                <span>PROJECT INFORMATION</span>
                <span class="material-symbols-outlined text-[13px]">open_in_new</span>
              </a>
            </div>
            <div class="flex items-center gap-space-md text-outline font-label-sm text-label-sm flex-wrap">
              <a href="https://info.cindypawford.com" class="px-2.5 py-1 bg-surface-container hover:bg-surface-container-high border border-outline-variant/40 text-primary hover:text-on-surface rounded font-label-sm text-label-sm flex items-center gap-1 transition-colors">
                <span class="material-symbols-outlined text-xs text-secondary">info</span>
                <span>Project Information</span>
              </a>
              <span>ENCRYPTION: AES-256-GCM</span>
              <span>REPLICATION: 1,024 NODES</span>
              <span class="text-primary-fixed-dim font-bold">ALL {len(eras)} ERAS CANONICAL</span>
            </div>
          </footer>
        </div>
      </div>

      <script>
        // Filter matrix logic for Timeline
        const filterBtns = document.querySelectorAll('#archive-filter-deck .filter-btn');
        const entries = document.querySelectorAll('.timeline-entry');

        filterBtns.forEach(btn => {{
          btn.addEventListener('click', () => {{
            filterBtns.forEach(b => {{
              b.classList.remove('bg-primary-container', 'text-on-primary-container', 'font-bold', 'shadow-md');
              b.classList.add('bg-surface-container', 'text-on-surface-variant');
            }});
            btn.classList.remove('bg-surface-container', 'text-on-surface-variant');
            btn.classList.add('bg-primary-container', 'text-on-primary-container', 'font-bold', 'shadow-md');

            const cat = btn.getAttribute('data-category');
            entries.forEach(entry => {{
              if (cat === 'all' || entry.getAttribute('data-cat') === cat) {{
                entry.style.display = 'flex';
              }} else {{
                entry.style.display = 'none';
              }}
            }});
          }});
        }});

        // Dynamic synchronization with logbook.json
        fetch('./logbook.json')
          .then(res => res.json())
          .then(data => {{
            const count = data.entries ? data.entries.length : 0;
            console.log(`[CindyOS Archive] logbook.json synchronized: ${{count}} verified entries`);
            const syncBadge = document.getElementById('logbook-sync-status');
            if (syncBadge) {{
              syncBadge.textContent = `LEDGER: logbook.json (${{count}} ENTRIES VERIFIED)`;
            }}
          }})
          .catch(err => {{
            console.warn('[CindyOS Archive] logbook.json fetch fallback:', err);
          }});

        // Chiptune audio preview generator using Web Audio API
        function triggerChiptune(freq, label) {{
          const statusEl = document.getElementById('sound-status');
          if (statusEl) statusEl.textContent = 'PLAYING: ' + label;

          try {{
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {{
              const ctx = new AudioContext();
              const osc = ctx.createOscillator();
              const gain = ctx.createGain();
              osc.type = 'square';
              osc.frequency.setValueAtTime(freq, ctx.currentTime);
              gain.gain.setValueAtTime(0.08, ctx.currentTime);
              gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
              osc.connect(gain);
              gain.connect(ctx.destination);
              osc.start();
              osc.stop(ctx.currentTime + 0.36);
            }}
          }} catch(e) {{
            console.warn('AudioContext not supported yet', e);
          }}

          setTimeout(() => {{
            if (statusEl) statusEl.textContent = 'STATUS: STANDBY';
          }}, 1000);
        }}
      </script>
    </main>
  </div>
</body>
</html>
"""

    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"[SUCCESS] Digital Museum Portal compiled at {OUTPUT_HTML_PATH} ({len(eras)} eras, {len(entries)} logbook entries).")

if __name__ == "__main__":
    build_portal()
