/**
 * Cindy Pawford Floating Platform Shell
 * Un-nukeable Web Component with Closed Shadow DOM Isolation
 */
(function () {
  if (customElements.get("cindy-platform-dock")) return;

  const API_BASE = window.CINDY_API_URL || "";

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
      this.#fetchTelemetry();
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
            color: #FAFAFA !important;
            box-sizing: border-box !important;
          }

          *, *::before, *::after {
            box-sizing: border-box !important;
            margin: 0;
            padding: 0;
          }

          /* Floating Dock Button */
          .platform-dock-btn {
            background: linear-gradient(135deg, #18181B 0%, #0A0A0B 100%) !important;
            color: #D4AF37 !important;
            border: 1px solid rgba(212, 175, 55, 0.45) !important;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.65), 0 0 16px rgba(212, 175, 55, 0.2) !important;
            border-radius: 9999px !important;
            padding: 10px 20px !important;
            font-size: 13px !important;
            font-weight: 600 !important;
            letter-spacing: 0.04em !important;
            cursor: pointer !important;
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
            backdrop-filter: blur(12px) !important;
            user-select: none !important;
          }

          .platform-dock-btn:hover {
            transform: translateY(-2px) scale(1.02) !important;
            border-color: #D4AF37 !important;
            box-shadow: 0 12px 36px rgba(0, 0, 0, 0.75), 0 0 24px rgba(212, 175, 55, 0.35) !important;
          }

          .dock-badge-pulse {
            width: 8px !important;
            height: 8px !important;
            border-radius: 50% !important;
            background-color: #10B981 !important;
            box-shadow: 0 0 8px #10B981 !important;
            animation: pulse 2s infinite !important;
          }

          @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.8; }
            50% { transform: scale(1.2); opacity: 1; }
            100% { transform: scale(0.95); opacity: 0.8; }
          }

          /* Backdrop */
          .drawer-backdrop {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            background: rgba(0, 0, 0, 0.65) !important;
            backdrop-filter: blur(6px) !important;
            opacity: 0 !important;
            pointer-events: none !important;
            transition: opacity 0.3s ease !important;
            z-index: 2147483645 !important;
          }

          .drawer-backdrop.open {
            opacity: 1 !important;
            pointer-events: auto !important;
          }

          /* Slide-Out Drawer */
          .drawer-panel {
            position: fixed !important;
            top: 0 !important;
            right: -420px !important;
            width: 400px !important;
            max-width: calc(100vw - 32px) !important;
            height: 100vh !important;
            background: #0D0E12 !important;
            border-left: 1px solid rgba(212, 175, 55, 0.25) !important;
            box-shadow: -12px 0 48px rgba(0, 0, 0, 0.85) !important;
            display: flex !important;
            flex-direction: column !important;
            transition: right 0.35s cubic-bezier(0.16, 1, 0.3, 1) !important;
            z-index: 2147483646 !important;
            overflow-y: auto !important;
          }

          .drawer-panel.open {
            right: 0 !important;
          }

          .drawer-header {
            padding: 24px 24px 16px 24px !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
          }

          .drawer-title {
            font-size: 16px !important;
            font-weight: 700 !important;
            letter-spacing: 0.05em !important;
            color: #D4AF37 !important;
            text-transform: uppercase !important;
          }

          .drawer-close-btn {
            background: transparent !important;
            border: none !important;
            color: #71717A !important;
            font-size: 20px !important;
            cursor: pointer !important;
            padding: 4px 8px !important;
            border-radius: 4px !important;
            line-height: 1 !important;
            transition: color 0.2s ease !important;
          }

          .drawer-close-btn:hover {
            color: #FAFAFA !important;
          }

          .drawer-body {
            padding: 24px !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 24px !important;
            flex: 1 !important;
          }

          /* Telemetry Badge */
          .telemetry-card {
            background: rgba(24, 24, 27, 0.75) !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            border-radius: 10px !important;
            padding: 12px 16px !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 6px !important;
          }

          .telemetry-title {
            font-size: 11px !important;
            text-transform: uppercase !important;
            letter-spacing: 0.06em !important;
            color: #A1A1AA !important;
            display: flex !important;
            align-items: center !important;
            gap: 6px !important;
          }

          .telemetry-badge {
            font-size: 12px !important;
            font-weight: 600 !important;
            color: #E4E4E7 !important;
          }

          /* Sections */
          .section-block {
            display: flex !important;
            flex-direction: column !important;
            gap: 12px !important;
          }

          .section-heading {
            font-size: 13px !important;
            font-weight: 600 !important;
            letter-spacing: 0.04em !important;
            color: #D4AF37 !important;
            text-transform: uppercase !important;
          }

          /* Archive Links */
          .archive-links {
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
          }

          .archive-btn {
            background: rgba(39, 39, 42, 0.5) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            color: #FAFAFA !important;
            border-radius: 8px !important;
            padding: 10px 14px !important;
            font-size: 13px !important;
            text-decoration: none !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            transition: all 0.2s ease !important;
          }

          .archive-btn:hover {
            background: rgba(212, 175, 55, 0.1) !important;
            border-color: rgba(212, 175, 55, 0.4) !important;
            color: #D4AF37 !important;
            transform: translateX(2px) !important;
          }

          /* Telegram Channel */
          .telegram-btn {
            background: linear-gradient(135deg, #0284C7 0%, #0369A1 100%) !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 8px !important;
            padding: 10px 14px !important;
            font-size: 13px !important;
            font-weight: 600 !important;
            text-decoration: none !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 8px !important;
            transition: opacity 0.2s ease !important;
          }

          .telegram-btn:hover {
            opacity: 0.9 !important;
          }

          /* Suggestion Box Form */
          .suggestion-form {
            display: flex !important;
            flex-direction: column !important;
            gap: 8px !important;
          }

          .suggestion-textarea {
            width: 100% !important;
            height: 72px !important;
            background: #18181B !important;
            border: 1px solid rgba(255, 255, 255, 0.15) !important;
            border-radius: 8px !important;
            padding: 10px 12px !important;
            color: #FAFAFA !important;
            font-size: 13px !important;
            font-family: inherit !important;
            resize: none !important;
          }

          .suggestion-textarea:focus {
            outline: none !important;
            border-color: #D4AF37 !important;
            box-shadow: 0 0 8px rgba(212, 175, 55, 0.25) !important;
          }

          .form-footer {
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
          }

          .char-count {
            font-size: 11px !important;
            color: #71717A !important;
          }

          .char-count.limit {
            color: #EF4444 !important;
          }

          .submit-btn {
            background: #D4AF37 !important;
            color: #0A0A0B !important;
            border: none !important;
            border-radius: 6px !important;
            padding: 6px 14px !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            cursor: pointer !important;
            transition: all 0.2s ease !important;
          }

          .submit-btn:hover {
            background: #E5C158 !important;
            transform: scale(1.02) !important;
          }

          .form-message {
            font-size: 12px !important;
            min-height: 16px !important;
          }

          .form-message.success { color: #10B981 !important; }
          .form-message.error { color: #EF4444 !important; }

          /* Suggestion Board List */
          .suggestion-list {
            display: flex !important;
            flex-direction: column !important;
            gap: 10px !important;
            max-height: 240px !important;
            overflow-y: auto !important;
          }

          .suggestion-card {
            background: rgba(24, 24, 27, 0.6) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 8px !important;
            padding: 10px 12px !important;
            display: flex !important;
            justify-content: space-between !important;
            align-items: center !important;
            gap: 10px !important;
          }

          .suggestion-text {
            font-size: 12px !important;
            color: #D4D4D8 !important;
            line-height: 1.4 !important;
            flex: 1 !important;
            word-break: break-word !important;
          }

          .vote-btn {
            background: rgba(212, 175, 55, 0.1) !important;
            border: 1px solid rgba(212, 175, 55, 0.3) !important;
            color: #D4AF37 !important;
            border-radius: 6px !important;
            padding: 6px 10px !important;
            font-size: 12px !important;
            font-weight: 600 !important;
            cursor: pointer !important;
            display: flex !important;
            align-items: center !important;
            gap: 4px !important;
            transition: all 0.2s ease !important;
            flex-shrink: 0 !important;
          }

          .vote-btn:hover {
            background: #D4AF37 !important;
            color: #0A0A0B !important;
          }

          .empty-state {
            font-size: 12px !important;
            color: #71717A !important;
            text-align: center !important;
            padding: 16px 0 !important;
            font-style: italic !important;
          }
        </style>

        <div class="drawer-backdrop" id="backdrop"></div>

        <button class="platform-dock-btn" id="dock-btn" aria-label="Open Atelier Platform Vault">
          <span class="dock-badge-pulse"></span>
          <span>Atelier Platform</span>
          <span>✨</span>
        </button>

        <aside class="drawer-panel" id="drawer" role="dialog" aria-modal="true" aria-hidden="true">
          <div class="drawer-header">
            <h2 class="drawer-title">Platform Shell</h2>
            <button class="drawer-close-btn" id="close-btn" aria-label="Close Platform Vault">✕</button>
          </div>

          <div class="drawer-body">
            <!-- Appliance Telemetry -->
            <div class="telemetry-card">
              <span class="telemetry-title">⚡ Appliance Telemetry</span>
              <span class="telemetry-badge" id="telemetry-badge">Powered by ASUS Ascent GX10 • GB10 Unified Architecture • Hermes Agent</span>
            </div>

            <!-- Suggestion Box & Upvote Board -->
            <div class="section-block">
              <h3 class="section-heading">Executive Feature Requests</h3>
              <form class="suggestion-form" id="suggest-form">
                <textarea class="suggestion-textarea" id="suggest-input" maxlength="140" placeholder="Pitch Cindy an avant-garde runway feature (max 140 chars)..."></textarea>
                <div class="form-footer">
                  <span class="char-count" id="char-counter">140 left</span>
                  <button type="submit" class="submit-btn" id="submit-suggest">Submit</button>
                </div>
                <div class="form-message" id="form-message"></div>
              </form>

              <div class="suggestion-list" id="suggestions-container">
                <div class="empty-state">Loading active community suggestions...</div>
              </div>
            </div>

            <!-- Archive Vault -->
            <div class="section-block">
              <h3 class="section-heading">Archive Museum</h3>
              <div class="archive-links">
                <a href="https://archive.cindypawford.com" target="_blank" rel="noopener" class="archive-btn">
                  <span>🏛️ Historical Museum Portal</span>
                  <span>→</span>
                </a>
                <a href="https://archive.cindypawford.com/2024-genesis/" target="_blank" rel="noopener" class="archive-btn">
                  <span>✨ Era 1: 2024 Genesis Archive</span>
                  <span>→</span>
                </a>
              </div>
            </div>

            <!-- Direct Telegram Channel -->
            <div class="section-block">
              <h3 class="section-heading">Autonomous Channels</h3>
              <a href="https://t.me/CindyPawford_bot" target="_blank" rel="noopener" class="telegram-btn">
                <span>💬 Talk to Cindy on Telegram (@CindyPawford_bot)</span>
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
        charCounter.textContent = `${remaining} left`;
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

    async #fetchTelemetry() {
      try {
        const res = await fetch("/era-info.json");
        if (res.ok) {
          const data = await res.json();
          if (data.model) {
            const badge = this.#shadow.getElementById("telemetry-badge");
            badge.textContent = `Powered by ASUS Ascent GX10 • ${data.model} • Hermes Agent`;
          }
        }
      } catch {
        // Fallback to default styling
      }
    }

    async #fetchSuggestions() {
      const container = this.#shadow.getElementById("suggestions-container");
      try {
        const res = await fetch(`${API_BASE}/api/top-suggestions`);
        if (!res.ok) throw new Error("API response not ok");
        const data = await res.json();
        this.#suggestions = data.suggestions || [];
        this.#eraInfo = { era_id: data.era_id, is_active: data.is_active };
        this.#renderSuggestions();
      } catch (err) {
        container.innerHTML = `<div class="empty-state">Unable to load suggestions right now.</div>`;
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
        if (res.ok) {
          const data = await res.json();
          const target = this.#suggestions.find((s) => s.id === id);
          if (target) {
            target.votes = data.votes;
            this.#renderSuggestions();
          }
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

        const data = await res.json();
        if (res.ok) {
          msg.className = "form-message success";
          msg.textContent = "Submitted for Cindy's atelier consideration!";
          input.value = "";
          this.#shadow.getElementById("char-counter").textContent = "140 left";
          await this.#fetchSuggestions();
          setTimeout(() => {
            msg.textContent = "";
          }, 3000);
        } else {
          msg.className = "form-message error";
          msg.textContent = data.error || "Submission failed.";
        }
      } catch (err) {
        msg.className = "form-message error";
        msg.textContent = "Network error submitting suggestion.";
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
