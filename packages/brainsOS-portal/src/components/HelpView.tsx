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
  Github,
  Keyboard,
  Globe,
  Command,
  Sparkles
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
    id: 'trace',
    name: 'Langfuse Observatory',
    category: 'Telemetry & Tracing',
    desc: 'Distributed OpenTelemetry session tracing, token breakdown, and latency diagnostics.',
    icon: Activity,
    color: '#3b82f6',
    path: '/project/brainsos/sessions',
    port: '3001',
    hotkey: '⌘5',
  },
  {
    id: 'security',
    name: 'LiteLLM Gateway',
    category: 'Model Governance',
    desc: 'Hardware-serialized LLM proxy, virtual tenant keys, model registration, and usage telemetry.',
    icon: Shield,
    color: '#f59e0b',
    path: '/proxy/ui/usage',
    port: '4000',
    hotkey: '⌘3',
  },
  {
    id: 'console',
    name: 'Operator Studio (VS Code)',
    category: 'Development Environment',
    desc: 'Full-featured web IDE with integrated terminal, file tree, and workspace editing.',
    icon: Terminal,
    color: '#00f2fe',
    path: '/editor/',
    port: '8443',
    hotkey: '⌘2',
  },
  {
    id: 'comms',
    name: 'SOGo Webmail & Groupware',
    category: 'Agent Communications',
    desc: 'Agent messaging, CalDAV calendar, CardDAV contacts, and scheduled reminders.',
    icon: Mail,
    color: '#ec4899',
    path: '/mail/',
    port: '20000',
    hotkey: '⌘1',
  },
  {
    id: 'network',
    name: 'Tool Egress Gateway (mitmweb)',
    category: 'Egress Inspection',
    desc: 'Live outbound HTTP/HTTPS inspection console, token redaction, and egress policy auditing.',
    icon: Network,
    color: '#10b981',
    path: '/efw/',
    port: '8081',
    hotkey: '⌘4',
  },
  {
    id: 'users',
    name: 'Authentik Identity Provider',
    category: 'Identity & Access (IdP)',
    desc: 'Single Sign-On (SSO) authority, user directory, and Forward-Auth audit event logs.',
    icon: Lock,
    color: '#a855f7',
    path: '/auth/if/admin/#/events/log',
    port: '9000',
    hotkey: '⌘6',
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
  { keys: ['⌘', '1'], action: 'Switch to Comms', target: 'SOGo Webmail & Calendar', color: '#ec4899', category: 'subsystem' },
  { keys: ['⌘', '2'], action: 'Switch to Console', target: 'VS Code IDE & Terminal', color: '#00f2fe', category: 'subsystem' },
  { keys: ['⌘', '3'], action: 'Switch to Security', target: 'LiteLLM Gateway & Usage', color: '#f59e0b', category: 'subsystem' },
  { keys: ['⌘', '4'], action: 'Switch to Network', target: 'Tool Egress Gateway (mitmweb)', color: '#10b981', category: 'subsystem' },
  { keys: ['⌘', '5'], action: 'Switch to Trace', target: 'Langfuse Observatory', color: '#3b82f6', category: 'subsystem' },
  { keys: ['⌘', '6'], action: 'Switch to Identity', target: 'Authentik IdP & Event Logs', color: '#a855f7', category: 'subsystem' },
  { keys: ['⌘', 'H'], action: 'Toggle Help & URLs', target: 'This Tool Reference Page', color: '#eab308', category: 'subsystem' },
  { keys: ['⌘', 'K'], action: 'Toggle HUD Drawer', target: 'Subsystems Slide-Over Palette', color: '#00f2fe', category: 'hud' },
  { keys: ['⌘', 'U'], action: 'Toggle Account Popout', target: 'Operator Profile & Settings', color: '#ec4899', category: 'hud' },
  { keys: ['ESC'], action: 'Close Modal / Drawer', target: 'Dismiss any open HUD overlay', color: '#94a3b8', category: 'hud' },
  { keys: ['F11'], action: 'Toggle Fullscreen', target: 'Expand viewport to 100% display', color: '#10b981', category: 'hud' },
];

export const HelpView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'tools' | 'hotkeys'>('tools');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [activePressed, setActivePressed] = useState<string | null>(null);

  // Compute live absolute URLs based on current host
  const getToolUrl = (tool: ToolItem) => {
    if (tool.isExternal) return tool.path;
    if (typeof window === 'undefined') return tool.path;

    const host = window.location.hostname;
    const proto = window.location.protocol;
    const port = window.location.port ? `:${window.location.port}` : '';

    if (tool.id === 'trace') {
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
      if (e.metaKey || e.ctrlKey) {
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
              Tools &amp; Hotkeys
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              Direct URLs to appliance subsystem tools and complete keyboard shortcuts guide.
            </p>
          </div>

          {/* 2 Simple Tabs: Tool URLs & Hotkeys */}
          <div className="flex items-center p-1 rounded-xl bg-[#111622] border border-white/10 shrink-0 font-mono text-xs">
            <button
              onClick={() => setActiveTab('tools')}
              className={`px-4 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
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
              className={`px-4 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${
                activeTab === 'hotkeys'
                  ? 'bg-[#ec4899]/15 text-[#ec4899] border border-[#ec4899]/30 shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Keyboard className="w-3.5 h-3.5" />
              <span>Hotkeys</span>
              <Sparkles className="w-3 h-3 text-[#eab308]" />
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
                <span>Subsystem Direct Navigation (⌘1 – ⌘6, ⌘H)</span>
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
      </div>
    </div>
  );
};
