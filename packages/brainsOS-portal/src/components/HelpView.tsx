import React, { useState, useEffect } from 'react';
import {
  ExternalLink,
  Copy,
  Check,
  Activity,
  Shield,
  Terminal,
  Mail,
  Network,
  Lock,
  Cpu,
  GitBranch,
  Github,
  Keyboard,
  Globe,
  Command,
  Sparkles,
  Layers,
  ArrowRight,
  FileText,
  KeyRound,
  Bug,
  Lightbulb,
  MessageSquarePlus
} from 'lucide-react';

interface ToolItem {
  id: string;
  name: string;
  category: string;
  desc: string;
  icon: React.ElementType;
  color: string;
  path: string;
  port?: string;
  hotkey?: string;
  isExternal?: boolean;
}

const TOOLS: ToolItem[] = [
  {
    id: 'mail',
    name: 'Webmail (SOGo & Groupware)',
    category: '1. Secure Communications',
    desc: 'Encrypt and log every message in and out — Agent messaging, CalDAV calendar, and CardDAV directory.',
    icon: Mail,
    color: '#ec4899',
    path: '/mail/',
    port: '20000',
    hotkey: 'Alt+1',
  },
  {
    id: 'auth',
    name: 'Authentik Identity Provider',
    category: '2. Identity Management',
    desc: 'Give each agent its own scoped credentials — Single Sign-On (SSO) authority, user directory, and Forward-Auth audit logs.',
    icon: Lock,
    color: '#a855f7',
    path: '/auth/if/admin/#/events/log',
    port: '9000',
    hotkey: 'Alt+2',
  },
  {
    id: 'gateway',
    name: 'LiteLLM Gateway',
    category: '3. Routing & Guardrails',
    desc: 'Check every model call against policy — Hardware-serialized LLM proxy, virtual tenant keys, and usage governance.',
    icon: Shield,
    color: '#f59e0b',
    path: '/proxy/ui/usage',
    port: '4000',
    hotkey: 'Alt+3',
  },
  {
    id: 'telemetry',
    name: 'Langfuse Observatory',
    category: '4. Telemetry Data',
    desc: 'Trace decisions and benchmark performance — Distributed OpenTelemetry session tracing, token breakdown, and latency diagnostics.',
    icon: Activity,
    color: '#3b82f6',
    path: '/project/brainsos/sessions',
    port: '3001',
    hotkey: 'Alt+4',
  },
  {
    id: 'egress',
    name: 'Egress Proxy (mitmweb)',
    category: '5. Network Firewalls',
    desc: 'Allow only approved destinations — Live outbound HTTP/HTTPS inspection console, token redaction, and egress policy auditing.',
    icon: Network,
    color: '#10b981',
    path: '/efw/',
    port: '8081',
    hotkey: 'Alt+5',
  },
  {
    id: 'editor',
    name: 'Code Console (VS Code)',
    category: '6. Readable Memory',
    desc: 'Keep notes in readable files people can audit — Full-featured web IDE for inspecting OKF Markdown memories and workspaces.',
    icon: Terminal,
    color: '#00f2fe',
    path: '/editor/',
    port: '8443',
    hotkey: 'Alt+6',
  },
  {
    id: 'git',
    name: 'Git Server (Gitea)',
    category: '7. Source Control',
    desc: 'Version prompts and configs so changes roll back — Local Git server for agent souls, fleet settings, and memory history.',
    icon: GitBranch,
    color: '#f97316',
    path: '/git/',
    port: '3000',
    hotkey: 'Alt+7',
  },
  {
    id: 'system',
    name: 'System Manager & Host Console',
    category: '8. Platform Operations',
    desc: 'System Manager, Updates & Host Console — Appliance identity, 1-click container & OS security updates, and interactive XTerm.js shell.',
    icon: Cpu,
    color: '#00f2fe',
    path: '/system',
    hotkey: 'Alt+8',
  },
  {
    id: 'github',
    name: 'brainsOS.ai Repository',
    category: 'Project Source Code',
    desc: 'Core open-source platform repository, architectural specifications, tickets, and releases.',
    icon: Github,
    color: '#f8fafc',
    path: 'https://github.com/patternsatscale/brainsOS.ai',
    isExternal: true,
  },
];

interface HotkeyItem {
  keys: string[];
  action: string;
  target: string;
  color: string;
  category: 'subsystem' | 'hud';
}

const HOTKEYS: HotkeyItem[] = [
  { keys: ['Alt', '1'], action: 'Switch to Webmail', target: 'Secure Communications — Encrypt and log every message in and out', color: '#ec4899', category: 'subsystem' },
  { keys: ['Alt', '2'], action: 'Switch to Authentik', target: 'Identity Management — Give each agent its own scoped credentials', color: '#a855f7', category: 'subsystem' },
  { keys: ['Alt', '3'], action: 'Switch to LiteLLM', target: 'Routing & Guardrails — Check every model call against policy', color: '#f59e0b', category: 'subsystem' },
  { keys: ['Alt', '4'], action: 'Switch to Langfuse', target: 'Telemetry Data — Trace decisions and benchmark performance', color: '#3b82f6', category: 'subsystem' },
  { keys: ['Alt', '5'], action: 'Switch to Egress Proxy', target: 'Network Firewalls — Allow only approved destinations', color: '#10b981', category: 'subsystem' },
  { keys: ['Alt', '6'], action: 'Switch to Code Console', target: 'Readable Memory — Keep notes in readable files people can audit', color: '#00f2fe', category: 'subsystem' },
  { keys: ['Alt', '7'], action: 'Switch to Git Server', target: 'Source Control — Version prompts and configs so changes roll back', color: '#f97316', category: 'subsystem' },
  { keys: ['Alt', '8'], action: 'Switch to System', target: 'System Manager, Updates & Host Console', color: '#00f2fe', category: 'subsystem' },
  { keys: ['Alt', '9'], action: 'Switch to Help & Architecture', target: 'FAQs & Architecture Matrix', color: '#eab308', category: 'subsystem' },
  { keys: ['⌘', 'K'], action: 'Toggle HUD Drawer', target: 'Subsystems Slide-Over Palette', color: '#00f2fe', category: 'hud' },
  { keys: ['⌘', 'U'], action: 'Toggle Account Popout', target: 'Operator Profile & Settings', color: '#ec4899', category: 'hud' },
  { keys: ['ESC'], action: 'Close Modal / Drawer', target: 'Dismiss any open HUD overlay', color: '#94a3b8', category: 'hud' },
  { keys: ['F11'], action: 'Toggle Fullscreen', target: 'Expand viewport to 100% display', color: '#10b981', category: 'hud' },
];

interface ArchLayerItem {
  step: string;
  title: string;
  stack: string;
  detail: string;
  color: string;
  icon: React.ElementType;
}

const ARCH_FLOW_LAYERS: ArchLayerItem[] = [
  {
    step: '01',
    title: '1. Secure Communications',
    stack: 'Stalwart Mail + Roundcube / SOGo',
    detail: 'TLS & audit logging for every inbound/outbound email, CalDAV event, and agent task.',
    color: '#ec4899',
    icon: Mail,
  },
  {
    step: '02',
    title: '2. Identity Management',
    stack: 'Authentik SSO',
    detail: 'Scoped per-user & per-agent credentials with single-origin Forward-Auth gating.',
    color: '#a855f7',
    icon: Lock,
  },
  {
    step: '03',
    title: '3. Routing & Guardrails',
    stack: 'LiteLLM Proxy (:4000)',
    detail: 'Policy checks, virtual tenant budget caps & hardware serialization (max_parallel_requests: 1).',
    color: '#f59e0b',
    icon: Shield,
  },
  {
    step: '04',
    title: '4. Telemetry Data',
    stack: 'Langfuse + Telemetry API',
    detail: 'Distributed OpenTelemetry decision traces, token latency benchmarks & millijoule accounting.',
    color: '#3b82f6',
    icon: Activity,
  },
  {
    step: '05',
    title: '5. Network Firewalls',
    stack: 'Egress MITM Proxy (:8082)',
    detail: 'Destination allowlists, in-transit secret injection & token redaction in mitmweb.',
    color: '#10b981',
    icon: Network,
  },
  {
    step: '06',
    title: '6. Readable Memory',
    stack: 'Memory Viewer + WebDAV / VS Code',
    detail: 'Pure human-auditable Open Knowledge Format (OKF) Markdown files in /memories.',
    color: '#00f2fe',
    icon: FileText,
  },
  {
    step: '07',
    title: '7. Source Control',
    stack: 'Gitea + Code Server',
    detail: 'Versioned prompts, SOUL.md personas & agent codebases with instant Git rollback.',
    color: '#f97316',
    icon: GitBranch,
  },
];

interface DockerPlaneItem {
  name: string;
  role: string;
  color: string;
  services: string[];
  boundary: string;
}

const DOCKER_PLANES: DockerPlaneItem[] = [
  {
    name: 'brainsos-ingress-net',
    role: 'Single-Origin TLS & SSO Perimeter',
    color: '#a855f7',
    services: ['caddy (:443)', 'authentik-server', 'portal', 'sogo (:20000)'],
    boundary: 'Exposes only :80/:443 to LAN/VPC; enforces Authentik Forward-Auth across every UI route.',
  },
  {
    name: 'brainsos-control-net',
    role: 'LLM Governance & Control Databases',
    color: '#f59e0b',
    services: ['litellm (:4000)', 'litellm-db (Postgres)', 'authentik-db', 'redis'],
    boundary: 'Zero host DB port bindings; agent runners are completely excluded from this bridge.',
  },
  {
    name: 'brainsos-internal-net',
    role: 'Sandboxed Autonomous Agent Execution',
    color: '#00f2fe',
    services: ['hermes-runner (:8642)', 'egress-proxy (:8082)', 'agent apps'],
    boundary: 'Agents can only reach litellm:4000 and egress-proxy:8082 — zero access to Postgres DBs, IMDSv2, or docker.sock.',
  },
  {
    name: 'brainsos-ide-net',
    role: 'Operator Inspection & Git Versioning',
    color: '#f97316',
    services: ['code-server (:8443)', 'gitea (:3000)', 'webdav'],
    boundary: 'Pre-wired to /data (operator/agent-box) for auditing OKF Markdown memories and SOUL.md prompts.',
  },
  {
    name: 'brainsos-telemetry-net',
    role: 'Distributed Observability & Tracing',
    color: '#3b82f6',
    services: ['langfuse-web (:3001)', 'langfuse-worker', 'clickhouse', 'minio'],
    boundary: 'Ingests asynchronous OpenTelemetry spans from LiteLLM and Hermes without exposing storage engines.',
  },
];

const ARCH_GUARDRAILS = [
  {
    title: 'Memory Plane Purity',
    badge: 'Rule 1 • /memories',
    color: '#00f2fe',
    icon: FileText,
    desc: '/memories is strictly reserved for human-auditable Open Knowledge Format (OKF) Markdown files — zero opaque vector DBs, SQLite binaries, or runtime caches.',
  },
  {
    title: 'In-Transit Egress Auth',
    badge: 'Rule 10 • :8082 Proxy',
    color: '#10b981',
    icon: KeyRound,
    desc: 'Agent containers hold zero raw GitHub PATs or API tokens in .env. Credentials are injected in transit by the egress proxy and redacted in mitmweb.',
  },
  {
    title: 'Unified Memory Protection',
    badge: 'Rule 3 • Hardware Bus',
    color: '#f59e0b',
    icon: Cpu,
    desc: 'LiteLLM serializes local inference requests (max_parallel_requests: 1) to protect the unified LPDDR5x memory bus from bandwidth thrashing.',
  },
];

export const HelpView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'tools' | 'hotkeys' | 'architecture' | 'feedback'>('tools');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [activePressed, setActivePressed] = useState<string | null>(null);
  const [issueType, setIssueType] = useState<'bug' | 'feature'>('bug');
  const [issuePlane, setIssuePlane] = useState<string>('General / Portal');
  const [issueTitle, setIssueTitle] = useState<string>('');
  const [issueDetails, setIssueDetails] = useState<string>('');
  const [issueExpected, setIssueExpected] = useState<string>('');

  const buildGitHubIssueUrl = () => {
    const repoBase = 'https://github.com/patternsatscale/brainsOS.ai/issues/new';
    const prefix = issueType === 'bug' ? '[Bug]' : '[Feature]';
    const cleanTitle = issueTitle.trim() || (issueType === 'bug' ? 'Describe the issue' : 'Concise feature summary');
    const fullTitle = cleanTitle.startsWith('[') ? cleanTitle : `${prefix} ${cleanTitle}`;
    const label = issueType === 'bug' ? 'type:bug' : 'type:feat';
    const template = issueType === 'bug' ? 'bug_report.md' : 'feature_request.md';
    const hostInfo = typeof window !== 'undefined' ? window.location.hostname : 'brainsos-appliance';

    const bodyLines =
      issueType === 'bug'
        ? [
            '## 1. Observed Behavior',
            issueDetails.trim() || '<!-- Describe what happened, error messages, or unexpected behavior -->',
            '',
            '## 2. Expected Behavior',
            issueExpected.trim() || '<!-- Describe what you expected to happen -->',
            '',
            '## 3. Environment & Subsystem Context',
            `- **Affected Subsystem**: ${issuePlane}`,
            `- **Appliance Host**: \`${hostInfo}\``,
            `- **Release**: \`v0.1.5 (ARM64)\``,
          ]
        : [
            '## 1. Problem Statement or Opportunity',
            issueDetails.trim() || '<!-- What problem does this solve or what capability does it unlock? -->',
            '',
            '## 2. Proposed Solution & Subsystem',
            issueExpected.trim() || '<!-- How should this work? -->',
            '',
            `- **Target Subsystem**: ${issuePlane}`,
            `- **Appliance Version**: \`v0.1.5 (ARM64)\``,
          ];

    const params = new URLSearchParams({
      template,
      labels: label,
      title: fullTitle,
      body: bodyLines.join('\n'),
    });
    return `${repoBase}?${params.toString()}`;
  };

  // Compute live absolute URLs based on current host
  const getToolUrl = (tool: ToolItem) => {
    if (tool.isExternal) return tool.path;
    if (typeof window === 'undefined') return tool.path;

    const host = window.location.hostname;
    const proto = window.location.protocol;
    const port = window.location.port ? `:${window.location.port}` : '';

    if (tool.id === 'telemetry' || tool.id === 'trace') {
      if (!host.startsWith('langfuse.')) {
        return `${proto}//langfuse.${host}${port}/project/brainsos/sessions`;
      }
      return `${proto}//${host}${port}/project/brainsos/sessions`;
    }
    return `${proto}//${host}${port}${tool.path}`;
  };

  const handleCopy = (tool: ToolItem) => {
    const url = getToolUrl(tool);
    navigator.clipboard.writeText(url);
    setCopiedId(tool.id);
    setTimeout(() => setCopiedId(null), 1800);
  };

  // Interactive live key listener for fun feedback
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const key = e.key.toUpperCase();
      if (e.altKey) {
        setActivePressed(`Alt${key}`);
      } else if (e.metaKey || e.ctrlKey) {
        setActivePressed(`⌘${key}`);
      } else if (key === 'ESCAPE') {
        setActivePressed('ESC');
      } else if (key === 'F11') {
        setActivePressed('F11');
      }
      setTimeout(() => setActivePressed(null), 800);
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className="w-full h-full flex flex-col bg-[#07090E] text-slate-200 overflow-y-auto font-sans selection:bg-[#00f2fe] selection:text-black">
      {/* Top Header Bar */}
      <div className="px-8 pt-8 pb-5 border-b border-white/10 bg-gradient-to-b from-[#0E131F] to-[#07090E] shrink-0">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 font-mono text-[11px] text-slate-400">
              <span className="w-2 h-2 rounded-full bg-[#00f2fe] shadow-[0_0_8px_#00f2fe] animate-pulse" />
              <span className="text-[#00f2fe] font-semibold uppercase tracking-wider">Appliance Reference</span>
              <span>•</span>
              <span>brainsOS.ai</span>
            </div>
            <h1 className="font-headline font-bold text-2xl text-white tracking-tight mt-1">
              Tools, Hotkeys &amp; Architecture
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              Direct URLs to appliance subsystem tools, keyboard shortcuts, and zero-trust architecture blueprints.
            </p>
          </div>

          {/* 4 Simple Tabs: Tool URLs, Hotkeys, Architecture & Feedback */}
          <div className="flex flex-wrap items-center p-1 rounded-xl bg-[#111622] border border-white/10 shrink-0 font-mono text-xs">
            <button
              onClick={() => setActiveTab('tools')}
              className={`px-3.5 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
                activeTab === 'tools'
                  ? 'bg-[#00f2fe]/15 text-[#00f2fe] border border-[#00f2fe]/30 shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Tool URLs</span>
            </button>
            <button
              onClick={() => setActiveTab('hotkeys')}
              className={`px-3.5 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
                activeTab === 'hotkeys'
                  ? 'bg-[#ec4899]/15 text-[#ec4899] border border-[#ec4899]/30 shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Keyboard className="w-3.5 h-3.5" />
              <span>Hotkeys</span>
              <Sparkles className="w-3 h-3 text-[#eab308]" />
            </button>
            <button
              onClick={() => setActiveTab('architecture')}
              className={`px-3.5 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
                activeTab === 'architecture'
                  ? 'bg-[#10b981]/15 text-[#10b981] border border-[#10b981]/30 shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Architecture</span>
            </button>
            <button
              onClick={() => setActiveTab('feedback')}
              className={`px-3.5 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
                activeTab === 'feedback'
                  ? 'bg-[#f59e0b]/15 text-[#f59e0b] border border-[#f59e0b]/30 shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <MessageSquarePlus className="w-3.5 h-3.5" />
              <span>Bugs &amp; Features</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Body */}
      <div className="flex-1 p-8 max-w-5xl mx-auto w-full">
        {/* TAB 1: TOOL URLS */}
        {activeTab === 'tools' && (
          <div className="space-y-4 animate-in fade-in duration-150">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {TOOLS.map((tool) => {
                const Icon = tool.icon;
                const url = getToolUrl(tool);
                const isCopied = copiedId === tool.id;

                return (
                  <div
                    key={tool.id}
                    className="p-5 rounded-2xl bg-[#0E131F] border border-white/10 hover:border-white/20 transition-all flex flex-col justify-between group shadow-lg"
                  >
                    <div>
                      {/* Top Row: Icon + Name + Hotkey Badge */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-3">
                          <div
                            className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 border"
                            style={{
                              backgroundColor: `${tool.color}15`,
                              borderColor: `${tool.color}35`,
                              color: tool.color,
                            }}
                          >
                            <Icon className="w-4 h-4" />
                          </div>
                          <div>
                            <div className="font-headline font-bold text-sm text-white group-hover:text-[#00f2fe] transition-colors">
                              {tool.name}
                            </div>
                            <div className="font-mono text-[10px] text-slate-500 uppercase tracking-wider">
                              {tool.category} {tool.port && `• Port ${tool.port}`}
                            </div>
                          </div>
                        </div>

                        {tool.hotkey && (
                          <kbd className="px-2 py-0.5 rounded bg-white/5 border border-white/10 font-mono text-[11px] text-slate-400 shrink-0 font-bold">
                            {tool.hotkey}
                          </kbd>
                        )}
                        {tool.isExternal && (
                          <span className="px-2 py-0.5 rounded bg-white/5 border border-white/10 font-mono text-[10px] text-slate-400 shrink-0">
                            GitHub
                          </span>
                        )}
                      </div>

                      {/* Description */}
                      <p className="text-xs text-slate-400 mt-3 leading-relaxed">
                        {tool.desc}
                      </p>
                    </div>

                    {/* Bottom URL Capsule & Actions */}
                    <div className="mt-4 pt-3 border-t border-white/5">
                      <div className="flex items-center gap-2 bg-[#080B10] p-1.5 pl-3 rounded-xl border border-white/5">
                        <span className="font-mono text-[11px] text-slate-300 truncate flex-1 select-all">
                          {url}
                        </span>

                        {/* Copy URL Button */}
                        <button
                          onClick={() => handleCopy(tool)}
                          className="p-1.5 px-2.5 rounded-lg bg-white/5 hover:bg-white/15 text-slate-400 hover:text-white transition-all text-xs font-mono flex items-center gap-1.5 shrink-0"
                          title="Copy Full URL to Clipboard"
                        >
                          {isCopied ? (
                            <>
                              <Check className="w-3.5 h-3.5 text-emerald-400" />
                              <span className="text-[10px] text-emerald-400 font-semibold">Copied</span>
                            </>
                          ) : (
                            <>
                              <Copy className="w-3.5 h-3.5" />
                              <span className="text-[10px]">Copy</span>
                            </>
                          )}
                        </button>

                        {/* Launch in New Tab */}
                        <a
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          className="p-1.5 px-2.5 rounded-lg bg-[#00f2fe]/10 hover:bg-[#00f2fe]/20 text-[#00f2fe] border border-[#00f2fe]/30 transition-all text-xs font-mono flex items-center gap-1 shrink-0"
                          title="Open in Clean Browser Tab"
                        >
                          <span className="text-[10px] font-semibold">Open</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 2: KEYBOARD HOTKEYS */}
        {activeTab === 'hotkeys' && (
          <div className="space-y-6 animate-in fade-in duration-150">
            {/* Live Press Banner */}
            <div className="p-4 rounded-2xl bg-gradient-to-r from-[#00f2fe]/10 via-[#ec4899]/10 to-[#f59e0b]/10 border border-white/10 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-xl bg-white/10 flex items-center justify-center text-[#eab308]">
                  <Sparkles className="w-4 h-4" />
                </div>
                <div>
                  <div className="font-headline font-bold text-xs text-white">
                    Interactive Hotkey Engine
                  </div>
                  <div className="text-[11px] text-slate-400">
                    Press any shortcut on your keyboard to test instantaneous navigation and HUD toggling.
                  </div>
                </div>
              </div>

              {activePressed && (
                <div className="px-3 py-1.5 rounded-xl bg-white/20 border border-white/30 font-mono text-sm font-bold text-white shadow-[0_0_12px_rgba(255,255,255,0.3)] animate-bounce">
                  {activePressed}
                </div>
              )}
            </div>

            {/* Section 1: Subsystem Navigation */}
            <div>
              <h2 className="font-headline font-bold text-xs uppercase tracking-wider text-slate-400 mb-3 px-1 flex items-center gap-2">
                <Command className="w-3.5 h-3.5 text-[#00f2fe]" />
                <span>Subsystem Direct Navigation (Alt+1 – Alt+9)</span>
              </h2>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {HOTKEYS.filter((h) => h.category === 'subsystem').map((h, idx) => {
                  const keyString = h.keys.join('');
                  const isMatching = activePressed === keyString;

                  return (
                    <div
                      key={idx}
                      className={`p-3.5 rounded-xl bg-[#0E131F] border transition-all flex items-center justify-between ${
                        isMatching
                          ? 'border-[#00f2fe] bg-[#00f2fe]/10 shadow-[0_0_15px_rgba(0,242,254,0.3)] scale-[1.02]'
                          : 'border-white/10 hover:border-white/20'
                      }`}
                    >
                      <div>
                        <div className="font-headline font-bold text-xs text-white flex items-center gap-2">
                          <span
                            className="w-2 h-2 rounded-full"
                            style={{ backgroundColor: h.color }}
                          />
                          <span>{h.action}</span>
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                          {h.target}
                        </div>
                      </div>

                      {/* 3D Tactile Keycaps */}
                      <div className="flex items-center gap-1 font-mono text-xs font-bold">
                        {h.keys.map((k, kIdx) => (
                          <kbd
                            key={kIdx}
                            className="px-2.5 py-1 rounded-lg bg-[#181f2e] border border-white/20 border-b-2 text-white shadow-md"
                            style={{ borderColor: isMatching ? h.color : undefined }}
                          >
                            {k}
                          </kbd>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Section 2: HUD & Modal Controls */}
            <div className="pt-2">
              <h2 className="font-headline font-bold text-xs uppercase tracking-wider text-slate-400 mb-3 px-1 flex items-center gap-2">
                <Keyboard className="w-3.5 h-3.5 text-[#ec4899]" />
                <span>HUD &amp; Modal Controls</span>
              </h2>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {HOTKEYS.filter((h) => h.category === 'hud').map((h, idx) => {
                  const keyString = h.keys.join('');
                  const isMatching = activePressed === keyString;

                  return (
                    <div
                      key={idx}
                      className={`p-3.5 rounded-xl bg-[#0E131F] border transition-all flex items-center justify-between ${
                        isMatching
                          ? 'border-[#ec4899] bg-[#ec4899]/10 shadow-[0_0_15px_rgba(236,72,153,0.3)] scale-[1.02]'
                          : 'border-white/10 hover:border-white/20'
                      }`}
                    >
                      <div>
                        <div className="font-headline font-bold text-xs text-white flex items-center gap-2">
                          <span
                            className="w-2 h-2 rounded-full"
                            style={{ backgroundColor: h.color }}
                          />
                          <span>{h.action}</span>
                        </div>
                        <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                          {h.target}
                        </div>
                      </div>

                      {/* 3D Tactile Keycaps */}
                      <div className="flex items-center gap-1 font-mono text-xs font-bold">
                        {h.keys.map((k, kIdx) => (
                          <kbd
                            key={kIdx}
                            className="px-2.5 py-1 rounded-lg bg-[#181f2e] border border-white/20 border-b-2 text-white shadow-md"
                            style={{ borderColor: isMatching ? h.color : undefined }}
                          >
                            {k}
                          </kbd>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: ARCHITECTURE DIAGRAMS */}
        {activeTab === 'architecture' && (
          <div className="space-y-6 animate-in fade-in duration-150">
            {/* Section 1: Enterprise Agent in a Box — 7-Layer Request Flow */}
            <div className="bg-[#0d111a]/90 border border-slate-800/80 rounded-2xl p-6 shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 border-b border-white/10">
                <div>
                  <div className="flex items-center gap-2 font-mono text-[10px] text-[#00f2fe] uppercase tracking-wider">
                    <Layers className="w-3.5 h-3.5" />
                    <span>Blueprint 01 • Request Lifecycle</span>
                  </div>
                  <h2 className="font-headline font-bold text-base text-white mt-0.5">
                    Enterprise Agent in a Box — 7-Layer Request Flow
                  </h2>
                </div>
                <div className="font-mono text-[11px] text-slate-400 bg-white/5 px-3 py-1 rounded-lg border border-white/10">
                  Inbound Email / Chat / API → Governed Agent Turn → Audited Output
                </div>
              </div>

              <div className="mt-5 grid grid-cols-1 md:grid-cols-7 gap-2.5 items-stretch">
                {ARCH_FLOW_LAYERS.map((layer, idx) => {
                  const Icon = layer.icon;
                  return (
                    <div key={layer.step} className="flex md:flex-col items-center gap-2">
                      <div className="w-full flex-1 p-3.5 rounded-xl bg-[#0E131F] border border-white/10 hover:border-white/20 transition-all flex flex-col justify-between">
                        <div>
                          <div className="flex items-center justify-between gap-1.5">
                            <div
                              className="w-7 h-7 rounded-lg flex items-center justify-center border shrink-0"
                              style={{
                                backgroundColor: `${layer.color}15`,
                                borderColor: `${layer.color}35`,
                                color: layer.color,
                              }}
                            >
                              <Icon className="w-3.5 h-3.5" />
                            </div>
                            <span
                              className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded border"
                              style={{
                                backgroundColor: `${layer.color}10`,
                                borderColor: `${layer.color}30`,
                                color: layer.color,
                              }}
                            >
                              L{idx + 1}
                            </span>
                          </div>
                          <div className="font-headline font-bold text-xs text-white mt-2.5 leading-snug">
                            {layer.title.replace(/^\d+\.\s*/, '')}
                          </div>
                          <div className="font-mono text-[10px] text-slate-300 mt-1">
                            {layer.stack}
                          </div>
                        </div>
                        <p className="text-[11px] text-slate-400 mt-2 leading-relaxed border-t border-white/5 pt-2">
                          {layer.detail}
                        </p>
                      </div>
                      {idx < ARCH_FLOW_LAYERS.length - 1 && (
                        <ArrowRight className="hidden md:block w-3.5 h-3.5 text-slate-600 shrink-0 -my-1 rotate-0" />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Section 2: Zero-Trust Docker Network Isolation (5 Planes) */}
            <div className="bg-[#0d111a]/90 border border-slate-800/80 rounded-2xl p-6 shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 border-b border-white/10">
                <div>
                  <div className="flex items-center gap-2 font-mono text-[10px] text-[#10b981] uppercase tracking-wider">
                    <Network className="w-3.5 h-3.5" />
                    <span>Blueprint 02 • Container Bridge Topology</span>
                  </div>
                  <h2 className="font-headline font-bold text-base text-white mt-0.5">
                    Zero-Trust Docker Network Isolation (5 Planes)
                  </h2>
                </div>
                <span className="font-mono text-[11px] text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-lg border border-emerald-500/20">
                  18 Services • 5 Isolated Bridge Subnets • Zero Host DB Ports
                </span>
              </div>

              <div className="mt-5 grid grid-cols-1 md:grid-cols-5 gap-3">
                {DOCKER_PLANES.map((plane) => (
                  <div
                    key={plane.name}
                    className="p-4 rounded-xl bg-[#0E131F] border border-white/10 flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: plane.color, boxShadow: `0 0 8px ${plane.color}` }}
                        />
                        <span className="font-mono text-[11px] font-bold text-white truncate">
                          {plane.name}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-300 font-semibold mt-1.5">
                        {plane.role}
                      </div>

                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {plane.services.map((svc) => (
                          <span
                            key={svc}
                            className="px-2 py-0.5 rounded bg-[#080B10] border border-white/10 font-mono text-[10px] text-slate-300"
                          >
                            {svc}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="mt-3 pt-2.5 border-t border-white/5 text-[11px] text-slate-400 leading-relaxed">
                      {plane.boundary}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Section 3: Core Architectural Guardrails (Quick Reference) */}
            <div className="bg-[#0d111a]/90 border border-slate-800/80 rounded-2xl p-6 shadow-xl">
              <div className="flex items-center justify-between gap-2 pb-4 border-b border-white/10">
                <div>
                  <div className="flex items-center gap-2 font-mono text-[10px] text-[#f59e0b] uppercase tracking-wider">
                    <Shield className="w-3.5 h-3.5" />
                    <span>Blueprint 03 • Inviolable Guardrails</span>
                  </div>
                  <h2 className="font-headline font-bold text-base text-white mt-0.5">
                    Core Architectural Guardrails (Quick Reference)
                  </h2>
                </div>
              </div>

              <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-4">
                {ARCH_GUARDRAILS.map((g) => {
                  const Icon = g.icon;
                  return (
                    <div
                      key={g.title}
                      className="p-4 rounded-xl bg-[#0E131F] border border-white/10 flex flex-col justify-between"
                    >
                      <div>
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2.5">
                            <div
                              className="w-8 h-8 rounded-lg flex items-center justify-center border shrink-0"
                              style={{
                                backgroundColor: `${g.color}15`,
                                borderColor: `${g.color}35`,
                                color: g.color,
                              }}
                            >
                              <Icon className="w-4 h-4" />
                            </div>
                            <div className="font-headline font-bold text-sm text-white">
                              {g.title}
                            </div>
                          </div>
                          <span
                            className="font-mono text-[10px] px-2 py-0.5 rounded border shrink-0"
                            style={{
                              backgroundColor: `${g.color}10`,
                              borderColor: `${g.color}30`,
                              color: g.color,
                            }}
                          >
                            {g.badge}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400 mt-3 leading-relaxed">
                          {g.desc}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: BUGS & FEATURE REQUESTS (GITHUB ISSUE COMPOSER) */}
        {activeTab === 'feedback' && (
          <div className="space-y-6 animate-in fade-in duration-150">
            {/* Top 1-Click Direct GitHub Templates */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <a
                href="https://github.com/patternsatscale/brainsOS.ai/issues/new?template=bug_report.md"
                target="_blank"
                rel="noopener noreferrer"
                className="p-5 rounded-2xl bg-[#0E131F] border border-rose-500/25 hover:border-rose-500/50 transition-all flex flex-col justify-between group shadow-lg"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <div className="w-9 h-9 rounded-xl bg-rose-500/15 border border-rose-500/35 text-rose-400 flex items-center justify-center">
                      <Bug className="w-4 h-4" />
                    </div>
                    <ExternalLink className="w-3.5 h-3.5 text-slate-500 group-hover:text-rose-400 transition-colors" />
                  </div>
                  <div className="font-headline font-bold text-sm text-white mt-3 group-hover:text-rose-400 transition-colors">
                    Report a Bug on GitHub
                  </div>
                  <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
                    Open the official Bug Report template directly on <span className="font-mono text-slate-300">brainsOS.ai</span>.
                  </p>
                </div>
                <div className="mt-4 font-mono text-[11px] text-rose-400 flex items-center gap-1.5">
                  <span>issues/new?template=bug_report.md</span>
                </div>
              </a>

              <a
                href="https://github.com/patternsatscale/brainsOS.ai/issues/new?template=feature_request.md"
                target="_blank"
                rel="noopener noreferrer"
                className="p-5 rounded-2xl bg-[#0E131F] border border-amber-500/25 hover:border-amber-500/50 transition-all flex flex-col justify-between group shadow-lg"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <div className="w-9 h-9 rounded-xl bg-amber-500/15 border border-amber-500/35 text-amber-400 flex items-center justify-center">
                      <Lightbulb className="w-4 h-4" />
                    </div>
                    <ExternalLink className="w-3.5 h-3.5 text-slate-500 group-hover:text-amber-400 transition-colors" />
                  </div>
                  <div className="font-headline font-bold text-sm text-white mt-3 group-hover:text-amber-400 transition-colors">
                    Request a Feature / Agent
                  </div>
                  <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
                    Propose a new capability, agent persona, skill, or UX enhancement on GitHub.
                  </p>
                </div>
                <div className="mt-4 font-mono text-[11px] text-amber-400 flex items-center gap-1.5">
                  <span>issues/new?template=feature_request.md</span>
                </div>
              </a>

              <a
                href="https://github.com/patternsatscale/brainsOS.ai/issues"
                target="_blank"
                rel="noopener noreferrer"
                className="p-5 rounded-2xl bg-[#0E131F] border border-white/10 hover:border-[#00f2fe]/40 transition-all flex flex-col justify-between group shadow-lg"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <div className="w-9 h-9 rounded-xl bg-[#00f2fe]/15 border border-[#00f2fe]/35 text-[#00f2fe] flex items-center justify-center">
                      <Github className="w-4 h-4" />
                    </div>
                    <ExternalLink className="w-3.5 h-3.5 text-slate-500 group-hover:text-[#00f2fe] transition-colors" />
                  </div>
                  <div className="font-headline font-bold text-sm text-white mt-3 group-hover:text-[#00f2fe] transition-colors">
                    Browse Open Issues &amp; Roadmap
                  </div>
                  <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
                    See active tickets, release milestones, and community discussions on GitHub.
                  </p>
                </div>
                <div className="mt-4 font-mono text-[11px] text-[#00f2fe] flex items-center gap-1.5">
                  <span>github.com/patternsatscale/brainsOS.ai/issues</span>
                </div>
              </a>
            </div>

            {/* Quick Pre-Filled GitHub Issue Form */}
            <div className="bg-[#0d111a]/90 border border-slate-800/80 rounded-2xl p-6 shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 border-b border-white/10">
                <div>
                  <div className="flex items-center gap-2 font-mono text-[10px] text-[#f59e0b] uppercase tracking-wider">
                    <MessageSquarePlus className="w-3.5 h-3.5" />
                    <span>Quick GitHub Issue Composer</span>
                  </div>
                  <h2 className="font-headline font-bold text-base text-white mt-0.5">
                    Draft Here &amp; Open Pre-Filled on GitHub
                  </h2>
                </div>
                <span className="font-mono text-[11px] text-slate-400 bg-white/5 px-3 py-1 rounded-lg border border-white/10">
                  Auto-attaches subsystem &amp; appliance metadata
                </span>
              </div>

              <div className="mt-5 space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Type Toggle */}
                  <div>
                    <label className="block font-mono text-[11px] text-slate-400 uppercase tracking-wider mb-1.5">
                      Issue Type
                    </label>
                    <div className="grid grid-cols-2 gap-2 p-1 rounded-xl bg-[#080B10] border border-white/10">
                      <button
                        type="button"
                        onClick={() => setIssueType('bug')}
                        className={`py-2 px-3 rounded-lg font-mono text-xs font-medium flex items-center justify-center gap-2 transition-all ${
                          issueType === 'bug'
                            ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40'
                            : 'text-slate-400 hover:text-white'
                        }`}
                      >
                        <Bug className="w-3.5 h-3.5" />
                        <span>Bug Report</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setIssueType('feature')}
                        className={`py-2 px-3 rounded-lg font-mono text-xs font-medium flex items-center justify-center gap-2 transition-all ${
                          issueType === 'feature'
                            ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                            : 'text-slate-400 hover:text-white'
                        }`}
                      >
                        <Lightbulb className="w-3.5 h-3.5" />
                        <span>Feature Request</span>
                      </button>
                    </div>
                  </div>

                  {/* Subsystem Selector */}
                  <div>
                    <label className="block font-mono text-[11px] text-slate-400 uppercase tracking-wider mb-1.5">
                      Subsystem / Layer
                    </label>
                    <select
                      value={issuePlane}
                      onChange={(e) => setIssuePlane(e.target.value)}
                      className="w-full px-3.5 py-2.5 rounded-xl bg-[#080B10] border border-white/10 text-xs text-white font-mono focus:outline-none focus:border-[#00f2fe]/50"
                    >
                      <option value="General / Portal">General / Unified Portal UI</option>
                      <option value="1. Secure Communications (Mail / SOGo)">1. Secure Communications (Mail / SOGo)</option>
                      <option value="2. Identity Management (Authentik SSO)">2. Identity Management (Authentik SSO)</option>
                      <option value="3. Routing & Guardrails (LiteLLM Proxy)">3. Routing &amp; Guardrails (LiteLLM Proxy)</option>
                      <option value="4. Telemetry Data (Langfuse)">4. Telemetry Data (Langfuse)</option>
                      <option value="5. Network Firewalls (Egress Proxy)">5. Network Firewalls (Egress Proxy)</option>
                      <option value="6. Readable Memory & Code Console">6. Readable Memory &amp; Code Console</option>
                      <option value="7. Source Control (Gitea)">7. Source Control (Gitea)</option>
                      <option value="8. System Manager & Host Console">8. System Manager &amp; Host Console</option>
                      <option value="Agent Fleet (Bawtford / Hermes)">Agent Fleet (Bawtford / Hermes)</option>
                    </select>
                  </div>
                </div>

                {/* Title Input */}
                <div>
                  <label className="block font-mono text-[11px] text-slate-400 uppercase tracking-wider mb-1.5">
                    Title / Summary
                  </label>
                  <input
                    type="text"
                    value={issueTitle}
                    onChange={(e) => setIssueTitle(e.target.value)}
                    placeholder={
                      issueType === 'bug'
                        ? 'e.g. Webmail session times out after switching tabs'
                        : 'e.g. Add dark-mode PDF export for agent memory logs'
                    }
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#080B10] border border-white/10 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-[#00f2fe]/50"
                  />
                </div>

                {/* Observed / Problem Details */}
                <div>
                  <label className="block font-mono text-[11px] text-slate-400 uppercase tracking-wider mb-1.5">
                    {issueType === 'bug' ? 'What Happened? (Observed Behavior / Steps)' : 'Problem Statement or Idea'}
                  </label>
                  <textarea
                    rows={3}
                    value={issueDetails}
                    onChange={(e) => setIssueDetails(e.target.value)}
                    placeholder={
                      issueType === 'bug'
                        ? 'Describe what happened, steps to reproduce, or paste any console output...'
                        : 'Describe the workflow improvement or feature you would like to see...'
                    }
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#080B10] border border-white/10 text-xs text-white placeholder:text-slate-600 focus:outline-none focus:border-[#00f2fe]/50 font-mono"
                  />
                </div>

                {/* Expected / Proposed */}
                <div>
                  <label className="block font-mono text-[11px] text-slate-400 uppercase tracking-wider mb-1.5">
                    {issueType === 'bug' ? 'Expected Behavior (Optional)' : 'Proposed Behavior (Optional)'}
                  </label>
                  <textarea
                    rows={2}
                    value={issueExpected}
                    onChange={(e) => setIssueExpected(e.target.value)}
                    placeholder={
                      issueType === 'bug'
                        ? 'What should have happened instead?'
                        : 'Any thoughts on how it should look or work?'
                    }
                    className="w-full px-3.5 py-2.5 rounded-xl bg-[#080B10] border border-white/10 text-xs text-white placeholder:text-slate-600 focus:outline-none focus:border-[#00f2fe]/50 font-mono"
                  />
                </div>

                {/* Submit Row */}
                <div className="pt-2 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <span className="text-[11px] text-slate-500 font-mono">
                    Opens <span className="text-slate-300">github.com/patternsatscale/brainsOS.ai/issues/new</span> in a new tab with your fields pre-filled.
                  </span>
                  <a
                    href={buildGitHubIssueUrl()}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-5 py-2.5 rounded-xl bg-[#00f2fe]/15 hover:bg-[#00f2fe]/25 text-[#00f2fe] border border-[#00f2fe]/40 font-mono text-xs font-semibold flex items-center justify-center gap-2 transition-all shrink-0 shadow-sm"
                  >
                    <Github className="w-4 h-4" />
                    <span>Continue on GitHub</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
