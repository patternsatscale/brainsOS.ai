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
  FileText,
  Globe,
  Lock,
  UserCheck,
  Mail,
  Download,
  Wand2,
  CheckCircle2,
  KeyRound
} from 'lucide-react';

interface GitStatus {
  is_git: boolean;
  branch: string;
  available_branches?: string[];
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
  platform_name?: string;
  platform_detail?: string;
  firstboot_wizard_completed?: boolean;
  url?: string;
  local_domain?: string;
  admin_username?: string;
  admin_email?: string;
  tls_mode?: string;
  acme_email?: string;
  hostname?: string;
  preserve_hostname?: boolean;
  public_ipv4?: string;
  local_ipv4?: string;
  instance_id?: string;
  git: GitStatus;
  services: Record<string, ServiceStatus>;
  disk?: DiskStatus;
  overall_update_available: boolean;
}

interface DnsCheckResult {
  domain: string;
  valid_syntax: boolean;
  resolved_ip: string | null;
  public_ipv4: string;
  matches_appliance: boolean;
  message: string;
}

const DEFAULT_STATUS: SystemStatus = {
  platform: "brainsOS",
  platform_name: "AWS EC2 Appliance (AMI)",
  platform_detail: "AWS ARM64 Graviton • EC2",
  firstboot_wizard_completed: true,
  url: "ec2-32-192-215-107.compute-1.amazonaws.com",
  local_domain: "jsm.cloud.aws.brainsos.ai",
  admin_username: "jsm",
  admin_email: "jsm@jsm.cloud.aws.brainsos.ai",
  tls_mode: "internal",
  acme_email: "",
  hostname: "jsm.cloud.aws.brainsos.ai",
  preserve_hostname: true,
  public_ipv4: "32.192.215.107",
  local_ipv4: "172.31.24.180",
  instance_id: "i-0d32ae443d40e32d4",
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
    available_branches: ["main", "task/320-appliance-rehearsal"],
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
  branch?: string;
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

export interface SystemManagerProps {
  standaloneWizard?: boolean;
}

export const SystemManager: React.FC<SystemManagerProps> = ({ standaloneWizard = false }) => {
  const [status, setStatus] = useState<SystemStatus | null>(import.meta.env.DEV ? DEFAULT_STATUS : null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState<boolean>(false);
  const [lastChecked, setLastChecked] = useState<string>('Just now');
  const [confirmTarget, setConfirmTarget] = useState<UpdateTarget | null>(null);
  const [selectedBranch, setSelectedBranch] = useState<string>('');

  // First-Boot Setup Wizard & Appliance Identity State (#332 / #333)
  const [wizardOpen, setWizardOpen] = useState<boolean>(false);
  const [wizardStep, setWizardStep] = useState<1 | 2 | 3>(1);
  const [wizardAutoOpened, setWizardAutoOpened] = useState<boolean>(false);
  const [setupBootstrapToken, setSetupBootstrapToken] = useState<string>('');
  const [setupLocalDomain, setSetupLocalDomain] = useState<string>('local.brainsos.ai');
  const [setupAdminUsername, setSetupAdminUsername] = useState<string>('admin');
  const [setupAdminPassword, setSetupAdminPassword] = useState<string>('');
  const [setupAdminPasswordConfirm, setSetupAdminPasswordConfirm] = useState<string>('');
  const [setupUrl, setSetupUrl] = useState<string>('local.brainsos.ai');
  const [setupTlsMode, setSetupTlsMode] = useState<'internal' | 'acme' | 'route53'>('internal');
  const [setupAcmeEmail, setSetupAcmeEmail] = useState<string>('');
  const [setupError, setSetupError] = useState<string | null>(null);
  const [dnsChecking, setDnsChecking] = useState<boolean>(false);
  const [dnsCheckResult, setDnsCheckResult] = useState<DnsCheckResult | null>(null);
  const [newConfiguredUrl, setNewConfiguredUrl] = useState<string | null>(null);

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
        if (data?.git?.branch) {
          setSelectedBranch((prev) => prev || data.git.branch);
        }
        if (data?.local_domain) {
          setSetupLocalDomain((prev) => (prev === 'local.brainsos.ai' ? data.local_domain : prev));
        }
        if (data?.admin_username) {
          setSetupAdminUsername((prev) => (prev === 'admin' ? data.admin_username : prev));
        }
        if (data?.url) {
          setSetupUrl((prev) => (prev === 'local.brainsos.ai' ? data.url : prev));
        }
        if (data?.tls_mode && ['internal', 'acme', 'route53'].includes(data.tls_mode)) {
          setSetupTlsMode(data.tls_mode as 'internal' | 'acme' | 'route53');
        }
        if (data?.acme_email) {
          setSetupAcmeEmail((prev) => prev || data.acme_email);
        }
        if (data?.firstboot_wizard_completed === false && !wizardAutoOpened) {
          setWizardAutoOpened(true);
          setWizardStep(1);
          setWizardOpen(true);
        }
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

  // Fallback polling when an SSE connection drops mid-stream (e.g. during Caddy ingress reload)
  const pollJobUntilComplete = async (
    jobId: string,
    addLog: (text: string, type?: 'log' | 'info' | 'error' | 'success') => void,
    onSuccess?: () => void
  ) => {
    addLog(`🔄 Ingress proxy reloading — reattaching to background job ${jobId}...`, 'info');
    let seenCount = 0;
    for (let attempt = 0; attempt < 90; attempt++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const res = await fetch(`/api/v1/system/jobs/${jobId}`);
        if (!res.ok) continue;
        const job = await res.json();
        const jobLogs: string[] = Array.isArray(job.logs) ? job.logs : [];
        if (seenCount === 0 && jobLogs.length > 0) {
          seenCount = Math.max(0, jobLogs.length - 3);
        }
        while (seenCount < jobLogs.length) {
          addLog(jobLogs[seenCount], 'log');
          seenCount++;
        }
        if (job.status === 'success') {
          addLog(`✅ Background job ${jobId} completed successfully!`, 'success');
          setExecutionStatus('success');
          if (onSuccess) onSuccess();
          fetchStatus();
          return;
        }
        if (job.status === 'failed') {
          addLog(`❌ Background job ${jobId} exited with code ${job.exit_code}.`, 'error');
          setExecutionStatus('failed');
          fetchStatus();
          return;
        }
      } catch {
        // Wait for Caddy ingress to finish restarting
      }
    }
    setExecutionStatus('failed');
    addLog(`⚠️ Timed out waiting for background job ${jobId}.`, 'error');
  };

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
          version: target.targetVersion,
          containers_only: target.containersOnly,
          full: target.full,
          branch: target.branch
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

      const activeJobId = res.headers.get('X-Job-ID') || '';
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let completedCleanly = false;

      try {
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
                  completedCleanly = true;
                  if (payload.exit_code === 0) {
                    addLog(`✅ Update completed successfully! All health invariants satisfied.`, 'success');
                    setExecutionStatus('success');
                  } else {
                    addLog(`❌ Update exited with error code ${payload.exit_code}. Rollback evaluated.`, 'error');
                    setExecutionStatus('failed');
                  }
                } else if (payload.type === 'error') {
                  completedCleanly = true;
                  addLog(`⚠️ Error: ${payload.line}`, 'error');
                  setExecutionStatus('failed');
                }
              } catch {
                addLog(line.slice(6));
              }
            }
          }
        }
      } catch (streamErr: unknown) {
        if (activeJobId && !completedCleanly) {
          await pollJobUntilComplete(activeJobId, addLog);
          return;
        }
        throw streamErr;
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

  const handleOpenWizard = (initialStep: 1 | 2 | 3 = 1) => {
    if (status?.local_domain) setSetupLocalDomain(status.local_domain);
    if (status?.admin_username) setSetupAdminUsername(status.admin_username);
    if (status?.url) setSetupUrl(status.url);
    if (status?.tls_mode && ['internal', 'acme', 'route53'].includes(status.tls_mode)) {
      setSetupTlsMode(status.tls_mode as 'internal' | 'acme' | 'route53');
    }
    if (status?.acme_email) setSetupAcmeEmail(status.acme_email);
    setSetupAdminPassword('');
    setSetupAdminPasswordConfirm('');
    setSetupError(null);
    setDnsCheckResult(null);
    setWizardStep(initialStep);
    setWizardOpen(true);
  };

  const handleVerifyDns = async () => {
    if (!setupUrl.trim()) return;
    setDnsChecking(true);
    setDnsCheckResult(null);
    try {
      const res = await fetch('/api/v1/system/dns-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: setupUrl.trim() }),
      });
      if (res.ok) {
        const data: DnsCheckResult = await res.json();
        setDnsCheckResult(data);
      } else {
        setDnsCheckResult({
          domain: setupUrl.trim(),
          valid_syntax: false,
          resolved_ip: null,
          public_ipv4: status?.public_ipv4 || '',
          matches_appliance: false,
          message: `DNS check failed (HTTP ${res.status})`,
        });
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setDnsCheckResult({
        domain: setupUrl.trim(),
        valid_syntax: false,
        resolved_ip: null,
        public_ipv4: status?.public_ipv4 || '',
        matches_appliance: false,
        message: `DNS check error: ${errMsg}`,
      });
    } finally {
      setDnsChecking(false);
    }
  };

  const handleDismissWizard = async () => {
    setSetupError(null);
    if (status?.firstboot_wizard_completed === false && !setupBootstrapToken.trim()) {
      setSetupError('Please enter your EC2 Instance ID (i-...) in Step 1 to verify ownership before skipping first-boot setup.');
      setWizardStep(1);
      return;
    }
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    try {
      const res = await fetch('/api/v1/system/setup', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          dismiss_only: true,
          bootstrap_token: setupBootstrapToken.trim() || undefined,
        }),
      });
      if (!res.ok) {
        let errorDetail = res.statusText;
        try {
          const errData = await res.json();
          if (errData && errData.detail) errorDetail = errData.detail;
        } catch {
          // fallback
        }
        setSetupError(errorDetail);
        if (res.status === 403) setWizardStep(1);
        return;
      }
    } catch {
      // Ignore dismiss error in preview
    }
    setWizardOpen(false);
    if (standaloneWizard || status?.firstboot_wizard_completed === false) {
      window.location.href = '/';
      return;
    }
    fetchStatus();
  };

  const handleApplySetup = async () => {
    setSetupError(null);
    const cleanLocal = setupLocalDomain.trim().replace(/^https?:\/\//i, '').replace(/\/.*$/, '');
    const cleanUser = setupAdminUsername.trim();
    const cleanUrl = setupUrl.trim().replace(/^https?:\/\//i, '').replace(/\/.*$/, '');

    if (status?.firstboot_wizard_completed === false && !setupBootstrapToken.trim()) {
      setSetupError('Please enter the EC2 Instance ID (i-...) of this appliance to authorize first-boot setup.');
      setWizardStep(1);
      return;
    }
    if (!cleanUser || !/^[a-zA-Z0-9._-]{2,64}$/.test(cleanUser)) {
      setSetupError('Administrator username must be 2–64 alphanumeric characters.');
      setWizardStep(1);
      return;
    }
    if (setupAdminPassword || status?.firstboot_wizard_completed === false) {
      if (setupAdminPassword && setupAdminPassword.length < 8) {
        setSetupError('Administrator password must be at least 8 characters long.');
        setWizardStep(1);
        return;
      }
      if (setupAdminPassword !== setupAdminPasswordConfirm) {
        setSetupError('Password and confirmation do not match.');
        setWizardStep(1);
        return;
      }
    }
    if (!cleanLocal || !/^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(cleanLocal)) {
      setSetupError('Please enter a valid fully-qualified local domain (e.g. jsm.cloud.aws.brainsos.ai).');
      setWizardStep(2);
      return;
    }
    if (!cleanUrl) {
      setSetupError('Please enter a valid external web URL or hostname.');
      setWizardStep(3);
      return;
    }
    if ((setupTlsMode === 'acme' || setupTlsMode === 'route53') && (!setupAcmeEmail.trim() || !setupAcmeEmail.includes('@'))) {
      setSetupError('A valid ACME contact email address is required for Let\'s Encrypt / Route 53 TLS.');
      setWizardStep(3);
      return;
    }

    const previousUrl = status?.url || '';
    const wasFirstBoot = status?.firstboot_wizard_completed === false;
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

    let res: Response;
    try {
      res = await fetch('/api/v1/system/setup', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          bootstrap_token: setupBootstrapToken.trim() || undefined,
          local_domain: cleanLocal,
          admin_username: cleanUser,
          admin_password: setupAdminPassword || undefined,
          url: cleanUrl,
          tls_mode: setupTlsMode,
          acme_email: setupAcmeEmail.trim() || undefined,
          mark_wizard_completed: true,
          force: true,
        }),
      });
    } catch (netErr: unknown) {
      const errMsg = netErr instanceof Error ? netErr.message : String(netErr);
      setSetupError(`Failed connecting to System API: ${errMsg}`);
      return;
    }

    if (!res.ok) {
      let errorDetail = res.statusText;
      try {
        const errData = await res.json();
        if (errData && errData.detail) errorDetail = errData.detail;
      } catch {
        // fallback
      }
      setSetupError(errorDetail);
      if (res.status === 403) {
        setWizardStep(1);
      }
      return;
    }

    setWizardOpen(false);
    setTerminalOpen(true);
    setExecutionStatus('running');

    const startTimestamp = new Date().toLocaleTimeString();
    setLogs([
      {
        id: 1,
        timestamp: startTimestamp,
        text: `🪄 Applying Appliance Identity & Custom Domain Configuration...`,
        type: 'info',
      },
      {
        id: 2,
        timestamp: startTimestamp,
        text: `🌐 Local Domain: ${cleanLocal} | Admin: ${cleanUser}@${cleanLocal} | Web URL: https://${cleanUrl}/ (${setupTlsMode})`,
        type: 'info',
      },
    ]);

    let logCounter = 3;
    const addLog = (text: string, type: 'log' | 'info' | 'error' | 'success' = 'log') => {
      const ts = new Date().toLocaleTimeString();
      setLogs((prev) => [...prev, { id: logCounter++, timestamp: ts, text, type }]);
    };

    try {
      if (!res.body) throw new Error('Response body is null');

      const activeJobId = res.headers.get('X-Job-ID') || '';
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let completedCleanly = false;

      try {
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
                  addLog(`⚙️ Executing: ${payload.cmd}`, 'info');
                } else if (payload.type === 'complete') {
                  completedCleanly = true;
                  if (payload.exit_code === 0) {
                    addLog(`✅ Appliance identity, hostname, mailboxes, and TLS configured!`, 'success');
                    setExecutionStatus('success');
                    if (wasFirstBoot || (previousUrl && cleanUrl.toLowerCase() !== previousUrl.toLowerCase())) {
                      setNewConfiguredUrl(`https://${cleanUrl}/`);
                    }
                  } else {
                    addLog(`❌ Setup exited with code ${payload.exit_code}.`, 'error');
                    setExecutionStatus('failed');
                  }
                } else if (payload.type === 'error') {
                  completedCleanly = true;
                  addLog(`⚠️ Error: ${payload.line}`, 'error');
                  setExecutionStatus('failed');
                }
              } catch {
                addLog(line.slice(6));
              }
            }
          }
        }
      } catch (streamErr: unknown) {
        if (activeJobId && !completedCleanly) {
          await pollJobUntilComplete(activeJobId, addLog, () => {
            if (wasFirstBoot || (previousUrl && cleanUrl.toLowerCase() !== previousUrl.toLowerCase())) {
              setNewConfiguredUrl(`https://${cleanUrl}/`);
            }
          });
          return;
        }
        throw streamErr;
      }

      fetchStatus();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setExecutionStatus('failed');
      addLog(`❌ Setup failed: ${errMsg}`, 'error');
    }
  };

  const isStandaloneWizard = Boolean(standaloneWizard || status?.firstboot_wizard_completed === false);

  const renderWizardCardContent = (standalone: boolean) => (
    <div className="w-full max-w-2xl bg-[#0D111A] border border-white/15 rounded-2xl p-6 sm:p-8 shadow-2xl space-y-5 animate-in zoom-in-95">
      {/* Wizard Header */}
      <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-gradient-to-br from-purple-500/20 to-[#00f2fe]/20 border border-purple-500/40 text-[#00f2fe]">
            <Wand2 className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-headline font-bold text-lg text-white">
                brainsOS Appliance Identity &amp; First-Boot Setup Wizard
              </h3>
              <span className="px-2 py-0.5 rounded bg-purple-500/20 border border-purple-500/40 font-mono text-[10px] text-purple-300 font-semibold">
                STEP {wizardStep} OF 3
              </span>
            </div>
            <p className="font-mono text-xs text-slate-400 mt-0.5">
              Configure coherent unit hostname &amp; mail domain, administrator credentials, and HTTPS ingress
            </p>
          </div>
        </div>
        {!standalone && (
          <button
            onClick={() => setWizardOpen(false)}
            className="w-8 h-8 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white flex items-center justify-center transition-colors shrink-0"
            title="Close Wizard"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Step Progress Pills */}
      <div className="grid grid-cols-3 gap-2 font-mono text-xs">
        <button
          type="button"
          onClick={() => setWizardStep(1)}
          className={`p-2.5 rounded-xl border text-left transition-all ${
            wizardStep === 1
              ? 'bg-purple-500/20 border-purple-400 text-white'
              : 'bg-white/[0.03] border-white/10 text-slate-400 hover:text-white'
          }`}
        >
          <div className="text-[10px] text-purple-300 font-bold">1. ADMIN &amp; VERIFY</div>
          <div className="truncate font-semibold mt-0.5">Instance ID &amp; Credentials</div>
        </button>
        <button
          type="button"
          onClick={() => setWizardStep(2)}
          className={`p-2.5 rounded-xl border text-left transition-all ${
            wizardStep === 2
              ? 'bg-purple-500/20 border-purple-400 text-white'
              : 'bg-white/[0.03] border-white/10 text-slate-400 hover:text-white'
          }`}
        >
          <div className="text-[10px] text-purple-300 font-bold">2. UNIT IDENTITY</div>
          <div className="truncate font-semibold mt-0.5">Local Domain &amp; Hostname</div>
        </button>
        <button
          type="button"
          onClick={() => setWizardStep(3)}
          className={`p-2.5 rounded-xl border text-left transition-all ${
            wizardStep === 3
              ? 'bg-purple-500/20 border-purple-400 text-white'
              : 'bg-white/[0.03] border-white/10 text-slate-400 hover:text-white'
          }`}
        >
          <div className="text-[10px] text-purple-300 font-bold">3. WEB ACCESS &amp; TLS</div>
          <div className="truncate font-semibold mt-0.5">Browser URL &amp; Certificates</div>
        </button>
      </div>

      {setupError && (
        <div className="p-3 rounded-xl bg-red-500/15 border border-red-500/40 text-red-200 font-mono text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
          <span>{setupError}</span>
        </div>
      )}

      {/* STEP 1: Primary Administrator Account & Pre-Sign-In Instance ID Verification */}
      {wizardStep === 1 && (
        <div className="space-y-4 font-mono text-xs">
          {(standalone || status?.firstboot_wizard_completed === false) && (
            <div className="p-3.5 rounded-xl bg-purple-500/10 border border-purple-500/40 space-y-2">
              <label className="block text-purple-200 font-semibold flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-[#00f2fe]" />
                <span>EC2 Instance ID Verification Key (Required for Pre-Sign-In Setup)</span>
              </label>
              <p className="text-[11px] text-slate-300 font-sans">
                Because you are configuring this appliance before your first sign-in, enter the AWS EC2 Instance ID (<code className="font-mono text-[#00f2fe]">i-...</code>) from your AWS Console to verify ownership.
              </p>
              <input
                type="password"
                value={setupBootstrapToken}
                onChange={(e) => setSetupBootstrapToken(e.target.value)}
                placeholder="e.g. i-0123456789abcdef0"
                className="w-full px-3.5 py-2.5 rounded-xl bg-[#07090E] border border-purple-500/40 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label className="block text-slate-200 font-semibold">
              Primary Administrator Username (<code className="text-purple-300">BRAINSOS_ADMIN_USERNAME</code>)
            </label>
            <p className="text-[11px] text-slate-400 font-sans">
              Creates or updates your primary Authentik superuser and provisions <code className="font-mono text-emerald-300">{setupAdminUsername.trim() || 'admin'}@{setupLocalDomain.trim() || 'local.brainsos.ai'}</code> with full Dovecot/SOGo shared oversight over all agent mailboxes.
            </p>
            <input
              type="text"
              value={setupAdminUsername}
              onChange={(e) => setSetupAdminUsername(e.target.value)}
              placeholder="admin (or e.g. jsm)"
              className="w-full px-3.5 py-2.5 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="block text-slate-200 font-semibold flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5 text-amber-400" />
                <span>New Administrator Password</span>
              </label>
              <input
                type="password"
                value={setupAdminPassword}
                onChange={(e) => setSetupAdminPassword(e.target.value)}
                placeholder={status?.firstboot_wizard_completed && !standalone ? 'Leave blank to keep current password' : 'Enter new password (min 8 chars)'}
                className="w-full px-3.5 py-2.5 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
              />
            </div>
            <div className="space-y-1.5">
              <label className="block text-slate-200 font-semibold">
                Confirm Administrator Password
              </label>
              <input
                type="password"
                value={setupAdminPasswordConfirm}
                onChange={(e) => setSetupAdminPasswordConfirm(e.target.value)}
                placeholder="Re-enter password"
                className="w-full px-3.5 py-2.5 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
              />
            </div>
          </div>

          <div className="p-3.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-[11px] text-slate-300 space-y-1">
            <div className="text-amber-300 font-semibold">Unified Credential Rotation (Zero Data Loss)</div>
            <p className="font-sans text-slate-400">
              Setting a password here atomically rotates the initial EC2 <code className="font-mono text-slate-200">instance-id</code> bootstrap password across Authentik SSO (<code className="font-mono text-slate-200">{setupAdminUsername.trim() || 'admin'}</code> &amp; <code className="font-mono text-slate-200">admin</code>), SOGo Webmail, Dovecot IMAP/SMTP, Langfuse, and Operator IDE.
            </p>
          </div>
        </div>
      )}

      {/* STEP 2: Unit Identity & Local Domain */}
      {wizardStep === 2 && (
        <div className="space-y-4 font-mono text-xs">
          <div className="space-y-1.5">
            <label className="block text-slate-200 font-semibold">
              Appliance Local Domain &amp; Unit FQDN (<code className="text-purple-300">BRAINSOS_LOCAL_DOMAIN</code>)
            </label>
            <p className="text-[11px] text-slate-400 font-sans">
              Gives this brainsOS unit a coherent identity across OS hostname (<code className="font-mono">hostname -f</code>), Postfix/Dovecot/SOGo mailboxes, and Langfuse traces—even when accessed via a raw AWS EC2 URL.
            </p>
            <input
              type="text"
              value={setupLocalDomain}
              onChange={(e) => setSetupLocalDomain(e.target.value)}
              placeholder="e.g. jsm.cloud.aws.brainsos.ai or dgx.local.brainsos.ai"
              className="w-full px-3.5 py-2.5 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
            />
          </div>

          {/* Live Identity Preview */}
          {(() => {
            const previewDom = (setupLocalDomain.trim() || 'local.brainsos.ai').replace(/^https?:\/\//i, '').replace(/\/.*$/, '');
            const shortHost = previewDom.split('.')[0] || 'brainsos';
            const previewUser = setupAdminUsername.trim() || 'admin';
            const mailboxes = [
              `${previewUser}@${previewDom}`,
              `terrastella@${previewDom}`,
              `bawtford@${previewDom}`,
              `marvin@${previewDom}`,
              `ping@${previewDom}`,
              `claude@${previewDom}`,
              `gpt@${previewDom}`,
            ];
            return (
              <div className="p-4 rounded-xl bg-[#07090E]/90 border border-white/10 space-y-3">
                <div className="text-[11px] uppercase tracking-wider text-purple-300 font-semibold">
                  Live Coherent Identity Preview
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                  <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/5">
                    <span className="text-slate-500 block">OS Hostname (/etc/hosts &amp; cloud-init):</span>
                    <span className="text-white font-semibold">{previewDom}</span>
                    <span className="text-emerald-400 block text-[10px] mt-0.5">short: {shortHost} • preserve_hostname: true</span>
                  </div>
                  <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/5">
                    <span className="text-slate-500 block">Langfuse Trace Telemetry Tag:</span>
                    <span className="text-[#00f2fe] font-semibold">local_domain = {previewDom}</span>
                    <span className="text-slate-400 block text-[10px] mt-0.5">OTel resource host.name: {previewDom}</span>
                  </div>
                </div>
                <div>
                  <span className="text-slate-400 text-[11px] block mb-1.5">Provisioned Postfix / Dovecot / SOGo Mailboxes:</span>
                  <div className="flex flex-wrap gap-1.5">
                    {mailboxes.map((mb, i) => (
                      <span
                        key={mb}
                        className={`px-2 py-0.5 rounded-md text-[10px] border ${
                          i === 0
                            ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300 font-semibold'
                            : 'bg-white/5 border-white/10 text-slate-300'
                        }`}
                      >
                        {mb}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* STEP 3: External Web Access & TLS Mode */}
      {wizardStep === 3 && (
        <div className="space-y-4 font-mono text-xs">
          <div className="space-y-1.5">
            <label className="block text-slate-200 font-semibold">
              External Web Access URL / Hostname (<code className="text-[#00f2fe]">BRAINSOS_URL</code>)
            </label>
            <p className="text-[11px] text-slate-400 font-sans">
              The browser-facing hostname or URL used to reach the Portal, Authentik SSO, LiteLLM, and Langfuse (for example, your AWS EC2 public DNS name or a custom domain).
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={setupUrl}
                onChange={(e) => {
                  setSetupUrl(e.target.value);
                  setDnsCheckResult(null);
                }}
                placeholder="e.g. ec2-32-192-215-107.compute-1.amazonaws.com or portal.example.com"
                className="flex-1 px-3.5 py-2.5 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
              />
              <button
                type="button"
                onClick={handleVerifyDns}
                disabled={dnsChecking || !setupUrl.trim()}
                className="px-3.5 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/15 text-xs font-mono text-[#00f2fe] transition-all shrink-0 disabled:opacity-50"
              >
                {dnsChecking ? 'Checking...' : 'Verify DNS'}
              </button>
            </div>
          </div>

          {dnsCheckResult && (
            <div
              className={`p-3 rounded-xl border text-[11px] ${
                dnsCheckResult.matches_appliance
                  ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-200'
                  : 'bg-amber-500/15 border-amber-500/40 text-amber-200'
              }`}
            >
              <div>{dnsCheckResult.message}</div>
            </div>
          )}

          <div className="space-y-2">
            <label className="block text-slate-200 font-semibold">
              TLS Certificate Mode
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              <button
                type="button"
                onClick={() => setSetupTlsMode('internal')}
                className={`p-3 rounded-xl border text-left transition-all space-y-1 ${
                  setupTlsMode === 'internal'
                    ? 'bg-[#00f2fe]/15 border-[#00f2fe] text-white'
                    : 'bg-[#07090E] border-white/10 text-slate-400 hover:text-white'
                }`}
              >
                <div className="font-bold text-xs flex items-center gap-1.5">
                  <Lock className="w-3.5 h-3.5 text-[#00f2fe]" />
                  <span>Internal CA</span>
                </div>
                <p className="text-[10px] font-sans text-slate-400">
                  Self-signed Caddy CA. Best for raw EC2 <code className="font-mono">.amazonaws.com</code> URLs, VPN, or LAN.
                </p>
              </button>

              <button
                type="button"
                onClick={() => setSetupTlsMode('acme')}
                className={`p-3 rounded-xl border text-left transition-all space-y-1 ${
                  setupTlsMode === 'acme'
                    ? 'bg-emerald-500/15 border-emerald-400 text-white'
                    : 'bg-[#07090E] border-white/10 text-slate-400 hover:text-white'
                }`}
              >
                <div className="font-bold text-xs flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Public ACME</span>
                </div>
                <p className="text-[10px] font-sans text-slate-400">
                  Automatic Let&apos;s Encrypt / ZeroSSL HTTP-01 cert (requires DNS A record → {status?.public_ipv4 || 'appliance IP'}).
                </p>
              </button>

              <button
                type="button"
                onClick={() => setSetupTlsMode('route53')}
                className={`p-3 rounded-xl border text-left transition-all space-y-1 ${
                  setupTlsMode === 'route53'
                    ? 'bg-purple-500/15 border-purple-400 text-white'
                    : 'bg-[#07090E] border-white/10 text-slate-400 hover:text-white'
                }`}
              >
                <div className="font-bold text-xs flex items-center gap-1.5">
                  <Globe className="w-3.5 h-3.5 text-purple-400" />
                  <span>Route 53 DNS-01</span>
                </div>
                <p className="text-[10px] font-sans text-slate-400">
                  Automatic Let&apos;s Encrypt DNS-01 cert via AWS Route 53 IAM role.
                </p>
              </button>
            </div>
          </div>

          {(setupTlsMode === 'acme' || setupTlsMode === 'route53') && (
            <div className="space-y-1.5">
              <label className="block text-slate-200 font-semibold">
                ACME Contact Email (<code className="text-emerald-300">ACME_EMAIL</code>)
              </label>
              <input
                type="email"
                value={setupAcmeEmail}
                onChange={(e) => setSetupAcmeEmail(e.target.value)}
                placeholder={`e.g. ${setupAdminUsername.trim() || 'admin'}@${setupLocalDomain.trim() || 'brainsos.ai'}`}
                className="w-full px-3.5 py-2.5 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
              />
            </div>
          )}
        </div>
      )}

      {/* Wizard Footer Navigation */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-white/10">
        <div>
          {(standalone || status?.firstboot_wizard_completed === false) && (
            <button
              type="button"
              onClick={handleDismissWizard}
              className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-[11px] font-mono text-slate-400 hover:text-white transition-colors"
            >
              Skip &amp; Keep Defaults
            </button>
          )}
        </div>

        <div className="flex items-center gap-2.5">
          {wizardStep > 1 && (
            <button
              type="button"
              onClick={() => setWizardStep((prev) => (prev === 3 ? 2 : 1))}
              className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-mono text-slate-300 hover:text-white transition-colors"
            >
              ← Back
            </button>
          )}

          {wizardStep < 3 ? (
            <button
              type="button"
              onClick={() => setWizardStep((prev) => (prev === 1 ? 2 : 3))}
              className="px-5 py-2 rounded-xl bg-purple-500/30 hover:bg-purple-500/40 border border-purple-400/50 text-white font-mono text-xs font-bold transition-all"
            >
              Next Step →
            </button>
          ) : (
            <button
              type="button"
              onClick={handleApplySetup}
              className="px-5 py-2 rounded-xl bg-gradient-to-r from-purple-500 to-[#00f2fe] hover:opacity-95 text-slate-950 font-mono text-xs font-bold transition-all shadow-[0_0_18px_rgba(0,242,254,0.3)] flex items-center gap-1.5"
            >
              <Check className="w-4 h-4" />
              <span>Apply Identity &amp; Complete Setup</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );

  if (isStandaloneWizard) {
    return (
      <div className="min-h-screen w-full bg-[#07090E] text-slate-200 flex flex-col items-center justify-center p-4 sm:p-8 font-sans antialiased selection:bg-[#00f2fe] selection:text-black">
        {/* Standalone Top Bar */}
        <div className="w-full max-w-2xl flex items-center justify-between mb-4 px-1">
          <div className="flex items-center gap-2.5">
            <div className="w-2.5 h-2.5 rounded-full bg-[#00f2fe] shadow-[0_0_10px_#00f2fe]" />
            <span className="font-mono text-xs uppercase tracking-widest text-slate-300 font-bold">
              brainsOS.ai • Appliance First-Boot Onboarding
            </span>
          </div>
          <a
            href="/system/ca.crt"
            download="brainsos-caddy-root-ca.crt"
            className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 hover:text-white text-[11px] font-mono transition-all flex items-center gap-1.5"
            title="Download Caddy Root CA certificate to trust self-signed HTTPS in your browser/OS"
          >
            <Download className="w-3.5 h-3.5 text-[#00f2fe]" />
            <span>Download Root CA</span>
          </a>
        </div>

        {executionStatus === 'idle' ? (
          renderWizardCardContent(true)
        ) : (
          <div className="w-full max-w-2xl bg-[#0D111A] border border-white/15 rounded-2xl p-6 sm:p-8 shadow-2xl space-y-5 animate-in fade-in">
            <div className="flex items-center justify-between gap-4 border-b border-white/10 pb-4">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-[#00f2fe]/10 border border-[#00f2fe]/30 text-[#00f2fe]">
                  {executionStatus === 'running' ? (
                    <RefreshCw className="w-6 h-6 animate-spin" />
                  ) : executionStatus === 'success' ? (
                    <CheckCircle2 className="w-6 h-6 text-emerald-400" />
                  ) : (
                    <AlertTriangle className="w-6 h-6 text-red-400" />
                  )}
                </div>
                <div>
                  <h3 className="font-headline font-bold text-lg text-white">
                    {executionStatus === 'running'
                      ? 'Applying Appliance Identity & Provisioning Subsystems...'
                      : executionStatus === 'success'
                      ? 'Appliance Setup Complete — Ready for Sign-In'
                      : 'Appliance Setup Encountered an Error'}
                  </h3>
                  <p className="font-mono text-xs text-slate-400 mt-0.5">
                    {executionStatus === 'running'
                      ? 'Configuring OS hostname, Postfix/Dovecot/SOGo mailboxes, Authentik SSO, Langfuse, and Caddy TLS'
                      : executionStatus === 'success'
                      ? 'All identity, mail, observability, and ingress planes are synchronized.'
                      : 'Review the execution log below and return to the wizard to adjust settings.'}
                  </p>
                </div>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-[#05070B] border border-white/10 font-mono text-[11.5px] leading-5 text-slate-300 max-h-80 min-h-48 overflow-y-auto space-y-1">
              {logs.map((log) => (
                <div key={log.id} className="flex items-start gap-2.5">
                  <span className="text-slate-600 select-none text-[10px] shrink-0 font-mono">
                    [{log.timestamp}]
                  </span>
                  <div className="break-all font-mono">
                    {renderAnsiLine(log.text)}
                  </div>
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>

            {executionStatus === 'success' && (
              <div className="p-4 rounded-xl bg-emerald-500/15 border border-emerald-500/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="text-xs font-mono text-emerald-200">
                  Sign in with <strong className="text-white">{setupAdminUsername.trim() || 'admin'}</strong> and your configured password.
                </div>
                <a
                  href={newConfiguredUrl || '/'}
                  className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-400 to-[#00f2fe] text-slate-950 font-mono text-xs font-bold transition-all flex items-center justify-center gap-2 shrink-0 shadow-[0_0_18px_rgba(16,185,129,0.35)]"
                >
                  <span>Proceed to Sign In</span>
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>
            )}

            {executionStatus === 'failed' && (
              <div className="flex items-center justify-end pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setExecutionStatus('idle');
                    setWizardOpen(true);
                  }}
                  className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-mono text-white transition-colors"
                >
                  ← Return to Setup Wizard
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

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
            onClick={() => handleOpenWizard(1)}
            className="px-3.5 py-1.5 rounded-xl bg-purple-500/15 hover:bg-purple-500/25 border border-purple-500/40 text-xs font-mono text-purple-300 hover:text-white transition-all flex items-center gap-2"
            title="Configure Appliance Identity, Local Domain, Admin Credentials & TLS"
          >
            <Wand2 className="w-3.5 h-3.5 text-purple-400" />
            <span>Identity &amp; Domain Setup</span>
          </button>

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
              full: true,
              branch: selectedBranch || status?.git?.branch || 'main'
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
        {status?.overall_update_available && (() => {
          const pendingServices = Object.values(status.services || {}).filter((s) => s.update_available);
          const pendingNames = pendingServices.map((s) =>
            s.name.replace(' Control Plane Gateway', ' Gateway').replace(' Session Observability', ' Observability')
          );
          const gitPending = Boolean(status.git?.update_available);
          let bannerDesc = '';
          if (pendingServices.length > 0 && gitPending) {
            bannerDesc = `${pendingNames.join(' and ')} (${pendingServices.map(s => `${s.current_version} → ${s.latest_version}`).join(', ')}) and ${status.git.commits_behind} Git commit(s) are ready to install.`;
          } else if (pendingServices.length === 1) {
            const svc = pendingServices[0];
            bannerDesc = `${pendingNames[0]} has a newer upstream container release available (${svc.current_version} → ${svc.latest_version}).`;
          } else if (pendingServices.length > 1) {
            bannerDesc = `${pendingNames.join(' and ')} have newer upstream container releases available (${pendingServices.map(s => `${s.current_version} → ${s.latest_version}`).join(', ')}).`;
          } else if (gitPending) {
            bannerDesc = `brainsOS.ai Platform Core is ${status.git.commits_behind} commit(s) behind origin/${status.git.branch || 'main'}.`;
          }
          return (
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
                    {bannerDesc}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {pendingServices.length > 0 ? (
                  <button
                    onClick={() => setConfirmTarget({
                      id: 'containers',
                      name: `Upstream Containers (${pendingNames.join(' & ')})`,
                      containersOnly: true
                    })}
                    className="px-3.5 py-1.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
                  >
                    <ArrowUpCircle className="w-3.5 h-3.5" />
                    <span>Update Containers Only</span>
                  </button>
                ) : (
                  <button
                    onClick={() => setConfirmTarget({
                      id: 'git',
                      name: 'brainsOS.ai Platform Core (Git Pull)',
                      full: true,
                      branch: selectedBranch || status.git.branch || 'main'
                    })}
                    className="px-3.5 py-1.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
                  >
                    <ArrowUpCircle className="w-3.5 h-3.5" />
                    <span>Pull Latest Source</span>
                  </button>
                )}
              </div>
            </div>
          );
        })()}

        {/* 3. System Hardware & Telemetry Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
          <div className="p-4 rounded-2xl bg-[#141a26]/70 border border-white/5 space-y-1.5">
            <div className="flex items-center justify-between text-slate-400">
              <span className="font-mono text-[10px] uppercase tracking-wider font-semibold">Appliance Platform</span>
              <Server className="w-4 h-4 text-[#00f2fe]" />
            </div>
            <div className="font-headline font-bold text-base text-white">
              {status?.platform_name || (status?.platform && status.platform !== 'brainsOS' ? status.platform : 'AWS EC2 Appliance (AMI)')}
            </div>
            <div className="font-mono text-[11px] text-slate-400 flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>{status?.platform_detail || 'AWS ARM64 Graviton • EC2'}</span>
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

        {/* 3A. First-Boot Setup Prompt / New URL Redirect Banner (#333) */}
        {status?.firstboot_wizard_completed === false && (
          <div className="p-4 rounded-2xl bg-gradient-to-r from-purple-500/15 via-[#00f2fe]/10 to-transparent border border-purple-500/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4 animate-in fade-in">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-purple-500/20 text-purple-300 border border-purple-500/30">
                <Wand2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-headline font-semibold text-sm text-white">
                  Welcome to brainsOS — Complete First-Boot Appliance Setup
                </h3>
                <p className="font-mono text-xs text-slate-300 mt-0.5">
                  Configure your unit local domain (<code className="text-[#00f2fe]">BRAINSOS_LOCAL_DOMAIN</code>), rotate the initial <code className="text-amber-300">instance-id</code> bootstrap password, and choose your TLS mode.
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => handleOpenWizard(1)}
                className="px-4 py-1.5 rounded-xl bg-gradient-to-r from-purple-500 to-[#00f2fe] text-slate-950 font-mono text-xs font-bold transition-all flex items-center gap-1.5 shadow-[0_0_15px_rgba(168,85,247,0.3)]"
              >
                <Wand2 className="w-3.5 h-3.5" />
                <span>Launch Setup Wizard</span>
              </button>
            </div>
          </div>
        )}

        {newConfiguredUrl && (
          <div className="p-4 rounded-2xl bg-emerald-500/15 border border-emerald-500/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4 animate-in fade-in">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                <CheckCircle2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-headline font-semibold text-sm text-emerald-300">
                  Appliance Identity &amp; SSO Ready — Proceed to Sign In
                </h3>
                <p className="font-mono text-xs text-slate-300 mt-0.5">
                  Caddy and Authentik SSO are now serving on <a href={newConfiguredUrl} className="text-[#00f2fe] underline">{newConfiguredUrl}</a> with your configured administrator account.
                </p>
              </div>
            </div>
            <a
              href={newConfiguredUrl}
              className="px-4 py-1.5 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-200 hover:text-white text-xs font-mono font-semibold transition-all flex items-center gap-1.5 shrink-0"
            >
              <span>Proceed to Sign In ({newConfiguredUrl})</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        )}

        {/* 3A-2. Persistent Appliance Identity, Domain & TLS Card (#332 / #333) */}
        <div className="p-5 rounded-2xl bg-[#141a26]/90 border border-white/10 hover:border-purple-500/40 transition-all space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400 shrink-0">
                <Globe className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center gap-2.5 flex-wrap">
                  <h2 className="font-headline font-bold text-white text-base">
                    Appliance Identity, Custom Domain &amp; TLS Ingress
                  </h2>
                  {status?.tls_mode === 'route53' ? (
                    <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-semibold">
                      TLS: ROUTE 53 DNS-01 ACME
                    </span>
                  ) : status?.tls_mode === 'acme' ? (
                    <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-mono text-[10px] font-semibold">
                      TLS: PUBLIC ACME (LET&apos;S ENCRYPT)
                    </span>
                  ) : (
                    <span className="px-2.5 py-0.5 rounded-full bg-cyan-500/20 border border-cyan-500/40 text-[#00f2fe] font-mono text-[10px] font-semibold">
                      TLS: INTERNAL SELF-SIGNED CA
                    </span>
                  )}
                  {status?.preserve_hostname && (
                    <span className="px-2.5 py-0.5 rounded-full bg-purple-500/20 border border-purple-500/40 text-purple-300 font-mono text-[10px] font-semibold">
                      HOSTNAME PERSISTENT
                    </span>
                  )}
                </div>
                <p className="font-mono text-xs text-slate-400 mt-0.5">
                  Decoupled Unit Identity (<code className="text-purple-300">BRAINSOS_LOCAL_DOMAIN</code>) &amp; Browser Access URL (<code className="text-[#00f2fe]">BRAINSOS_URL</code>)
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0 flex-wrap">
              <a
                href="/system/ca.crt"
                download="brainsos-caddy-root-ca.crt"
                className="px-3 py-1.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 border border-white/10 text-slate-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5"
                title="Download Caddy Root CA certificate to trust self-signed HTTPS in your browser/OS"
              >
                <Download className="w-3.5 h-3.5 text-[#00f2fe]" />
                <span>Download Root CA</span>
              </a>

              <button
                onClick={() => handleOpenWizard(1)}
                className="px-3.5 py-1.5 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5 shadow-[0_0_12px_rgba(168,85,247,0.15)]"
              >
                <Wand2 className="w-3.5 h-3.5" />
                <span>Configure Domain &amp; Identity</span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2 border-t border-white/5 font-mono text-xs">
            {/* Column 1: Unit Local Domain & OS Hostname */}
            <div className="p-3.5 rounded-xl bg-[#0B0E14]/60 border border-white/5 space-y-1.5">
              <div className="text-white font-medium flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5 text-purple-400" />
                <span>Unit Local Domain &amp; Mailboxes</span>
              </div>
              <div className="space-y-1 text-[11px] text-slate-400">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">BRAINSOS_LOCAL_DOMAIN:</span>
                  <span className="text-purple-300 font-semibold truncate">{status?.local_domain || 'local.brainsos.ai'}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">OS Hostname (FQDN):</span>
                  <span className="text-slate-200 truncate">{status?.hostname || status?.local_domain || 'local.brainsos.ai'}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">Agent Mail Domain:</span>
                  <span className="text-emerald-400 truncate">@{status?.local_domain || 'local.brainsos.ai'}</span>
                </div>
              </div>
            </div>

            {/* Column 2: External Web Access & Network */}
            <div className="p-3.5 rounded-xl bg-[#0B0E14]/60 border border-white/5 space-y-1.5">
              <div className="text-white font-medium flex items-center gap-1.5">
                <Globe className="w-3.5 h-3.5 text-[#00f2fe]" />
                <span>External Web Access &amp; Network</span>
              </div>
              <div className="space-y-1 text-[11px] text-slate-400">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">BRAINSOS_URL:</span>
                  <span className="text-[#00f2fe] font-semibold truncate" title={status?.url}>
                    {status?.url || 'local.brainsos.ai'}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">Public / Private IPv4:</span>
                  <span className="text-slate-200">
                    {status?.public_ipv4 || 'N/A'} {status?.local_ipv4 ? `/ ${status.local_ipv4}` : ''}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">Instance ID:</span>
                  <span className="text-slate-300">{status?.instance_id || 'Baremetal / Local'}</span>
                </div>
              </div>
            </div>

            {/* Column 3: Primary Administrator & SSO */}
            <div className="p-3.5 rounded-xl bg-[#0B0E14]/60 border border-white/5 space-y-1.5">
              <div className="text-white font-medium flex items-center gap-1.5">
                <UserCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>Primary Administrator &amp; SSO</span>
              </div>
              <div className="space-y-1 text-[11px] text-slate-400">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">Admin Username:</span>
                  <span className="text-white font-semibold">{status?.admin_username || 'admin'}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">Admin Mailbox:</span>
                  <span className="text-emerald-400 truncate">
                    {status?.admin_email || `${status?.admin_username || 'admin'}@${status?.local_domain || 'local.brainsos.ai'}`}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-500">SOGo / Dovecot ACL:</span>
                  <span className="text-slate-300">Full Fleet Oversight</span>
                </div>
              </div>
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
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <h3 className="font-headline font-bold text-white text-base">brainsOS.ai Platform Core</h3>
                    {selectedBranch && selectedBranch !== (status.git.branch || 'main') ? (
                      <span className="px-2.5 py-0.5 rounded-full bg-purple-500/20 border border-purple-500/40 text-purple-300 font-mono text-[10px] font-semibold">
                        BRANCH SWITCH TARGET: {selectedBranch}
                      </span>
                    ) : status.git.commits_behind > 0 || status.git.update_available ? (
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
                  <div className="flex flex-wrap items-center gap-4 mt-2.5 font-mono text-xs text-slate-400">
                    <div className="flex items-center gap-2">
                      <label htmlFor="branch-selector" className="text-slate-500">Branch:</label>
                      <select
                        id="branch-selector"
                        value={selectedBranch || status.git.branch || 'main'}
                        onChange={(e) => setSelectedBranch(e.target.value)}
                        className="px-2.5 py-1 rounded-lg bg-[#0B0E14] border border-purple-500/40 hover:border-purple-400 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-xs transition-colors cursor-pointer"
                        title="Select target remote branch to pull or switch to"
                      >
                        {(status.git.available_branches && status.git.available_branches.length > 0
                          ? status.git.available_branches
                          : [status.git.branch || 'main']
                        ).map((br) => (
                          <option key={br} value={br} className="bg-[#0B0E14] text-white">
                            {br}{br === (status.git.branch || 'main') ? ' (active)' : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <span className="text-slate-500">Local Commit: </span>
                      <span className="text-[#00f2fe] font-medium">{status.git.current_commit.substring(0, 7)}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">Remote Tracking: </span>
                      <span className="text-purple-400 font-medium">
                        origin/{selectedBranch || status.git.branch || 'main'}
                        {(!selectedBranch || selectedBranch === status.git.branch) && status.git.remote_commit && ` (${status.git.remote_commit.substring(0, 7)})`}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex sm:flex-col items-center sm:items-end justify-between sm:justify-center gap-2 shrink-0">
                <a
                  href={`https://github.com/patternsatscale/brainsOS.ai/commits/${selectedBranch || status.git.branch || 'main'}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs font-mono text-slate-400 hover:text-purple-400 flex items-center gap-1 transition-colors"
                >
                  <span>Commit History</span>
                  <ExternalLink className="w-3 h-3" />
                </a>

                <button
                  onClick={() => {
                    const targetBranch = selectedBranch || status.git.branch || 'main';
                    const isSwitch = targetBranch !== (status.git.branch || 'main');
                    setConfirmTarget({
                      id: 'git-source',
                      name: isSwitch
                        ? `Switch Branch & Sync Source -> ${targetBranch}`
                        : `brainsOS.ai Platform Source Code (git pull origin/${targetBranch} & rebuild)`,
                      full: true,
                      branch: targetBranch
                    });
                  }}
                  className="px-3.5 py-1.5 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-300 hover:text-white text-xs font-mono font-medium transition-all flex items-center gap-1.5 shadow-[0_0_10px_rgba(168,85,247,0.15)]"
                >
                  <Play className="w-3 h-3 fill-current" />
                  <span>
                    {selectedBranch && selectedBranch !== (status.git.branch || 'main')
                      ? `Switch & Sync (${selectedBranch})`
                      : 'Pull Latest Source'}
                  </span>
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
            {(status.services.hermes || status.services['runner-hermes']) && (() => {
              const hermesSvc = status.services.hermes || status.services['runner-hermes'];
              return (
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
                    <span className="text-white font-medium">{hermesSvc.current_version}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 block text-[10px] uppercase">Release Line</span>
                    <span className="text-purple-400 font-medium">Native ARM64</span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1">
                  <a
                    href={hermesSvc.changelog_url || 'https://github.com/patternsatscale/brainsOS.ai/releases'}
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
              );
            })()}
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
              {confirmTarget.branch && (
                <div className="flex items-center justify-between pb-2 border-b border-white/5">
                  <span className="text-slate-400">Target Git Branch:</span>
                  <span className="text-purple-400 font-semibold">origin/{confirmTarget.branch}</span>
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

      {/* 7. 3-Step Guided First-Boot Setup & Appliance Identity Wizard Modal (#332 / #333) */}
      {wizardOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4 animate-in fade-in overflow-y-auto">
          {renderWizardCardContent(false)}
        </div>
      )}
    </div>
  );
};
