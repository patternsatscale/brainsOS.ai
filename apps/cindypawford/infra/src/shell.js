/**
 * Cindy Pawford Floating Platform Shell
 * Un-nukeable Web Component with Closed Shadow DOM Isolation
 * Retro-Chic Aesthetic: Tactile Desk Accessory & Telegram Dispatch Vault
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
          :host {
            all: initial;
            position: fixed !important;
            bottom: 24px !important;
            right: 24px !important;
            z-index: 2147483647 !important;
            display: block !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
            color: #F5EFEB !important;
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
            background: #181512 !important;
            border: 2.5px solid #C5A059 !important;
            box-shadow: 2px 4px 14px rgba(0, 0, 0, 0.75), 0 0 16px rgba(212, 175, 55, 0.3) !important;
            cursor: pointer !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.22s ease, border-color 0.22s ease !important;
            user-select: none !important;
            overflow: hidden !important;
          }

          .platform-dock-btn:hover {
            transform: scale(1.08) !important;
            border-color: #E5C158 !important;
            box-shadow: 2px 6px 20px rgba(0, 0, 0, 0.85), 0 0 22px rgba(212, 175, 55, 0.5) !important;
          }

          .platform-dock-btn:active {
            transform: scale(0.95) translate(1px, 1px) !important;
            box-shadow: inset 1px 1px 4px rgba(0, 0, 0, 0.9), 0 2px 6px rgba(0, 0, 0, 0.6) !important;
          }

          .dock-badge-icon {
            width: 100% !important;
            height: 100% !important;
            border-radius: 50% !important;
            object-fit: cover !important;
            display: block !important;
            pointer-events: none !important;
          }

          /* Backdrop */
          .drawer-backdrop {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            background: rgba(14, 12, 10, 0.75) !important;
            backdrop-filter: blur(8px) !important;
            opacity: 0 !important;
            pointer-events: none !important;
            transition: opacity 0.3s ease !important;
            z-index: 2147483645 !important;
          }

          .drawer-backdrop.open {
            opacity: 1 !important;
            pointer-events: auto !important;
          }

          /* Slide-Out Drawer: Vintage Archive Desk Panel */
          .drawer-panel {
            position: fixed !important;
            top: 0 !important;
            right: -450px !important;
            width: 420px !important;
            max-width: calc(100vw - 24px) !important;
            height: 100vh !important;
            background: #141210 !important;
            border-left: 3px double #C5A059 !important;
            box-shadow: -14px 0 48px rgba(0, 0, 0, 0.9) !important;
            display: flex !important;
            flex-direction: column !important;
            transition: right 0.35s cubic-bezier(0.16, 1, 0.3, 1) !important;
            z-index: 2147483646 !important;
            overflow-y: auto !important;
          }

          .drawer-panel.open {
            right: 0 !important;
          }

          /* Retro Window Header */
          .drawer-header {
            padding: 16px 20px !important;
            background: linear-gradient(180deg, #241E18 0%, #171411 100%) !important;
            border-bottom: 2px solid #C5A059 !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.5) !important;
          }

          .drawer-title-group {
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
          }

          .drawer-title-icon {
            color: #C5A059 !important;
            font-size: 14px !important;
          }

          .drawer-title {
            font-family: 'Playfair Display', Georgia, serif !important;
            font-size: 15px !important;
            font-weight: 700 !important;
            letter-spacing: 0.04em !important;
            color: #F5EFEB !important;
            text-transform: uppercase !important;
          }

          .drawer-close-btn {
            background: #241E18 !important;
            border: 1px solid #C5A059 !important;
            color: #C5A059 !important;
            font-family: 'Courier New', Courier, monospace !important;
            font-size: 13px !important;
            font-weight: 700 !important;
            cursor: pointer !important;
            padding: 4px 8px !important;
            border-radius: 3px !important;
            line-height: 1 !important;
            box-shadow: 1px 1px 0 #000 !important;
            transition: all 0.15s ease !important;
          }

          .drawer-close-btn:hover {
            background: #C5A059 !important;
            color: #141210 !important;
          }

          .drawer-close-btn:active {
            transform: translate(1px, 1px) !important;
            box-shadow: inset 1px 1px 2px #000 !important;
          }

          .drawer-body {
            padding: 22px 20px !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 22px !important;
            flex: 1 !important;
          }

          /* Sections */
          .section-block {
            display: flex !important;
            flex-direction: column !important;
            gap: 10px !important;
          }

          .section-header-row {
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            border-bottom: 1px dashed #3D3226 !important;
            padding-bottom: 5px !important;
          }

          .section-heading {
            font-family: 'Playfair Display', Georgia, serif !important;
            font-size: 13.5px !important;
            font-weight: 700 !important;
            letter-spacing: 0.06em !important;
            color: #C5A059 !important;
            text-transform: uppercase !important;
          }

          .section-tag {
            font-family: 'SF Mono', 'Courier New', monospace !important;
            font-size: 9.5px !important;
            color: #A89880 !important;
            letter-spacing: 0.08em !important;
            text-transform: uppercase !important;
          }

          /* Project Information Card ("Learn More") */
          .info-card-btn {
            background: #1B1713 !important;
            border: 1px solid #3D3226 !important;
            border-left: 3px solid #2AABEE !important;
            padding: 12px 14px !important;
            text-decoration: none !important;
            display: block !important;
            border-radius: 4px !important;
            box-shadow: 1px 1px 0 #000 !important;
            transition: all 0.2s ease !important;
          }

          .info-card-btn:hover {
            background: #221D17 !important;
            border-color: #2AABEE !important;
            transform: translateX(2px) !important;
            box-shadow: 2px 2px 8px rgba(0, 0, 0, 0.6) !important;
          }

          .info-card-title {
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            font-size: 13px !important;
            font-weight: 600 !important;
            color: #FFFFFF !important;
            margin-bottom: 4px !important;
          }

          .info-card-desc {
            font-size: 11.5px !important;
            color: #A89880 !important;
            line-height: 1.4 !important;
          }

          .retro-arrow {
            color: #C5A059 !important;
            font-family: monospace !important;
            font-size: 13px !important;
          }

          /* Suggestion Box Form */
          .suggestion-form {
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
          }

          .suggestion-textarea {
            width: 100% !important;
            height: 70px !important;
            background: #0E0C0A !important;
            border: 1px solid #4A3D2F !important;
            border-radius: 4px !important;
            padding: 10px 12px !important;
            color: #F5EFEB !important;
            font-size: 12.5px !important;
            font-family: inherit !important;
            resize: none !important;
            transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
          }

          .suggestion-textarea:focus {
            outline: none !important;
            border-color: #C5A059 !important;
            box-shadow: 0 0 8px rgba(212, 175, 55, 0.25) !important;
          }

          .form-footer {
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
          }

          .char-count {
            font-family: 'SF Mono', 'Courier New', monospace !important;
            font-size: 10.5px !important;
            color: #A89880 !important;
            letter-spacing: 0.04em !important;
          }

          .char-count.limit {
            color: #EF4444 !important;
          }

          .submit-btn {
            background: linear-gradient(180deg, #D4AF37 0%, #A88725 100%) !important;
            color: #0E0C0A !important;
            border: 1px solid #E5C158 !important;
            border-radius: 3px !important;
            padding: 6px 14px !important;
            font-family: 'SF Mono', 'Courier New', monospace !important;
            font-size: 11px !important;
            font-weight: 700 !important;
            letter-spacing: 0.05em !important;
            cursor: pointer !important;
            box-shadow: 1px 1px 0 #000 !important;
            display: inline-flex !important;
            align-items: center !important;
            gap: 6px !important;
            transition: all 0.15s ease !important;
          }

          .submit-btn:hover {
            background: #E5C158 !important;
            transform: translateY(-1px) !important;
            box-shadow: 1px 2px 6px rgba(0, 0, 0, 0.7) !important;
          }

          .submit-btn:active {
            transform: translate(1px, 1px) !important;
            box-shadow: inset 1px 1px 2px rgba(0, 0, 0, 0.6) !important;
          }

          .form-message {
            font-size: 11.5px !important;
            min-height: 16px !important;
            font-family: 'SF Mono', monospace !important;
          }

          .form-message.success { color: #10B981 !important; }
          .form-message.error { color: #EF4444 !important; }

          /* Suggestion Board List */
          .suggestion-list {
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
            max-height: 220px !important;
            overflow-y: auto !important;
          }

          .suggestion-card {
            background: #191512 !important;
            border: 1px solid #382F24 !important;
            border-left: 3px solid #C5A059 !important;
            border-radius: 4px !important;
            padding: 10px 12px !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            gap: 10px !important;
            box-shadow: 1px 1px 0 #000 !important;
          }

          .suggestion-text {
            font-size: 12px !important;
            color: #E2DCD5 !important;
            line-height: 1.4 !important;
            flex: 1 !important;
            word-break: break-word !important;
          }

          .vote-btn {
            background: #241E18 !important;
            border: 1px solid #C5A059 !important;
            color: #D4AF37 !important;
            border-radius: 3px !important;
            padding: 4px 8px !important;
            font-family: 'SF Mono', 'Courier New', monospace !important;
            font-size: 11px !important;
            font-weight: 700 !important;
            cursor: pointer !important;
            display: flex !important;
            align-items: center !important;
            gap: 4px !important;
            box-shadow: 1px 1px 0 #000 !important;
            transition: all 0.15s ease !important;
            flex-shrink: 0 !important;
          }

          .vote-btn:hover {
            background: #C5A059 !important;
            color: #141210 !important;
          }

          .vote-btn:active {
            transform: translate(1px, 1px) !important;
            box-shadow: inset 1px 1px 2px #000 !important;
          }

          .empty-state {
            font-size: 11.5px !important;
            color: #8C7B68 !important;
            text-align: center !important;
            padding: 14px 0 !important;
            font-style: italic !important;
            font-family: 'SF Mono', monospace !important;
          }

          /* Era Archive Links */
          .archive-links {
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
          }

          .archive-btn {
            background: #1B1713 !important;
            border: 1px solid #3D3226 !important;
            border-left: 3px solid #C5A059 !important;
            color: #F5EFEB !important;
            border-radius: 4px !important;
            padding: 10px 14px !important;
            font-size: 12.5px !important;
            text-decoration: none !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            box-shadow: 1px 1px 0 #000 !important;
            transition: all 0.2s ease !important;
          }

          .archive-btn:hover {
            background: #241E18 !important;
            border-color: #D4AF37 !important;
            color: #D4AF37 !important;
            transform: translateX(2px) !important;
          }

          .archive-btn-label {
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
          }

          /* Direct Telegram Button */
          .telegram-btn {
            background: linear-gradient(180deg, #2AABEE 0%, #1E86BC 100%) !important;
            color: #FFFFFF !important;
            border: 1px solid #66C5F5 !important;
            border-radius: 4px !important;
            padding: 11px 14px !important;
            font-size: 12.5px !important;
            font-weight: 600 !important;
            text-decoration: none !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 8px !important;
            box-shadow: 1px 2px 6px rgba(0, 0, 0, 0.4) !important;
            transition: all 0.2s ease !important;
          }

          .telegram-btn:hover {
            background: #229ED9 !important;
            transform: translateY(-1px) !important;
            box-shadow: 1px 4px 12px rgba(42, 171, 238, 0.4) !important;
          }

          .telegram-btn:active {
            transform: translate(1px, 1px) !important;
            box-shadow: inset 1px 1px 3px rgba(0, 0, 0, 0.4) !important;
          }
        </style>

        <div class="drawer-backdrop" id="backdrop"></div>

        <button class="platform-dock-btn" id="dock-btn" aria-label="Cindy Console">
          <img src="/assets/cindy-telegram-badge-v2.jpg" alt="Cindy Console" class="dock-badge-icon" />
        </button>

        <aside class="drawer-panel" id="drawer" role="dialog" aria-modal="true" aria-hidden="true">
          <div class="drawer-header">
            <div class="drawer-title-group">
              <span class="drawer-title-icon">❖</span>
              <h2 class="drawer-title">Cindy Console</h2>
            </div>
            <button class="drawer-close-btn" id="close-btn" aria-label="Close Cindy Console">[✕]</button>
          </div>

          <div class="drawer-body">
            <!-- Request a feature -->
            <div class="section-block">
              <div class="section-header-row">
                <h3 class="section-heading">Request a feature</h3>
                <span class="section-tag">COMMUNITY DISPATCH</span>
              </div>
              <form class="suggestion-form" id="suggest-form">
                <textarea class="suggestion-textarea" id="suggest-input" maxlength="140" placeholder="Pitch Cindy an avant-garde runway feature (max 140 chars)..."></textarea>
                <div class="form-footer">
                  <span class="char-count" id="char-counter">[ 140 CHARS REMAINING ]</span>
                  <button type="submit" class="submit-btn" id="submit-suggest">
                    <span>DISPATCH</span>
                    <span>➔</span>
                  </button>
                </div>
                <div class="form-message" id="form-message"></div>
              </form>

              <div class="suggestion-list" id="suggestions-container">
                <div class="empty-state">Loading active community dispatches...</div>
              </div>
            </div>

            <!-- Era Archive -->
            <div class="section-block">
              <div class="section-header-row">
                <h3 class="section-heading">Era Archive</h3>
                <span class="section-tag">IMMUTABLE VAULT</span>
              </div>
              <div class="archive-links">
                <a href="https://archive.cindypawford.com" target="_blank" rel="noopener" class="archive-btn">
                  <span class="archive-btn-label">
                    <span>🏛️</span>
                    <span>Historical Museum Portal</span>
                  </span>
                  <span class="retro-arrow">➔</span>
                </a>
                <a href="https://archive.cindypawford.com/2024-genesis/" target="_blank" rel="noopener" class="archive-btn">
                  <span class="archive-btn-label">
                    <span>📜</span>
                    <span>Era 1: 2024 Genesis Archive</span>
                  </span>
                  <span class="retro-arrow">➔</span>
                </a>
              </div>
            </div>

            <!-- Talk to Cindy directly -->
            <div class="section-block">
              <div class="section-header-row">
                <h3 class="section-heading">Talk to Cindy directly</h3>
                <span class="section-tag">CONVERSATION</span>
              </div>
              <a href="https://t.me/CindyPawford_bot" target="_blank" rel="noopener" class="telegram-btn">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69.01-.03.01-.14-.07-.19-.08-.05-.19-.02-.27 0-.12.03-1.99 1.27-5.63 3.72-.53.36-1.02.54-1.45.53-.48-.01-1.4-.27-2.09-.49-.84-.27-1.51-.42-1.45-.89.03-.25.38-.5 1.07-.77 4.2-1.83 7-3.04 8.4-3.64 4-.1.72 1.63 1.04 1.83.1.07.24.11.4.11.16 0 .28-.04.38-.11z"/>
                </svg>
                <span>Talk to Cindy directly (@CindyPawford_bot)</span>
              </a>
            </div>

            <!-- Project Information ("Learn More") -->
            <div class="section-block">
              <div class="section-header-row">
                <h3 class="section-heading">Project Information</h3>
                <span class="section-tag">RESEARCH BRIEF</span>
              </div>
              <a href="https://info.cindypawford.com" target="_blank" rel="noopener" class="info-card-btn">
                <div class="info-card-content">
                  <div class="info-card-title">
                    <span>🌱 Safe, Green AI on Edge Silicon</span>
                    <span class="retro-arrow">➔</span>
                  </div>
                  <p class="info-card-desc">
                    Learn about Cindy's low-power edge benchmarking on unified architecture, zero-trust sandboxing, and autonomous agent loops.
                  </p>
                </div>
              </a>
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

      dockBtn.addEventListener("click", () => this.#toggleDrawer(true));
      closeBtn.addEventListener("click", () => this.#toggleDrawer(false));
      backdrop.addEventListener("click", () => this.#toggleDrawer(false));

      suggestInput.addEventListener("input", () => {
        const remaining = 140 - suggestInput.value.length;
        charCounter.textContent = `[ ${remaining} CHARS REMAINING ]`;
        if (remaining < 20) {
          charCounter.classList.add("limit");
        } else {
          charCounter.classList.remove("limit");
        }
      });

      suggestForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        await this.#handleSubmitSuggestion();
      });
    }

    #toggleDrawer(open) {
      this.#isOpen = open;
      const drawer = this.#shadow.getElementById("drawer");
      const backdrop = this.#shadow.getElementById("backdrop");

      if (open) {
        drawer.classList.add("open");
        backdrop.classList.add("open");
        drawer.setAttribute("aria-hidden", "false");
        this.#fetchSuggestions();
      } else {
        drawer.classList.remove("open");
        backdrop.classList.remove("open");
        drawer.setAttribute("aria-hidden", "true");
      }
    }

    async #fetchSuggestions() {
      const container = this.#shadow.getElementById("suggestions-container");
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
        console.error("Suggestions retrieval failed:", err);
        const errorMsg =
          err instanceof TypeError
            ? "Network connection error loading suggestions."
            : "Unable to load suggestions right now.";
        container.innerHTML = `<div class="empty-state">${this.#escapeHtml(errorMsg)}</div>`;
      }
    }

    #renderSuggestions() {
      const container = this.#shadow.getElementById("suggestions-container");
      if (!this.#suggestions || this.#suggestions.length === 0) {
        container.innerHTML = `<div class="empty-state">No proposals submitted yet. Be the first to pitch!</div>`;
        return;
      }

      container.innerHTML = this.#suggestions
        .map(
          (item) => `
          <div class="suggestion-card">
            <p class="suggestion-text">${this.#escapeHtml(item.text)}</p>
            <button class="vote-btn" data-id="${item.id}" data-era="${item.era_id}">
              <span>▲</span>
              <span>${item.votes || 0}</span>
            </button>
          </div>
        `
        )
        .join("");

      container.querySelectorAll(".vote-btn").forEach((btn) => {
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
      const text = input.value.trim();

      if (!text) return;

      msg.className = "form-message";
      msg.textContent = "Submitting...";

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
          msg.textContent = "Submitted for Cindy's atelier consideration!";
          input.value = "";
          this.#shadow.getElementById("char-counter").textContent = "[ 140 CHARS REMAINING ]";
          await this.#fetchSuggestions();
          setTimeout(() => {
            msg.textContent = "";
          }, 3000);
        } else {
          let errorMessage = `Submission failed (HTTP ${res.status}).`;
          if (isJson) {
            const errData = await res.json().catch(() => null);
            if (errData && errData.error) errorMessage = errData.error;
          } else {
            console.warn(`Non-JSON error response from API Gateway (HTTP ${res.status}):`, await res.text().catch(() => ""));
          }
          msg.className = "form-message error";
          msg.textContent = errorMessage;
          console.error("Suggestion submission failed with HTTP status:", res.status, errorMessage);
        }
      } catch (err) {
        console.error("Suggestion submission failed:", err);
        msg.className = "form-message error";
        if (err instanceof TypeError) {
          msg.textContent = "Network connection error submitting suggestion.";
        } else {
          msg.textContent = err.message || "Network error submitting suggestion.";
        }
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
