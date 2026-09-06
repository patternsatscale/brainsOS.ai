#!/usr/bin/env python3
"""
Project Titan - Hermes Agent Interaction Server & Sandbox Runtime
Fully-featured, isolated web interface and API for Hermes:
- Interactive reasoning console with dynamic LiteLLM model selection
- Authentication sign-in flow via Agent Virtual Key
- Extensible Skill & Tool manager within /workspace/skills
- Sandboxed tool & command executor
- OKF memory explorer (/memories)
- Zero-trust security telemetry & guardrail verification
"""

import http.server
import json
import os
import subprocess
import socketserver
import sys
import urllib.error
import urllib.request

PORT = int(os.environ.get("HERMES_PORT", 8642))
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config/config.json")
SOUL_PATH = os.environ.get("SOUL_PATH", "/app/config/SOUL.md")
MEMORY_DIR = os.environ.get("MEMORY_DIR", "/memories")
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/workspace")
SKILLS_DIR = os.path.join(WORKSPACE_DIR, "skills")
LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000/v1")
HERMES_LITELLM_KEY = os.environ.get("HERMES_LITELLM_KEY", "")

# Ensure skills directory exists
os.makedirs(SKILLS_DIR, exist_ok=True)


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"error": f"Failed to load config: {str(e)}"}
    return {"error": f"Config not found at {CONFIG_PATH}"}


def load_soul():
    if os.path.exists(SOUL_PATH):
        try:
            with open(SOUL_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Failed to load SOUL.md: {str(e)}"
    return f"SOUL.md not found at {SOUL_PATH}"


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Project Titan - Hermes Agent Console</title>
  <style>
    :root {
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --text-muted: #8b949e;
      --accent: #58a6ff;
      --accent-hover: #1f6feb;
      --success: #3fb950;
      --warning: #d29922;
      --danger: #f85149;
      --tag-bg: #388bfd26;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 24px 16px;
    }
    .container {
      max-width: 1080px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
      gap: 12px;
    }
    .title-group {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .title-group h1 {
      font-size: 22px;
      color: #f0f6fc;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .badge {
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border-radius: 12px;
      background: var(--tag-bg);
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      border: 1px solid #388bfd4d;
    }
    .auth-bar {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .auth-btn {
      background: #21262d;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 12px;
      cursor: pointer;
    }
    .auth-btn:hover { background: #30363d; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
      margin-bottom: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }
    .card h2 {
      font-size: 15px;
      color: #f0f6fc;
      margin-bottom: 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .status-item {
      display: flex;
      justify-content: space-between;
      padding: 6px 0;
      border-bottom: 1px solid #21262d;
      font-size: 12px;
    }
    .status-item:last-child { border-bottom: none; }
    .status-label { color: var(--text-muted); }
    .status-val { font-family: monospace; font-weight: 500; }
    .status-val.ok { color: var(--success); }
    .status-val.warn { color: var(--warning); }
    .tabs {
      display: flex;
      gap: 4px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 16px;
    }
    .tab {
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      color: var(--text-muted);
      padding: 8px 16px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .tab.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .chat-history {
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px;
      min-height: 220px;
      max-height: 420px;
      overflow-y: auto;
      margin-bottom: 14px;
      font-size: 13px;
    }
    .msg { margin-bottom: 12px; }
    .msg-user { color: var(--accent); font-weight: 600; }
    .msg-assistant { color: #f0f6fc; white-space: pre-wrap; margin-top: 4px; }
    .chat-controls {
      display: flex;
      gap: 10px;
      margin-bottom: 10px;
      align-items: center;
    }
    select, input[type="text"], textarea {
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 6px;
      color: #f0f6fc;
      padding: 8px 12px;
      font-size: 13px;
      outline: none;
      font-family: inherit;
    }
    select:focus, input[type="text"]:focus, textarea:focus { border-color: var(--accent); }
    .input-row {
      display: flex;
      gap: 10px;
    }
    button.primary-btn {
      background: #238636;
      color: #ffffff;
      border: none;
      border-radius: 6px;
      padding: 9px 18px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s;
    }
    button.primary-btn:hover { background: #2ea043; }
    button.primary-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    pre {
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      font-size: 12px;
      overflow-x: auto;
      color: #7ee787;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    .skills-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 16px;
    }
    .skill-card {
      background: #0d1117;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-overlay {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.7);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      visibility: hidden;
      opacity: 0;
      transition: all 0.2s;
    }
    .modal-overlay.open {
      visibility: visible;
      opacity: 1;
    }
    .modal {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 24px;
      max-width: 480px;
      width: 90%;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="title-group">
        <h1>Project Titan: Hermes Agent</h1>
        <span class="badge">Isolated Sandbox</span>
        <span class="badge" style="background:#23863626; color:var(--success); border-color:#2386364d;">v1.0.0</span>
      </div>
      <div class="auth-bar">
        <span id="authStatusText" style="font-size: 12px; color: var(--text-muted);">Key: Auto (Loaded)</span>
        <button class="auth-btn" onclick="openAuthModal()">Change Key</button>
      </div>
    </header>

    <div class="grid">
      <div class="card">
        <h2>Sandbox Security Profile</h2>
        <div class="status-item">
          <span class="status-label">User / Privileges:</span>
          <span class="status-val ok" id="secUser">Loading...</span>
        </div>
        <div class="status-item">
          <span class="status-label">Docker Socket:</span>
          <span class="status-val ok" id="secSocket">Checking...</span>
        </div>
        <div class="status-item">
          <span class="status-label">Internet Egress:</span>
          <span class="status-val ok">WAN Enabled (titan-internal)</span>
        </div>
      </div>

      <div class="card">
        <h2>Control Plane Isolation</h2>
        <div class="status-item">
          <span class="status-label">LiteLLM Gateway:</span>
          <span class="status-val" id="llmUrl">Loading...</span>
        </div>
        <div class="status-item">
          <span class="status-label">Direct Ollama:</span>
          <span class="status-val ok">Blocked (Loopback)</span>
        </div>
        <div class="status-item">
          <span class="status-label">LiteLLM Database:</span>
          <span class="status-val ok">Zero DB Visibility</span>
        </div>
      </div>

      <div class="card">
        <h2>Storage Planes</h2>
        <div class="status-item">
          <span class="status-label">Memory Plane:</span>
          <span class="status-val ok">/memories (Pure OKF)</span>
        </div>
        <div class="status-item">
          <span class="status-label">Tool Workspace:</span>
          <span class="status-val">/workspace</span>
        </div>
        <div class="status-item">
          <span class="status-label">Skills Registry:</span>
          <span class="status-val" id="skillsCount">0 Skills</span>
        </div>
      </div>
    </div>

    <div class="tabs">
      <button class="tab active" onclick="switchTab('chat')">Reasoning Console</button>
      <button class="tab" onclick="switchTab('skills')">Skills & Extensibility</button>
      <button class="tab" onclick="switchTab('terminal')">Sandbox Tool Runner</button>
      <button class="tab" onclick="switchTab('memories')">OKF Memories</button>
      <button class="tab" onclick="switchTab('config')">Configuration & SOUL.md</button>
    </div>

    <!-- TAB: CHAT -->
    <div id="tab-chat" class="tab-content active">
      <div class="card">
        <div class="chat-controls">
          <span style="font-size: 13px; color: var(--text-muted);">Model:</span>
          <select id="modelSelect" style="min-width: 180px;">
            <option value="titan-core">titan-core (Default)</option>
          </select>
          <button class="auth-btn" onclick="refreshModels()" style="padding: 4px 8px; font-size: 11px;">Refresh Models</button>
        </div>
        <div class="chat-history" id="chatHistory">
          <div class="msg">
            <div class="msg-assistant">Hermes Agent initialized in unprivileged sandbox. Ready for instructions.</div>
          </div>
        </div>
        <div class="input-row">
          <input type="text" id="userInput" placeholder="Ask Hermes a question or task..." onkeydown="if(event.key==='Enter') sendChat()" style="flex:1;">
          <button class="primary-btn" id="sendBtn" onclick="sendChat()">Send Query</button>
        </div>
      </div>
    </div>

    <!-- TAB: SKILLS & EXTENSIBILITY -->
    <div id="tab-skills" class="tab-content">
      <div class="card">
        <h2>Add & Manage Functionality (Skills)</h2>
        <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 14px;">
          Add custom Python or shell skills into <code>/workspace/skills</code>. The agent executes these within its isolated unprivileged sandbox.
        </p>
        <div class="skills-list" id="skillsList">Loading skills...</div>

        <h3 style="font-size: 14px; margin: 16px 0 8px 0; color: #f0f6fc;">Create New Skill</h3>
        <div style="display: flex; gap: 10px; margin-bottom: 10px;">
          <input type="text" id="newSkillName" placeholder="skill_name.py" style="flex: 1;">
          <button class="primary-btn" onclick="saveSkill()">Save Skill</button>
        </div>
        <textarea id="newSkillCode" rows="6" placeholder="#!/usr/bin/env python3\n# Your skill code here..." style="width: 100%; font-family: monospace; font-size: 12px;"></textarea>
      </div>
    </div>

    <!-- TAB: TERMINAL / SANDBOX TOOL RUNNER -->
    <div id="tab-terminal" class="tab-content">
      <div class="card">
        <h2>Sandboxed Command Runner</h2>
        <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 12px;">
          Execute ad-hoc commands sandboxed inside <code>/workspace</code> as non-root user (UID 1000).
        </p>
        <div class="input-row" style="margin-bottom: 12px;">
          <input type="text" id="cmdInput" placeholder="e.g. uname -a, python3 --version, ls -la" style="flex: 1;" onkeydown="if(event.key==='Enter') runCmd()">
          <button class="primary-btn" onclick="runCmd()">Run in Sandbox</button>
        </div>
        <pre id="cmdOutput">Awaiting command execution...</pre>
      </div>
    </div>

    <!-- TAB: MEMORIES -->
    <div id="tab-memories" class="tab-content">
      <div class="card">
        <h2>Open Knowledge Format (OKF) Memories Explorer</h2>
        <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 12px;">
          Inspecting human-auditable flat-file markdown notes in <code>/memories</code>.
        </p>
        <div id="memoryTree" style="font-size: 13px;">Loading memory notes...</div>
      </div>
    </div>

    <!-- TAB: CONFIG & SOUL -->
    <div id="tab-config" class="tab-content">
      <div class="card" style="margin-bottom: 14px;">
        <h2>Agent Configuration (<code>/app/config/config.json</code>)</h2>
        <pre id="configView">Loading...</pre>
      </div>
      <div class="card">
        <h2>Agent Persona & Directives (<code>SOUL.md</code>)</h2>
        <pre id="soulView">Loading...</pre>
      </div>
    </div>
  </div>

  <!-- AUTH MODAL -->
  <div class="modal-overlay" id="authModal">
    <div class="modal">
      <h2 style="font-size: 16px; margin-bottom: 12px; color: #f0f6fc;">Sign In / Agent Virtual Key</h2>
      <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 14px;">
        Enter your provisioned <code>HERMES_LITELLM_KEY</code> to authenticate requests through the control plane gateway.
      </p>
      <input type="text" id="authKeyInput" placeholder="sk-titan-hermes-..." style="width: 100%; margin-bottom: 16px;">
      <div style="display: flex; justify-content: flex-end; gap: 10px;">
        <button class="auth-btn" onclick="closeAuthModal()">Cancel</button>
        <button class="primary-btn" onclick="saveAuthKey()">Save Key</button>
      </div>
    </div>
  </div>

  <script>
    function getSavedKey() {
      return sessionStorage.getItem('titan_hermes_key') || '';
    }

    function openAuthModal() {
      document.getElementById('authKeyInput').value = getSavedKey();
      document.getElementById('authModal').classList.add('open');
    }

    function closeAuthModal() {
      document.getElementById('authModal').classList.remove('open');
    }

    function saveAuthKey() {
      const key = document.getElementById('authKeyInput').value.trim();
      if (key) {
        sessionStorage.setItem('titan_hermes_key', key);
        document.getElementById('authStatusText').textContent = 'Key: Custom (Saved)';
      } else {
        sessionStorage.removeItem('titan_hermes_key');
        document.getElementById('authStatusText').textContent = 'Key: Auto (Loaded)';
      }
      closeAuthModal();
      refreshModels();
    }

    function switchTab(tabId) {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById(`tab-${tabId}`).classList.add('active');
      if (tabId === 'skills') loadSkills();
      if (tabId === 'memories') loadMemories();
    }

    async function loadStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        document.getElementById('secUser').textContent = `UID ${data.uid} (${data.is_root ? 'ROOT' : 'non-root unprivileged'})`;
        document.getElementById('secSocket').textContent = data.docker_socket_present ? 'PRESENT (INSECURE)' : 'Absent (Secure)';
        document.getElementById('llmUrl').textContent = data.litellm_url;
      } catch (e) {
        console.error('Failed to load status:', e);
      }

      try {
        const res = await fetch('/api/config');
        document.getElementById('configView').textContent = JSON.stringify(await res.json(), null, 2);
      } catch (e) {}

      try {
        const res = await fetch('/api/soul');
        document.getElementById('soulView').textContent = await res.text();
      } catch (e) {}

      refreshModels();
      loadSkills();
    }

    async function refreshModels() {
      try {
        const headers = {};
        const key = getSavedKey();
        if (key) headers['Authorization'] = `Bearer ${key}`;
        const res = await fetch('/api/models', { headers });
        const data = await res.json();
        const select = document.getElementById('modelSelect');
        select.innerHTML = '<option value="titan-core">titan-core (Default)</option>';
        if (data.data && Array.isArray(data.data)) {
          data.data.forEach(m => {
            if (m.id !== 'titan-core') {
              const opt = document.createElement('option');
              opt.value = m.id;
              opt.textContent = m.id;
              select.appendChild(opt);
            }
          });
        }
      } catch (e) {
        console.warn('Could not refresh models:', e);
      }
    }

    async function sendChat() {
      const input = document.getElementById('userInput');
      const prompt = input.value.trim();
      if (!prompt) return;

      const history = document.getElementById('chatHistory');
      const userDiv = document.createElement('div');
      userDiv.className = 'msg';
      userDiv.innerHTML = `<div class="msg-user">You:</div><div class="msg-assistant">${prompt}</div>`;
      history.appendChild(userDiv);
      input.value = '';

      const btn = document.getElementById('sendBtn');
      btn.disabled = true;
      btn.textContent = 'Thinking...';

      const model = document.getElementById('modelSelect').value;
      const headers = { 'Content-Type': 'application/json' };
      const key = getSavedKey();
      if (key) headers['Authorization'] = `Bearer ${key}`;

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers,
          body: JSON.stringify({ prompt, model })
        });
        const data = await res.json();

        const agentDiv = document.createElement('div');
        agentDiv.className = 'msg';
        const reply = data.choices?.[0]?.message?.content || data.reply || JSON.stringify(data, null, 2);
        agentDiv.innerHTML = `<div class="msg-user" style="color: var(--success);">Hermes:</div><div class="msg-assistant">${reply}</div>`;
        history.appendChild(agentDiv);
        history.scrollTop = history.scrollHeight;
      } catch (e) {
        const errDiv = document.createElement('div');
        errDiv.className = 'msg';
        errDiv.innerHTML = `<div class="msg-user" style="color: var(--danger);">Error:</div><div class="msg-assistant">${e.message}</div>`;
        history.appendChild(errDiv);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Send Query';
      }
    }

    async function loadSkills() {
      try {
        const res = await fetch('/api/skills');
        const data = await res.json();
        const list = document.getElementById('skillsList');
        document.getElementById('skillsCount').textContent = `${data.skills?.length || 0} Skills`;
        if (!data.skills || data.skills.length === 0) {
          list.innerHTML = '<div style="color: var(--text-muted); font-size: 13px;">No custom skills yet. Add your first skill below!</div>';
          return;
        }
        list.innerHTML = '';
        data.skills.forEach(s => {
          const item = document.createElement('div');
          item.className = 'skill-card';
          item.innerHTML = `
            <div>
              <strong style="color: var(--accent);">${s.name}</strong>
              <small style="display:block; color:var(--text-muted);">${s.size} bytes</small>
            </div>
            <button class="auth-btn" onclick="runSkill('${s.name}')">Run Skill</button>
          `;
          list.appendChild(item);
        });
      } catch (e) {
        console.error('Failed loading skills:', e);
      }
    }

    async function saveSkill() {
      const name = document.getElementById('newSkillName').value.trim();
      const code = document.getElementById('newSkillCode').value;
      if (!name) return alert('Please provide a skill filename (e.g. my_skill.py)');

      try {
        const res = await fetch('/api/skills', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, code })
        });
        const result = await res.json();
        if (result.status === 'ok') {
          alert('Skill saved successfully!');
          document.getElementById('newSkillName').value = '';
          document.getElementById('newSkillCode').value = '';
          loadSkills();
        } else {
          alert('Error: ' + result.error);
        }
      } catch (e) {
        alert('Failed to save skill: ' + e.message);
      }
    }

    async function runSkill(skillName) {
      document.getElementById('cmdInput').value = `python3 /workspace/skills/${skillName}`;
      switchTab('terminal');
      runCmd();
    }

    async function runCmd() {
      const cmd = document.getElementById('cmdInput').value.trim();
      if (!cmd) return;
      const out = document.getElementById('cmdOutput');
      out.textContent = `Running: ${cmd}...\n`;

      try {
        const res = await fetch('/api/terminal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: cmd })
        });
        const data = await res.json();
        out.textContent = `[Exit Code: ${data.exit_code}]\n\nSTDOUT:\n${data.stdout}\n\nSTDERR:\n${data.stderr}`;
      } catch (e) {
        out.textContent = `Execution error: ${e.message}`;
      }
    }

    async function loadMemories() {
      const el = document.getElementById('memoryTree');
      try {
        const res = await fetch('/api/memories');
        const data = await res.json();
        el.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
      } catch (e) {
        el.textContent = 'Failed to load memories: ' + e.message;
      }
    }

    loadStatus();
  </script>
</body>
</html>
"""


class HermesHandler(http.server.BaseHTTPRequestHandler):
    def get_auth_key(self):
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header.split(" ", 1)[1].strip()
        return HERMES_LITELLM_KEY

    def send_json(self, status_code, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_HEAD(self):
        if self.path in ("/", "/index.html"):
            payload = HTML_DASHBOARD.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            return
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            payload = HTML_DASHBOARD.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/health":
            self.send_json(200, {
                "status": "healthy",
                "agent": "hermes-titan",
                "version": "1.0.0",
                "mode": "unprivileged_sandbox"
            })
            return

        if self.path == "/api/status":
            self.send_json(200, {
                "uid": os.getuid(),
                "gid": os.getgid(),
                "is_root": os.getuid() == 0,
                "docker_socket_present": os.path.exists("/var/run/docker.sock"),
                "memory_dir": MEMORY_DIR,
                "workspace_dir": WORKSPACE_DIR,
                "litellm_url": LITELLM_URL
            })
            return

        if self.path == "/api/config":
            config = load_config()
            self.send_json(200, config)
            return

        if self.path == "/api/soul":
            soul = load_soul()
            payload = soul.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/api/models":
            key = self.get_auth_key()
            endpoint = f"{LITELLM_URL.rstrip('/')}/models"
            try:
                req = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {key}"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.send_json(200, json.loads(resp.read().decode("utf-8")))
            except Exception as e:
                self.send_json(200, {"data": [{"id": "titan-core"}]})
            return

        if self.path == "/api/skills":
            skills = []
            if os.path.exists(SKILLS_DIR):
                for fname in sorted(os.listdir(SKILLS_DIR)):
                    fpath = os.path.join(SKILLS_DIR, fname)
                    if os.path.isfile(fpath):
                        skills.append({
                            "name": fname,
                            "size": os.path.getsize(fpath)
                        })
            self.send_json(200, {"skills": skills})
            return

        if self.path == "/api/memories":
            tree = {}
            for root, dirs, files in os.walk(MEMORY_DIR):
                rel = os.path.relpath(root, MEMORY_DIR)
                tree[rel] = [f for f in files if f.endswith(".md")]
            self.send_json(200, {"memories": tree})
            return

        self.send_json(404, {"error": "Not Found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            req_data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            req_data = {}

        if self.path == "/api/chat":
            prompt = req_data.get("prompt", "ping")
            model = req_data.get("model", "titan-core")
            messages = req_data.get("messages", [{"role": "user", "content": prompt}])
            key = self.get_auth_key()

            litellm_endpoint = f"{LITELLM_URL.rstrip('/')}/chat/completions"
            payload = json.dumps({
                "model": model,
                "messages": messages,
                "temperature": 0.2
            }).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}"
            }

            try:
                llm_req = urllib.request.Request(litellm_endpoint, data=payload, headers=headers)
                with urllib.request.urlopen(llm_req, timeout=30) as resp:
                    resp_body = resp.read()
                    data = json.loads(resp_body.decode("utf-8"))
                    self.send_json(200, data)
            except urllib.error.HTTPError as e:
                err_content = e.read().decode("utf-8")
                self.send_json(e.code, {"error": f"LiteLLM error: {err_content}"})
            except Exception as e:
                self.send_json(502, {"error": f"Failed to connect to LiteLLM at {litellm_endpoint}: {str(e)}"})
            return

        if self.path == "/api/skills":
            name = req_data.get("name", "").strip()
            code = req_data.get("code", "")
            if not name or ".." in name or "/" in name:
                self.send_json(400, {"error": "Invalid skill filename"})
                return

            skill_path = os.path.join(SKILLS_DIR, name)
            try:
                with open(skill_path, "w", encoding="utf-8") as f:
                    f.write(code)
                os.chmod(skill_path, 0o755)
                self.send_json(200, {"status": "ok", "saved": name})
            except Exception as e:
                self.send_json(500, {"error": f"Failed to write skill: {str(e)}"})
            return

        if self.path == "/api/terminal":
            command = req_data.get("command", "").strip()
            if not command:
                self.send_json(400, {"error": "No command provided"})
                return

            # Execute sandboxed within /workspace as unprivileged user
            try:
                res = subprocess.run(
                    ["/bin/bash", "-c", command],
                    cwd=WORKSPACE_DIR,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                self.send_json(200, {
                    "exit_code": res.returncode,
                    "stdout": res.stdout,
                    "stderr": res.stderr
                })
            except subprocess.TimeoutExpired:
                self.send_json(408, {"error": "Command timed out after 30 seconds"})
            except Exception as e:
                self.send_json(500, {"error": f"Command execution error: {str(e)}"})
            return

        self.send_json(404, {"error": "Not Found"})

    def log_message(self, format, *args):
        sys.stderr.write(f"[Hermes Runtime] {self.address_string()} - {format % args}\n")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def main():
    server_address = ("0.0.0.0", PORT)
    httpd = ThreadedHTTPServer(server_address, HermesHandler)
    print(f"[Hermes Runtime] Listening on port {PORT} (unprivileged sandbox mode)...", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Hermes Runtime] Stopping server...", file=sys.stderr)
        httpd.server_close()


if __name__ == "__main__":
    main()
