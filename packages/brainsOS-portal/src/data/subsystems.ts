export interface Subsystem {
  id: string;
  title: string;
  desc: string;
  route: string;
  hotkey: string;
  color: string;
  icon: string;
  previewHtml: string;
}

export const SUBSYSTEMS: Record<string, Subsystem> = {
  console: {
    id: "console",
    title: "Console",
    desc: "Web IDE & Terminal",
    route: "/editor/",
    hotkey: "⌘1",
    color: "#00f2fe",
    icon: "Terminal",
    previewHtml: `
      <div style="display:flex; height:100vh; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#1e1e1e; color:#cccccc; overflow:hidden; user-select:none;">
        <div style="width:48px; background:#333333; display:flex; flex-direction:column; align-items:center; padding-top:12px; gap:20px; color:#858585; border-right:1px solid #222;">
          <div style="color:#ffffff; cursor:pointer;" title="Explorer">📁</div>
          <div style="cursor:pointer;" title="Search">🔍</div>
          <div style="cursor:pointer;" title="Source Control">🌿</div>
          <div style="cursor:pointer;" title="Run & Debug">▶️</div>
          <div style="cursor:pointer;" title="Extensions">🧩</div>
        </div>
        <div style="width:230px; background:#252526; border-right:1px solid #181818; display:flex; flex-direction:column; font-size:12px;">
          <div style="padding:10px 14px; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; font-size:11px; color:#bbbbbb;">Explorer: brainsOS</div>
          <div style="padding:5px 14px; color:#ffffff; background:#37373d; display:flex; align-items:center; gap:6px;">
            <span>📂</span> <b>packages</b>
          </div>
          <div style="padding:4px 26px; color:#fff; display:flex; align-items:center; gap:6px; background:#094771;">
            <span>🐍</span> agent.py
          </div>
          <div style="padding:4px 26px; color:#999999; display:flex; align-items:center; gap:6px;">
            <span>⚙️</span> config.yaml
          </div>
          <div style="padding:4px 26px; color:#999999; display:flex; align-items:center; gap:6px;">
            <span>📝</span> SOUL.md
          </div>
          <div style="padding:5px 14px; color:#999999; display:flex; align-items:center; gap:6px; margin-top:4px;">
            <span>📁</span> agent_workspaces
          </div>
          <div style="padding:5px 14px; color:#999999; display:flex; align-items:center; gap:6px;">
            <span>📁</span> data / memories
          </div>
        </div>
        <div style="flex:1; display:flex; flex-direction:column; background:#1e1e1e; overflow:hidden;">
          <div style="height:35px; background:#252526; display:flex; align-items:center; font-size:12px; border-bottom:1px solid #181818;">
            <div style="padding:8px 16px; background:#1e1e1e; color:#ffffff; border-top:2px solid #00f2fe; display:flex; align-items:center; gap:8px;">
              <span>🐍</span> agent.py <span style="font-size:10px; color:#888;">×</span>
            </div>
            <div style="padding:8px 16px; background:#2d2d2d; color:#999; display:flex; align-items:center; gap:8px;">
              <span>⚙️</span> config.yaml
            </div>
          </div>
          <div style="padding:4px 16px; font-size:11px; color:#888; background:#1e1e1e; border-bottom:1px solid #282828;">
            packages &gt; brainsOS-agent &gt; agent.py
          </div>
          <div style="flex:1; display:flex; font-family:'JetBrains Mono',Consolas,monospace; font-size:13px; line-height:20px; padding:12px 0; overflow-y:auto; user-select:text;">
            <div style="width:45px; text-align:right; padding-right:16px; color:#5a5a5a; user-select:none;">
              1<br>2<br>3<br>4<br>5<br>6<br>7<br>8<br>9<br>10<br>11<br>12<br>13<br>14
            </div>
            <div style="flex:1; color:#d4d4d4;">
              <span style="color:#569cd6;">from</span> dataclasses <span style="color:#569cd6;">import</span> dataclass<br>
              <span style="color:#569cd6;">from</span> brainsos.runtime <span style="color:#569cd6;">import</span> ApplianceHost, SubsystemRegistry<br><br>
              <span style="color:#6a9955;"># Production Target: ASUS Ascent GX10 (NVIDIA GB10 ARM64)</span><br>
              <span style="color:#569cd6;">class</span> <span style="color:#4ec9b0;">BrainsOSKernel</span>:<br>
              &nbsp;&nbsp;&nbsp;&nbsp;<span style="color:#569cd6;">def</span> <span style="color:#dcdcaa;">__init__</span>(<span style="color:#9cdcfe;">self</span>, <span style="color:#9cdcfe;">host_id</span>: <span style="color:#4ec9b0;">str</span> = <span style="color:#ce9178;">"ASUS-Ascent-GX10"</span>):<br>
              &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span style="color:#9cdcfe;">self</span>.<span style="color:#9cdcfe;">host_id</span> = <span style="color:#9cdcfe;">host_id</span><br>
              &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span style="color:#9cdcfe;">self</span>.<span style="color:#9cdcfe;">subsystems</span> = SubsystemRegistry.discover()<br>
              &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span style="color:#9cdcfe;">self</span>.<span style="color:#9cdcfe;">memory_bus_speed</span> = <span style="color:#ce9178;">"273 GB/s unified LPDDR5x"</span><br><br>
              &nbsp;&nbsp;&nbsp;&nbsp;<span style="color:#569cd6;">async def</span> <span style="color:#dcdcaa;">spawn_tenant_runner</span>(<span style="color:#9cdcfe;">self</span>, <span style="color:#9cdcfe;">tenant</span>: <span style="color:#4ec9b0;">str</span>):<br>
              &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span style="color:#6a9955;"># Enforce Rule 9 Multi-Tenant Partitioning</span><br>
              &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span style="color:#c586c0;">return await</span> <span style="color:#9cdcfe;">self</span>.<span style="color:#9cdcfe;">subsystems</span>.boot_stateless_runner(<span style="color:#9cdcfe;">tenant</span>)
            </div>
          </div>
          <div style="height:150px; background:#181818; border-top:1px solid #333; display:flex; flex-direction:column; font-family:'JetBrains Mono',monospace; font-size:12px;">
            <div style="padding:6px 12px; background:#252526; display:flex; align-items:center; justify-content:space-between; font-size:11px; color:#aaa; border-bottom:1px solid #1e1e1e;">
              <div style="display:flex; gap:12px;">
                <span style="color:#fff; font-weight:600; border-bottom:1px solid #00f2fe;">TERMINAL</span>
                <span>OUTPUT</span>
                <span>DEBUG CONSOLE</span>
                <span>PORTS</span>
              </div>
              <div style="margin-left:auto; display:flex; gap:8px;">
                <span>bash</span>
                <span>+</span>
                <span>×</span>
              </div>
            </div>
            <div style="padding:10px 14px; color:#33ff33; line-height:19px; overflow-y:auto; user-select:text;">
              <span style="color:#00f2fe;">operator@brainsos-gx10</span>:<span style="color:#3b82f6;">~/Development/brainsOS.ai</span>$ python3 -m pytest tests/ -q<br>
              <span style="color:#fff;">................................................. [100%]</span><br>
              <span style="color:#10b981; font-weight:bold;">49 passed in 0.84s (All Architectural Guardrails Satisfied)</span><br>
              <span style="color:#00f2fe;">operator@brainsos-gx10</span>:<span style="color:#3b82f6;">~/Development/brainsOS.ai</span>$ <span style="animation:pulse 1s infinite;">█</span>
            </div>
          </div>
        </div>
      </div>
    `
  },
  comms: {
    id: "comms",
    title: "Comms",
    desc: "Agent Webmail Interface",
    route: "/mail/",
    hotkey: "⌘2",
    color: "#ec4899",
    icon: "Mail",
    previewHtml: `
      <div style="display:flex; height:100vh; font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#0B0E14; color:#e2e8f0; overflow:hidden;">
        <div style="width:200px; background:#111622; border-right:1px solid rgba(255,255,255,0.08); padding:16px 12px; display:flex; flex-direction:column; gap:6px;">
          <div style="font-weight:700; font-size:13px; color:#ec4899; padding:4px 8px; margin-bottom:8px;">SOGo Webmail</div>
          <div style="padding:8px 12px; background:rgba(236,72,153,0.15); border-radius:8px; font-size:12px; color:#fff; font-weight:600; display:flex; justify-content:space-between;">
            <span>📥 Inbox</span><span style="background:#ec4899; color:#fff; border-radius:10px; padding:0 6px; font-size:10px;">3</span>
          </div>
          <div style="padding:8px 12px; border-radius:8px; font-size:12px; color:#94a3b8;">📤 Sent</div>
          <div style="padding:8px 12px; border-radius:8px; font-size:12px; color:#94a3b8;">📝 Drafts</div>
          <div style="padding:8px 12px; border-radius:8px; font-size:12px; color:#94a3b8;">🏷️ Ingress Tasks</div>
        </div>
        <div style="width:310px; background:#141a29; border-right:1px solid rgba(255,255,255,0.08); display:flex; flex-direction:column;">
          <div style="padding:12px 14px; border-bottom:1px solid rgba(255,255,255,0.08); font-size:12px; font-weight:600; color:#fff;">Agent Inbox • cindy@brainsos.local</div>
          <div style="padding:12px 14px; background:rgba(255,255,255,0.04); border-bottom:1px solid rgba(255,255,255,0.05); cursor:pointer;">
            <div style="font-size:12px; font-weight:600; color:#fff; display:flex; justify-content:space-between;"><span>Hermes Orchestrator</span><span style="font-size:10px; color:#94a3b8;">10:14 AM</span></div>
            <div style="font-size:11px; color:#ec4899; margin-top:2px;">[TICKET #246] Portal Architecture</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:2px;">Full-bleed iframe boundary verified on GX10...</div>
          </div>
          <div style="padding:12px 14px; border-bottom:1px solid rgba(255,255,255,0.05); cursor:pointer;">
            <div style="font-size:12px; font-weight:600; color:#fff; display:flex; justify-content:space-between;"><span>Tool Egress Gateway</span><span style="font-size:10px; color:#94a3b8;">09:45 AM</span></div>
            <div style="font-size:11px; color:#fff; margin-top:2px;">Egress Token Injected [OK]</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:2px;">Mitmproxy sanitized GitHub bearer...</div>
          </div>
        </div>
        <div style="flex:1; padding:24px 32px; background:#0e131f; overflow-y:auto;">
          <div style="font-size:18px; font-weight:700; color:#fff;">[TICKET #246] Portal Architecture Verification</div>
          <div style="font-size:12px; color:#94a3b8; margin-top:6px;">From: <b>Hermes Orchestrator</b> &lt;hermes@brainsos.local&gt; • 10:14 AM</div>
          <div style="margin-top:20px; font-size:13px; line-height:22px; color:#cbd5e1; border-top:1px solid rgba(255,255,255,0.1); padding-top:16px;">
            Cindy,<br><br>The thin spine and expandable HUD drawer are live. The full-bleed iframe has 100% canvas real estate and zero layout shift.<br><br>Appliance Host: <b>ASUS Ascent GX10</b><br>Architecture: <b>ARM64</b>
          </div>
        </div>
      </div>
    `
  },
  security: {
    id: "security",
    title: "Security",
    desc: "LiteLLM Gateway & Virtual Keys",
    route: "/proxy/",
    hotkey: "⌘3",
    color: "#f59e0b",
    icon: "Shield",
    previewHtml: `
      <div style="height:100vh; padding:28px 36px; font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#0B0E14; color:#f8fafc; overflow-y:auto;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:16px; margin-bottom:24px;">
          <div>
            <h1 style="font-size:20px; font-weight:700; margin:0; color:#f59e0b;">LiteLLM Gateway &amp; Key Governance</h1>
            <p style="font-size:12px; color:#94a3b8; margin:4px 0 0;">Hardware Concurrency Serialization • Rule 3 Protection</p>
          </div>
          <div style="background:rgba(245,158,11,0.15); border:1px solid #f59e0b; color:#f59e0b; padding:6px 14px; border-radius:8px; font-size:12px; font-family:monospace;">
            max_parallel_requests: 1 [LOCKED]
          </div>
        </div>
        <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; margin-bottom:24px;">
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:16px;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase;">Active Virtual Keys</div>
            <div style="font-size:24px; font-weight:700; color:#fff; margin-top:6px;">12 Tenants</div>
            <div style="font-size:11px; color:#10b981; margin-top:4px;">● Isolated PostgreSQL Vault</div>
          </div>
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:16px;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase;">Memory Bandwidth</div>
            <div style="font-size:24px; font-weight:700; color:#00f2fe; margin-top:6px;">273 GB/s</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:4px;">LPDDR5x Unified Bus</div>
          </div>
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:16px;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase;">Loopback Inference</div>
            <div style="font-size:24px; font-weight:700; color:#f59e0b; margin-top:6px;">127.0.0.1:11434</div>
            <div style="font-size:11px; color:#10b981; margin-top:4px;">● Rule 2 Loopback Enforced</div>
          </div>
        </div>
        <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:20px;">
          <div style="font-weight:600; font-size:14px; margin-bottom:12px;">Registered Models</div>
          <table style="width:100%; font-size:12px; border-collapse:collapse; font-family:monospace;">
            <thead>
              <tr style="text-align:left; color:#94a3b8; border-bottom:1px solid rgba(255,255,255,0.1);">
                <th style="padding:8px;">Model Alias</th>
                <th style="padding:8px;">Target Engine</th>
                <th style="padding:8px;">Concurrency</th>
                <th style="padding:8px;">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr style="border-bottom:1px solid rgba(255,255,255,0.05); color:#fff;">
                <td style="padding:10px 8px; color:#00f2fe;">qwen2.5:32b</td>
                <td style="padding:10px 8px;">Ollama (GB10 Natively)</td>
                <td style="padding:10px 8px;">1 request max</td>
                <td style="padding:10px 8px; color:#10b981;">Nominal</td>
              </tr>
              <tr style="color:#fff;">
                <td style="padding:10px 8px; color:#ec4899;">llama-3.3:70b-instruct</td>
                <td style="padding:10px 8px;">Host Ollama Loopback</td>
                <td style="padding:10px 8px;">1 request max</td>
                <td style="padding:10px 8px; color:#10b981;">Ready</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    `
  },
  network: {
    id: "network",
    title: "Network",
    desc: "Egress Proxy & Tool Traffic",
    route: "/efw/",
    hotkey: "⌘4",
    color: "#10b981",
    icon: "Network",
    previewHtml: `
      <div style="height:100vh; padding:28px 36px; font-family:monospace; background:#0B0E14; color:#10b981; overflow-y:auto;">
        <div style="border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:16px; margin-bottom:20px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <h1 style="font-size:18px; font-weight:700; color:#10b981; margin:0;">mitmproxy Tool Egress Gateway</h1>
            <div style="font-size:11px; color:#94a3b8; margin-top:4px;">Rule 10 In-Transit Credential Injection &amp; Masking</div>
          </div>
          <span style="background:rgba(16,185,129,0.15); border:1px solid #10b981; padding:4px 10px; border-radius:6px; font-size:11px;">PROXY :8082 ACTIVE</span>
        </div>
        <div style="background:#111622; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:16px; font-size:12px; line-height:22px;">
          <div style="color:#94a3b8; margin-bottom:8px;">// Live Egress Inspection Stream:</div>
          <div><span style="color:#fff;">[10:18:22]</span> <span style="color:#00f2fe;">192.168.128.4</span> <span style="color:#ec4899;">POST</span> https://api.github.com/graphql &rarr; <span style="color:#f59e0b;">INJECT: Authorization: Bearer [INJECTED_CINDY_TOKEN]</span> &rarr; <span style="color:#10b981;">200 OK (210ms)</span></div>
          <div><span style="color:#fff;">[10:19:04]</span> <span style="color:#00f2fe;">192.168.128.4</span> <span style="color:#10b981;">GET</span> https://api.github.com/repos/brainsOS/issues &rarr; <span style="color:#f59e0b;">INJECT: Authorization</span> &rarr; <span style="color:#10b981;">200 OK (145ms)</span></div>
          <div><span style="color:#fff;">[10:20:11]</span> <span style="color:#eab308;">192.168.128.99</span> <span style="color:#ec4899;">CONNECT</span> https://unauthorized-host.com &rarr; <span style="color:#ef4444; font-weight:bold;">403 FORBIDDEN (Egress Policy Blocked)</span></div>
        </div>
      </div>
    `
  },
  trace: {
    id: "trace",
    title: "Trace",
    desc: "Session Tracing & Observability",
    route: "/langfuse/",
    hotkey: "⌘5",
    color: "#3b82f6",
    icon: "Activity",
    previewHtml: `
      <div style="height:100vh; padding:28px 36px; font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#0B0E14; color:#f8fafc; overflow-y:auto;">
        <div style="border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:16px; margin-bottom:20px; display:flex; justify-content:space-between; align-items:center;">
          <div>
            <h1 style="font-size:18px; font-weight:700; color:#3b82f6; margin:0;">Langfuse OpenTelemetry Observatory</h1>
            <div style="font-size:11px; color:#94a3b8; margin-top:4px;">Distributed Tracing &amp; Prompt Token Breakdown</div>
          </div>
          <div style="font-family:monospace; font-size:11px; background:rgba(59,130,246,0.15); border:1px solid #3b82f6; color:#3b82f6; padding:4px 10px; border-radius:6px;">OTEL Collector Online</div>
        </div>
        <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:16px; font-size:12px;">
          <div style="font-weight:600; font-size:13px; margin-bottom:12px;">Latest Trace: hermes-subagent-dispatch-8841</div>
          <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; font-family:monospace; font-size:11px;">
            <div style="background:#0e131d; padding:10px; border-radius:6px;"><span style="color:#94a3b8;">Total Latency:</span> <b style="color:#fff;">382ms</b></div>
            <div style="background:#0e131d; padding:10px; border-radius:6px;"><span style="color:#94a3b8;">Prompt Tokens:</span> <b style="color:#00f2fe;">3,120</b></div>
            <div style="background:#0e131d; padding:10px; border-radius:6px;"><span style="color:#94a3b8;">Completion:</span> <b style="color:#10b981;">284</b></div>
            <div style="background:#0e131d; padding:10px; border-radius:6px;"><span style="color:#ec4899;">Cost:</span> <b style="color:#ec4899;">$0.0000 (Local)</b></div>
          </div>
          <div style="font-family:monospace; font-size:11px; color:#94a3b8; line-height:22px; background:#0e131d; padding:12px; border-radius:6px;">
            &boxur;&boxh; root_span: run_turn (382ms)<br>
            &nbsp;&nbsp;&boxur;&boxh; model_call: qwen2.5:32b (360ms) [LiteLLM Gateway Serialized]<br>
            &nbsp;&nbsp;&boxur;&boxh; tool_execution: file_edit (14ms)<br>
            &nbsp;&nbsp;&boxur;&boxh; memory_append: OKF Markdown (8ms) [Rule 1 Purity Verified]
          </div>
        </div>
      </div>
    `
  },
  users: {
    id: "users",
    title: "Identity",
    desc: "Authentik IdP & Provisioning",
    route: "/auth/if/admin/",
    hotkey: "⌘6",
    color: "#a855f7",
    icon: "Users",
    previewHtml: `
      <div style="height:100vh; padding:28px 36px; font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#0B0E14; color:#f8fafc; overflow-y:auto;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:16px; margin-bottom:24px;">
          <div>
            <h1 style="font-size:20px; font-weight:700; margin:0; color:#a855f7;">Authentik Identity &amp; Access Governance</h1>
            <p style="font-size:12px; color:#94a3b8; margin:4px 0 0;">Zero-Trust Single Sign-On • User &amp; Tenant Provisioning Engine</p>
          </div>
          <div style="display:flex; gap:10px;">
            <a href="/auth/if/admin/#/identity/users" target="_blank" style="text-decoration:none; background:rgba(168,85,247,0.15); border:1px solid #a855f7; color:#a855f7; padding:6px 14px; border-radius:8px; font-size:12px; font-weight:600; display:flex; align-items:center; gap:6px;">
              <span>+ Provision User</span>
            </a>
            <div style="background:rgba(16,185,129,0.15); border:1px solid #10b981; color:#10b981; padding:6px 14px; border-radius:8px; font-size:12px; font-family:monospace;">
              Embedded Outpost: ONLINE
            </div>
          </div>
        </div>

        <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; margin-bottom:24px;">
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:16px;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase;">Provisioned Users</div>
            <div style="font-size:24px; font-weight:700; color:#fff; margin-top:6px;">4 Accounts</div>
            <div style="font-size:11px; color:#a855f7; margin-top:4px;">● 1 Superuser, 3 Service Tenants</div>
          </div>
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:16px;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase;">Active SSO Sessions</div>
            <div style="font-size:24px; font-weight:700; color:#00f2fe; margin-top:6px;">1 Live Session</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:4px;">First-Party Cookie (*.local.brainsos.ai)</div>
          </div>
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:16px;">
            <div style="font-size:11px; color:#94a3b8; text-transform:uppercase;">MFA &amp; Passkeys</div>
            <div style="font-size:24px; font-weight:700; color:#10b981; margin-top:6px;">FIDO2 / WebAuthn</div>
            <div style="font-size:11px; color:#10b981; margin-top:4px;">Hardware Enclave Ready</div>
          </div>
        </div>

        <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:20px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
            <div style="font-weight:600; font-size:14px;">User Directory &amp; Tenant Accounts</div>
            <span style="font-size:11px; color:#94a3b8; font-family:monospace;">Domain: local.brainsos.ai</span>
          </div>
          <table style="width:100%; font-size:12px; border-collapse:collapse; font-family:monospace;">
            <thead>
              <tr style="text-align:left; color:#94a3b8; border-bottom:1px solid rgba(255,255,255,0.1);">
                <th style="padding:8px;">Username</th>
                <th style="padding:8px;">Display Name</th>
                <th style="padding:8px;">Role / Groups</th>
                <th style="padding:8px;">Auth Type</th>
                <th style="padding:8px;">Status</th>
              </tr>
            </thead>
            <tbody>
              <tr style="border-bottom:1px solid rgba(255,255,255,0.05); color:#fff;">
                <td style="padding:10px 8px; color:#00f2fe; font-weight:bold;">operator</td>
                <td style="padding:10px 8px;">Appliance Operator</td>
                <td style="padding:10px 8px;"><span style="background:rgba(0,242,254,0.15); color:#00f2fe; padding:2px 8px; border-radius:4px; font-size:10px;">authentik Admins</span></td>
                <td style="padding:10px 8px;">Password / FIDO2</td>
                <td style="padding:10px 8px; color:#10b981;">Active</td>
              </tr>
              <tr style="border-bottom:1px solid rgba(255,255,255,0.05); color:#fff;">
                <td style="padding:10px 8px; color:#ec4899;">cindy</td>
                <td style="padding:10px 8px;">Cindy Pawford</td>
                <td style="padding:10px 8px;"><span style="background:rgba(236,72,153,0.15); color:#ec4899; padding:2px 8px; border-radius:4px; font-size:10px;">Agent Fleet</span></td>
                <td style="padding:10px 8px;">Forward-Auth Proxy</td>
                <td style="padding:10px 8px; color:#10b981;">Active</td>
              </tr>
              <tr style="border-bottom:1px solid rgba(255,255,255,0.05); color:#fff;">
                <td style="padding:10px 8px; color:#a855f7;">hermes</td>
                <td style="padding:10px 8px;">Hermes Orchestrator</td>
                <td style="padding:10px 8px;"><span style="background:rgba(168,85,247,0.15); color:#a855f7; padding:2px 8px; border-radius:4px; font-size:10px;">Service Runner</span></td>
                <td style="padding:10px 8px;">Internal Token</td>
                <td style="padding:10px 8px; color:#10b981;">Active</td>
              </tr>
              <tr style="color:#fff;">
                <td style="padding:10px 8px; color:#94a3b8;">akadmin</td>
                <td style="padding:10px 8px;">Built-in System Admin</td>
                <td style="padding:10px 8px;"><span style="background:rgba(255,255,255,0.1); color:#fff; padding:2px 8px; border-radius:4px; font-size:10px;">Superuser</span></td>
                <td style="padding:10px 8px;">Bootstrap Secret</td>
                <td style="padding:10px 8px; color:#10b981;">Active</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    `
  },
  help: {
    id: "help",
    title: "Help",
    desc: "FAQs & Architecture Matrix",
    route: "https://docs.brainsos.local",
    hotkey: "⌘H",
    color: "#eab308",
    icon: "HelpCircle",
    previewHtml: `
      <div style="height:100vh; padding:32px 40px; font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#0B0E14; color:#f8fafc; overflow-y:auto;">
        <div style="border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:16px; margin-bottom:24px;">
          <h1 style="font-size:22px; font-weight:700; color:#eab308; margin:0;">brainsOS Architectural Matrix &amp; Rules</h1>
          <p style="font-size:12px; color:#94a3b8; margin:4px 0 0;">Zero-Trust Operating Guardrails &amp; Plane Separation Protocol</p>
        </div>
        <div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:16px;">
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:16px;">
            <div style="font-weight:700; color:#00f2fe; font-size:13px; margin-bottom:8px;">Rule 1: Memory Plane Purity (/memories)</div>
            <p style="color:#cbd5e1; line-height:20px; margin:0;">Strictly reserved for human-auditable Open Knowledge Format (OKF) Markdown files. Zero SQLite, vector indices, or caches.</p>
          </div>
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:16px;">
            <div style="font-weight:700; color:#ec4899; font-size:13px; margin-bottom:8px;">Rule 2: Raw Inference Boundary</div>
            <p style="color:#cbd5e1; line-height:20px; margin:0;">Ollama runs natively on the host bound strictly to loopback (127.0.0.1:11434). Agent containers route strictly through LiteLLM proxy.</p>
          </div>
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:16px;">
            <div style="font-weight:700; color:#f59e0b; font-size:13px; margin-bottom:8px;">Rule 3: Hardware Serialization</div>
            <p style="color:#cbd5e1; line-height:20px; margin:0;">LiteLLM enforces max_parallel_requests: 1 to protect the unified 273 GB/s memory bus from bandwidth thrashing.</p>
          </div>
          <div style="background:#141a26; border:1px solid rgba(255,255,255,0.08); border-radius:10px; padding:16px;">
            <div style="font-weight:700; color:#eab308; font-size:13px; margin-bottom:8px;">Rule 14: Two-Repository Architecture</div>
            <p style="color:#cbd5e1; line-height:20px; margin:0;">Stateless open-source platform core (brainsOS.ai) is decoupled from proprietary fleet repositories (BRAINSOS_DATA_DIR). Zero proprietary client IP in the public codebase.</p>
          </div>
        </div>
      </div>
    `
  }
};
