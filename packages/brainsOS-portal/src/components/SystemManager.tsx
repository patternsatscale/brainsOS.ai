import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Cpu,
  RefreshCw,
  AlertTriangle,
  ExternalLink,
  Terminal,
  Shield,
  Activity,
  GitBranch,
  Server,
  Play,
  Check,
  Copy,
  X,
  ChevronDown,
  ChevronUp,
  Sparkles,
  ArrowUpCircle,
  Clock,
  Layers,
  HardDrive,
  Trash2,
  FileText
} from 'lucide-react';

interface GitStatus {
  is_git: boolean;
  branch: string;
  current_commit: string;
  remote_commit: string;
  commits_behind: number;
  update_available: boolean;
}

interface ServiceStatus {
  name: string;
  current_version: string;
  latest_version: string;
  update_available: boolean;
  changelog_url: string;
}

interface DiskStatus {
  total_gb: number;
  used_gb: number;
  free_gb: number;
  free_pct: number;
  warning: boolean;
}

interface SystemStatus {
  platform: string;
  git: GitStatus;
  services: Record<string, ServiceStatus>;
  disk?: DiskStatus;
  overall_update_available: boolean;
}

const DEFAULT_STATUS: SystemStatus = {
  platform: "brainsOS Appliance (ARM64)",
  disk: {
    total_gb: 915.3,
    used_gb: 221.6,
    free_gb: 647.2,
    free_pct: 70.7,
    warning: false,
  },
  git: {
    is_git: true,
    branch: "main",
    current_commit: "8e2513c",
    remote_commit: "8e2513c",
    commits_behind: 0,
    update_available: false,
  },
  services: {
    litellm: {
      name: "LiteLLM Gateway",
      current_version: "v1.105.0",
      latest_version: "1.106.5",
      update_available: true,
      changelog_url: "https://github.com/BerriAI/litellm/releases",
    },
    langfuse: {
      name: "Langfuse Observability",
      current_version: "4.58.0",
      latest_version: "4.71.0",
      update_available: true,
      changelog_url: "https://github.com/langfuse/langfuse/releases",
    },
    caddy: {
      name: "Caddy Ingress",
      current_version: "2.8.4",
      latest_version: "2.8.4",
      update_available: false,
      changelog_url: "https://github.com/caddyserver/caddy/releases",
    },
    hermes: {
      name: "Hermes Agent Runner",
      current_version: "v0.1.0-arm64",
      latest_version: "v0.1.0-arm64",
      update_available: false,
      changelog_url: "https://github.com/patternsatscale/brainsOS.ai/releases",
    },
  },
  overall_update_available: true,
};

interface UpdateTarget {
  id: string;
  name: string;
  targetVersion?: string;
  service?: string;
  containersOnly?: boolean;
  full?: boolean;
}

interface LogEntry {
  id: number;
  timestamp: string;
  text: string;
  type: 'log' | 'info' | 'error' | 'success';
}

// Convert ANSI color escape codes into HTML spans
const renderAnsiLine = (text: string) => {
  // Strip or convert standard bash ANSI color sequences
  const clean = text.replace(/\x1B\[[0-9;]*[a-zA-Z]/g, (match) => {
    if (match === '\x1b[0;32m' || match === '\x1b[32m') return '§GREEN§';
    if (match === '\x1b[0;34m' || match === '\x1b[34m') return '§BLUE§';
    if (match === '\x1b[1;33m' || match === '\x1b[33m') return '§YELLOW§';
    if (match === '\x1b[0;31m' || match === '\x1b[31m') return '§RED§';
    if (match === '\x1b[1m') return '§BOLD§';
    if (match === '\x1b[0m') return '§RESET§';
    return '';
  });

  const parts = clean.split(/(§GREEN§|§BLUE§|§YELLOW§|§RED§|§BOLD§|§RESET§)/);
  let currentClass = 'text-slate-300';

  return parts.map((part, idx) => {
    if (part === '§GREEN§') { currentClass = 'text-emerald-400 font-medium'; return null; }
    if (part === '§BLUE§') { currentClass = 'text-cyan-400'; return null; }
    if (part === '§YELLOW§') { currentClass = 'text-amber-300'; return null; }
    if (part === '§RED§') { currentClass = 'text-red-400 font-semibold'; return null; }
    if (part === '§BOLD§') { currentClass = 'text-white font-bold'; return null; }
    if (part === '§RESET§') { currentClass = 'text-slate-300'; return null; }
    if (!part) return null;
    return <span key={idx} className={currentClass}>{part}</span>;
  });
};

export const SystemManager: React.FC = () => {
  const [status, setStatus] = useState<SystemStatus | null>(import.meta.env.DEV ? DEFAULT_STATUS : null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState<boolean>(false);
  const [lastChecked, setLastChecked] = useState<string>('Just now');
  const [confirmTarget, setConfirmTarget] = useState<UpdateTarget | null>(null);

  // Terminal & SSE Log Drawer State
  const [terminalOpen, setTerminalOpen] = useState<boolean>(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [executionStatus, setExecutionStatus] = useState<'idle' | 'running' | 'success' | 'failed'>('idle');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copiedLogs, setCopiedLogs] = useState<boolean>(false);

  const logsEndRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll terminal logs
  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  // Fetch CSRF token on mount (Ticket #325 D2/D4)
  const fetchCsrfToken = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/system/csrf');
      if (res.ok) {
        const data = await res.json();
        if (data && data.csrf_token) {
          setCsrfToken(data.csrf_token);
        }
      }
    } catch {
      // Ignore CSRF pre-fetch failure, handled on request
    }
  }, []);

  // Fetch live system status
  const fetchStatus = useCallback(async () => {
    setIsChecking(true);
    try {
      const res = await fetch('/api/v1/system/status');
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        setStatusError(null);
      } else {
        if (!import.meta.env.DEV) {
          setStatus(null);
        }
        setStatusError(`System API returned HTTP ${res.status}: ${res.statusText}`);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      if (!import.meta.env.DEV) {
        setStatus(null);
      }
      setStatusError(`Failed connecting to System API: ${errMsg}`);
    } finally {
      setIsChecking(false);
      setLastChecked(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchCsrfToken();
  }, [fetchStatus, fetchCsrfToken]);

  // Trigger an update action
  const handleConfirmUpdate = async () => {
    if (!confirmTarget) return;

    const target = confirmTarget;
    setConfirmTarget(null);
    setTerminalOpen(true);
    setExecutionStatus('running');

    const startTimestamp = new Date().toLocaleTimeString();
    setLogs([
      {
        id: 1,
        timestamp: startTimestamp,
        text: `🚀 Initializing appliance update for: ${target.name}...`,
        type: 'info'
      },
      {
        id: 2,
        timestamp: startTimestamp,
        text: `🛡️ Pre-flight snapshot: Executing scripts/control/backup.sh configuration freeze...`,
        type: 'info'
      }
    ]);

    let logCounter = 3;
    const addLog = (text: string, type: 'log' | 'info' | 'error' | 'success' = 'log') => {
      const ts = new Date().toLocaleTimeString();
      setLogs((prev) => [...prev, { id: logCounter++, timestamp: ts, text, type }]);
    };

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken;
    }

    try {
      const res = await fetch('/api/v1/system/update', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          service: target.service,
          containers_only: target.containersOnly,
          full: target.full
        })
      });

      if (!res.ok) {
        let errorDetail = res.statusText;
        try {
          const errData = await res.json();
          if (errData && errData.detail) errorDetail = errData.detail;
        } catch {
          // Fall back to status text
        }
        throw new Error(`HTTP ${res.status}: ${errorDetail}`);
      }

      if (!res.body) {
        throw new Error('Response body is null');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.type === 'log') {
                addLog(payload.line, 'log');
              } else if (payload.type === 'start') {
                addLog(`⚙️ Command launched: ${payload.cmd}`, 'info');
              } else if (payload.type === 'complete') {
                if (payload.exit_code === 0) {
                  addLog(`✅ Update completed successfully! All health invariants satisfied.`, 'success');
                  setExecutionStatus('success');
                } else {
                  addLog(`❌ Update exited with error code ${payload.exit_code}. Rollback evaluated.`, 'error');
                  setExecutionStatus('failed');
                }
              } else if (payload.type === 'error') {
                addLog(`⚠️ Error: ${payload.line}`, 'error');
                setExecutionStatus('failed');
              }
            } catch {
              addLog(line.slice(6));
            }
          }
        }
      }

      // Re-fetch system status after update finishes
      fetchStatus();

    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      if (import.meta.env.DEV) {
        // If live API unavailable, simulate a realistic update session in UI preview mode only
        addLog(`[Local Simulation Mode Active: ${errMsg}]`, 'info');
        addLog(`[INFO] Pulling container updates for ${target.name}...`, 'log');
        await new Promise(r => setTimeout(r, 600));
        addLog(`[INFO] Updating environment parameters in .env...`, 'log');
        await new Promise(r => setTimeout(r, 600));
        addLog(`[INFO] Recreating container topology...`, 'log');
        await new Promise(r => setTimeout(r, 800));
        addLog(`[SUCCESS] Container restarted cleanly.`, 'success');
        addLog(`[INFO] Running post-update health verification...`, 'log');
        await new Promise(r => setTimeout(r, 700));
        addLog(`[SUCCESS] Health check passed on all planes!`, 'success');
        addLog(`✅ In-place update completed with 0 errors.`, 'success');
        setExecutionStatus('success');
      } else {
        // Production failure state (Audit #11 / D4)
        setExecutionStatus('failed');
        addLog(`❌ In-place update failed: ${errMsg}`, 'error');
        addLog(`💡 Remediation: Verify daemon is active ('systemctl status brainsos-system-api') and review journal logs ('journalctl -u brainsos-system-api -n 50').`, 'info');
      }
    }
  };

  const handlePruneLogs = async (checkOnly: boolean = false, dryRun: boolean = false) => {
    setTerminalOpen(true);
    setExecutionStatus('running');

    const startTimestamp = new Date().toLocaleTimeString();
    const actionLabel = checkOnly
      ? 'Auditing storage & log usage'
      : dryRun
      ? 'Simulating log pruning (dry-run)'
      : 'Pruning logs & vacuuming systemd journal';

    setLogs([
      {
        id: 1,
        timestamp: startTimestamp,
        text: `🧹 Initiating maintenance: ${actionLabel}...`,
        type: 'info'
      },
      {
        id: 2,
        timestamp: startTimestamp,
        text: `🛡️ Rule 1 Invariant: /memories and all OKF Markdown files are strictly protected.`,
        type: 'info'
      }
    ]);

    let logCounter = 3;
    const addLog = (text: string, type: 'log' | 'info' | 'error' | 'success' = 'log') => {
      const ts = new Date().toLocaleTimeString();
      setLogs((prev) => [...prev, { id: logCounter++, timestamp: ts, text, type }]);
    };

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken;
    }

    try {
      const response = await fetch('/api/v1/system/prune-logs', {
        method: 'POST',
        headers,
        body: JSON.stringify({ check: checkOnly, dry_run: dryRun })
      });

      if (!response.ok) {
        let errorDetail = response.statusText;
        try {
          const errData = await response.json();
          if (errData && errData.detail) errorDetail = errData.detail;
        } catch {
          // Fall back to status text
        }
        throw new Error(`HTTP ${response.status}: ${errorDetail}`);
      }

      if (!response.body) {
        throw new Error('Response body is null');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.type === 'start') {
                addLog(`▶ Command: ${payload.cmd}`, 'info');
              } else if (payload.type === 'log') {
                addLog(payload.line, 'log');
              } else if (payload.type === 'complete') {
                if (payload.exit_code === 0) {
                  addLog(`✨ Operation completed successfully (exit code 0).`, 'success');
                  setExecutionStatus('success');
                } else {
                  addLog(`❌ Operation failed with exit code ${payload.exit_code}`, 'error');
                  setExecutionStatus('failed');
                }
              } else if (payload.type === 'error') {
                addLog(`⚠️ Error: ${payload.line}`, 'error');
                setExecutionStatus('failed');
              }
            } catch {
              addLog(line.slice(6));
            }
          }
        }
      }

      fetchStatus();

    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      if (import.meta.env.DEV) {
        addLog(`[Local Simulation Mode Active: ${errMsg}]`, 'info');
        if (checkOnly) {
          addLog(`[INFO] Checking filesystem disk space...`, 'log');
          addLog(`[INFO] Disk Status: Total: 915.3 GB | Used: 221.6 GB (24.2%) | Free: 647.2 GB (70.7%)`, 'log');
          addLog(`[SUCCESS] Available disk space is healthy (70.7% free, threshold >= 15%).`, 'success');
          addLog(`[INFO] Auditing log storage consumers...`, 'log');
          addLog(`[INFO] systemd journal usage: Archived and active journals take up 2.5G.`, 'log');
          addLog(`[INFO] Docker disk utilization: Images: 26.5GB, Reclaimable: 13.5GB`, 'log');
        } else {
          addLog(`[INFO] Checking filesystem disk space...`, 'log');
          addLog(`[INFO] Vacuuming systemd journal logs (--vacuum-size=500M)...`, 'log');
          await new Promise(r => setTimeout(r, 500));
          addLog(`[SUCCESS] Vacuumed systemd journal. Reclaimed 2.0 GB.`, 'success');
          addLog(`[INFO] Truncating oversized container logs (>50MB)...`, 'log');
          await new Promise(r => setTimeout(r, 600));
          addLog(`[SUCCESS] Docker container logs verified under 50MB bound.`, 'success');
          addLog(`[INFO] Cleaning ephemeral logs in /tmp older than 7 days...`, 'log');
          await new Promise(r => setTimeout(r, 400));
          addLog(`[SUCCESS] Log pruning & retention maintenance complete.`, 'success');
          addLog(`[INFO] Available Disk Space: 649.2 GB (70.9% free)`, 'log');
        }
        setExecutionStatus('success');
      } else {
        setExecutionStatus('failed');
        addLog(`❌ Maintenance execution failed: ${errMsg}`, 'error');
        addLog(`💡 Remediation: Verify daemon is active ('systemctl status brainsos-system-api') or run scripts/control/prune-logs.sh on host.`, 'info');
      }
    }
  };

  const handleCopyLogs = () => {
    const text = logs.map(l => `[${l.timestamp}] ${l.text}`).join('\n');
    navigator.clipboard.writeText(text);
    setCopiedLogs(true);
    setTimeout(() => setCopiedLogs(false), 2000);
  };

  const handleClearLogs = () => {
    setLogs([]);
    setExecutionStatus('idle');
  };

  return (
    <div className="h-full flex flex-col bg-[#07090E] text-slate-200 overflow-y-auto font-sans antialiased selection:bg-[#00f2fe] selection:text-black">
      {/* 1. Header Bar */}
      <div className="border-b border-white/10 bg-[#0B0E14]/80 backdrop-blur-md px-6 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 shrink-0">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-[#00f2fe]/10 border border-[#00f2fe]/30 text-[#00f2fe]">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="font-headline font-bold text-lg text-white tracking-tight">
                  System Manager &amp; Update Center
                </h1>
                <span className="font-mono text-[10px] uppercase px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 font-semibold">
                  Appliance Active
                </span>
              </div>
              <p className="font-mono text-[11px] text-slate-400 mt-0.5">
                Universal Appliance Lifecycle • Upstream Container &amp; Git Engine • Automated Rollbacks
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={fetchStatus}
            disabled={isChecking}
            className="px-3.5 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-xs font-mono text-slate-300 hover:text-white transition-all flex items-center gap-2 disabled:opacity-50"
            title="Check upstream registries for updates"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-[#00f2fe] ${isChecking ? 'animate-spin' : ''}`} />
            <span>{isChecking ? 'Checking...' : 'Check for Updates'}</span>
          </button>

          <button
            onClick={() => setConfirmTarget({
              id: 'full',
              name: 'brainsOS Platform (Full Stack & Containers)',
              full: true
            })}
            disabled={!status}
            className={`px-4 py-1.5 rounded-xl border text-xs font-mono font-semibold transition-all flex items-center gap-2 ${
              !status
                ? 'opacity-40 cursor-not-allowed bg-slate-800 border-slate-700 text-slate-500'
                : 'bg-gradient-to-r from-[#00f2fe]/20 to-blue-600/20 hover:from-[#00f2fe]/30 hover:to-blue-600/30 border-[#00f2fe]/40 hover:border-[#00f2fe] text-[#00f2fe] hover:text-white shadow-[0_0_15px_rgba(0,242,254,0.15)]'
            }`}
          >
            <ArrowUpCircle className="w-4 h-4" />
            <span>Update Platform</span>
          </button>
        </div>
      </div>

      <div className="p-6 space-y-6 max-w-7xl w-full mx-auto flex-1">
        {/* Status Unavailable Warning Banner (Audit #11 / D4) */}
        {(!status || statusError) && (
          <div className="p-4 rounded-2xl bg-red-500/10 border border-red-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-4 animate-in fade-in">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-red-500/20 text-red-400 border border-red-500/30">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-headline font-semibold text-sm text-red-300">
                  Status unavailable
                </h3>
                <p className="font-mono text-xs text-slate-400 mt-0.5">
                  {statusError || "Live platform status could not be queried. Verify that the brainsos-system-api daemon is running."}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={fetchStatus}
                className="px-3.5 py-1.5 rounded-xl bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-200 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isChecking ? 'animate-spin' : ''}`} />
                <span>Retry Connection</span>
              </button>
            </div>
          </div>
        )}

        {/* 2. Update Available Alert Banner */}
        {status?.overall_update_available && (
          <div className="p-4 rounded-2xl bg-gradient-to-r from-amber-500/10 via-amber-500/5 to-transparent border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-4 animate-in fade-in">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-amber-500/20 text-amber-400 border border-amber-500/30">
                <Sparkles className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-headline font-semibold text-sm text-amber-300">
                  Upstream Software Updates Available
                </h3>
                <p className="font-mono text-xs text-slate-400 mt-0.5">
                  LiteLLM Gateway and Langfuse Observability have newer upstream container releases available.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => setConfirmTarget({
                  id: 'containers',
                  name: 'All Upstream Containers (LiteLLM & Langfuse)',
                  containersOnly: true
                })}
                className="px-3.5 py-1.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
              >
                <ArrowUpCircle className="w-3.5 h-3.5" />
                <span>Update Containers Only</span>
              </button>
            </div>
          </div>
        )}

        {/* 3. System Hardware & Telemetry Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
          <div className="p-4 rounded-2xl bg-[#141a26]/70 border border-white/5 space-y-1.5">
            <div className="flex items-center justify-between text-slate-400">
              <span className="font-mono text-[10px] uppercase tracking-wider font-semibold">Appliance Platform</span>
              <Server className="w-4 h-4 text-[#00f2fe]" />
            </div>
            <div className="font-headline font-bold text-base text-white">ASUS Ascent GX10</div>
            <div className="font-mono text-[11px] text-slate-400 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>NVIDIA GB10 ARM64 • 273 GB/s</span>
            </div>
          </div>

          <div className="p-4 rounded-2xl bg-[#141a26]/70 border border-white/5 space-y-1.5">
            <div className="flex items-center justify-between text-slate-400">
              <span className="font-mono text-[10px] uppercase tracking-wider font-semibold">Git Repository Core</span>
              <GitBranch className="w-4 h-4 text-purple-400" />
            </div>
            <div className="font-headline font-bold text-base text-white">
              {status ? (status.git.branch || 'main') : 'Status unavailable'}
              {status && (
                <span className="font-mono text-xs font-normal text-slate-400 ml-2">
                  ({status.git.current_commit.substring(0, 7)})
                </span>
              )}
            </div>
            <div className="font-mono text-[11px] text-slate-400">
              {status ? (
                status.git.commits_behind > 0 ? (
                  <span className="text-amber-400 font-medium">⚠️ {status.git.commits_behind} commits behind origin</span>
                ) : (
                  <span className="text-emerald-400">● Clean &amp; Synced with origin</span>
                )
              ) : (
                <span className="text-slate-500">Probe offline</span>
              )}
            </div>
          </div>

          {/* Storage & Disk Capacity Metric */}
          <div className="p-4 rounded-2xl bg-[#141a26]/70 border border-white/5 space-y-1.5">
            <div className="flex items-center justify-between text-slate-400">
              <span className="font-mono text-[10px] uppercase tracking-wider font-semibold">Storage Capacity</span>
              <HardDrive className="w-4 h-4 text-[#00f2fe]" />
            </div>
            <div className="font-headline font-bold text-base text-white">
              {status?.disk ? `${status.disk.free_gb} GB Free` : 'Status unavailable'}
            </div>
            <div className="font-mono text-[11px] text-slate-400 flex items-center justify-between">
              {status?.disk ? (
                <>
                  <span className={status.disk.warning ? 'text-amber-400 font-semibold' : 'text-emerald-400'}>
                    {status.disk.free_pct}% available
                  </span>
                  <span className="text-slate-500">({status.disk.total_gb} GB)</span>
                </>
              ) : (
                <span className="text-slate-500">Probe offline</span>
              )}
            </div>
          </div>

          <div className="p-4 rounded-2xl bg-[#141a26]/70 border border-white/5 space-y-1.5">
            <div className="flex items-center justify-between text-slate-400">
              <span className="font-mono text-[10px] uppercase tracking-wider font-semibold">Update Guardrails</span>
              <Shield className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="font-headline font-bold text-base text-emerald-400">Auto-Rollback Active</div>
            <div className="font-mono text-[11px] text-slate-400">
              Pre-flight snapshot via backup.sh
            </div>
          </div>

          <div className="p-4 rounded-2xl bg-[#141a26]/70 border border-white/5 space-y-1.5">
            <div className="flex items-center justify-between text-slate-400">
              <span className="font-mono text-[10px] uppercase tracking-wider font-semibold">Registry Sync</span>
              <Clock className="w-4 h-4 text-slate-400" />
            </div>
            <div className="font-headline font-bold text-base text-white">{lastChecked}</div>
            <div className="font-mono text-[11px] text-slate-400">
              {status ? (status.overall_update_available ? 'Updates pending install' : 'All services current') : 'Status unavailable'}
            </div>
          </div>
        </div>

        {/* 3B. Dedicated Log Management & Disk Retention Safeguards Section */}
        <div className="p-5 rounded-2xl bg-[#141a26]/90 border border-white/10 hover:border-cyan-500/40 transition-all space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/20 text-[#00f2fe] shrink-0">
                <HardDrive className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center gap-2.5">
                  <h2 className="font-headline font-bold text-white text-base">
                    Log Management &amp; Disk Retention Safeguards
                  </h2>
                  {status?.disk?.warning ? (
                    <span className="px-2.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-300 font-mono text-[10px] font-semibold animate-pulse">
                      LOW DISK SPACE ({status.disk.free_pct}% FREE)
                    </span>
                  ) : (
                    <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-semibold">
                      DISK HEALTHY ({status?.disk ? `${status.disk.free_pct}% FREE` : 'STATUS UNAVAILABLE'})
                    </span>
                  )}
                </div>
                <p className="font-mono text-xs text-slate-400 mt-0.5">
                  Automated journal vacuuming • Docker container log bounding • Ephemeral temp log cleanup
                </p>
              </div>
            </div>

            {/* Interactive Maintenance Actions */}
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => handlePruneLogs(true, false)}
                className="px-3 py-1.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 border border-white/10 text-slate-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
                title="Audit disk and log usage without removing files"
              >
                <Activity className="w-3.5 h-3.5 text-cyan-400" />
                <span>Audit Storage</span>
              </button>

              <button
                onClick={() => handlePruneLogs(false, true)}
                className="px-3 py-1.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 border border-white/10 text-slate-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
                title="Simulate log pruning actions without deleting"
              >
                <FileText className="w-3.5 h-3.5 text-amber-400" />
                <span>Dry Run</span>
              </button>

              <button
                onClick={() => handlePruneLogs(false, false)}
                className="px-3.5 py-1.5 rounded-xl bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-500/40 text-[#00f2fe] hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5 shadow-[0_0_12px_rgba(0,242,254,0.15)]"
                title="Prune old container logs, vacuum systemd journal, and clean ephemeral files"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Prune Logs &amp; Free Space</span>
              </button>
            </div>
          </div>

          {/* Metrics & Enforced Bounds Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-white/5">
            {/* Column 1: Disk Capacity Bar */}
            <div className="p-3.5 rounded-xl bg-[#0B0E14]/60 border border-white/5 space-y-2">
              <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                <span className="flex items-center gap-1.5 text-white font-medium">
                  <HardDrive className="w-3.5 h-3.5 text-[#00f2fe]" />
                  <span>Root Filesystem Usage</span>
                </span>
                <span className="text-[#00f2fe] font-semibold">
                  {status?.disk ? `${status.disk.free_gb} GB Free` : 'Status unavailable'}
                </span>
              </div>

              {/* Progress Bar */}
              <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    status?.disk?.warning
                      ? 'bg-gradient-to-r from-amber-500 to-red-500'
                      : 'bg-gradient-to-r from-[#00f2fe] to-emerald-400'
                  }`}
                  style={{ width: `${status?.disk ? Math.min(100, Math.max(0, 100 - status.disk.free_pct)) : 0}%` }}
                />
              </div>

              <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
                <span>
                  Used: {status?.disk ? `${status.disk.used_gb} GB (${((status.disk.used_gb / status.disk.total_gb) * 100).toFixed(1)}%)` : 'Status unavailable'}
                </span>
                <span>
                  Total: {status?.disk ? `${status.disk.total_gb} GB` : 'Status unavailable'}
                </span>
              </div>
            </div>

            {/* Column 2: Active Retention Bounds */}
            <div className="p-3.5 rounded-xl bg-[#0B0E14]/60 border border-white/5 space-y-1.5">
              <div className="text-xs font-mono font-medium text-white flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-emerald-400" />
                <span>Enforced Retention Policies</span>
              </div>
              <div className="space-y-1 font-mono text-[11px] text-slate-400">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">systemd-journald:</span>
                  <span className="text-slate-300 font-medium">500MB max • 30d retention</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Docker container logs:</span>
                  <span className="text-slate-300 font-medium">50MB max • 3 files bound</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Host / Caddy logs:</span>
                  <span className="text-slate-300 font-medium">14d retention • daily gzip</span>
                </div>
              </div>
            </div>

            {/* Column 3: Automated Timer & Memory Plane Guardrail */}
            <div className="p-3.5 rounded-xl bg-[#0B0E14]/60 border border-white/5 space-y-1.5">
              <div className="text-xs font-mono font-medium text-white flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-purple-400" />
                <span>Scheduled Maintenance</span>
              </div>
              <div className="space-y-1 font-mono text-[11px] text-slate-400">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Daily Prune Timer:</span>
                  <span className="text-emerald-400 font-medium">03:30 UTC Active</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Rule 1 Invariant:</span>
                  <span className="text-slate-300 font-medium">/memories strictly protected</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">CLI Maintenance:</span>
                  <span className="text-[#00f2fe] font-medium">make prune-logs</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 4. Service Version Cards Grid */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-headline font-bold text-sm uppercase tracking-wider text-slate-400 flex items-center gap-2">
              <Layers className="w-4 h-4 text-[#00f2fe]" />
              <span>Service Planes &amp; Upstream Release Status</span>
            </h2>
            <span className="font-mono text-xs text-slate-500">
              Managed via docker/compose and scripts/control/update.sh
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {!status ? (
              <div className="col-span-1 md:col-span-2 p-8 rounded-2xl bg-[#141a26]/60 border border-white/5 text-center space-y-3">
                <div className="inline-flex p-3 rounded-2xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  <AlertTriangle className="w-6 h-6" />
                </div>
                <h3 className="font-headline font-bold text-lg text-white">Status Unavailable</h3>
                <p className="font-mono text-xs text-slate-400 max-w-md mx-auto">
                  Live service status could not be queried from the host system daemon. Verify that the <code>brainsos-system-api</code> daemon is running and reachable.
                </p>
                <button
                  onClick={fetchStatus}
                  className="mt-2 px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono text-slate-200 transition-all inline-flex items-center gap-2"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isChecking ? 'animate-spin' : ''}`} />
                  <span>Retry Telemetry Probe</span>
                </button>
              </div>
            ) : (
              <>
                {/* Card 0: brainsOS.ai Core Platform (Source Code) */}
                <div className="col-span-1 md:col-span-2 p-5 rounded-2xl bg-[#141a26]/90 border border-white/10 hover:border-purple-500/40 transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div className="flex items-start gap-3.5">
                    <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400 shrink-0">
                      <GitBranch className="w-5 h-5" />
                    </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    <h3 className="font-headline font-bold text-white text-base">brainsOS.ai Platform Core</h3>
                    {status.git.commits_behind > 0 || status.git.update_available ? (
                      <span className="px-2.5 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-300 font-mono text-[10px] font-semibold animate-pulse">
                        SOURCE UPDATE AVAILABLE ({status.git.commits_behind || 1} COMMITS)
                      </span>
                    ) : (
                      <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-semibold">
                        SYNCED WITH ORIGIN
                      </span>
                    )}
                  </div>
                  <p className="font-mono text-xs text-slate-400 mt-0.5">
                    Git Source Code • Python Packages &amp; Topology Orchestration
                  </p>
                  <div className="flex flex-wrap items-center gap-4 mt-2 font-mono text-xs text-slate-400">
                    <div>
                      <span className="text-slate-500">Branch: </span>
                      <span className="text-white font-medium">{status.git.branch || 'main'}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">Local Commit: </span>
                      <span className="text-[#00f2fe] font-medium">{status.git.current_commit.substring(0, 7)}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">Remote Tracking: </span>
                      <span className="text-purple-400 font-medium">
                        origin/{status.git.branch || 'main'}
                        {status.git.remote_commit && ` (${status.git.remote_commit.substring(0, 7)})`}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex sm:flex-col items-center sm:items-end justify-between sm:justify-center gap-2 shrink-0">
                <a
                  href={`https://github.com/patternsatscale/brainsOS.ai/commits/${status.git.branch || 'main'}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs font-mono text-slate-400 hover:text-purple-400 flex items-center gap-1 transition-colors"
                >
                  <span>Commit History</span>
                  <ExternalLink className="w-3 h-3" />
                </a>

                <button
                  onClick={() => setConfirmTarget({
                    id: 'git-source',
                    name: 'brainsOS.ai Platform Source Code (git pull origin & rebuild)',
                    full: true
                  })}
                  className="px-3.5 py-1.5 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5 shadow-[0_0_10px_rgba(168,85,247,0.15)]"
                >
                  <Play className="w-3 h-3 fill-current" />
                  <span>Pull Latest Source</span>
                </button>
              </div>
            </div>

            {/* Card 1: LiteLLM Gateway */}
            {status.services.litellm && (
              <div className="p-5 rounded-2xl bg-[#141a26]/80 border border-white/10 hover:border-[#00f2fe]/40 transition-all flex flex-col justify-between space-y-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
                      <Shield className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="font-headline font-bold text-white text-base">LiteLLM Gateway</h3>
                      <p className="font-mono text-xs text-slate-400">Control Plane • Hardware Serialized LLM Proxy</p>
                    </div>
                  </div>
                  {status.services.litellm.update_available ? (
                    <span className="shrink-0 px-3 py-1 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-300 font-mono text-[10px] font-semibold animate-pulse flex flex-col items-center justify-center text-center leading-tight">
                      <span>UPDATE</span>
                      <span>AVAILABLE</span>
                    </span>
                  ) : (
                    <span className="shrink-0 px-3 py-1 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-semibold flex flex-col items-center justify-center text-center leading-tight">
                      <span>UP TO</span>
                      <span>DATE</span>
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3 py-2 border-y border-white/5 font-mono text-xs">
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Current Version</span>
                    <span className="text-white font-medium">{status.services.litellm.current_version}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Latest Upstream</span>
                    <span className="text-amber-400 font-medium">{status.services.litellm.latest_version}</span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <a
                    href={status.services.litellm.changelog_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-mono text-slate-400 hover:text-[#00f2fe] flex items-center gap-1 transition-colors"
                  >
                    <span>Changelog</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>

                  {status.services.litellm.update_available && (
                    <button
                      onClick={() => setConfirmTarget({
                        id: 'litellm',
                        name: 'LiteLLM Gateway',
                        targetVersion: status.services.litellm.latest_version,
                        service: 'litellm'
                      })}
                      className="px-3.5 py-1.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
                    >
                      <Play className="w-3 h-3 fill-current" />
                      <span>Update to {status.services.litellm.latest_version}</span>
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Card 2: Langfuse Observability */}
            {status.services.langfuse && (
              <div className="p-5 rounded-2xl bg-[#141a26]/80 border border-white/10 hover:border-[#3b82f6]/40 transition-all flex flex-col justify-between space-y-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
                      <Activity className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="font-headline font-bold text-white text-base">Langfuse Observability</h3>
                      <p className="font-mono text-xs text-slate-400">Telemetry Plane • OpenTelemetry Session Tracing</p>
                    </div>
                  </div>
                  {status.services.langfuse.update_available ? (
                    <span className="shrink-0 px-3 py-1 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-300 font-mono text-[10px] font-semibold animate-pulse flex flex-col items-center justify-center text-center leading-tight">
                      <span>UPDATE</span>
                      <span>AVAILABLE</span>
                    </span>
                  ) : (
                    <span className="shrink-0 px-3 py-1 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-semibold flex flex-col items-center justify-center text-center leading-tight">
                      <span>UP TO</span>
                      <span>DATE</span>
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3 py-2 border-y border-white/5 font-mono text-xs">
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Current Version</span>
                    <span className="text-white font-medium">{status.services.langfuse.current_version}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Latest Upstream</span>
                    <span className="text-amber-400 font-medium">{status.services.langfuse.latest_version}</span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <a
                    href={status.services.langfuse.changelog_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-mono text-slate-400 hover:text-[#3b82f6] flex items-center gap-1 transition-colors"
                  >
                    <span>Changelog</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>

                  {status.services.langfuse.update_available && (
                    <button
                      onClick={() => setConfirmTarget({
                        id: 'langfuse',
                        name: 'Langfuse Observability',
                        targetVersion: status.services.langfuse.latest_version,
                        service: 'langfuse'
                      })}
                      className="px-3.5 py-1.5 rounded-xl bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/40 text-blue-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
                    >
                      <Play className="w-3 h-3 fill-current" />
                      <span>Update to {status.services.langfuse.latest_version}</span>
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Card 3: Caddy Ingress */}
            {status.services.caddy && (
              <div className="p-5 rounded-2xl bg-[#141a26]/80 border border-white/10 hover:border-emerald-500/40 transition-all flex flex-col justify-between space-y-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                      <Server className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="font-headline font-bold text-white text-base">Caddy Ingress</h3>
                      <p className="font-mono text-xs text-slate-400">Ingress Plane • L7 Reverse Proxy &amp; TLS Edge</p>
                    </div>
                  </div>
                  <span className="shrink-0 px-3 py-1 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-semibold flex flex-col items-center justify-center text-center leading-tight">
                    <span>UP TO</span>
                    <span>DATE</span>
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 py-2 border-y border-white/5 font-mono text-xs">
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Current Version</span>
                    <span className="text-white font-medium">{status.services.caddy.current_version}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Latest Upstream</span>
                    <span className="text-emerald-400 font-medium">{status.services.caddy.latest_version}</span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <a
                    href={status.services.caddy.changelog_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-mono text-slate-400 hover:text-emerald-400 flex items-center gap-1 transition-colors"
                  >
                    <span>Changelog</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                  <span className="text-xs font-mono text-slate-500">Auto-renewing ACME</span>
                </div>
              </div>
            )}

            {/* Card 4: Hermes Agent Runner */}
            {status.services.hermes && (
              <div className="p-5 rounded-2xl bg-[#141a26]/80 border border-white/10 hover:border-purple-500/40 transition-all flex flex-col justify-between space-y-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
                      <Cpu className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="font-headline font-bold text-white text-base">Hermes Agent Runner</h3>
                      <p className="font-mono text-xs text-slate-400">Agent Plane • Stateless Multi-Tenant Engine (Rule 9)</p>
                    </div>
                  </div>
                  <span className="shrink-0 px-3 py-1 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-semibold flex flex-col items-center justify-center text-center leading-tight">
                    <span>UP TO</span>
                    <span>DATE</span>
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 py-2 border-y border-white/5 font-mono text-xs">
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Current Version</span>
                    <span className="text-white font-medium">{status.services.hermes.current_version}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Release Line</span>
                    <span className="text-purple-400 font-medium">Native ARM64</span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <a
                    href={status.services.hermes.changelog_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-mono text-slate-400 hover:text-purple-400 flex items-center gap-1 transition-colors"
                  >
                    <span>Release Notes</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                  <span className="text-xs font-mono text-slate-500">Stateless Registry Active</span>
                </div>
              </div>
            )}
              </>
            )}
          </div>
        </div>

        {/* 5. Collapsible Terminal Log Drawer */}
        <div className="rounded-2xl border border-white/10 bg-[#0B0E14] overflow-hidden shadow-2xl">
          <div
            onClick={() => setTerminalOpen(prev => !prev)}
            className="px-5 py-3.5 bg-[#10141f] border-b border-white/5 flex items-center justify-between cursor-pointer select-none group"
          >
            <div className="flex items-center gap-3">
              <div className="p-1.5 rounded-lg bg-white/5 group-hover:bg-[#00f2fe]/20 text-[#00f2fe] transition-colors">
                <Terminal className="w-4 h-4" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-headline font-bold text-xs text-white">
                    Update Stream Terminal
                  </span>
                  {executionStatus === 'running' && (
                    <span className="font-mono text-[9px] uppercase px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30 flex items-center gap-1 animate-pulse">
                      <RefreshCw className="w-2.5 h-2.5 animate-spin" />
                      <span>RUNNING</span>
                    </span>
                  )}
                  {executionStatus === 'success' && (
                    <span className="font-mono text-[9px] uppercase px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                      SUCCESS
                    </span>
                  )}
                  {executionStatus === 'failed' && (
                    <span className="font-mono text-[9px] uppercase px-2 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30">
                      FAILED
                    </span>
                  )}
                </div>
                <p className="font-mono text-[10px] text-slate-400">
                  {logs.length > 0 ? `${logs.length} events logged` : 'Awaiting update command execution...'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
              {logs.length > 0 && (
                <>
                  <button
                    onClick={() => setAutoScroll(prev => !prev)}
                    className={`px-2 py-1 rounded-lg text-[10px] font-mono transition-all ${
                      autoScroll
                        ? 'bg-[#00f2fe]/20 text-[#00f2fe] border border-[#00f2fe]/30'
                        : 'bg-white/5 text-slate-400 hover:text-white'
                    }`}
                    title="Toggle automatic scrolling to bottom"
                  >
                    Scroll: {autoScroll ? 'ON' : 'OFF'}
                  </button>
                  <button
                    onClick={handleCopyLogs}
                    className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white transition-all text-xs flex items-center gap-1 font-mono"
                    title="Copy Terminal Logs"
                  >
                    {copiedLogs ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                  <button
                    onClick={handleClearLogs}
                    className="px-2 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white transition-all text-[10px] font-mono"
                  >
                    Clear
                  </button>
                </>
              )}

              <button
                onClick={() => setTerminalOpen(prev => !prev)}
                className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white transition-all"
                title={terminalOpen ? 'Collapse Terminal' : 'Expand Terminal'}
              >
                {terminalOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {terminalOpen && (
            <div className="p-4 bg-[#05070B] font-mono text-[11.5px] leading-5 text-slate-300 max-h-80 min-h-48 overflow-y-auto space-y-1">
              {logs.length === 0 ? (
                <div className="text-slate-600 italic py-6 text-center select-none">
                  No active execution stream. Click &quot;Update Platform&quot; or an individual service to stream stdout/stderr.
                </div>
              ) : (
                logs.map((log) => (
                  <div key={log.id} className="flex items-start gap-2.5">
                    <span className="text-slate-600 select-none text-[10px] shrink-0 font-mono">
                      [{log.timestamp}]
                    </span>
                    <div className="break-all font-mono">
                      {renderAnsiLine(log.text)}
                    </div>
                  </div>
                ))
              )}
              <div ref={logsEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* 6. Pre-flight Confirmation Modal */}
      {confirmTarget && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in">
          <div className="w-full max-w-lg bg-[#0E131F] border border-white/15 rounded-2xl p-6 shadow-2xl space-y-5 animate-in zoom-in-95">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-400">
                  <AlertTriangle className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="font-headline font-bold text-base text-white">
                    Pre-Flight Update Confirmation
                  </h3>
                  <p className="font-mono text-xs text-slate-400 mt-0.5">
                    Review execution boundaries and impact
                  </p>
                </div>
              </div>
              <button
                onClick={() => setConfirmTarget(null)}
                className="w-7 h-7 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white flex items-center justify-center transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-4 rounded-xl bg-white/[0.03] border border-white/5 space-y-3 font-mono text-xs">
              <div className="flex items-center justify-between pb-2 border-b border-white/5">
                <span className="text-slate-400">Target Action:</span>
                <span className="text-[#00f2fe] font-semibold">{confirmTarget.name}</span>
              </div>
              {confirmTarget.targetVersion && (
                <div className="flex items-center justify-between pb-2 border-b border-white/5">
                  <span className="text-slate-400">Target Version:</span>
                  <span className="text-amber-400 font-semibold">{confirmTarget.targetVersion}</span>
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Rollback Guard:</span>
                <span className="text-emerald-400 font-semibold">Enabled (Automated Snapshot)</span>
              </div>
            </div>

            <div className="space-y-2 text-xs font-sans text-slate-300">
              <p className="flex items-start gap-2">
                <span className="text-amber-400 font-bold shrink-0">⚠️</span>
                <span>
                  <strong>Graceful Restart Notice:</strong> Target container services will be briefly restarted. Active completions or HTTP proxy requests will be momentarily serialized.
                </span>
              </p>
              <p className="flex items-start gap-2">
                <span className="text-emerald-400 font-bold shrink-0">🛡️</span>
                <span>
                  <strong>Pre-Flight Snapshot:</strong> An automated backup of environment parameters and configurations will be stored before changes occur.
                </span>
              </p>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setConfirmTarget(null)}
                className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-mono text-slate-300 hover:text-white transition-colors"
              >
                Cancel (Esc)
              </button>
              <button
                onClick={handleConfirmUpdate}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 font-mono text-xs font-bold transition-all shadow-[0_0_15px_rgba(245,158,11,0.25)] flex items-center gap-1.5"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Confirm &amp; Apply Update</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
