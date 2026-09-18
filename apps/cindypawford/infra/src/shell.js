/**
 * Cindy Pawford Floating Platform Shell
 * Un-nukeable Web Component with Closed Shadow DOM Isolation
 * CindyOS "Phosphor Hound" Retro-Futuristic Espionage Terminal Aesthetic
 */
(function () {
  if (customElements.get("cindy-platform-dock")) return;

  const API_BASE = (
    (typeof window !== "undefined" && window.CINDY_API_URL) ||
    (typeof document !== "undefined" && document.querySelector('meta[name="cindy-api-url"]')?.getAttribute("content")) ||
    "https://api.cindypawford.com"
  ).replace(/\/+$/, "");

  class CindyPlatformDock extends HTMLElement {
    #shadow;
    #isOpen = false;
    #suggestions = [];
    #eraInfo = { era_id: "autumn-paws-gala-2026", is_active: true };

    constructor() {
      super();
      // Closed Shadow DOM enforces total isolation from host stylesheets
      this.#shadow = this.attachShadow({ mode: "closed" });
      this.#render();
    }

    connectedCallback() {
      this.#attachEventListeners();
      this.#fetchSuggestions();
    }

    #render() {
      this.#shadow.innerHTML = `
        <style>
          @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap');

          :host {
            all: initial !important;
            position: fixed !important;
            bottom: 24px !important;
            right: 24px !important;
            z-index: 2147483647 !important;
            display: block !important;
            font-family: "JetBrains Mono", Courier, monospace !important;
            color: #ece0d9 !important;
            box-sizing: border-box !important;
          }

          *, *::before, *::after {
            box-sizing: border-box !important;
            margin: 0;
            padding: 0;
          }

          /* Floating Dock Button: Tactile Desk Accessory Badge */
          .platform-dock-btn {
            width: 62px !important;
            height: 62px !important;
            padding: 0 !important;
            border-radius: 50% !important;
            background: #17120e !important;
            border: 2px solid #00ff66 !important;
            box-shadow: 0 0 16px rgba(0, 255, 102, 0.4), 0 4px 16px rgba(0, 0, 0, 0.8) !important;
            cursor: pointer !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.22s ease, border-color 0.22s ease !important;
            user-select: none !important;
            overflow: hidden !important;
            position: relative !important;
          }

          .platform-dock-btn:hover {
            transform: scale(1.08) !important;
            border-color: #6bff83 !important;
            box-shadow: 0 0 24px rgba(0, 255, 102, 0.65), 0 6px 20px rgba(0, 0, 0, 0.9) !important;
          }

          .platform-dock-btn:active {
            transform: scale(0.95) translate(1px, 1px) !important;
          }

          .dock-badge-icon {
            width: 100% !important;
            height: 100% !important;
            border-radius: 50% !important;
            object-fit: cover !important;
            display: block !important;
            pointer-events: none !important;
          }

          .dock-beacon-dot {
            position: absolute !important;
            bottom: 3px !important;
            right: 3px !important;
            width: 11px !important;
            height: 11px !important;
            background: #00ff66 !important;
            border: 2px solid #17120e !important;
            border-radius: 50% !important;
            box-shadow: 0 0 8px #00ff66 !important;
            animation: pulse-beacon 2s cubic-bezier(0.4, 0, 0.6, 1) infinite !important;
          }

          @keyframes pulse-beacon {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.45; transform: scale(0.85); }
          }

          /* Backdrop */
          .drawer-backdrop {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            background: rgba(13, 10, 8, 0.75) !important;
            backdrop-filter: blur(5px) !important;
            -webkit-backdrop-filter: blur(5px) !important;
            opacity: 0 !important;
            visibility: hidden !important;
            pointer-events: none !important;
            transition: opacity 0.25s ease, visibility 0.25s ease !important;
            z-index: 2147483645 !important;
          }

          .drawer-backdrop.open {
            opacity: 1 !important;
            visibility: visible !important;
            pointer-events: auto !important;
          }

          /* Main Console Panel (Desktop Slide-out Drawer / Chassis) */
          .drawer-panel {
            position: fixed !important;
            top: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            width: 580px !important;
            max-width: 95vw !important;
            height: 100vh !important;
            background: #17120e !important;
            border-left: 2px solid #00ff66 !important;
            box-shadow: -10px 0 40px rgba(0, 0, 0, 0.85), -2px 0 20px rgba(0, 255, 102, 0.18) !important;
            display: flex !important;
            flex-direction: column !important;
            transform: translateX(105%) !important;
            visibility: hidden !important;
            pointer-events: none !important;
            transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.3s !important;
            z-index: 2147483646 !important;
            overflow: hidden !important;
          }

          .drawer-panel.open {
            transform: translateX(0) !important;
            visibility: visible !important;
            pointer-events: auto !important;
          }

          /* Subtle CRT scanline overlay */
          .crt-scanlines {
            position: absolute !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            bottom: 0 !important;
            background: repeating-linear-gradient(
              to bottom,
              rgba(0, 0, 0, 0) 0px,
              rgba(0, 0, 0, 0) 2px,
              rgba(0, 0, 0, 0.25) 2px,
              rgba(0, 0, 0, 0.25) 4px
            ) !important;
            pointer-events: none !important;
            z-index: 10 !important;
            opacity: 0.65 !important;
          }

          /* Mobile Handle Bar (swipe-to-dismiss) */
          .mobile-handle {
            display: none !important;
            width: 44px !important;
            height: 5px !important;
            background: #3e3833 !important;
            border-radius: 9999px !important;
            margin: 10px auto 4px auto !important;
            flex-shrink: 0 !important;
          }

          /* Modal Chrome Header Bar */
          .drawer-header {
            padding: 12px 18px !important;
            background: #201b16 !important;
            border-bottom: 1px solid #3e3833 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            flex-shrink: 0 !important;
            user-select: none !important;
            position: relative !important;
            z-index: 2 !important;
          }

          .header-left {
            display: flex !important;
            align-items: center !important;
            gap: 10px !important;
          }

          .crt-dots {
            display: flex !important;
            align-items: center !important;
            gap: 5px !important;
          }

          .crt-dot {
            width: 10px !important;
            height: 10px !important;
            border-radius: 50% !important;
            display: inline-block !important;
          }

          .crt-dot.red { background: #ffb4ab !important; box-shadow: 0 0 5px rgba(255, 180, 171, 0.6) !important; }
          .crt-dot.amber { background: #ffb86c !important; box-shadow: 0 0 5px rgba(255, 184, 108, 0.6) !important; }
          .crt-dot.green { background: #00ff66 !important; box-shadow: 0 0 5px rgba(0, 255, 102, 0.6) !important; }

          .drawer-title-group {
            display: flex !important;
            align-items: center !important;
            gap: 7px !important;
          }

          .drawer-glyph {
            color: #ffb86c !important;
            font-size: 14px !important;
            line-height: 1 !important;
          }

          .drawer-title {
            font-family: "Space Mono", monospace !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            color: #6bff83 !important;
            letter-spacing: -0.01em !important;
          }

          .version-chip {
            background: #241f1a !important;
            color: #ffb86c !important;
            font-family: "Space Mono", monospace !important;
            font-size: 8.5px !important;
            font-weight: 700 !important;
            padding: 1px 5px !important;
            border-radius: 2px !important;
            border: 1px solid #3e3833 !important;
            letter-spacing: 0.05em !important;
          }

          .header-right {
            display: flex !important;
            align-items: center !important;
            gap: 12px !important;
          }

          .telemetry-chip-live {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
            font-family: "Space Mono", monospace !important;
            font-size: 9px !important;
            font-weight: 700 !important;
            color: #edffe8 !important;
          }

          .pulse-green {
            width: 6px !important;
            height: 6px !important;
            background: #00ff66 !important;
            border-radius: 50% !important;
            box-shadow: 0 0 6px #00ff66 !important;
            animation: pulse-beacon 1.4s ease-in-out infinite !important;
          }

          .drawer-close-btn {
            background: #241f1a !important;
            color: #b9ccb5 !important;
            border: 1px solid #3e3833 !important;
            border-radius: 3px !important;
            padding: 5px 10px !important;
            font-family: "Space Mono", monospace !important;
            font-size: 10px !important;
            font-weight: 700 !important;
            letter-spacing: 0.05em !important;
            cursor: pointer !important;
            transition: all 0.15s ease !important;
          }

          .drawer-close-btn:hover {
            background: rgba(255, 180, 171, 0.18) !important;
            color: #ffb4ab !important;
            border-color: #ffb4ab !important;
          }

          /* Drawer Scrollable Body Inner Deck */
          .drawer-body {
            padding: 18px !important;
            overflow-y: auto !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 18px !important;
            flex: 1 !important;
            position: relative !important;
            z-index: 2 !important;
            scroll-behavior: smooth !important;
          }

          .drawer-body::-webkit-scrollbar {
            width: 6px !important;
          }
          .drawer-body::-webkit-scrollbar-track {
            background: #17120e !important;
          }
          .drawer-body::-webkit-scrollbar-thumb {
            background: #2f2924 !important;
            border-radius: 3px !important;
          }
          .drawer-body::-webkit-scrollbar-thumb:hover {
            background: #3e3833 !important;
          }

          /* 1. TOP SECTION: PROMINENT ENLARGE CINDY ILLUSTRATION & OPERATOR HEADLINE */
          .operator-card {
            background: #201b16 !important;
            border: 1px solid #3e3833 !important;
            border-radius: 10px !important;
            padding: 16px !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            text-align: center !important;
            gap: 12px !important;
            box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.6) !important;
            position: relative !important;
          }

          .operator-dialtone-strip {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 6px !important;
            flex-wrap: wrap !important;
            background: #241f1a !important;
            border: 1px solid #3e3833 !important;
            border-radius: 9999px !important;
            padding: 4px 12px !important;
            font-family: "Space Mono", monospace !important;
            font-size: 8.5px !important;
            letter-spacing: 0.05em !important;
            color: #ffb86c !important;
          }

          .operator-dialtone-strip .ping-dot {
            width: 6px !important;
            height: 6px !important;
            background: #00ff66 !important;
            border-radius: 50% !important;
            box-shadow: 0 0 6px #00ff66 !important;
            animation: pulse-beacon 1.2s infinite !important;
          }

          /* Distinctive Retro CRT Border Housing Cindy Illustration Centered & Enlarged */
          .operator-crt-chassis {
            position: relative !important;
            margin: 4px 0 !important;
          }

          .operator-crt-glow {
            position: absolute !important;
            inset: -4px !important;
            border-radius: 16px !important;
            background: linear-gradient(135deg, rgba(255, 184, 108, 0.3) 0%, rgba(0, 255, 102, 0.25) 50%, rgba(0, 229, 255, 0.2) 100%) !important;
            filter: blur(8px) !important;
            opacity: 0.8 !important;
          }

          .operator-avatar-box {
            position: relative !important;
            width: 170px !important;
            height: 170px !important;
            border-radius: 14px !important;
            padding: 8px !important;
            background: #120d09 !important;
            border: 2px solid rgba(255, 184, 108, 0.6) !important;
            box-shadow: 0 0 28px rgba(0, 255, 102, 0.15), inset 0 0 16px rgba(0, 0, 0, 0.9) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            overflow: hidden !important;
          }

          /* CRT Corner Accents */
          .crt-corner {
            position: absolute !important;
            font-family: "Space Mono", monospace !important;
            font-size: 7.5px !important;
            line-height: 1 !important;
            pointer-events: none !important;
            user-select: none !important;
          }

          .crt-corner.tl { top: 3px !important; left: 5px !important; color: #ffb86c !important; }
          .crt-corner.tr { top: 3px !important; right: 5px !important; color: #00ff66 !important; }
          .crt-corner.bl { bottom: 3px !important; left: 5px !important; color: #849581 !important; }
          .crt-corner.br { bottom: 3px !important; right: 5px !important; color: #ffdcbc !important; }

          .operator-avatar-img {
            width: 100% !important;
            height: 100% !important;
            border-radius: 10px !important;
            object-fit: cover !important;
            border: 1px solid #3e3833 !important;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.7) !important;
          }

          .operator-live-badge {
            position: absolute !important;
            bottom: 6px !important;
            left: 50% !important;
            transform: translateX(-50%) !important;
            background: rgba(18, 13, 9, 0.92) !important;
            border: 1px solid rgba(0, 255, 102, 0.5) !important;
            color: #6bff83 !important;
            font-family: "Space Mono", monospace !important;
            font-size: 7.5px !important;
            font-weight: 700 !important;
            letter-spacing: 0.08em !important;
            padding: 2px 8px !important;
            border-radius: 9999px !important;
            display: flex !important;
            align-items: center !important;
            gap: 4px !important;
            white-space: nowrap !important;
            backdrop-filter: blur(4px) !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.8) !important;
          }

          .rec-ping {
            width: 5px !important;
            height: 5px !important;
            background: #00ff66 !important;
            border-radius: 50% !important;
            animation: pulse-beacon 1s infinite !important;
          }

          .operator-headline {
            font-family: "Space Mono", monospace !important;
            font-size: 15px !important;
            font-weight: 700 !important;
            color: #ece0d9 !important;
            letter-spacing: -0.01em !important;
          }

          .operator-headline .hl-green {
            color: #00ff66 !important;
            text-decoration: underline !important;
            text-decoration-color: rgba(0, 255, 102, 0.6) !important;
            text-shadow: 0 0 10px rgba(0, 255, 102, 0.4) !important;
          }

          .operator-copy {
            font-size: 11.5px !important;
            line-height: 1.5 !important;
            color: #b9ccb5 !important;
            max-width: 480px !important;
          }

          .operator-chips {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 6px !important;
            flex-wrap: wrap !important;
            margin-top: 2px !important;
          }

          .operator-chip {
            font-family: "Space Mono", monospace !important;
            font-size: 8.5px !important;
            font-weight: 700 !important;
            padding: 3px 8px !important;
            background: #241f1a !important;
            border: 1px solid #3e3833 !important;
            border-radius: 3px !important;
            letter-spacing: 0.04em !important;
          }

          .operator-chip.cindy { color: #d0e69f !important; }
          .operator-chip.uplink { color: #ffb86c !important; }
          .operator-chip.sandbox { color: #00ff66 !important; }

          /* 2. COMMUNITY FEATURE DISPATCH (INPUT & UPVOTE FEED) */
          .section-block {
            background: #201b16 !important;
            border: 1px solid #3e3833 !important;
            border-radius: 10px !important;
            padding: 16px !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 14px !important;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4) !important;
          }

          .section-header-row {
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            gap: 8px !important;
            padding-bottom: 6px !important;
            border-bottom: 1px solid rgba(62, 56, 51, 0.6) !important;
            flex-wrap: wrap !important;
          }

          .section-title-wrap {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
          }

          .section-heading {
            font-family: "Space Mono", monospace !important;
            font-size: 12.5px !important;
            font-weight: 700 !important;
            color: #edffe8 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.04em !important;
          }

          .section-tag {
            font-family: "Space Mono", monospace !important;
            font-size: 9px !important;
            color: #ffb86c !important;
            letter-spacing: 0.06em !important;
          }

          .section-status-right {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
            font-family: "Space Mono", monospace !important;
            font-size: 8.5px !important;
          }

          .section-status-right .voting-open {
            color: #6bff83 !important;
            display: flex !important;
            align-items: center !important;
            gap: 4px !important;
          }

          /* Terminal Dispatch Input Box */
          .dispatch-box {
            background: #120d09 !important;
            border: 1px solid #3e3833 !important;
            border-radius: 8px !important;
            padding: 12px !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
            box-shadow: inset 0 0 14px rgba(0, 0, 0, 0.8) !important;
          }

          .dispatch-input-header {
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            font-family: "Space Mono", monospace !important;
            font-size: 9.5px !important;
          }

          .input-prompt-label {
            color: #ffb86c !important;
            font-weight: 700 !important;
          }

          .char-counter {
            color: #849581 !important;
            font-size: 9px !important;
            font-family: "Space Mono", monospace !important;
          }

          .char-counter.limit {
            color: #ffb4ab !important;
            font-weight: 700 !important;
          }

          .dispatch-input-row {
            display: flex !important;
            gap: 8px !important;
            align-items: stretch !important;
          }

          .input-shell-wrap {
            flex: 1 !important;
            display: flex !important;
            align-items: center !important;
            background: #201b16 !important;
            border: 1px solid #3e3833 !important;
            border-radius: 4px !important;
            padding: 0 10px !important;
            min-height: 44px !important;
            transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
          }

          .input-shell-wrap:focus-within {
            border-color: #00ff66 !important;
            box-shadow: 0 0 12px rgba(0, 255, 102, 0.3) !important;
          }

          .input-prefix {
            color: #00ff66 !important;
            font-family: "JetBrains Mono", monospace !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            margin-right: 6px !important;
            user-select: none !important;
          }

          .dispatch-input {
            flex: 1 !important;
            background: transparent !important;
            border: none !important;
            outline: none !important;
            color: #6bff83 !important;
            font-family: "JetBrains Mono", monospace !important;
            font-size: 13px !important;
            padding: 6px 0 !important;
            min-height: 40px !important;
          }

          .dispatch-input::placeholder {
            color: #6e6459 !important;
            font-size: 11.5px !important;
          }

          .crt-cursor {
            display: inline-block !important;
            width: 7px !important;
            height: 14px !important;
            background: #00ff66 !important;
            margin-left: 4px !important;
            animation: blink 1s step-end infinite !important;
          }

          @keyframes blink {
            0%, 49% { opacity: 1; }
            50%, 100% { opacity: 0; }
          }

          .dispatch-submit-btn {
            background: #00ff66 !important;
            color: #120d09 !important;
            border: none !important;
            border-radius: 4px !important;
            padding: 0 16px !important;
            font-family: "Space Mono", monospace !important;
            font-size: 11px !important;
            font-weight: 700 !important;
            letter-spacing: 0.06em !important;
            text-transform: uppercase !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 6px !important;
            cursor: pointer !important;
            min-height: 44px !important;
            box-shadow: 0 0 14px rgba(0, 255, 102, 0.4) !important;
            transition: all 0.15s ease !important;
            white-space: nowrap !important;
          }

          .dispatch-submit-btn:hover {
            background: #6bff83 !important;
            box-shadow: 0 0 20px rgba(0, 255, 102, 0.65) !important;
            transform: translateY(-1px) !important;
          }

          .dispatch-submit-btn:active {
            transform: translateY(1px) !important;
          }

          .form-message {
            font-size: 10.5px !important;
            padding-top: 4px !important;
            display: none !important;
            font-family: "Space Mono", monospace !important;
          }

          .form-message.success {
            display: block !important;
            color: #00ff66 !important;
          }

          .form-message.error {
            display: block !important;
            color: #ffb4ab !important;
          }

          /* Dispatches List & Upvotes */
          .dispatches-header-row {
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            font-family: "Space Mono", monospace !important;
            font-size: 9px !important;
            color: #b9ccb5 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.08em !important;
            padding: 4px 2px 0 2px !important;
          }

          .dispatches-list {
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
          }

          .dispatch-card {
            background: #17120e !important;
            border: 1px solid #3e3833 !important;
            border-radius: 6px !important;
            padding: 10px 12px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            gap: 12px !important;
            transition: border-color 0.15s ease, background-color 0.15s ease !important;
          }

          .dispatch-card:hover {
            border-color: #5c5248 !important;
            background: #241f1a !important;
          }

          .dispatch-card-left {
            display: flex !important;
            align-items: center !important;
            gap: 10px !important;
            min-width: 0 !important;
            flex: 1 !important;
          }

          .upvote-btn {
            background: #241f1a !important;
            border: 1px solid rgba(62, 56, 51, 0.8) !important;
            border-radius: 4px !important;
            color: #edffe8 !important;
            font-family: "Space Mono", monospace !important;
            font-size: 10px !important;
            font-weight: 700 !important;
            padding: 6px 10px !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            min-width: 44px !important;
            min-height: 44px !important;
            cursor: pointer !important;
            transition: all 0.15s ease !important;
          }

          .upvote-btn:hover {
            background: #00ff66 !important;
            color: #17120e !important;
            box-shadow: 0 0 12px rgba(0, 255, 102, 0.45) !important;
          }

          .upvote-btn .up-arrow {
            color: #ffb86c !important;
            font-size: 10px !important;
            line-height: 1 !important;
            transition: color 0.15s ease !important;
          }

          .upvote-btn:hover .up-arrow {
            color: #17120e !important;
          }

          .upvote-btn .v-count {
            font-size: 12px !important;
            font-weight: 700 !important;
          }

          .dispatch-text-col {
            display: flex !important;
            flex-direction: column !important;
            gap: 2px !important;
            min-width: 0 !important;
          }

          .dispatch-text {
            font-size: 12px !important;
            color: #ece0d9 !important;
            font-weight: 700 !important;
            line-height: 1.35 !important;
            word-break: break-word !important;
          }

          .dispatch-meta {
            font-family: "Space Mono", monospace !important;
            font-size: 8.5px !important;
            color: #849581 !important;
          }

          .dispatch-status-badge {
            font-family: "Space Mono", monospace !important;
            font-size: 8.5px !important;
            font-weight: 700 !important;
            padding: 4px 8px !important;
            border-radius: 3px !important;
            white-space: nowrap !important;
            letter-spacing: 0.04em !important;
          }

          .status-triage {
            background: rgba(255, 184, 108, 0.15) !important;
            color: #ffb86c !important;
            border: 1px solid rgba(255, 184, 108, 0.35) !important;
          }

          .status-queue {
            background: rgba(0, 255, 102, 0.15) !important;
            color: #6bff83 !important;
            border: 1px solid rgba(0, 255, 102, 0.35) !important;
          }

          .status-chip {
            background: rgba(208, 230, 159, 0.18) !important;
            color: #d0e69f !important;
            border: 1px solid rgba(208, 230, 159, 0.4) !important;
          }

          .empty-state {
            text-align: center !important;
            padding: 16px !important;
            font-size: 11px !important;
            color: #849581 !important;
            font-family: "JetBrains Mono", monospace !important;
          }

          /* 3. QUICK-ACTION CARDS DOCK (3-COLUMN DESKTOP / 1-COLUMN MOBILE) */
          .quick-actions-grid {
            display: grid !important;
            grid-template-columns: repeat(3, 1fr) !important;
            gap: 12px !important;
          }

          .action-dock-card {
            background: #201b16 !important;
            border: 1px solid #3e3833 !important;
            border-radius: 8px !important;
            padding: 12px !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: space-between !important;
            gap: 10px !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4) !important;
          }

          .dock-card-header {
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            gap: 4px !important;
          }

          .dock-card-title {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
            font-family: "Space Mono", monospace !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            color: #ece0d9 !important;
          }

          .dock-card-badge {
            font-family: "Space Mono", monospace !important;
            font-size: 8px !important;
            padding: 2px 6px !important;
            border-radius: 9999px !important;
            letter-spacing: 0.05em !important;
            white-space: nowrap !important;
          }

          .dock-card-badge.green {
            background: rgba(0, 255, 102, 0.1) !important;
            color: #6bff83 !important;
            border: 1px solid rgba(0, 255, 102, 0.25) !important;
            display: flex !important;
            align-items: center !important;
            gap: 4px !important;
          }

          .dock-card-badge.vault {
            color: #b9ccb5 !important;
          }

          .dock-card-badge.brief {
            color: #d0e69f !important;
          }

          .dock-button-stack {
            display: flex !important;
            flex-direction: column !important;
            gap: 6px !important;
          }

          .dock-nav-btn {
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            background: #241f1a !important;
            border: 1px solid #3e3833 !important;
            border-radius: 4px !important;
            padding: 8px 10px !important;
            font-family: "Space Mono", monospace !important;
            font-size: 9.5px !important;
            font-weight: 700 !important;
            color: #ece0d9 !important;
            text-decoration: none !important;
            min-height: 44px !important;
            cursor: pointer !important;
            transition: all 0.15s ease !important;
          }

          .dock-nav-btn:hover {
            background: #2f2924 !important;
            border-color: #00ff66 !important;
            color: #00ff66 !important;
          }

          .dock-nav-btn.primary-action {
            background: #2f2924 !important;
            color: #ffb86c !important;
            border-color: #5c5248 !important;
          }

          .dock-nav-btn.primary-action:hover {
            background: #ffb86c !important;
            color: #17120e !important;
            border-color: #ffdcbc !important;
            box-shadow: 0 0 12px rgba(255, 184, 108, 0.4) !important;
          }

          .dock-btn-label-group {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
          }

          .research-mini-box {
            background: #17120e !important;
            border: 1px solid #3e3833 !important;
            border-radius: 4px !important;
            padding: 8px !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 4px !important;
          }

          .research-mini-title {
            font-family: "JetBrains Mono", monospace !important;
            font-size: 10px !important;
            font-weight: 700 !important;
            color: #d0e69f !important;
            line-height: 1.3 !important;
          }

          .research-mini-metrics {
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            font-family: "Space Mono", monospace !important;
            font-size: 8px !important;
            color: #849581 !important;
          }

          /* 4. TERMINAL FOOTER STATUS BAR */
          .drawer-footer {
            padding: 10px 18px !important;
            background: #120d09 !important;
            border-top: 1px solid #3e3833 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: space-between !important;
            font-family: "Space Mono", monospace !important;
            font-size: 8.5px !important;
            color: #849581 !important;
            flex-shrink: 0 !important;
            gap: 8px !important;
            flex-wrap: wrap !important;
            position: relative !important;
            z-index: 2 !important;
          }

          .drawer-footer .left-status {
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
            flex-wrap: wrap !important;
          }

          .drawer-footer .right-status {
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
          }

          .drawer-footer .ready-tag {
            color: #00ff66 !important;
            font-weight: 700 !important;
          }

          /* MOBILE RESPONSIVE OPTIMIZATION (< 768px) */
          @media (max-width: 768px) {
            :host {
              bottom: calc(16px + env(safe-area-inset-bottom, 0px)) !important;
              right: calc(16px + env(safe-area-inset-right, 0px)) !important;
            }

            .platform-dock-btn {
              width: 58px !important;
              height: 58px !important;
              touch-action: manipulation !important;
              -webkit-tap-highlight-color: transparent !important;
            }

            .platform-dock-btn.hidden-when-open {
              opacity: 0 !important;
              pointer-events: none !important;
              transform: scale(0.8) !important;
            }

            .drawer-panel {
              top: auto !important;
              left: 0 !important;
              right: 0 !important;
              bottom: 0 !important;
              width: 100vw !important;
              max-width: 100vw !important;
              height: 88vh !important;
              height: 88dvh !important;
              max-height: 88vh !important;
              max-height: 88dvh !important;
              border-radius: 16px 16px 0 0 !important;
              border-left: none !important;
              border-top: 2px solid #00ff66 !important;
              box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.9), 0 -2px 16px rgba(0, 255, 102, 0.2) !important;
              transform: translateY(105%) !important;
              transition: transform 0.28s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.28s !important;
            }

            .drawer-panel.open {
              transform: translateY(0) !important;
              visibility: visible !important;
              pointer-events: auto !important;
            }

            .mobile-handle {
              display: block !important;
              cursor: grab !important;
              touch-action: none !important;
            }

            .drawer-header {
              padding: 10px 14px !important;
              touch-action: none !important;
            }

            .drawer-close-btn {
              min-height: 38px !important;
              padding: 6px 12px !important;
              font-size: 11px !important;
              touch-action: manipulation !important;
            }

            .drawer-body {
              padding: 12px !important;
              padding-bottom: calc(28px + env(safe-area-inset-bottom, 0px)) !important;
              gap: 14px !important;
            }

            /* Operator card on mobile: scaled gracefully */
            .operator-avatar-box {
              width: 130px !important;
              height: 130px !important;
              padding: 6px !important;
            }

            .operator-headline {
              font-size: 13px !important;
            }

            .operator-copy {
              font-size: 10.5px !important;
              line-height: 1.4 !important;
            }

            .operator-chips {
              gap: 4px !important;
            }

            .operator-chip {
              font-size: 7.5px !important;
              padding: 2px 6px !important;
            }

            /* Input box on mobile: font-size 16px to prevent iOS auto-zoom */
            .dispatch-input {
              font-size: 16px !important;
            }

            .dispatch-input-row {
              flex-direction: column !important;
              gap: 8px !important;
            }

            .dispatch-submit-btn {
              width: 100% !important;
              min-height: 44px !important;
              touch-action: manipulation !important;
            }

            /* 1-Column Stacking for Quick Actions */
            .quick-actions-grid {
              grid-template-columns: 1fr !important;
              gap: 10px !important;
            }

            .dock-nav-btn {
              min-height: 44px !important;
              touch-action: manipulation !important;
            }

            .upvote-btn {
              min-width: 44px !important;
              min-height: 44px !important;
              touch-action: manipulation !important;
            }
          }
        </style>

        <div class="drawer-backdrop" id="backdrop"></div>

        <button class="platform-dock-btn" id="dock-btn" aria-label="Cindy Console" title="Open Cindy Console">
          <img src="/assets/cindy_desk_support.jpg" onerror="this.src='https://lh3.googleusercontent.com/aida-public/AB6AXuCZfQtUKKEiO9NLea7VLN-QY_ZJOXf9dRb3w1JR14PfOTG1CQFmgfR7FeaY8DGSaOdovMpaONXxwOOdDUnqL-t8h19yW054Ds66jXzbWafi5406IRLxpZn1lB1rAzgj0iPhBWv_57U9kUSySEtWdiQTX4USe_Uvd8_1L1cgY-auKnHaqUJQd62SkoDlePpX_nTWXNDCgQCQ-7Eq4MjB-BvS2Kl2V1S3TBxNWT_396k7tr-Bl7kajdFVXiKLSTombPFW'" alt="Cindy Console" class="dock-badge-icon" />
          <span class="dock-beacon-dot"></span>
        </button>

        <aside class="drawer-panel" id="drawer" role="dialog" aria-modal="true" aria-hidden="true">
          <div class="crt-scanlines"></div>
          <div class="mobile-handle"></div>

          <div class="drawer-header">
            <div class="header-left">
              <div class="crt-dots">
                <span class="crt-dot red"></span>
                <span class="crt-dot amber"></span>
                <span class="crt-dot green"></span>
              </div>
              <div class="drawer-title-group">
                <span class="drawer-glyph">❖</span>
                <h2 class="drawer-title">Cindy Console</h2>
                <span class="version-chip">[WHITE_HAT_OPERATOR // VARIANT A]</span>
              </div>
            </div>
            <div class="header-right">
              <div class="telemetry-chip-live">
                <span class="pulse-green"></span>
                <span>CH_07::ONLINE</span>
              </div>
              <button class="drawer-close-btn" id="close-btn" aria-label="Close Cindy Console">[✕] DISMISS</button>
            </div>
          </div>

          <div class="drawer-body">
            <!-- 1. Top Section: Prominent Enlarge Cindy Illustration Placed Above Operator Headline -->
            <div class="operator-card">
              <div class="operator-dialtone-strip">
                <span class="ping-dot"></span>
                <span style="color:#00ff66;font-weight:700;">● DIALTONE ACQUIRED</span>
                <span style="color:#6e6459;">//</span>
                <span>CANINE OPERATOR DESK</span>
                <span style="color:#6e6459;">//</span>
                <span style="color:#00e5ff;">CH_07::DUPLEX_CARRIER_ONLINE</span>
              </div>

              <!-- Distinctive Retro CRT Border Housing Cindy Illustration Centered & Enlarged -->
              <div class="operator-crt-chassis">
                <div class="operator-crt-glow"></div>
                <div class="operator-avatar-box">
                  <span class="crt-corner tl">┌ REC_TAPE</span>
                  <span class="crt-corner tr">9600_BAUD ┐</span>
                  <span class="crt-corner bl">└ CH_SEC</span>
                  <span class="crt-corner br">0-DAY_PATCH ┘</span>
                  <img src="/assets/cindy_desk_support.jpg" onerror="this.src='https://lh3.googleusercontent.com/aida-public/AB6AXuCZfQtUKKEiO9NLea7VLN-QY_ZJOXf9dRb3w1JR14PfOTG1CQFmgfR7FeaY8DGSaOdovMpaONXxwOOdDUnqL-t8h19yW054Ds66jXzbWafi5406IRLxpZn1lB1rAzgj0iPhBWv_57U9kUSySEtWdiQTX4USe_Uvd8_1L1cgY-auKnHaqUJQd62SkoDlePpX_nTWXNDCgQCQ-7Eq4MjB-BvS2Kl2V1S3TBxNWT_396k7tr-Bl7kajdFVXiKLSTombPFW'" alt="Cindy Pawford, white hat canine operator" class="operator-avatar-img" />
                  <div class="operator-live-badge">
                    <span class="rec-ping"></span>
                    <span>REC // LIVE OPERATOR</span>
                  </div>
                </div>
              </div>

              <h3 class="operator-headline">
                OPERATOR STATUS: <span class="hl-green">ON THE LINE</span>
              </h3>
              <p class="operator-copy">
                Benevolent systems auditor, zero-day patcher, and digital canine operator. Have you tried power-cycling your chassis, patting the mainframe, or offering positive reinforcement?
              </p>
              <div class="operator-chips">
                <span class="operator-chip cindy">OPERATOR: CINDY PAWFORD</span>
                <span class="operator-chip uplink">BERLIN_UPLINK::44.1MHz</span>
                <span class="operator-chip sandbox">SANDBOX: ZERO-TRUST SHIELDED</span>
              </div>
            </div>

            <!-- 2. Hero Call to Action: REQUEST A FEATURE / DISPATCH IMPROVEMENT -->
            <div class="section-block">
              <div class="section-header-row">
                <div class="section-title-wrap">
                  <span style="color:#00ff66;font-size:13px;font-weight:700;">➔</span>
                  <h3 class="section-heading">REQUEST A FEATURE / DISPATCH IMPROVEMENT</h3>
                </div>
                <div class="section-status-right">
                  <span class="section-tag">// COMMUNITY DISPATCH HUB</span>
                  <span style="color:#3e3833;">|</span>
                  <span class="voting-open">
                    <span class="pulse-green"></span>
                    <span>VOTING OPEN</span>
                  </span>
                </div>
              </div>

              <!-- Interactive Terminal Dispatch Input Box -->
              <form class="dispatch-box" id="suggest-form">
                <div class="dispatch-input-header">
                  <div class="input-prompt-label">
                    <span style="color:#00ff66;">&gt;</span>
                    <span>submit_dispatch:</span>
                    <span style="color:#849581;font-weight:400;">[DIRECT TO WHITE HAT OPERATOR BUFFER]</span>
                  </div>
                  <span class="char-counter" id="char-counter">[ 140 CHARS REMAINING ]</span>
                </div>
                <div class="dispatch-input-row">
                  <div class="input-shell-wrap">
                    <span class="input-prefix">#</span>
                    <input type="text" class="dispatch-input" id="suggest-input" maxlength="140" placeholder="Dispatch a feature, zero-day suggestion, or enhancement tape ID..." autocomplete="off" />
                    <span class="crt-cursor"></span>
                  </div>
                  <button type="submit" class="dispatch-submit-btn" id="submit-suggest">
                    <span>[DISPATCH TO CINDY ➔]</span>
                  </button>
                </div>
                <div class="form-message" id="form-message"></div>
              </form>

              <!-- Prominent Community Feature Voting Stream -->
              <div class="dispatches-header-row">
                <span>TOP-RANKED OPERATOR DISPATCHES &amp; COMMUNITY AUDITS</span>
                <span style="color:#849581;">SORT: BY CONSENSUS VOTES</span>
              </div>
              <div class="dispatches-list" id="suggestions-container">
                <div class="empty-state">Loading active dispatches from edge relay...</div>
              </div>
            </div>

            <!-- 3. Streamlined Action Menu Bars: Talk to Cindy, Era Archive & Project Information -->
            <div class="quick-actions-grid">
              <!-- Dock Card 1: Talk to Cindy -->
              <div class="action-dock-card">
                <div class="dock-card-header">
                  <div class="dock-card-title">
                    <span style="color:#ffb86c;">➔</span>
                    <span>Talk to Cindy</span>
                  </div>
                  <span class="dock-card-badge green">
                    <span class="pulse-green"></span>
                    <span>EDGE LIVE</span>
                  </span>
                </div>
                <div class="dock-button-stack">
                  <a href="https://t.me/CindyPawford_bot" target="_blank" rel="noopener noreferrer" class="dock-nav-btn primary-action">
                    <div class="dock-btn-label-group">
                      <span>✉</span>
                      <span>[➔ CONNECT TELEGRAM SECURE UPLINK]</span>
                    </div>
                    <span>➔</span>
                  </a>
                  <button type="button" class="dock-nav-btn" id="direct-dispatch-btn">
                    <div class="dock-btn-label-group">
                      <span>⌨</span>
                      <span>[➔ OPEN DIRECT OPERATOR DISPATCH]</span>
                    </div>
                    <span>➔</span>
                  </button>
                </div>
              </div>

              <!-- Dock Card 2: Era Archive -->
              <div class="action-dock-card">
                <div class="dock-card-header">
                  <div class="dock-card-title">
                    <span style="color:#ffb86c;">▲</span>
                    <span>Era Archive</span>
                  </div>
                  <span class="dock-card-badge vault">// IMMUTABLE VAULT</span>
                </div>
                <div class="dock-button-stack">
                  <a href="https://archive.cindypawford.com" target="_blank" rel="noopener" class="dock-nav-btn">
                    <div class="dock-btn-label-group">
                      <span>🏛️</span>
                      <span>[HISTORICAL VAULT &amp; ERAS ➔]</span>
                    </div>
                    <span style="color:#00ff66;">➔</span>
                  </a>
                  <a href="https://archive.cindypawford.com/2024-genesis/" target="_blank" rel="noopener" class="dock-nav-btn">
                    <div class="dock-btn-label-group">
                      <span>📜</span>
                      <span>Era 1: 2024 Genesis Archive</span>
                    </div>
                    <span style="color:#ffb86c;">➔</span>
                  </a>
                </div>
              </div>

              <!-- Dock Card 3: Project Information -->
              <div class="action-dock-card">
                <div class="dock-card-header">
                  <div class="dock-card-title">
                    <span style="color:#00e5ff;">::</span>
                    <span>Project Information</span>
                  </div>
                  <span class="dock-card-badge brief">// RESEARCH BRIEF</span>
                </div>
                <div class="research-mini-box">
                  <div class="research-mini-title">Safe, Green AI on Edge Silicon // Patterns at Scale</div>
                  <div class="research-mini-metrics">
                    <span>UNIFIED MEMORY: 16 GB</span>
                    <span style="color:#00ff66;font-weight:700;">4.8W LOW POWER</span>
                  </div>
                </div>
                <a href="https://info.cindypawford.com" target="_blank" rel="noopener" class="dock-nav-btn">
                  <div class="dock-btn-label-group">
                    <span>🌱</span>
                    <span>[LEARN MORE ➔]</span>
                  </div>
                  <span style="color:#00ff66;">➔</span>
                </a>
              </div>
            </div>
          </div>

          <!-- Terminal Footer Status Bar -->
          <div class="drawer-footer">
            <div class="left-status">
              <span>TERMINAL_SESSION: #409-WHITE-HAT-MAIN</span>
              <span style="color:#3e3833;">|</span>
              <span>ENCRYPTION: HARDWARE_TPM_V2</span>
              <span style="color:#3e3833;">|</span>
              <span>STATUS: BENEVOLENT_DEFENSE</span>
            </div>
            <div class="right-status">
              <span style="color:#ffb86c;">●</span>
              <span>SYSTEM VOLTAGE: 5.02V</span>
              <span style="color:#3e3833;">|</span>
              <span class="ready-tag">READY_FOR_COMMUNITY_DISPATCH</span>
            </div>
          </div>
        </aside>
      `;
    }

    #attachEventListeners() {
      const dockBtn = this.#shadow.getElementById("dock-btn");
      const closeBtn = this.#shadow.getElementById("close-btn");
      const backdrop = this.#shadow.getElementById("backdrop");
      const suggestForm = this.#shadow.getElementById("suggest-form");
      const suggestInput = this.#shadow.getElementById("suggest-input");
      const charCounter = this.#shadow.getElementById("char-counter");
      const directDispatchBtn = this.#shadow.getElementById("direct-dispatch-btn");

      if (dockBtn) dockBtn.addEventListener("click", () => this.#toggleDrawer(true));
      if (closeBtn) closeBtn.addEventListener("click", () => this.#toggleDrawer(false));
      if (backdrop) backdrop.addEventListener("click", () => this.#toggleDrawer(false));

      if (directDispatchBtn && suggestInput) {
        directDispatchBtn.addEventListener("click", () => {
          suggestInput.focus();
          suggestInput.placeholder = "Dispatch ready: enter proposal for White Hat Operator Cindy...";
        });
      }

      if (suggestInput && charCounter) {
        suggestInput.addEventListener("input", () => {
          const remaining = 140 - suggestInput.value.length;
          charCounter.textContent = `[ ${remaining} CHARS REMAINING ]`;
          if (remaining < 20) {
            charCounter.classList.add("limit");
          } else {
            charCounter.classList.remove("limit");
          }
        });
      }

      if (suggestForm) {
        suggestForm.addEventListener("submit", async (e) => {
          e.preventDefault();
          await this.#handleSubmitSuggestion();
        });
      }

      // Close on Escape key
      window.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && this.#isOpen) {
          this.#toggleDrawer(false);
        }
      });

      // Mobile swipe down to dismiss gesture on handle & header
      const drawer = this.#shadow.getElementById("drawer");
      const mobileHandle = this.#shadow.querySelector(".mobile-handle");
      const drawerHeader = this.#shadow.querySelector(".drawer-header");
      let startY = 0;
      let currentY = 0;
      let isSwiping = false;

      const onTouchStart = (e) => {
        if (window.innerWidth > 768) return;
        startY = e.touches[0].clientY;
        currentY = startY;
        isSwiping = true;
      };

      const onTouchMove = (e) => {
        if (!isSwiping || window.innerWidth > 768) return;
        currentY = e.touches[0].clientY;
        const diff = currentY - startY;
        if (diff > 0 && drawer) {
          drawer.style.transform = `translateY(${diff}px)`;
          drawer.style.transition = "none";
        }
      };

      const onTouchEnd = () => {
        if (!isSwiping || window.innerWidth > 768) return;
        isSwiping = false;
        const diff = currentY - startY;
        if (drawer) {
          drawer.style.transition = "";
          drawer.style.transform = "";
        }
        if (diff > 75) {
          this.#toggleDrawer(false);
        }
      };

      if (mobileHandle) {
        mobileHandle.addEventListener("touchstart", onTouchStart, { passive: true });
        mobileHandle.addEventListener("touchmove", onTouchMove, { passive: true });
        mobileHandle.addEventListener("touchend", onTouchEnd, { passive: true });
      }
      if (drawerHeader) {
        drawerHeader.addEventListener("touchstart", onTouchStart, { passive: true });
        drawerHeader.addEventListener("touchmove", onTouchMove, { passive: true });
        drawerHeader.addEventListener("touchend", onTouchEnd, { passive: true });
      }
    }

    #toggleDrawer(open) {
      this.#isOpen = open;
      const drawer = this.#shadow.getElementById("drawer");
      const backdrop = this.#shadow.getElementById("backdrop");
      const dockBtn = this.#shadow.getElementById("dock-btn");

      if (open) {
        drawer.classList.add("open");
        backdrop.classList.add("open");
        if (dockBtn) dockBtn.classList.add("hidden-when-open");
        drawer.setAttribute("aria-hidden", "false");
        this.#fetchSuggestions();
      } else {
        drawer.classList.remove("open");
        backdrop.classList.remove("open");
        if (dockBtn) dockBtn.classList.remove("hidden-when-open");
        drawer.setAttribute("aria-hidden", "true");
      }
    }

    async #fetchSuggestions() {
      const container = this.#shadow.getElementById("suggestions-container");
      if (!container) return;
      try {
        const res = await fetch(`${API_BASE}/api/top-suggestions`);
        const contentType = res.headers ? res.headers.get("content-type") : "";
        const isJson = contentType && contentType.includes("application/json");

        if (!res.ok) {
          let errorDetail = `HTTP ${res.status}`;
          if (isJson) {
            const errData = await res.json().catch(() => null);
            if (errData && errData.error) errorDetail = errData.error;
          }
          throw new Error(`Failed to load suggestions: ${errorDetail}`);
        }

        if (!isJson) {
          throw new Error("Unexpected non-JSON response received from suggestions API");
        }

        const data = await res.json();
        this.#suggestions = data.suggestions || [];
        this.#eraInfo = { era_id: data.era_id, is_active: data.is_active };
        this.#renderSuggestions();
      } catch (err) {
        // Render fallback mock dispatches if API is unavailable during offline / development
        this.#renderFallbackSuggestions();
      }
    }

    #renderFallbackSuggestions() {
      const container = this.#shadow.getElementById("suggestions-container");
      if (!container) return;

      const defaultDispatches = [
        { id: "DSP-4091", text: "Fix or replace the sprint game with deterministic arcade mode", votes: 24, status: "IN TRIAGE", author: "@whiskey_whisker", node: "0x8f4d" },
        { id: "DSP-3810", text: "Add 24k gold embroidered dog boots for the gala runway", votes: 18, status: "QUEUED FOR AUDIT", author: "@tuxedo_pup", node: "0x3a19" },
        { id: "DSP-3302", text: "Include 8-bit chiptune MIDI sound synthesizer module", votes: 12, status: "PATCH IN PROGRESS", author: "@chiptune_collie", node: "0x9c02" },
      ];

      container.innerHTML = defaultDispatches.map((item) => {
        let statusClass = "status-triage";
        if (item.status.includes("QUEUE") || item.status.includes("AUDIT")) statusClass = "status-queue";
        if (item.status.includes("PATCH") || item.status.includes("PROGRESS")) statusClass = "status-chip";

        return `
          <div class="dispatch-card">
            <div class="dispatch-card-left">
              <button class="upvote-btn" data-id="${item.id}" data-fallback="true" aria-label="Upvote dispatch ${item.id}">
                <span class="up-arrow">▲</span>
                <span class="v-count">${item.votes}</span>
              </button>
              <div class="dispatch-text-col">
                <span class="dispatch-text">${this.#escapeHtml(item.text)}</span>
                <span class="dispatch-meta">ID: ${item.id} // SUBMITTED BY: ${this.#escapeHtml(item.author)} // NODE_SIGNATURE: ${item.node}</span>
              </div>
            </div>
            <span class="dispatch-status-badge ${statusClass}">[${item.status}]</span>
          </div>
        `;
      }).join("");

      container.querySelectorAll(".upvote-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (btn.dataset.voted) return;
          const vCount = btn.querySelector(".v-count");
          if (vCount) {
            vCount.textContent = String(parseInt(vCount.textContent || "0", 10) + 1);
            btn.dataset.voted = "true";
            btn.style.background = "#00ff66";
            btn.style.color = "#120d09";
            btn.style.boxShadow = "0 0 12px rgba(0, 255, 102, 0.5)";
          }
        });
      });
    }

    #renderSuggestions() {
      const container = this.#shadow.getElementById("suggestions-container");
      if (!container) return;

      if (!this.#suggestions || this.#suggestions.length === 0) {
        this.#renderFallbackSuggestions();
        return;
      }

      container.innerHTML = this.#suggestions
        .map((item, idx) => {
          const ticketId = `DSP-${(4000 - idx).toString()}`;
          const statuses = ["IN TRIAGE", "QUEUED FOR AUDIT", "PATCH IN PROGRESS"];
          const status = statuses[idx % statuses.length];
          let statusClass = "status-triage";
          if (status.includes("QUEUE") || status.includes("AUDIT")) statusClass = "status-queue";
          if (status.includes("PATCH") || status.includes("PROGRESS")) statusClass = "status-chip";

          return `
            <div class="dispatch-card">
              <div class="dispatch-card-left">
                <button class="upvote-btn" data-id="${item.id}" data-era="${item.era_id}" aria-label="Upvote dispatch ${ticketId}">
                  <span class="up-arrow">▲</span>
                  <span class="v-count">${item.votes || 0}</span>
                </button>
                <div class="dispatch-text-col">
                  <span class="dispatch-text">${this.#escapeHtml(item.text)}</span>
                  <span class="dispatch-meta">ID: ${ticketId} // COMMUNITY NODE // NODE_SIGNATURE: 0x${(idx * 7 + 13).toString(16)}a</span>
                </div>
              </div>
              <span class="dispatch-status-badge ${statusClass}">[${status}]</span>
            </div>
          `;
        })
        .join("");

      container.querySelectorAll(".upvote-btn").forEach((btn) => {
        btn.addEventListener("click", () => this.#handleVote(btn.dataset.id, btn.dataset.era));
      });
    }

    async #handleVote(id, eraId) {
      if (!id) return;
      try {
        const res = await fetch(`${API_BASE}/api/vote/${id}?era=${encodeURIComponent(eraId || this.#eraInfo.era_id)}`, {
          method: "POST",
        });
        const contentType = res.headers ? res.headers.get("content-type") : "";
        const isJson = contentType && contentType.includes("application/json");

        if (res.ok) {
          if (isJson) {
            const data = await res.json();
            const target = this.#suggestions.find((s) => s.id === id);
            if (target && typeof data.votes === "number") {
              target.votes = data.votes;
              this.#renderSuggestions();
            }
          }
        } else {
          let errorDetail = `HTTP ${res.status}`;
          if (isJson) {
            const errData = await res.json().catch(() => null);
            if (errData && errData.error) errorDetail = errData.error;
          }
          console.error("Vote failed:", errorDetail);
        }
      } catch (err) {
        console.error("Vote failed:", err);
      }
    }

    async #handleSubmitSuggestion() {
      const input = this.#shadow.getElementById("suggest-input");
      const msg = this.#shadow.getElementById("form-message");
      const text = input ? input.value.trim() : "";

      if (!text || !msg) return;

      msg.className = "form-message";
      msg.textContent = "TRANSMITTING DISPATCH PACKET TO OPERATOR BUFFER...";
      msg.style.display = "block";

      try {
        const res = await fetch(`${API_BASE}/api/suggest`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, era_id: this.#eraInfo.era_id }),
        });

        const contentType = res.headers ? res.headers.get("content-type") : "";
        const isJson = contentType && contentType.includes("application/json");

        if (res.ok) {
          if (isJson) {
            await res.json().catch(() => ({}));
          }
          msg.className = "form-message success";
          msg.textContent = "✓ DISPATCH RECORDED // IN OPERATOR BUFFER";
          input.value = "";
          const counter = this.#shadow.getElementById("char-counter");
          if (counter) counter.textContent = "[ 140 CHARS REMAINING ]";
          await this.#fetchSuggestions();
          setTimeout(() => {
            msg.style.display = "none";
          }, 3500);
        } else {
          let errorMessage = `Submission failed (HTTP ${res.status}).`;
          if (isJson) {
            const errData = await res.json().catch(() => null);
            if (errData && errData.error) errorMessage = errData.error;
          }
          msg.className = "form-message error";
          msg.textContent = `[✕] ${errorMessage}`;
          console.error("Suggestion submission failed with HTTP status:", res.status, errorMessage);
        }
      } catch (err) {
        // In local preview/offline, simulate successful dispatch
        msg.className = "form-message success";
        msg.textContent = "✓ DISPATCH RECORDED (LOCAL PREVIEW MODE)";
        input.value = "";
        const counter = this.#shadow.getElementById("char-counter");
        if (counter) counter.textContent = "[ 140 CHARS REMAINING ]";
        setTimeout(() => {
          msg.style.display = "none";
        }, 3500);
      }
    }

    #escapeHtml(str) {
      const div = document.createElement("div");
      div.textContent = str;
      return div.innerHTML;
    }
  }

  customElements.define("cindy-platform-dock", CindyPlatformDock);

  // Auto-mount and Un-nukeable DOM Self-Healing Observer
  function ensureDockMounted() {
    if (!document.body) return;
    if (!document.querySelector("cindy-platform-dock")) {
      const dock = document.createElement("cindy-platform-dock");
      document.body.appendChild(dock);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureDockMounted);
  } else {
    ensureDockMounted();
  }

  // MutationObserver guarantees dock cannot be nuked by agent script
  const observer = new MutationObserver(() => {
    ensureDockMounted();
  });

  if (document.body) {
    observer.observe(document.body, { childList: true });
  } else {
    document.addEventListener("DOMContentLoaded", () => {
      observer.observe(document.body, { childList: true });
    });
  }
})();
