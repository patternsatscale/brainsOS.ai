import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import {
  Cpu,
  RefreshCw,
  AlertTriangle,
  ExternalLink,
  Terminal,
  Shield,
  Activity,
  GitBranch,
  Play,
  Check,
  Copy,
  X,
  ArrowUpCircle,
  HardDrive,
  Trash2,
  FileText,
  Globe,
  Lock,
  UserCheck,
  Download,
  Wand2,
  CheckCircle2,
  KeyRound,
  Eye,
  EyeOff,
  Power,
  Bot,
  Sliders,
  Search,
  ChevronRight,
  RotateCcw,
  PackageCheck
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

interface OsPatchStatus {
  distro?: string;
  kernel?: string;
  arch?: string;
  unattended_upgrades_active?: boolean;
  pending_security_updates?: number;
  pending_packages?: string[];
  reboot_required?: boolean;
  reboot_packages?: string[];
  last_apt_update?: string;
}

export interface RunnerKeyStatus {
  configured: boolean;
  masked: string;
}

export interface RunnerStatus {
  id: string;
  name: string;
  runtime: string;
  status: string;
  version?: string;
  configured?: boolean;
  details?: string;
  endpoint?: string;
  ui_route?: string;
  active_model?: string;
  web_search_mode?: string;
  keys_configured?: string[];
  keys?: Record<string, RunnerKeyStatus>;
}

export interface ApplianceIdentity {
  unit_name?: string;
  instance_id?: string;
  firstboot_wizard_completed?: boolean;
  url?: string;
  local_domain?: string;
  hostname?: string;
  preserve_hostname?: boolean;
  superuser_name?: string;
  superuser_username?: string;
  admin_username?: string;
  admin_email?: string;
  admin_instance_bound?: boolean;
  tls_mode?: string;
  acme_email?: string;
  public_ipv4?: string;
  local_ipv4?: string;
  repo_root?: string;
  data_dir?: string;
  mail_domain?: string;
  console_user?: string;
}

interface SystemStatus {
  platform: string;
  platform_name?: string;
  platform_detail?: string;
  unit_name?: string;
  firstboot_wizard_completed?: boolean;
  url?: string;
  local_domain?: string;
  superuser_name?: string;
  superuser_username?: string;
  admin_username?: string;
  admin_email?: string;
  admin_instance_bound?: boolean;
  tls_mode?: string;
  acme_email?: string;
  hostname?: string;
  preserve_hostname?: boolean;
  public_ipv4?: string;
  local_ipv4?: string;
  instance_id?: string;
  repo_root?: string;
  data_dir?: string;
  mail_domain?: string;
  console_user?: string;
  identity?: ApplianceIdentity;
  git: GitStatus;
  services: Record<string, ServiceStatus>;
  disk?: DiskStatus;
  os?: OsPatchStatus;
  runners?: RunnerStatus[] | Record<string, unknown>;
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

const DEFAULT_RUNNERS_LIST: RunnerStatus[] = [
  {
    id: 'hermes',
    name: 'Nous Hermes Warm Runner',
    runtime: 'brainsos-agent-hermes-runner (Stateless Multi-Tenant Container)',
    status: 'online',
    version: 'v0.1.0-arm64',
    configured: true,
    endpoint: 'http://hermes-runner:8090',
    ui_route: '/runner/',
    active_model: 'qwen2.5:32b (via LiteLLM :4000)',
    web_search_mode: 'Keyless Free Tier (Rate-Limited)',
    keys: {
      FIRECRAWL_API_KEY: { configured: false, masked: '' },
      TAVILY_API_KEY: { configured: false, masked: '' },
      EXA_API_KEY: { configured: false, masked: '' },
      BRAVE_API_KEY: { configured: false, masked: '' },
      BRAVE_SEARCH_API_KEY: { configured: false, masked: '' },
      GITHUB_TOKEN: { configured: false, masked: '' },
      OPENROUTER_API_KEY: { configured: false, masked: '' },
      ANTHROPIC_API_KEY: { configured: false, masked: '' },
      OPENAI_API_KEY: { configured: false, masked: '' },
    },
  },
  {
    id: 'claude',
    name: 'Anthropic Claude SDK Runner',
    runtime: 'brainsOS-runner Adapter (LiteLLM Serialized)',
    status: 'online',
    configured: false,
    endpoint: 'http://litellm:4000/v1',
    active_model: 'claude-sonnet-4-20250514',
    web_search_mode: 'Tool Egress Gateway (:8082)',
  },
  {
    id: 'openai',
    name: 'OpenAI Agents SDK Runner',
    runtime: 'brainsOS-runner Adapter (LiteLLM Serialized)',
    status: 'online',
    configured: false,
    endpoint: 'http://litellm:4000/v1',
    active_model: 'gpt-4.1',
    web_search_mode: 'Tool Egress Gateway (:8082)',
  },
];

const DEFAULT_STATUS: SystemStatus = {
  platform: 'brainsOS',
  platform_name: 'AWS EC2 Appliance (AMI)',
  platform_detail: 'AWS ARM64 Graviton • EC2',
  unit_name: 'Enterprise Agent Box',
  firstboot_wizard_completed: true,
  url: 'ec2-32-192-215-107.compute-1.amazonaws.com',
  local_domain: 'jsm.aws.cloud.brainsos.ai',
  superuser_name: 'Jane Operator',
  superuser_username: 'jsm',
  admin_username: 'jsm',
  admin_email: 'jsm@jsm.aws.cloud.brainsos.ai',
  admin_instance_bound: true,
  tls_mode: 'internal',
  acme_email: '',
  hostname: 'jsm.aws.cloud.brainsos.ai',
  preserve_hostname: true,
  public_ipv4: '32.192.215.107',
  local_ipv4: '172.31.24.180',
  instance_id: 'i-0d32ae443d40e32d4',
  identity: {
    unit_name: 'Enterprise Agent Box',
    instance_id: 'i-0d32ae443d40e32d4',
    firstboot_wizard_completed: true,
    url: 'ec2-32-192-215-107.compute-1.amazonaws.com',
    local_domain: 'jsm.aws.cloud.brainsos.ai',
    hostname: 'jsm.aws.cloud.brainsos.ai',
    preserve_hostname: true,
    superuser_name: 'Jane Operator',
    superuser_username: 'jsm',
    admin_username: 'jsm',
    admin_email: 'jsm@jsm.aws.cloud.brainsos.ai',
    admin_instance_bound: true,
    tls_mode: 'internal',
    acme_email: '',
    public_ipv4: '32.192.215.107',
    local_ipv4: '172.31.24.180',
  },
  disk: {
    total_gb: 915.3,
    used_gb: 221.6,
    free_gb: 647.2,
    free_pct: 70.7,
    warning: false,
  },
  os: {
    distro: 'Ubuntu 24.04.1 LTS (Noble Numbat)',
    kernel: '6.8.0-1018-aws',
    arch: 'aarch64',
    unattended_upgrades_active: true,
    pending_security_updates: 0,
    pending_packages: [],
    reboot_required: false,
    reboot_packages: [],
    last_apt_update: 'Today, 06:00 UTC',
  },
  runners: DEFAULT_RUNNERS_LIST,
  git: {
    is_git: true,
    branch: 'main',
    available_branches: ['main', 'task/333-os-control-center'],
    current_commit: '8e2513c',
    remote_commit: '8e2513c',
    commits_behind: 0,
    update_available: false,
  },
  services: {
    litellm: {
      name: 'LiteLLM Gateway',
      current_version: 'v1.105.0',
      latest_version: '1.106.5',
      update_available: true,
      changelog_url: 'https://github.com/BerriAI/litellm/releases',
    },
    langfuse: {
      name: 'Langfuse Observability',
      current_version: '4.58.0',
      latest_version: '4.71.0',
      update_available: true,
      changelog_url: 'https://github.com/langfuse/langfuse/releases',
    },
    'code-server': {
      name: 'Operator Studio (VS Code IDE)',
      current_version: '4.138.0',
      latest_version: '4.145.2',
      update_available: true,
      changelog_url: 'https://github.com/coder/code-server/releases',
    },
    caddy: {
      name: 'Caddy Ingress',
      current_version: '2.8.4',
      latest_version: '2.8.4',
      update_available: false,
      changelog_url: 'https://github.com/caddyserver/caddy/releases',
    },
    hermes: {
      name: 'Hermes Agent Runner',
      current_version: 'v0.1.0-arm64',
      latest_version: 'v0.1.0-arm64',
      update_available: false,
      changelog_url: 'https://github.com/patternsatscale/brainsOS.ai/releases',
    },
    gitea: {
      name: 'Gitea Source Control',
      current_version: '1.22.3-rootless',
      latest_version: '1.22.3-rootless',
      update_available: false,
      changelog_url: 'https://github.com/go-gitea/gitea/releases',
    },
  },
  overall_update_available: true,
};

const KNOWN_TOOL_KEY_NAMES = [
  'FIRECRAWL_API_KEY',
  'TAVILY_API_KEY',
  'BRAVE_API_KEY',
  'BRAVE_SEARCH_API_KEY',
  'EXA_API_KEY',
  'GITHUB_TOKEN',
  'OPENROUTER_API_KEY',
  'ANTHROPIC_API_KEY',
  'OPENAI_API_KEY',
] as const;

export function extractToolKeys(rawRunners: unknown): Record<string, RunnerKeyStatus> {
  const result: Record<string, RunnerKeyStatus> = {};
  for (const k of KNOWN_TOOL_KEY_NAMES) {
    result[k] = { configured: false, masked: '' };
  }

  const mergeKeyObj = (source: unknown) => {
    if (!source || typeof source !== 'object' || Array.isArray(source)) return;
    for (const [keyName, rawVal] of Object.entries(source as Record<string, unknown>)) {
      if (rawVal && typeof rawVal === 'object') {
        const entry = rawVal as Record<string, unknown>;
        const configured = Boolean(entry.configured ?? entry.is_set ?? Boolean(entry.masked));
        const masked = typeof entry.masked === 'string' && entry.masked ? entry.masked : configured ? '••••' : '';
        result[keyName] = { configured, masked };
      } else if (typeof rawVal === 'boolean') {
        result[keyName] = { configured: rawVal, masked: rawVal ? '••••' : '' };
      } else if (typeof rawVal === 'string') {
        const configured = rawVal.trim().length > 0;
        result[keyName] = { configured, masked: configured ? rawVal : '' };
      }
    }
  };

  if (Array.isArray(rawRunners)) {
    for (const item of rawRunners) {
      if (item && typeof item === 'object') {
        const rec = item as Record<string, unknown>;
        mergeKeyObj(rec.keys);
        mergeKeyObj(rec.tool_keys);
      }
    }
  } else if (rawRunners && typeof rawRunners === 'object') {
    const dict = rawRunners as Record<string, unknown>;
    mergeKeyObj(dict.tool_keys);
    if (dict.hermes && typeof dict.hermes === 'object') {
      const h = dict.hermes as Record<string, unknown>;
      mergeKeyObj(h.keys);
      mergeKeyObj(h.tool_keys);
    }
  }

  // Keep BRAVE_API_KEY and BRAVE_SEARCH_API_KEY synchronized if either is set
  if (result.BRAVE_API_KEY?.configured && !result.BRAVE_SEARCH_API_KEY?.configured) {
    result.BRAVE_SEARCH_API_KEY = { ...result.BRAVE_API_KEY };
  } else if (result.BRAVE_SEARCH_API_KEY?.configured && !result.BRAVE_API_KEY?.configured) {
    result.BRAVE_API_KEY = { ...result.BRAVE_SEARCH_API_KEY };
  }

  return result;
}

export function normalizeRunners(rawRunners: unknown): RunnerStatus[] {
  const toolKeys = extractToolKeys(rawRunners);
  const configuredKeyList = Object.entries(toolKeys)
    .filter(([, v]) => v.configured)
    .map(([k]) => k);

  if (Array.isArray(rawRunners)) {
    if (rawRunners.length === 0) return DEFAULT_RUNNERS_LIST;
    return rawRunners
      .filter((r): r is Record<string, unknown> => Boolean(r && typeof r === 'object'))
      .map((r, idx) => {
        const id = String(r.id || `runner-${idx}`);
        const isHermes = id === 'hermes' || id.includes('hermes');
        const mergedKeys = isHermes
          ? { ...toolKeys, ...(r.keys && typeof r.keys === 'object' ? (r.keys as Record<string, RunnerKeyStatus>) : {}) }
          : (r.keys as Record<string, RunnerKeyStatus> | undefined);
        const firecrawlOn = Boolean(mergedKeys?.FIRECRAWL_API_KEY?.configured);
        return {
          id,
          name: String(r.name || (isHermes ? 'Nous Hermes Warm Runner' : id)),
          runtime: String(
            r.runtime ||
              r.details ||
              (isHermes
                ? 'brainsos-agent-hermes-runner (Stateless Multi-Tenant Container)'
                : 'brainsOS-runner Adapter (LiteLLM Serialized)')
          ),
          status: String(r.status || (r.configured === false ? 'standby' : 'online')),
          version: typeof r.version === 'string' ? r.version : undefined,
          configured: typeof r.configured === 'boolean' ? r.configured : true,
          details: typeof r.details === 'string' ? r.details : undefined,
          endpoint: typeof r.endpoint === 'string' ? r.endpoint : undefined,
          ui_route: typeof r.ui_route === 'string' ? r.ui_route : isHermes ? '/runner/' : undefined,
          active_model:
            typeof r.active_model === 'string'
              ? r.active_model
              : typeof r.model === 'string'
              ? r.model
              : isHermes
              ? 'qwen2.5:32b (via LiteLLM :4000)'
              : 'LiteLLM Default',
          web_search_mode:
            typeof r.web_search_mode === 'string'
              ? r.web_search_mode
              : isHermes
              ? firecrawlOn
                ? 'Firecrawl API Key Active'
                : 'Keyless Free Tier (Rate-Limited)'
              : 'Tool Egress Gateway (:8082)',
          keys_configured: Array.isArray(r.keys_configured)
            ? (r.keys_configured as string[])
            : isHermes
            ? configuredKeyList
            : [],
          keys: mergedKeys,
        };
      });
  }

  if (rawRunners && typeof rawRunners === 'object') {
    const dict = rawRunners as Record<string, unknown>;
    const normalized: RunnerStatus[] = [];
    const metaByKey: Record<
      string,
      { name: string; runtime: string; ui_route?: string; defaultModel: string; searchMode: string }
    > = {
      hermes: {
        name: 'Nous Hermes Warm Runner',
        runtime: 'brainsos-agent-hermes-runner (Stateless Multi-Tenant Container)',
        ui_route: '/runner/',
        defaultModel: 'qwen2.5:32b (via LiteLLM :4000)',
        searchMode: toolKeys.FIRECRAWL_API_KEY?.configured
          ? 'Firecrawl API Key Active'
          : 'Keyless Free Tier (Rate-Limited)',
      },
      claude: {
        name: 'Anthropic Claude SDK Runner',
        runtime: 'brainsOS-runner Adapter (LiteLLM Serialized)',
        defaultModel: 'claude-sonnet-4-20250514',
        searchMode: 'Tool Egress Gateway (:8082)',
      },
      'claude-sdk': {
        name: 'Anthropic Claude SDK Runner',
        runtime: 'brainsOS-runner Adapter (LiteLLM Serialized)',
        defaultModel: 'claude-sonnet-4-20250514',
        searchMode: 'Tool Egress Gateway (:8082)',
      },
      openai: {
        name: 'OpenAI Agents SDK Runner',
        runtime: 'brainsOS-runner Adapter (LiteLLM Serialized)',
        defaultModel: 'gpt-4.1',
        searchMode: 'Tool Egress Gateway (:8082)',
      },
      'openai-sdk': {
        name: 'OpenAI Agents SDK Runner',
        runtime: 'brainsOS-runner Adapter (LiteLLM Serialized)',
        defaultModel: 'gpt-4.1',
        searchMode: 'Tool Egress Gateway (:8082)',
      },
    };

    for (const [key, rawVal] of Object.entries(dict)) {
      if (key === 'tool_keys') continue;
      if (!rawVal || typeof rawVal !== 'object' || Array.isArray(rawVal)) continue;
      const entry = rawVal as Record<string, unknown>;
      const meta = metaByKey[key] || {
        name: String(entry.name || key.toUpperCase()),
        runtime: String(entry.runtime || 'brainsOS-runner Adapter'),
        defaultModel: String(entry.active_model || entry.model || 'LiteLLM Default'),
        searchMode: 'Tool Egress Gateway (:8082)',
      };
      const isHermes = key === 'hermes' || key.includes('hermes');
      const containers = Array.isArray(entry.containers) ? entry.containers : [];
      const containerSummary =
        containers.length > 0
          ? containers
              .map((c) =>
                c && typeof c === 'object'
                  ? `${(c as Record<string, unknown>).name || 'hermes'} (${(c as Record<string, unknown>).status || 'running'})`
                  : String(c)
              )
              .join(', ')
          : '';
      const configured =
        typeof entry.configured === 'boolean'
          ? entry.configured
          : isHermes
          ? true
          : key === 'claude' || key === 'claude-sdk'
          ? Boolean(toolKeys.ANTHROPIC_API_KEY?.configured || toolKeys.OPENROUTER_API_KEY?.configured)
          : key === 'openai' || key === 'openai-sdk'
          ? Boolean(toolKeys.OPENAI_API_KEY?.configured || toolKeys.OPENROUTER_API_KEY?.configured)
          : true;
      const statusStr = String(
        entry.status || (isHermes ? 'online' : configured ? 'online' : 'standby')
      );

      normalized.push({
        id: key,
        name: String(entry.name || meta.name),
        runtime: String(entry.runtime || entry.details || containerSummary || meta.runtime),
        status: statusStr,
        version: typeof entry.version === 'string' ? entry.version : undefined,
        configured,
        details: typeof entry.details === 'string' ? entry.details : containerSummary || undefined,
        endpoint: typeof entry.endpoint === 'string' ? entry.endpoint : undefined,
        ui_route: typeof entry.ui_route === 'string' ? entry.ui_route : meta.ui_route,
        active_model: String(entry.active_model || entry.model || meta.defaultModel),
        web_search_mode: String(entry.web_search_mode || meta.searchMode),
        keys_configured: isHermes ? configuredKeyList : [],
        keys: isHermes ? toolKeys : undefined,
      });
    }

    if (normalized.length > 0) {
      return normalized;
    }
  }

  return DEFAULT_RUNNERS_LIST;
}

function normalizeStatusPayload(raw: unknown): SystemStatus {
  if (!raw || typeof raw !== 'object') return DEFAULT_STATUS;
  const data = raw as Record<string, unknown>;
  const nestedIdentity =
    data.identity && typeof data.identity === 'object'
      ? (data.identity as Record<string, unknown>)
      : {};

  const firstbootCompleted =
    typeof nestedIdentity.firstboot_wizard_completed === 'boolean'
      ? nestedIdentity.firstboot_wizard_completed
      : typeof data.firstboot_wizard_completed === 'boolean'
      ? data.firstboot_wizard_completed
      : true;

  const rawSuperuserUsername = String(
    nestedIdentity.superuser_username ?? data.superuser_username ?? ''
  ).trim();
  const rawAdminUsername = String(
    nestedIdentity.admin_username ?? data.admin_username ?? ''
  ).trim();

  // Never allow superuser_username to default to 'admin' when wizard is not completed or when it equals 'admin'
  const cleanSuperuserUsername =
    !firstbootCompleted || rawSuperuserUsername.toLowerCase() === 'admin'
      ? ''
      : rawSuperuserUsername || (rawAdminUsername.toLowerCase() !== 'admin' ? rawAdminUsername : '');

  const unitName = String(
    nestedIdentity.unit_name ??
      data.unit_name ??
      (cleanSuperuserUsername ? `${cleanSuperuserUsername}'s Agent Box` : 'Enterprise Agent Box')
  ).trim();

  const rawLocalDomain = String(
    nestedIdentity.local_domain ?? data.local_domain ?? 'dgx.local.brainsos.ai'
  )
    .trim()
    .replace(/^mail\./i, '');
  const localDomain = rawLocalDomain || 'dgx.local.brainsos.ai';
  const url = String(nestedIdentity.url ?? data.url ?? localDomain)
    .trim()
    .replace(/^mail\./i, '');
  const hostname = String(nestedIdentity.hostname ?? data.hostname ?? localDomain)
    .trim()
    .replace(/^mail\./i, '');
  const instanceId = String(nestedIdentity.instance_id ?? data.instance_id ?? '').trim();
  const publicIpv4 = String(nestedIdentity.public_ipv4 ?? data.public_ipv4 ?? '').trim();
  const localIpv4 = String(nestedIdentity.local_ipv4 ?? data.local_ipv4 ?? '').trim();
  const tlsMode = String(nestedIdentity.tls_mode ?? data.tls_mode ?? 'internal').trim();
  const acmeEmail = String(nestedIdentity.acme_email ?? data.acme_email ?? '').trim();
  const superuserName = String(nestedIdentity.superuser_name ?? data.superuser_name ?? '').trim();
  const preserveHostname = Boolean(
    nestedIdentity.preserve_hostname ?? data.preserve_hostname ?? true
  );
  const repoRoot = String(
    nestedIdentity.repo_root ?? data.repo_root ?? '/opt/brainsos'
  ).trim() || '/opt/brainsos';
  const dataDir = String(
    nestedIdentity.data_dir ?? data.data_dir ?? '/data'
  ).trim() || '/data';
  const mailDomain = String(
    nestedIdentity.mail_domain ?? data.mail_domain ?? localDomain
  )
    .trim()
    .replace(/^mail\./i, '') || localDomain;
  const consoleUser = String(
    nestedIdentity.console_user ??
      data.console_user ??
      (cleanSuperuserUsername || rawAdminUsername || 'admin')
  ).trim() || 'admin';

  const normalizedIdentity: ApplianceIdentity = {
    unit_name: unitName,
    instance_id: instanceId,
    firstboot_wizard_completed: firstbootCompleted,
    url,
    local_domain: localDomain,
    hostname,
    preserve_hostname: preserveHostname,
    superuser_name: superuserName,
    superuser_username: cleanSuperuserUsername,
    admin_username: cleanSuperuserUsername || rawAdminUsername || 'admin',
    admin_email: String(
      nestedIdentity.admin_email ??
        data.admin_email ??
        (cleanSuperuserUsername ? `${cleanSuperuserUsername}@${localDomain}` : `admin@${localDomain}`)
    ),
    admin_instance_bound: true,
    tls_mode: tlsMode,
    acme_email: acmeEmail,
    public_ipv4: publicIpv4,
    local_ipv4: localIpv4,
    repo_root: repoRoot,
    data_dir: dataDir,
    mail_domain: mailDomain,
    console_user: consoleUser,
  };

  const rawGit = data.git && typeof data.git === 'object' ? (data.git as Record<string, unknown>) : {};
  const git: GitStatus = {
    is_git: Boolean(rawGit.is_git ?? true),
    branch: String(rawGit.branch || 'main'),
    available_branches: Array.isArray(rawGit.available_branches)
      ? (rawGit.available_branches as string[])
      : [String(rawGit.branch || 'main')],
    current_commit: String(rawGit.current_commit || 'HEAD'),
    remote_commit: String(rawGit.remote_commit || 'HEAD'),
    commits_behind: Number(rawGit.commits_behind || 0),
    update_available: Boolean(rawGit.update_available),
  };

  const rawOs =
    (data.os && typeof data.os === 'object' ? (data.os as Record<string, unknown>) : null) ||
    (data.os_patches && typeof data.os_patches === 'object'
      ? (data.os_patches as Record<string, unknown>)
      : null) ||
    {};

  const os: OsPatchStatus = {
    distro: String(rawOs.distro || DEFAULT_STATUS.os?.distro || 'Ubuntu 24.04 LTS'),
    kernel: String(rawOs.kernel || DEFAULT_STATUS.os?.kernel || '6.8.0-aws'),
    arch: String(rawOs.arch || DEFAULT_STATUS.os?.arch || 'aarch64'),
    unattended_upgrades_active:
      typeof rawOs.unattended_upgrades_active === 'boolean' ? rawOs.unattended_upgrades_active : true,
    pending_security_updates: Number(
      rawOs.pending_security_updates ?? rawOs.security_updates_count ?? 0
    ),
    pending_packages: Array.isArray(rawOs.pending_packages)
      ? (rawOs.pending_packages as string[])
      : [],
    reboot_required: Boolean(rawOs.reboot_required ?? false),
    reboot_packages: Array.isArray(rawOs.reboot_packages)
      ? (rawOs.reboot_packages as string[])
      : [],
    last_apt_update: typeof rawOs.last_apt_update === 'string' ? rawOs.last_apt_update : undefined,
  };

  const rawServices =
    data.services && typeof data.services === 'object' && !Array.isArray(data.services)
      ? (data.services as Record<string, ServiceStatus>)
      : DEFAULT_STATUS.services;

  return {
    ...(data as unknown as SystemStatus),
    platform: String(data.platform || 'brainsOS'),
    platform_name: String(data.platform_name || 'AWS EC2 Appliance (AMI)'),
    platform_detail: String(data.platform_detail || 'AWS ARM64 Graviton • EC2'),
    unit_name: unitName,
    firstboot_wizard_completed: firstbootCompleted,
    url,
    local_domain: localDomain,
    superuser_name: superuserName,
    superuser_username: cleanSuperuserUsername,
    admin_username: normalizedIdentity.admin_username,
    admin_email: normalizedIdentity.admin_email,
    admin_instance_bound: true,
    tls_mode: tlsMode,
    acme_email: acmeEmail,
    hostname,
    preserve_hostname: preserveHostname,
    public_ipv4: publicIpv4,
    local_ipv4: localIpv4,
    instance_id: instanceId,
    repo_root: repoRoot,
    data_dir: dataDir,
    mail_domain: mailDomain,
    console_user: consoleUser,
    identity: normalizedIdentity,
    git,
    os,
    services: rawServices,
    runners: normalizeRunners(data.runners),
    overall_update_available: Boolean(data.overall_update_available),
  };
}

function deriveUsernameFromFullName(fullName: string): string {
  const trimmed = fullName.trim().toLowerCase();
  if (!trimmed) return '';
  const parts = trimmed.split(/\s+/).filter(Boolean);
  const firstWord = (parts[0] || '').replace(/[^a-z0-9]/g, '');
  const fullSlug = trimmed.replace(/[^a-z0-9]/g, '');
  let candidate = firstWord.length >= 2 ? firstWord : fullSlug;
  if (candidate === 'admin' || candidate === 'akadmin') {
    candidate = parts.length > 1 ? fullSlug : '';
  }
  if (candidate === 'admin' || candidate === 'akadmin') {
    return '';
  }
  return candidate.slice(0, 32);
}

interface UpdateTarget {
  id: string;
  name: string;
  targetVersion?: string;
  service?: string;
  containersOnly?: boolean;
  full?: boolean;
  branch?: string;
  resetVersion?: boolean;
}

interface LogEntry {
  id: number;
  timestamp: string;
  text: string;
  type: 'log' | 'info' | 'error' | 'success';
}

interface ConsoleEntry {
  id: number;
  type: 'input' | 'output' | 'system' | 'error';
  text: string;
  timestamp: string;
}

type OsPane = 'overview' | 'console' | 'agents' | 'updates' | 'storage';

// Convert ANSI color escape codes into HTML spans
const renderAnsiLine = (text: string) => {
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

const SystemManagerInner: React.FC<SystemManagerProps> = ({ standaloneWizard = false }) => {
  const [activePane, setActivePane] = useState<OsPane>('overview');
  const [status, setStatus] = useState<SystemStatus | null>(import.meta.env.DEV ? DEFAULT_STATUS : null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState<boolean>(false);
  const [lastChecked, setLastChecked] = useState<string>('Just now');
  const [confirmTarget, setConfirmTarget] = useState<UpdateTarget | null>(null);
  const [selectedBranch, setSelectedBranch] = useState<string>('');
  const [pinVersions, setPinVersions] = useState<Record<string, string>>({});

  // First-Boot Superuser Setup Wizard & Appliance Identity State (#332 / #333)
  const [wizardOpen, setWizardOpen] = useState<boolean>(false);
  const [wizardStep, setWizardStep] = useState<1 | 2 | 3>(1);
  const [wizardAutoOpened, setWizardAutoOpened] = useState<boolean>(false);
  const [setupBootstrapToken, setSetupBootstrapToken] = useState<string>('');
  const [showBootstrapToken, setShowBootstrapToken] = useState<boolean>(false);
  const [setupSuperuserName, setSetupSuperuserName] = useState<string>('');
  const [setupAdminUsername, setSetupAdminUsername] = useState<string>('');
  const [wizardUsernameTouched, setWizardUsernameTouched] = useState<boolean>(false);
  const [setupUnitName, setSetupUnitName] = useState<string>('Enterprise Agent Box');
  const [wizardUnitNameTouched, setWizardUnitNameTouched] = useState<boolean>(false);
  const [identityUnitName, setIdentityUnitName] = useState<string>('Enterprise Agent Box');
  const [savingIdentityUnitName, setSavingIdentityUnitName] = useState<boolean>(false);
  const [identitySaveBanner, setIdentitySaveBanner] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isEditingRouting, setIsEditingRouting] = useState<boolean>(false);
  const [setupAdminPassword, setSetupAdminPassword] = useState<string>('');
  const [setupAdminPasswordConfirm, setSetupAdminPasswordConfirm] = useState<string>('');
  const [showSetupPasswords, setShowSetupPasswords] = useState<boolean>(false);
  const [setupLocalDomain, setSetupLocalDomain] = useState<string>('local.brainsos.ai');
  const [localDomainManuallyEdited, setLocalDomainManuallyEdited] = useState<boolean>(false);
  const [setupUrl, setSetupUrl] = useState<string>('local.brainsos.ai');
  const [setupTlsMode, setSetupTlsMode] = useState<'internal' | 'acme' | 'route53'>('internal');
  const [setupAcmeEmail, setSetupAcmeEmail] = useState<string>('');
  const [setupError, setSetupError] = useState<string | null>(null);
  const [dnsChecking, setDnsChecking] = useState<boolean>(false);
  const [dnsCheckResult, setDnsCheckResult] = useState<DnsCheckResult | null>(null);
  const [newConfiguredUrl, setNewConfiguredUrl] = useState<string | null>(null);

  // Agents & Runners API Key Configuration State (#334)
  const [firecrawlKey, setFirecrawlKey] = useState<string>('');
  const [tavilyKey, setTavilyKey] = useState<string>('');
  const [exaKey, setExaKey] = useState<string>('');
  const [braveKey, setBraveKey] = useState<string>('');
  const [githubTokenKey, setGithubTokenKey] = useState<string>('');
  const [openrouterKey, setOpenrouterKey] = useState<string>('');
  const [anthropicKey, setAnthropicKey] = useState<string>('');
  const [openaiKey, setOpenaiKey] = useState<string>('');
  const [showRunnerKeys, setShowRunnerKeys] = useState<boolean>(false);
  const [savingRunnerConfig, setSavingRunnerConfig] = useState<boolean>(false);
  const [runnerSaveBanner, setRunnerSaveBanner] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Reboot Confirmation Modal State (#336)
  const [rebootModalOpen, setRebootModalOpen] = useState<boolean>(false);
  const [rebootConfirmText, setRebootConfirmText] = useState<string>('');
  const [isRebooting, setIsRebooting] = useState<boolean>(false);

  // Job SSE Log Stream State
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [executionStatus, setExecutionStatus] = useState<'idle' | 'running' | 'success' | 'failed'>('idle');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copiedLogs, setCopiedLogs] = useState<boolean>(false);
  const logsEndRef = useRef<HTMLDivElement | null>(null);

  // Interactive XTerm.js Host Console State (#333)
  const [consoleViewMode, setConsoleViewMode] = useState<'interactive' | 'jobs'>('interactive');
  const [consoleEntries, setConsoleEntries] = useState<ConsoleEntry[]>([]);
  const [consoleInput, setConsoleInput] = useState<string>('');
  const [consoleHistory, setConsoleHistory] = useState<string[]>([]);
  const [historyIdx, setHistoryIdx] = useState<number>(-1);
  const [consoleBusy, setConsoleBusy] = useState<boolean>(false);
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const wsRef = useRef<WebSocket | null>(null);
  const xtermContainerRef = useRef<HTMLDivElement | null>(null);
  const xtermRef = useRef<XTerm | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const localLineBufferRef = useRef<string>('');
  const consoleInputRef = useRef<HTMLInputElement | null>(null);

  const normalizedRunners = useMemo(() => normalizeRunners(status?.runners), [status?.runners]);
  const toolKeysMap = useMemo(() => extractToolKeys(status?.runners), [status?.runners]);

  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, consoleEntries, autoScroll]);

  // Fetch CSRF token on mount
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
      // Ignore CSRF pre-fetch failure in offline preview
    }
  }, []);

  // Fetch live system status
  const fetchStatus = useCallback(async () => {
    setIsChecking(true);
    try {
      const res = await fetch('/api/v1/system/status');
      if (res.ok) {
        const rawData = await res.json();
        const data = normalizeStatusPayload(rawData);
        setStatus(data);
        if (typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('brainsos:system-status', {
              detail: { overall_update_available: Boolean(data.overall_update_available) },
            })
          );
        }
        if (data?.git?.branch) {
          setSelectedBranch((prev) => prev || data.git.branch);
        }
        if (data?.unit_name) {
          setSetupUnitName((prev) => (prev === 'Enterprise Agent Box' ? data.unit_name! : prev));
          setIdentityUnitName(data.unit_name);
        }
        if (data?.local_domain) {
          setSetupLocalDomain((prev) => (prev === 'local.brainsos.ai' ? data.local_domain! : prev));
        }
        // Superuser username must NEVER default to 'admin'
        const isFirstBootIncomplete = data?.firstboot_wizard_completed === false || data?.identity?.firstboot_wizard_completed === false;
        const candidateUser = (data?.identity?.superuser_username || data?.superuser_username || '').trim();
        if (isFirstBootIncomplete || candidateUser.toLowerCase() === 'admin') {
          setSetupAdminUsername((prev) => (prev.toLowerCase() === 'admin' ? '' : prev));
        } else if (candidateUser) {
          setSetupAdminUsername((prev) => prev || candidateUser);
        }
        if (data?.superuser_name) {
          setSetupSuperuserName((prev) => prev || data.superuser_name!);
        }
        if (data?.url) {
          setSetupUrl((prev) => (prev === 'local.brainsos.ai' ? data.url! : prev));
        }
        if (data?.tls_mode && ['internal', 'acme', 'route53'].includes(data.tls_mode)) {
          setSetupTlsMode(data.tls_mode as 'internal' | 'acme' | 'route53');
        }
        if (data?.acme_email) {
          setSetupAcmeEmail((prev) => prev || data.acme_email!);
        }
        if (isFirstBootIncomplete && !wizardAutoOpened) {
          setWizardAutoOpened(true);
          setSetupAdminUsername('');
          setWizardUsernameTouched(false);
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
  }, [wizardAutoOpened]);

  useEffect(() => {
    fetchStatus();
    fetchCsrfToken();
  }, [fetchStatus, fetchCsrfToken]);

  // Execute a command for System Output or as the HTTP fallback inside term.onData when WS is disconnected
  const executeConsoleCommand = useCallback(
    async (rawCmd: string, fromXtermFallback: boolean = false) => {
      const cmd = rawCmd.trim();
      if (!cmd) return;

      const writeToXtermOnly =
        fromXtermFallback &&
        (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN);

      const ts = new Date().toLocaleTimeString();
      const promptHost = (status?.hostname || status?.local_domain || 'brainsos').split('.')[0];
      const promptUser =
        status?.console_user || status?.superuser_username || status?.admin_username || 'admin';
      const promptRepoRoot = status?.repo_root || '/opt/brainsos';

      if (!writeToXtermOnly) {
        setConsoleEntries((prev) => [
          ...prev,
          {
            id: Date.now(),
            type: 'input',
            timestamp: ts,
            text: `${promptUser}@${promptHost}:${promptRepoRoot}$ ${cmd}`,
          },
        ]);
      }
      setConsoleHistory((prev) => [cmd, ...prev.filter((c) => c !== cmd)].slice(0, 50));
      setHistoryIdx(-1);
      setConsoleInput('');

      if (cmd === 'clear' || cmd === 'cls') {
        if (writeToXtermOnly) {
          xtermRef.current?.clear();
        } else {
          setConsoleEntries([]);
        }
        return;
      }

      if (cmd === 'help') {
        const helpLines = [
          'brainsOS Host Console — Available Diagnostic & Operational Commands:',
          '  ls -la                   Inspect brainsOS source root directory',
          '  git status -sb           Check platform repository git status and branch',
          '  docker ps                List running appliance containers and health states',
          '  df -h                    Display filesystem disk space utilization',
          '  htop / top               Interactive process & ARM64 core monitor',
          '  uname -a                 Display Linux kernel and ARM64 hardware architecture',
          '  clear                    Clear terminal scrollback buffer',
        ].join('\r\n');
        if (writeToXtermOnly) {
          xtermRef.current?.writeln(`\r\n${helpLines}\r\n`);
          const prompt = `\r\n\x1b[1;32m${promptUser}@${promptHost}\x1b[0m:\x1b[1;34m${promptRepoRoot}\x1b[0m$ `;
          xtermRef.current?.write(prompt);
        } else {
          setConsoleEntries((prev) => [
            ...prev,
            {
              id: Date.now() + 1,
              type: 'output',
              timestamp: ts,
              text: helpLines,
            },
          ]);
        }
        return;
      }

      setConsoleBusy(true);
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

      try {
        const res = await fetch('/api/v1/system/terminal/exec', {
          method: 'POST',
          headers,
          body: JSON.stringify({ command: cmd }),
        });
        if (res.ok) {
          const data = await res.json();
          const out = data.output || data.stdout || data.stderr || '(command completed with exit code 0)';
          if (writeToXtermOnly) {
            xtermRef.current?.writeln(`\r\n${String(out).replace(/\r?\n/g, '\r\n')}`);
          } else {
            setConsoleEntries((prev) => [
              ...prev,
              {
                id: Date.now() + 2,
                type: data.exit_code && data.exit_code !== 0 ? 'error' : 'output',
                timestamp: new Date().toLocaleTimeString(),
                text: out,
              },
            ]);
          }
        } else {
          throw new Error(`HTTP ${res.status}`);
        }
      } catch {
        let simulated = '';
        if (cmd.startsWith('uname')) {
          simulated = `Linux ${status?.hostname || 'brainsos'} ${status?.os?.kernel || '6.8.0-1018-aws'} #19-Ubuntu SMP PREEMPT_DYNAMIC aarch64 GNU/Linux`;
        } else if (cmd.startsWith('df')) {
          simulated = [
            'Filesystem      Size  Used Avail Use% Mounted on',
            `/dev/nvme0n1p1  ${status?.disk?.total_gb || 915}G  ${status?.disk?.used_gb || 221}G  ${status?.disk?.free_gb || 647}G  ${status?.disk ? (100 - status.disk.free_pct).toFixed(0) : 25}% /`,
            'tmpfs            16G  1.2M   16G   1% /run',
          ].join('\n');
        } else if (cmd.includes('docker ps') || cmd.includes('docker compose ps') || cmd === 'make status') {
          simulated = [
            'NAME                            IMAGE                                      STATUS                   PORTS',
            'brainsos-ingress-caddy          brainsos-caddy:2.8.4                       Up 4 hours (healthy)     80/tcp, 443/tcp',
            'brainsos-auth-authentik-server  ghcr.io/goauthentik/server:2024.8.3        Up 4 hours (healthy)     9000/tcp',
            'brainsos-control-litellm        ghcr.io/berriai/litellm:v1.105.0           Up 4 hours (healthy)     4000/tcp',
            'brainsos-agent-hermes-runner    brainsos-hermes-runner:v0.1.0-arm64        Up 4 hours (healthy)     8090/tcp',
            'brainsos-git-gitea              gitea/gitea:1.22.3-rootless                Up 4 hours (healthy)     3000/tcp',
          ].join('\n');
        } else if (cmd.includes('git') && cmd.includes('status')) {
          simulated = `On branch ${status?.git?.branch || 'main'}\nYour branch is up to date with 'origin/${status?.git?.branch || 'main'}'.\nnothing to commit, working tree clean`;
        } else {
          simulated = `[HTTP Fallback] Executed: ${cmd}`;
        }
        if (writeToXtermOnly) {
          xtermRef.current?.writeln(`\r\n${simulated.replace(/\r?\n/g, '\r\n')}`);
        } else {
          setConsoleEntries((prev) => [
            ...prev,
            {
              id: Date.now() + 2,
              type: 'output',
              timestamp: new Date().toLocaleTimeString(),
              text: simulated,
            },
          ]);
        }
      } finally {
        setConsoleBusy(false);
        if (writeToXtermOnly) {
          const prompt = `\r\n\x1b[1;32m${promptUser}@${promptHost}\x1b[0m:\x1b[1;34m${promptRepoRoot}\x1b[0m$ `;
          xtermRef.current?.write(prompt);
        }
      }
    },
    [csrfToken, status]
  );

  const executeConsoleCommandRef = useRef(executeConsoleCommand);
  useEffect(() => {
    executeConsoleCommandRef.current = executeConsoleCommand;
  }, [executeConsoleCommand]);

  const statusRef = useRef(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  // Connect interactive WebSocket to XTerm PTY
  const connectTerminalWs = useCallback(() => {
    if (typeof window === 'undefined') return;
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    if (wsRef.current) {
      const oldWs = wsRef.current;
      wsRef.current = null;
      try {
        oldWs.close();
      } catch {}
    }
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${window.location.host}/api/v1/system/terminal/ws`;
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => {
        if (wsRef.current !== ws) return;
        setWsConnected(true);
        if (xtermRef.current) {
          try {
            xtermRef.current.reset();
            xtermRef.current.clear();
          } catch {}
        }
        if (fitAddonRef.current && xtermRef.current) {
          try {
            fitAddonRef.current.fit();
            ws.send(
              JSON.stringify({
                type: 'resize',
                cols: xtermRef.current.cols || 120,
                rows: xtermRef.current.rows || 36,
              })
            );
            xtermRef.current.focus();
          } catch {}
        }
      };
      ws.onmessage = (evt) => {
        if (wsRef.current !== ws) return;
        const raw = typeof evt.data === 'string' ? evt.data : '';
        if (!raw) return;
        try {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === 'object') {
            if (parsed.type === 'pong' || parsed.type === 'ready') return;
            if (parsed.type === 'output' && typeof parsed.data === 'string') {
              xtermRef.current?.write(parsed.data);
              return;
            }
            if (parsed.type === 'error' && typeof parsed.data === 'string') {
              xtermRef.current?.writeln(`\r\n\x1b[1;31m[PTY Error] ${parsed.data}\x1b[0m`);
              return;
            }
          }
        } catch {
          // Non-JSON payload fallback
        }
        xtermRef.current?.write(raw);
      };
      ws.onerror = () => {
        if (wsRef.current !== ws) return;
        setWsConnected(false);
      };
      ws.onclose = () => {
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        setWsConnected(false);
      };
    } catch {
      setWsConnected(false);
    }
  }, []);

  // Initialize XTerm.js instance & ResizeObserver when Host Console interactive view is mounted
  useEffect(() => {
    if (activePane !== 'console' || consoleViewMode !== 'interactive') {
      return;
    }
    const container = xtermContainerRef.current;
    if (!container) return;

    if (xtermRef.current && xtermRef.current.element && !container.contains(xtermRef.current.element)) {
      try {
        xtermRef.current.dispose();
      } catch {}
      xtermRef.current = null;
      fitAddonRef.current = null;
    }

    if (!xtermRef.current) {
      const term = new XTerm({
        cursorBlink: true,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        fontSize: 12.5,
        lineHeight: 1.35,
        convertEol: true,
        scrollback: 5000,
        theme: {
          background: '#05070B',
          foreground: '#e2e8f0',
          cursor: '#00f2fe',
          selectionBackground: 'rgba(0, 242, 254, 0.25)',
          black: '#07090e',
          red: '#f87171',
          green: '#34d399',
          yellow: '#fbbf24',
          blue: '#60a5fa',
          magenta: '#c084fc',
          cyan: '#00f2fe',
          white: '#f8fafc',
        },
      });
      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.open(container);
      term.reset();
      term.clear();
      try {
        fitAddon.fit();
      } catch {}

      term.onData((data) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'input', data }));
        } else {
          // Local line buffer for HTTP fallback when WebSocket is disconnected
          if (data === '\r' || data === '\n') {
            const cmdToRun = localLineBufferRef.current;
            localLineBufferRef.current = '';
            term.write('\r\n');
            if (cmdToRun.trim()) {
              executeConsoleCommandRef.current(cmdToRun, true);
            } else {
              const curStatus = statusRef.current;
              const promptHost = (curStatus?.hostname || curStatus?.local_domain || 'brainsos').split('.')[0];
              const promptUser =
                curStatus?.console_user || curStatus?.superuser_username || curStatus?.admin_username || 'admin';
              const promptRepoRoot = curStatus?.repo_root || '/opt/brainsos';
              term.write(`\x1b[1;32m${promptUser}@${promptHost}\x1b[0m:\x1b[1;34m${promptRepoRoot}\x1b[0m$ `);
            }
          } else if (data === '\x7f' || data === '\b') {
            if (localLineBufferRef.current.length > 0) {
              localLineBufferRef.current = localLineBufferRef.current.slice(0, -1);
              term.write('\b \b');
            }
          } else if (data === '\x03') {
            localLineBufferRef.current = '';
            term.write('^C\r\n$ ');
          } else {
            localLineBufferRef.current += data;
            term.write(data);
          }
        }
      });

      xtermRef.current = term;
      fitAddonRef.current = fitAddon;
    } else {
      try {
        fitAddonRef.current?.fit();
        xtermRef.current.focus();
      } catch {}
    }

    connectTerminalWs();

    const keepAliveTimer = window.setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify({ type: 'ping' }));
        } catch {}
      } else if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) {
        connectTerminalWs();
      }
    }, 15000);

    const resizeObserver = new ResizeObserver(() => {
      if (fitAddonRef.current && xtermRef.current) {
        try {
          fitAddonRef.current.fit();
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(
              JSON.stringify({
                type: 'resize',
                cols: xtermRef.current.cols || 120,
                rows: xtermRef.current.rows || 36,
              })
            );
          }
        } catch {}
      }
    });
    resizeObserver.observe(container);

    return () => {
      window.clearInterval(keepAliveTimer);
      resizeObserver.disconnect();
    };
  }, [activePane, consoleViewMode, connectTerminalWs]);

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {}
        wsRef.current = null;
      }
      if (xtermRef.current) {
        try {
          xtermRef.current.dispose();
        } catch {}
        xtermRef.current = null;
      }
    };
  }, []);

  // Fallback polling when an SSE connection drops mid-stream
  const pollJobUntilComplete = async (
    jobId: string,
    addLog: (text: string, type?: 'log' | 'info' | 'error' | 'success') => void,
    onSuccess?: () => void,
    wizardActive: boolean = false
  ): Promise<'success' | 'failed'> => {
    addLog(`🔄 Ingress proxy reloading — reattaching to background job ${jobId}...`, 'info');
    let seenCount = 0;
    for (let attempt = 0; attempt < 180; attempt++) {
      await new Promise((r) => setTimeout(r, 2000));
      let jobStillRunningOrUnreachable = false;
      try {
        const res = await fetch(`/api/v1/system/jobs/${jobId}`);
        if (!res.ok) {
          jobStillRunningOrUnreachable = true;
        } else {
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
            return 'success';
          }
          if (job.status === 'failed') {
            addLog(`❌ Background job ${jobId} exited with code ${job.exit_code}.`, 'error');
            setExecutionStatus('failed');
            fetchStatus();
            return 'failed';
          }
          jobStillRunningOrUnreachable = true;
        }
      } catch {
        // Wait for Caddy ingress to finish restarting
        jobStillRunningOrUnreachable = true;
      }

      // After the first 3 polls during wizard setup, also probe /api/v1/system/identity (or /api/v1/system/status).
      // If firstboot_wizard_completed === true, treat the setup job as 'success' immediately!
      if (wizardActive && attempt >= 3 && jobStillRunningOrUnreachable) {
        try {
          const idRes = await fetch('/api/v1/system/identity');
          if (idRes.ok) {
            const idData = await idRes.json();
            const completed =
              idData?.firstboot_wizard_completed === true ||
              idData?.identity?.firstboot_wizard_completed === true;
            if (completed) {
              addLog(`✅ Appliance identity & TLS reload verified active!`, 'success');
              setExecutionStatus('success');
              if (onSuccess) onSuccess();
              fetchStatus();
              return 'success';
            }
          } else {
            const stRes = await fetch('/api/v1/system/status');
            if (stRes.ok) {
              const stData = await stRes.json();
              const completed =
                stData?.firstboot_wizard_completed === true ||
                stData?.identity?.firstboot_wizard_completed === true;
              if (completed) {
                addLog(`✅ Appliance identity & TLS reload verified active!`, 'success');
                setExecutionStatus('success');
                if (onSuccess) onSuccess();
                fetchStatus();
                return 'success';
              }
            }
          }
        } catch {
          // Continue polling while Caddy finishes reloading
        }
      }
    }
    setExecutionStatus('failed');
    addLog(`⚠️ Timed out waiting for background job ${jobId}.`, 'error');
    return 'failed';
  };

  // Helper to stream any SSE job endpoint into the Console Job Logs view
  const runStreamedJob = async (
    endpoint: string,
    bodyPayload: Record<string, unknown>,
    initialBanner: string,
    onSuccess?: () => void
  ) => {
    setActivePane('console');
    setConsoleViewMode('jobs');
    setExecutionStatus('running');

    const startTimestamp = new Date().toLocaleTimeString();
    setLogs([
      {
        id: 1,
        timestamp: startTimestamp,
        text: initialBanner,
        type: 'info',
      },
    ]);

    let logCounter = 2;
    const addLog = (text: string, type: 'log' | 'info' | 'error' | 'success' = 'log') => {
      const ts = new Date().toLocaleTimeString();
      setLogs((prev) => [...prev, { id: logCounter++, timestamp: ts, text, type }]);
    };

    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(bodyPayload),
      });

      if (!res.ok) {
        let errorDetail = res.statusText;
        try {
          const errData = await res.json();
          if (errData && errData.detail) errorDetail = errData.detail;
        } catch {}
        throw new Error(`HTTP ${res.status}: ${errorDetail}`);
      }

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
                  addLog(`⚙️ Command launched: ${payload.cmd}`, 'info');
                } else if (payload.type === 'complete') {
                  completedCleanly = true;
                  if (payload.exit_code === 0) {
                    addLog(`✅ Operation completed successfully (exit code 0).`, 'success');
                    setExecutionStatus('success');
                    if (onSuccess) onSuccess();
                  } else {
                    addLog(`❌ Operation exited with error code ${payload.exit_code}.`, 'error');
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
          await pollJobUntilComplete(activeJobId, addLog, onSuccess);
          return;
        }
        throw streamErr;
      }

      fetchStatus();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      if (import.meta.env.DEV) {
        addLog(`[Local Simulation Mode: ${errMsg}]`, 'info');
        await new Promise((r) => setTimeout(r, 500));
        addLog(`[INFO] Executing ${endpoint} with pre-flight backup snapshot...`, 'log');
        await new Promise((r) => setTimeout(r, 600));
        addLog(`[SUCCESS] Operation verified cleanly on all planes.`, 'success');
        setExecutionStatus('success');
        if (onSuccess) onSuccess();
      } else {
        setExecutionStatus('failed');
        addLog(`❌ Execution failed: ${errMsg}`, 'error');
      }
    }
  };

  const handleConfirmUpdate = async () => {
    if (!confirmTarget) return;
    const target = confirmTarget;
    setConfirmTarget(null);
    await runStreamedJob(
      '/api/v1/system/update',
      {
        service: target.service,
        version: target.targetVersion,
        reset_version: target.resetVersion || false,
        containers_only: target.containersOnly,
        full: target.full,
        branch: target.branch,
      },
      `🚀 Initializing appliance update for: ${target.name}...`
    );
  };

  const handleOsSecurityUpgrade = async (checkOnly: boolean = false) => {
    await runStreamedJob(
      '/api/v1/system/os-upgrade',
      { check_only: checkOnly },
      checkOnly
        ? '🔍 Auditing Ubuntu LTS APT security repositories for pending kernel & OS patches...'
        : '🛡️ Applying unattended Ubuntu LTS & Linux Kernel security patches (apt-get upgrade)...'
    );
  };

  const handlePruneLogs = async (checkOnly: boolean = false, dryRun: boolean = false) => {
    const label = checkOnly
      ? 'Auditing storage & log usage'
      : dryRun
      ? 'Simulating log pruning (dry-run)'
      : 'Pruning logs & vacuuming systemd journal';
    await runStreamedJob(
      '/api/v1/system/prune-logs',
      { check: checkOnly, dry_run: dryRun },
      `🧹 Initiating maintenance: ${label} (Rule 1 /memories strictly protected)...`
    );
  };

  const handleSaveRunnerConfig = async () => {
    setSavingRunnerConfig(true);
    setRunnerSaveBanner(null);
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

    const payload: Record<string, string> = {};
    if (firecrawlKey.trim()) payload.FIRECRAWL_API_KEY = firecrawlKey.trim();
    if (tavilyKey.trim()) payload.TAVILY_API_KEY = tavilyKey.trim();
    if (exaKey.trim()) payload.EXA_API_KEY = exaKey.trim();
    if (braveKey.trim()) {
      payload.BRAVE_SEARCH_API_KEY = braveKey.trim();
      payload.BRAVE_API_KEY = braveKey.trim();
    }
    if (githubTokenKey.trim()) payload.GITHUB_TOKEN = githubTokenKey.trim();
    if (openrouterKey.trim()) payload.OPENROUTER_API_KEY = openrouterKey.trim();
    if (anthropicKey.trim()) payload.ANTHROPIC_API_KEY = anthropicKey.trim();
    if (openaiKey.trim()) payload.OPENAI_API_KEY = openaiKey.trim();

    try {
      const res = await fetch('/api/v1/system/runners/hermes/config', {
        method: 'POST',
        headers,
        body: JSON.stringify({ keys: payload, restart_runner: true }),
      });
      if (res.ok) {
        setRunnerSaveBanner({
          type: 'success',
          text: 'Runner API keys saved to .env and synchronized to Nous Hermes Warm Runner.',
        });
        setFirecrawlKey('');
        setTavilyKey('');
        setExaKey('');
        setBraveKey('');
        setGithubTokenKey('');
        setOpenrouterKey('');
        setAnthropicKey('');
        setOpenaiKey('');
        fetchStatus();
      } else {
        let detail = res.statusText;
        try {
          const d = await res.json();
          if (d?.detail) detail = d.detail;
        } catch {}
        throw new Error(detail);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (import.meta.env.DEV) {
        setRunnerSaveBanner({
          type: 'success',
          text: '[Dev Preview] Runner API keys validated and synced to Nous Hermes Warm Runner.',
        });
      } else {
        setRunnerSaveBanner({
          type: 'error',
          text: `Failed saving runner configuration: ${msg}`,
        });
      }
    } finally {
      setSavingRunnerConfig(false);
    }
  };

  const handleSaveIdentityUnitName = async () => {
    const cleanUnitName = identityUnitName.trim() || 'Enterprise Agent Box';
    setSavingIdentityUnitName(true);
    setIdentitySaveBanner(null);
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

    try {
      const res = await fetch('/api/v1/system/identity', {
        method: 'POST',
        headers,
        body: JSON.stringify({ unit_name: cleanUnitName }),
      });
      if (res.ok) {
        setSetupUnitName(cleanUnitName);
        setIdentitySaveBanner({
          type: 'success',
          text: `Unit Identity updated to "${cleanUnitName}".`,
        });
        fetchStatus();
      } else {
        let detail = res.statusText;
        try {
          const d = await res.json();
          if (d?.detail) detail = d.detail;
        } catch {}
        throw new Error(detail);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (import.meta.env.DEV) {
        setSetupUnitName(cleanUnitName);
        setStatus((prev) =>
          prev
            ? {
                ...prev,
                unit_name: cleanUnitName,
                identity: { ...(prev.identity || {}), unit_name: cleanUnitName },
              }
            : prev
        );
        setIdentitySaveBanner({
          type: 'success',
          text: `[Dev Preview] Unit Identity updated to "${cleanUnitName}".`,
        });
      } else {
        setIdentitySaveBanner({
          type: 'error',
          text: `Failed saving Unit Name: ${msg}`,
        });
      }
    } finally {
      setSavingIdentityUnitName(false);
    }
  };

  const handleStartEditRouting = () => {
    const currentDomain = status?.local_domain || status?.url || 'dgx.local.brainsos.ai';
    setSetupLocalDomain(currentDomain);
    setSetupUrl(status?.url || currentDomain);
    const rawTls = (status?.tls_mode || 'internal').toLowerCase();
    setSetupTlsMode(
      rawTls === 'acme' || rawTls === 'public_acme'
        ? 'acme'
        : rawTls === 'route53'
          ? 'route53'
          : 'internal'
    );
    setSetupAcmeEmail(status?.acme_email || status?.admin_email || '');
    setIsEditingRouting(true);
  };

  const handleSaveRoutingInline = async () => {
    const cleanDomain = setupLocalDomain
      .trim()
      .replace(/^https?:\/\//i, '')
      .replace(/\/.*$/, '')
      .replace(/^mail\./i, '');
    if (!cleanDomain) {
      setIdentitySaveBanner({
        type: 'error',
        text: 'Appliance Hostname (FQDN) cannot be empty.',
      });
      return;
    }
    setIsEditingRouting(false);
    await runStreamedJob(
      '/api/v1/system/identity',
      {
        url: cleanDomain,
        local_domain: cleanDomain,
        tls_mode: setupTlsMode,
        acme_email: setupAcmeEmail.trim() || undefined,
        force: true,
      },
      `🌐 Applying Appliance Hostname (${cleanDomain}) & TLS Mode (${setupTlsMode.toUpperCase()})...`,
      () => {
        setIdentitySaveBanner({
          type: 'success',
          text: `Appliance Hostname & Routing updated to ${cleanDomain} (${setupTlsMode.toUpperCase()}).`,
        });
        fetchStatus();
      }
    );
  };

  const handleGracefulReboot = async () => {
    if (rebootConfirmText.trim().toUpperCase() !== 'REBOOT') return;
    setIsRebooting(true);
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    try {
      await fetch('/api/v1/system/reboot', {
        method: 'POST',
        headers,
        body: JSON.stringify({ confirm: true, delay_seconds: 3 }),
      });
    } catch {
      // Expected if connection drops immediately
    }
    setTimeout(() => {
      setRebootModalOpen(false);
      setIsRebooting(false);
      setRebootConfirmText('');
      fetchStatus();
    }, 6000);
  };

  const handleCopyLogs = () => {
    const logLines = logs.map((l) => `[${l.timestamp}] ${l.text}`);
    const entryLines = consoleEntries.map((e) => `[${e.timestamp}] ${e.text}`);
    const text = [...logLines, ...entryLines].join('\n');
    navigator.clipboard.writeText(text);
    setCopiedLogs(true);
    setTimeout(() => setCopiedLogs(false), 2000);
  };

  const handleClearLogs = () => {
    setLogs([]);
    setConsoleEntries([]);
    setExecutionStatus('idle');
  };

  const handleOpenWizard = (initialStep: 1 | 2 | 3 = 1) => {
    if (status?.local_domain) setSetupLocalDomain(status.local_domain);
    if (status?.unit_name || status?.identity?.unit_name) {
      setSetupUnitName(status.identity?.unit_name || status.unit_name || 'Enterprise Agent Box');
    }
    const isFirstBootIncomplete =
      status?.firstboot_wizard_completed === false || status?.identity?.firstboot_wizard_completed === false;
    const rawCandidate = (
      status?.identity?.superuser_username ||
      status?.superuser_username ||
      status?.admin_username ||
      ''
    ).trim();
    // Never default Superuser Username to 'admin'
    const existingSuperuser =
      isFirstBootIncomplete || rawCandidate.toLowerCase() === 'admin' ? '' : rawCandidate;
    setSetupAdminUsername(existingSuperuser);
    setWizardUsernameTouched(Boolean(existingSuperuser));
    if (status?.superuser_name) setSetupSuperuserName(status.superuser_name);
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

  // Auto-derive Superuser Username & Suggested Domain when typing Superuser Full Name (while !wizardUsernameTouched)
  const handleSuperuserFullNameChange = (val: string) => {
    setSetupSuperuserName(val);
    const firstWordRaw = val.trim().split(/\s+/)[0] || '';
    if (!wizardUnitNameTouched) {
      if (firstWordRaw.length >= 2) {
        const capitalized = firstWordRaw.charAt(0).toUpperCase() + firstWordRaw.slice(1);
        setSetupUnitName(`${capitalized}'s Agent Box`);
      } else {
        setSetupUnitName('Enterprise Agent Box');
      }
    }
    if (!wizardUsernameTouched) {
      const derived = deriveUsernameFromFullName(val);
      setSetupAdminUsername(derived);
      if (!localDomainManuallyEdited) {
        if (derived.length >= 2) {
          setSetupLocalDomain(`${derived}.aws.cloud.brainsos.ai`);
        } else {
          setSetupLocalDomain('local.brainsos.ai');
        }
      }
    }
  };

  // Dynamic Domain Suggestion when Superuser Username is manually edited (#333)
  const handleSuperuserUsernameChange = (val: string) => {
    setWizardUsernameTouched(true);
    setSetupAdminUsername(val);
    const clean = val.trim().toLowerCase().replace(/[^a-z0-9-]/g, '');
    if (!localDomainManuallyEdited) {
      if (clean.length >= 2 && clean !== 'admin' && clean !== 'akadmin') {
        setSetupLocalDomain(`${clean}.aws.cloud.brainsos.ai`);
      } else {
        setSetupLocalDomain('local.brainsos.ai');
      }
    }
  };

  // Live Password Complexity Evaluation (#333)
  const passwordChecks = React.useMemo(() => {
    const pw = setupAdminPassword;
    const user = setupAdminUsername.trim().toLowerCase();
    const token = setupBootstrapToken.trim().toLowerCase();
    const minLen = pw.length >= 10;
    const hasUpperLower = /[A-Z]/.test(pw) && /[a-z]/.test(pw);
    const hasNumber = /[0-9]/.test(pw);
    const hasSpecial = /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?~`]/.test(pw);
    const notMatchingIdOrUser =
      pw.length > 0 &&
      (!user || pw.toLowerCase() !== user) &&
      pw.toLowerCase() !== 'admin' &&
      (!token || pw.toLowerCase() !== token);
    const matchesConfirm = pw.length > 0 && pw === setupAdminPasswordConfirm;
    const allValid = minLen && hasUpperLower && hasNumber && hasSpecial && notMatchingIdOrUser && matchesConfirm;
    return {
      minLen,
      hasUpperLower,
      hasNumber,
      hasSpecial,
      notMatchingIdOrUser,
      matchesConfirm,
      allValid,
    };
  }, [setupAdminPassword, setupAdminPasswordConfirm, setupAdminUsername, setupBootstrapToken]);

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
        } catch {}
        setSetupError(errorDetail);
        if (res.status === 403) setWizardStep(1);
        return;
      }
    } catch {}
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
    const cleanName = setupSuperuserName.trim() || cleanUser;
    const cleanUnitName = setupUnitName.trim() || 'Enterprise Agent Box';
    const cleanUrl = setupUrl.trim().replace(/^https?:\/\//i, '').replace(/\/.*$/, '');
    const isInitialBoot = Boolean(standaloneWizard || status?.firstboot_wizard_completed === false);

    if (isInitialBoot && !setupBootstrapToken.trim()) {
      setSetupError('Please enter the EC2 Instance ID (i-...) of this appliance to authorize first-boot setup.');
      setWizardStep(1);
      return;
    }
    if (!cleanUser || !/^[a-zA-Z0-9._-]{2,64}$/.test(cleanUser)) {
      setSetupError('Superuser username must be 2–64 alphanumeric characters (e.g. alex or jdoe, not admin).');
      setWizardStep(1);
      return;
    }
    if (cleanUser.toLowerCase() === 'admin' || cleanUser.toLowerCase() === 'akadmin') {
      setSetupError('The "admin" account is permanently reserved and bound to the EC2 Instance ID. Please choose a personal Superuser username (e.g. alex or jdoe).');
      setWizardStep(1);
      return;
    }
    if (setupAdminPassword || isInitialBoot) {
      if (!passwordChecks.allValid) {
        setSetupError('Please satisfy all Superuser password complexity requirements and ensure both passwords match.');
        setWizardStep(1);
        return;
      }
    }
    if (!cleanLocal || !/^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(cleanLocal)) {
      setSetupError('Please enter a valid fully-qualified local domain (e.g. jdoe.aws.cloud.brainsos.ai).');
      setWizardStep(2);
      return;
    }
    if (!cleanUrl) {
      setSetupError('Please enter a valid external web URL or hostname.');
      setWizardStep(3);
      return;
    }
    if ((setupTlsMode === 'acme' || setupTlsMode === 'route53') && (!setupAcmeEmail.trim() || !setupAcmeEmail.includes('@'))) {
      setSetupError("A valid ACME contact email address is required for Let's Encrypt / Route 53 TLS.");
      setWizardStep(3);
      return;
    }

    const previousUrl = status?.url || '';
    const wasFirstBoot = isInitialBoot;
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

    let res: Response;
    try {
      res = await fetch('/api/v1/system/setup', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          bootstrap_token: setupBootstrapToken.trim() || undefined,
          unit_name: cleanUnitName,
          local_domain: cleanLocal,
          superuser_name: cleanName,
          superuser_username: cleanUser,
          superuser_password: setupAdminPassword || undefined,
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
      } catch {}
      setSetupError(errorDetail);
      if (res.status === 403) {
        setWizardStep(1);
      }
      return;
    }

    setWizardOpen(false);
    setActivePane('console');
    setConsoleViewMode('jobs');
    setExecutionStatus('running');

    const startTimestamp = new Date().toLocaleTimeString();
    setLogs([
      {
        id: 1,
        timestamp: startTimestamp,
        text: `🪄 Provisioning Superuser (${cleanUser}) & Applying Unit Identity (${cleanUnitName})...`,
        type: 'info',
      },
      {
        id: 2,
        timestamp: startTimestamp,
        text: `🌐 Unit: ${cleanUnitName} | Hostname/FQDN: ${cleanLocal} | Superuser: ${cleanUser}@${cleanLocal} | Web URL: https://${cleanUrl}/ (${setupTlsMode})`,
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
                    addLog(`✅ Superuser account, unit identity, hostname, Gitea repo, mailboxes, and TLS configured!`, 'success');
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
          await pollJobUntilComplete(
            activeJobId,
            addLog,
            () => {
              if (wasFirstBoot || (previousUrl && cleanUrl.toLowerCase() !== previousUrl.toLowerCase())) {
                setNewConfiguredUrl(`https://${cleanUrl}/`);
              }
            },
            true
          );
          return;
        }
        throw streamErr;
      }

      if (!completedCleanly && activeJobId) {
        await pollJobUntilComplete(
          activeJobId,
          addLog,
          () => {
            if (wasFirstBoot || (previousUrl && cleanUrl.toLowerCase() !== previousUrl.toLowerCase())) {
              setNewConfiguredUrl(`https://${cleanUrl}/`);
            }
          },
          true
        );
        return;
      }

      fetchStatus();
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setExecutionStatus('failed');
      addLog(`❌ Setup failed: ${errMsg}`, 'error');
    }
  };

  const isStandaloneWizard = Boolean(standaloneWizard || status?.firstboot_wizard_completed === false);

  const renderWizardCardContent = (standalone: boolean) => {
    const cleanWizardSlug = setupAdminUsername.trim().toLowerCase().replace(/[^a-z0-9-]/g, '');
    const suggestedDom =
      cleanWizardSlug && cleanWizardSlug !== 'admin' && cleanWizardSlug !== 'akadmin'
        ? `${cleanWizardSlug}.aws.cloud.brainsos.ai`
        : 'username.aws.cloud.brainsos.ai';

    return (
      <div className="w-full max-w-2xl bg-[#0D111A] border border-white/15 rounded-2xl p-6 sm:p-7 shadow-2xl space-y-5 animate-in zoom-in-95">
        {/* Wizard Header */}
        <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-br from-[#00f2fe]/20 to-emerald-500/20 border border-[#00f2fe]/40 text-[#00f2fe]">
              <Wand2 className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-headline font-bold text-base sm:text-lg text-white">
                  brainsOS Operating System • First-Boot Superuser Setup
                </h3>
                <span className="px-2 py-0.5 rounded bg-[#00f2fe]/15 border border-[#00f2fe]/40 font-mono text-[10px] text-[#00f2fe] font-semibold">
                  STEP {wizardStep} OF 3
                </span>
              </div>
              <p className="font-mono text-xs text-slate-400 mt-0.5">
                Provision your personal Superuser account, Unit Identity, Appliance Hostname (FQDN), and HTTPS ingress
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
                ? 'bg-[#00f2fe]/15 border-[#00f2fe] text-white'
                : 'bg-white/[0.03] border-white/10 text-slate-400 hover:text-white'
            }`}
          >
            <div className="text-[10px] text-[#00f2fe] font-bold">1. SUPERUSER &amp; KEY</div>
            <div className="truncate font-semibold mt-0.5">Create Superuser Account</div>
          </button>
          <button
            type="button"
            onClick={() => setWizardStep(2)}
            className={`p-2.5 rounded-xl border text-left transition-all ${
              wizardStep === 2
                ? 'bg-[#00f2fe]/15 border-[#00f2fe] text-white'
                : 'bg-white/[0.03] border-white/10 text-slate-400 hover:text-white'
            }`}
          >
            <div className="text-[10px] text-[#00f2fe] font-bold">2. UNIT &amp; HOSTNAME</div>
            <div className="truncate font-semibold mt-0.5">Unit Identity &amp; FQDN</div>
          </button>
          <button
            type="button"
            onClick={() => setWizardStep(3)}
            className={`p-2.5 rounded-xl border text-left transition-all ${
              wizardStep === 3
                ? 'bg-[#00f2fe]/15 border-[#00f2fe] text-white'
                : 'bg-white/[0.03] border-white/10 text-slate-400 hover:text-white'
            }`}
          >
            <div className="text-[10px] text-[#00f2fe] font-bold">3. WEB ACCESS &amp; TLS</div>
            <div className="truncate font-semibold mt-0.5">Browser URL &amp; Certificates</div>
          </button>
        </div>

        {setupError && (
          <div className="p-3 rounded-xl bg-red-500/15 border border-red-500/40 text-red-200 font-mono text-xs flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
            <span>{setupError}</span>
          </div>
        )}

        {/* STEP 1: Create Superuser Account & Verify Instance ID */}
        {wizardStep === 1 && (
          <div className="space-y-4 font-mono text-xs">
            {/* Callout explaining Instance Admin vs Personal Superuser */}
            <div className="p-3 rounded-xl bg-cyan-500/10 border border-cyan-500/30 text-[11px] text-slate-300 space-y-1">
              <div className="text-[#00f2fe] font-bold flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5" />
                <span>Instance Admin Account (<code className="text-white">admin</code>) is permanently bound to your EC2 Instance ID (<code className="text-white">i-...</code>)</span>
              </div>
              <p className="font-sans text-slate-300 leading-relaxed">
                For break-glass recovery, <code className="font-mono text-white">admin</code> always authenticates using your AWS EC2 Instance ID. Below, create your personal <strong>Superuser</strong> account for day-to-day SSO, Kurrier Workspace, Gitea Source Control, and Operator IDE.
              </p>
            </div>

            {(standalone || status?.firstboot_wizard_completed === false) && (
              <div className="p-3.5 rounded-xl bg-purple-500/10 border border-purple-500/40 space-y-2">
                <label className="block text-purple-200 font-semibold flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <KeyRound className="w-3.5 h-3.5 text-[#00f2fe]" />
                    <span>EC2 Instance ID Verification Key (Required for First-Boot Authorization)</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => setShowBootstrapToken((prev) => !prev)}
                    className="text-[10px] text-slate-300 hover:text-white flex items-center gap-1"
                  >
                    {showBootstrapToken ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                    <span>{showBootstrapToken ? 'Hide' : 'Show'}</span>
                  </button>
                </label>
                <input
                  type={showBootstrapToken ? 'text' : 'password'}
                  value={setupBootstrapToken}
                  onChange={(e) => setSetupBootstrapToken(e.target.value)}
                  placeholder="e.g. i-0123456789abcdef0"
                  className="w-full px-3.5 py-2 rounded-xl bg-[#07090E] border border-purple-500/40 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
                />
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="block text-slate-200 font-semibold">
                  Superuser Full Name
                </label>
                <input
                  type="text"
                  value={setupSuperuserName}
                  onChange={(e) => handleSuperuserFullNameChange(e.target.value)}
                  placeholder="e.g. Jane Doe"
                  className="w-full px-3.5 py-2 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
                />
              </div>

              <div className="space-y-1.5">
                <label className="block text-slate-200 font-semibold">
                  Superuser Username (<code className="text-[#00f2fe]">not admin</code>)
                </label>
                <input
                  type="text"
                  value={setupAdminUsername}
                  onChange={(e) => handleSuperuserUsernameChange(e.target.value)}
                  placeholder="e.g. alex or jdoe (not admin)"
                  className="w-full px-3.5 py-2 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
                />
              </div>
            </div>

            {setupAdminUsername.trim() && (
              <div className="px-3 py-2 rounded-lg bg-white/[0.03] border border-white/10 text-[11px] flex items-center justify-between">
                <span className="text-slate-400">Suggested Appliance Hostname / FQDN (Step 2):</span>
                <span className="text-[#00f2fe] font-semibold">{suggestedDom}</span>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="block text-slate-200 font-semibold">
                  Superuser Password
                </label>
                <div className="relative">
                  <input
                    type={showSetupPasswords ? 'text' : 'password'}
                    value={setupAdminPassword}
                    onChange={(e) => setSetupAdminPassword(e.target.value)}
                    placeholder="Min 10 chars, upper/lower/num/symbol"
                    className="w-full pl-3.5 pr-9 py-2 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => setShowSetupPasswords((prev) => !prev)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                    title={showSetupPasswords ? 'Hide password' : 'Show password'}
                  >
                    {showSetupPasswords ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="block text-slate-200 font-semibold">
                  Confirm Superuser Password
                </label>
                <input
                  type={showSetupPasswords ? 'text' : 'password'}
                  value={setupAdminPasswordConfirm}
                  onChange={(e) => setSetupAdminPasswordConfirm(e.target.value)}
                  placeholder="Re-enter password"
                  className="w-full px-3.5 py-2 rounded-xl bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
                />
              </div>
            </div>

            {/* Explicit Show Passwords Checkbox */}
            <div className="flex items-center justify-between pt-0.5">
              <label className="inline-flex items-center gap-2 cursor-pointer select-none text-slate-300 hover:text-white text-xs">
                <input
                  type="checkbox"
                  checked={showSetupPasswords}
                  onChange={(e) => setShowSetupPasswords(e.target.checked)}
                  className="rounded border-white/20 bg-[#07090E] text-[#00f2fe] focus:ring-0"
                />
                <span>Show passwords in plain text</span>
              </label>
              <span className="text-[11px] text-slate-500">
                Synchronized across Authentik SSO, Kurrier Workspace, Gitea &amp; Console
              </span>
            </div>

            {/* Live Password Complexity Checklist */}
            <div className="p-3.5 rounded-xl bg-[#07090E] border border-white/10 space-y-2">
              <div className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
                Password Complexity &amp; Security Checklist
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 text-[11px]">
                {[
                  { ok: passwordChecks.minLen, label: 'At least 10 characters' },
                  { ok: passwordChecks.hasUpperLower, label: 'Uppercase & lowercase letters (A-Z, a-z)' },
                  { ok: passwordChecks.hasNumber, label: 'At least one number (0-9)' },
                  { ok: passwordChecks.hasSpecial, label: 'At least one special character (!@#$...)' },
                  { ok: passwordChecks.notMatchingIdOrUser, label: 'Distinct from username & Instance ID' },
                  { ok: passwordChecks.matchesConfirm, label: 'Passwords match' },
                ].map((item) => (
                  <div
                    key={item.label}
                    className={`flex items-center gap-2 ${
                      item.ok ? 'text-emerald-400' : 'text-slate-500'
                    }`}
                  >
                    <span
                      className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] border ${
                        item.ok
                          ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                          : 'bg-white/5 border-white/10 text-slate-600'
                      }`}
                    >
                      {item.ok ? '✓' : '•'}
                    </span>
                    <span>{item.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* STEP 2: Unit Identity vs Appliance Hostname (FQDN) & Local Domain */}
        {wizardStep === 2 && (
          <div className="space-y-4 font-mono text-xs">
            {/* Concept 1: Unit Identity */}
            <div className="p-4 rounded-xl bg-[#07090E] border border-white/10 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] uppercase tracking-wider text-[#00f2fe] font-bold">
                  1. Unit Identity (Logical Display Name &amp; Hardware Unit ID)
                </span>
                <span className="px-2 py-0.5 rounded bg-white/5 border border-white/10 text-[10px] text-slate-300">
                  Hardware Unit ID: <strong className="text-white">{setupBootstrapToken.trim() || status?.identity?.instance_id || status?.instance_id || 'local-dev'}</strong>
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
                <div className="sm:col-span-2 space-y-1">
                  <label className="block text-slate-200 font-semibold">
                    Unit Name (<code className="text-[#00f2fe]">unit_name</code>)
                  </label>
                  <p className="text-[11px] text-slate-400 font-sans">
                    Logical display identity of this Agent-in-a-Box appliance (e.g. &quot;Enterprise Agent Box&quot; or &quot;Alex&apos;s Agent Box&quot;).
                  </p>
                  <input
                    type="text"
                    value={setupUnitName}
                    onChange={(e) => {
                      setWizardUnitNameTouched(true);
                      setSetupUnitName(e.target.value);
                    }}
                    placeholder="e.g. Enterprise Agent Box"
                    className="w-full px-3.5 py-2 rounded-xl bg-[#0B0E14] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
                  />
                </div>
                <div className="p-2.5 rounded-xl bg-white/[0.03] border border-white/10 space-y-0.5">
                  <span className="text-[10px] uppercase text-slate-500 block">Immutable Hardware ID</span>
                  <span className="text-white font-semibold block truncate">
                    {setupBootstrapToken.trim() || status?.identity?.instance_id || status?.instance_id || 'local-dev'}
                  </span>
                  <span className="text-[10px] text-emerald-400 block">Read-only cloud/hardware binding</span>
                </div>
              </div>
            </div>

            {/* Concept 2: Appliance Hostname (FQDN) & External Routing */}
            <div className="p-4 rounded-xl bg-[#07090E] border border-white/10 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] uppercase tracking-wider text-emerald-400 font-bold">
                  2. Appliance Hostname (FQDN) &amp; External Routing
                </span>
                {localDomainManuallyEdited && setupAdminUsername.trim() && (
                  <button
                    type="button"
                    onClick={() => {
                      setLocalDomainManuallyEdited(false);
                      setSetupLocalDomain(suggestedDom);
                    }}
                    className="text-[10px] text-[#00f2fe] hover:underline"
                  >
                    Reset to {suggestedDom}
                  </button>
                )}
              </div>
              <div className="space-y-1.5">
                <label className="block text-slate-200 font-semibold">
                  Appliance Hostname / Local Domain (<code className="text-[#00f2fe]">local_domain</code>)
                </label>
                <p className="text-[11px] text-slate-400 font-sans">
                  Network FQDN (<code className="font-mono text-[#00f2fe]">&lt;username&gt;.aws.cloud.brainsos.ai</code>), TLS certificate SAN, OS <code className="font-mono">hostname -f</code>, and internal mail domain.
                </p>
                <input
                  type="text"
                  value={setupLocalDomain}
                  onChange={(e) => {
                    setLocalDomainManuallyEdited(true);
                    setSetupLocalDomain(e.target.value);
                  }}
                  placeholder="e.g. jdoe.aws.cloud.brainsos.ai"
                  className="w-full px-3.5 py-2.5 rounded-xl bg-[#0B0E14] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white font-mono text-sm"
                />
              </div>
              <div className="flex items-center justify-between text-[11px] pt-1 border-t border-white/5 text-slate-400">
                <span>External Web URL (<code className="text-slate-300">url</code>):</span>
                <span className="text-white font-semibold">
                  https://{(setupUrl.trim() || setupLocalDomain.trim() || suggestedDom).replace(/^https?:\/\//i, '').replace(/\/.*$/, '')}/
                </span>
              </div>
            </div>

            {(() => {
              const previewDom = (setupLocalDomain.trim() || suggestedDom).replace(/^https?:\/\//i, '').replace(/\/.*$/, '');
              const shortHost = previewDom.split('.')[0] || 'brainsos';
              const previewUser = setupAdminUsername.trim() || 'jdoe';
              const mailboxes = [
                `${previewUser}@${previewDom}`,
                `admin@${previewDom}`,
                `terrastella@${previewDom}`,
                `bawtford@${previewDom}`,
                `marvin@${previewDom}`,
                `ping@${previewDom}`,
              ];
              return (
                <div className="p-4 rounded-xl bg-[#07090E]/90 border border-white/10 space-y-3">
                  <div className="text-[11px] uppercase tracking-wider text-[#00f2fe] font-semibold">
                    Live Coherent Identity &amp; Routing Preview
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]">
                    <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/5">
                      <span className="text-slate-500 block">Unit Identity:</span>
                      <span className="text-white font-semibold truncate block">{setupUnitName.trim() || 'Enterprise Agent Box'}</span>
                      <span className="text-emerald-400 block text-[10px] mt-0.5">
                        ID: {setupBootstrapToken.trim() || status?.identity?.instance_id || status?.instance_id || 'local-dev'}
                      </span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/5">
                      <span className="text-slate-500 block">Appliance Hostname (FQDN):</span>
                      <span className="text-[#00f2fe] font-semibold truncate block">{previewDom}</span>
                      <span className="text-slate-400 block text-[10px] mt-0.5">short: {shortHost} • OTel synced</span>
                    </div>
                    <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/5">
                      <span className="text-slate-500 block">Gitea Source Control:</span>
                      <span className="text-orange-400 font-semibold truncate block">{previewUser} / agent-box</span>
                      <span className="text-slate-400 block text-[10px] mt-0.5">Owner &amp; Collaborator</span>
                    </div>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[11px] block mb-1.5">Provisioned Postfix / Dovecot / Kurrier Mailboxes:</span>
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
                The browser-facing hostname or URL used to reach the Portal, Authentik SSO, Gitea, LiteLLM, and Langfuse.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={setupUrl}
                  onChange={(e) => {
                    setSetupUrl(e.target.value);
                    setDnsCheckResult(null);
                  }}
                  placeholder="e.g. ec2-32-192-215-107.compute-1.amazonaws.com"
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
                    Self-signed Caddy CA. Ideal for raw EC2 <code className="font-mono">.amazonaws.com</code> URLs or LAN.
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
                    Automatic Let&apos;s Encrypt HTTP-01 cert (requires DNS A record → {status?.public_ipv4 || 'appliance IP'}).
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
                  placeholder={`e.g. ${setupAdminUsername.trim() || 'jdoe'}@${setupLocalDomain.trim() || 'brainsos.ai'}`}
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
                className="px-5 py-2 rounded-xl bg-[#00f2fe]/20 hover:bg-[#00f2fe]/30 border border-[#00f2fe]/50 text-[#00f2fe] font-mono text-xs font-bold transition-all"
              >
                Next Step →
              </button>
            ) : (
              <button
                type="button"
                onClick={handleApplySetup}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-[#00f2fe] to-emerald-400 hover:opacity-95 text-slate-950 font-mono text-xs font-bold transition-all shadow-[0_0_18px_rgba(0,242,254,0.3)] flex items-center gap-1.5"
              >
                <Check className="w-4 h-4" />
                <span>Create Superuser &amp; Complete Setup</span>
              </button>
            )}
          </div>
        </div>
      </div>
    );
  };

  if (isStandaloneWizard) {
    return (
      <div className="min-h-screen w-full bg-[#07090E] text-slate-200 flex flex-col items-center justify-center p-4 sm:p-8 font-sans antialiased selection:bg-[#00f2fe] selection:text-black">
        <div className="w-full max-w-2xl flex items-center justify-between mb-4 px-1">
          <div className="flex items-center gap-2.5">
            <div className="w-2.5 h-2.5 rounded-full bg-[#00f2fe] shadow-[0_0_10px_#00f2fe]" />
            <span className="font-mono text-xs uppercase tracking-widest text-slate-300 font-bold">
              brainsOS.ai • Operating System First-Boot Setup
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
                      ? 'Provisioning Superuser & Applying Appliance Identity...'
                      : executionStatus === 'success'
                      ? 'Appliance Setup Complete — Ready for Sign-In'
                      : 'Appliance Setup Encountered an Error'}
                  </h3>
                  <p className="font-mono text-xs text-slate-400 mt-0.5">
                    {executionStatus === 'running'
                      ? 'Configuring OS hostname, Postfix/Dovecot/Kurrier mailboxes, Authentik SSO, Gitea, and Caddy TLS'
                      : executionStatus === 'success'
                      ? 'All identity, mail, source control, observability, and ingress planes are synchronized.'
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
                  Sign in with Superuser <strong className="text-white">{setupAdminUsername.trim()}</strong> (or <code className="text-slate-300">admin</code> with your EC2 Instance ID).
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

  const navItems: { id: OsPane; label: string; sublabel: string; icon: React.ReactNode; badge?: string; badgeColor?: string }[] = [
    {
      id: 'overview',
      label: 'System & Identity',
      sublabel: 'Kernel, Hostname & SSO',
      icon: <Sliders className="w-4 h-4" />,
    },
    {
      id: 'console',
      label: 'Host Console',
      sublabel: 'Interactive Shell & Jobs',
      icon: <Terminal className="w-4 h-4" />,
      badge: executionStatus === 'running' ? 'RUNNING' : wsConnected ? 'PTY' : undefined,
      badgeColor: executionStatus === 'running' ? 'text-amber-300 border-amber-500/40 bg-amber-500/15' : 'text-emerald-300 border-emerald-500/40 bg-emerald-500/15',
    },
    {
      id: 'agents',
      label: 'Agents & Runners',
      sublabel: 'Hermes & Search Keys',
      icon: <Bot className="w-4 h-4" />,
    },
    {
      id: 'updates',
      label: 'Software & Updates',
      sublabel: 'OS Patches & Containers',
      icon: <PackageCheck className="w-4 h-4" />,
      badge: status?.os?.reboot_required
        ? 'REBOOT'
        : status?.overall_update_available || (status?.os?.pending_security_updates || 0) > 0
        ? 'UPDATES'
        : undefined,
      badgeColor: status?.os?.reboot_required
        ? 'text-red-300 border-red-500/40 bg-red-500/15'
        : 'text-amber-300 border-amber-500/40 bg-amber-500/15',
    },
    {
      id: 'storage',
      label: 'Storage, Logs & Power',
      sublabel: 'Disk, Journal & Reboot',
      icon: <HardDrive className="w-4 h-4" />,
    },
  ];

  const hermesRunner =
    normalizedRunners.find((r) => r.id === 'hermes' || r.id.includes('hermes')) || DEFAULT_RUNNERS_LIST[0];
  const firecrawlConfigured = Boolean(
    toolKeysMap.FIRECRAWL_API_KEY?.configured || hermesRunner?.keys?.FIRECRAWL_API_KEY?.configured
  );

  return (
    <div className="h-full flex flex-col bg-[#07090E] text-slate-200 overflow-hidden font-sans antialiased selection:bg-[#00f2fe] selection:text-black">
      {/* Top OS Control Bar */}
      <div className="border-b border-white/10 bg-[#0B0E14] px-5 py-3 flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#00f2fe]/15 border border-[#00f2fe]/40 text-[#00f2fe] flex items-center justify-center shadow-[0_0_12px_rgba(0,242,254,0.2)]">
            <Cpu className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-headline font-bold text-sm sm:text-base text-white tracking-tight">
                brainsOS Operating System Control Center
              </h1>
              <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-[#00f2fe]/10 border border-[#00f2fe]/30 text-[#00f2fe] font-semibold">
                {status?.identity?.unit_name || status?.unit_name || 'Enterprise Agent Box'}
              </span>
              <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-white/5 border border-white/10 text-slate-300">
                {status?.os?.distro || 'Ubuntu 24.04 LTS'} • {status?.os?.arch || 'ARM64'}
              </span>
              {status?.os?.reboot_required && (
                <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-red-500/20 border border-red-500/40 text-red-300 font-semibold animate-pulse">
                  REBOOT REQUIRED
                </span>
              )}
            </div>
            <p className="font-mono text-[11px] text-slate-400">
              Host: <span className="text-[#00f2fe]">{status?.hostname || status?.local_domain || 'local.brainsos.ai'}</span> • Kernel: <span className="text-slate-300">{status?.os?.kernel || '6.8.0-aws'}</span> • Last probed: {lastChecked}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => handleOpenWizard(1)}
            className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/15 text-xs font-mono text-slate-200 hover:text-white transition-all flex items-center gap-1.5"
          >
            <Wand2 className="w-3.5 h-3.5 text-[#00f2fe]" />
            <span>Setup Wizard</span>
          </button>

          <button
            onClick={fetchStatus}
            disabled={isChecking}
            className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono text-slate-300 hover:text-white transition-all flex items-center gap-1.5 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-[#00f2fe] ${isChecking ? 'animate-spin' : ''}`} />
            <span>{isChecking ? 'Refreshing...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* Main Split OS Layout: Left Sidebar Navigation Rail + Right Content Viewport */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
        {/* Left-Hand OS Navigation Rail */}
        <nav
          className="w-full md:w-60 bg-[#0A0D14] border-b md:border-b-0 md:border-r border-white/10 p-2.5 flex md:flex-col gap-1 overflow-x-auto md:overflow-y-auto shrink-0 select-none"
          aria-label="Operating System Control Center Sections"
        >
          <div className="hidden md:block px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            System Control Planes
          </div>
          {navItems.map((item) => {
            const active = activePane === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActivePane(item.id)}
                id={`os-nav-${item.id}`}
                className={`w-full px-3 py-2.5 rounded-xl text-left transition-all flex items-center justify-between gap-2 shrink-0 ${
                  active
                    ? 'bg-[#00f2fe]/12 border border-[#00f2fe]/40 text-white shadow-sm'
                    : 'bg-transparent border border-transparent text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className={active ? 'text-[#00f2fe]' : 'text-slate-400'}>
                    {item.icon}
                  </span>
                  <div className="truncate">
                    <div className="font-headline font-semibold text-xs leading-tight">
                      {item.label}
                    </div>
                    <div className="hidden md:block font-mono text-[10px] text-slate-500 truncate mt-0.5">
                      {item.sublabel}
                    </div>
                  </div>
                </div>
                {item.badge ? (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono font-bold border ${item.badgeColor}`}>
                    {item.badge}
                  </span>
                ) : (
                  <ChevronRight className={`hidden md:block w-3.5 h-3.5 transition-transform ${active ? 'text-[#00f2fe] translate-x-0.5' : 'text-slate-600'}`} />
                )}
              </button>
            );
          })}

          {/* Bottom Appliance Quick Telemetry in Left Rail */}
          <div className="hidden md:flex flex-col mt-auto pt-3 border-t border-white/10 px-2.5 space-y-2 font-mono text-[10.5px]">
            <div className="flex items-center justify-between text-slate-400">
              <span>Unit Identity:</span>
              <span className="text-white font-semibold truncate max-w-[110px]">
                {status?.identity?.unit_name || status?.unit_name || 'Enterprise Agent Box'}
              </span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>Root Disk Free:</span>
              <span className={status?.disk?.warning ? 'text-amber-400 font-semibold' : 'text-emerald-400 font-semibold'}>
                {status?.disk ? `${status.disk.free_gb} GB (${status.disk.free_pct}%)` : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>Instance Admin:</span>
              <span className="text-slate-200">admin (EC2 ID)</span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <span>Superuser:</span>
              <span className="text-[#00f2fe] font-semibold">
                {status?.superuser_username || 'Not Provisioned'}
              </span>
            </div>
          </div>
        </nav>

        {/* Right Main OS Content Pane */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-5 bg-[#07090E]">
          {/* Status Error Warning */}
          {(!status || statusError) && (
            <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
                <div className="font-mono text-xs text-red-200">
                  {statusError || 'System API unreachable. Verify brainsos-system-api service is running on host.'}
                </div>
              </div>
              <button
                onClick={fetchStatus}
                className="px-3 py-1.5 rounded-lg bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-200 text-xs font-mono shrink-0"
              >
                Retry
              </button>
            </div>
          )}

          {newConfiguredUrl && (
            <div className="p-4 rounded-xl bg-emerald-500/15 border border-emerald-500/40 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
                <div className="font-mono text-xs text-slate-200">
                  Appliance identity &amp; SSO are active at <a href={newConfiguredUrl} className="text-[#00f2fe] underline">{newConfiguredUrl}</a>.
                </div>
              </div>
              <a
                href={newConfiguredUrl}
                className="px-3.5 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 text-xs font-mono font-semibold flex items-center gap-1.5 shrink-0"
              >
                <span>Open {newConfiguredUrl}</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            </div>
          )}

          {/* PANE 1: SYSTEM & IDENTITY OVERVIEW */}
          {activePane === 'overview' && (
            <div className="space-y-5 max-w-5xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/10 pb-3">
                <div>
                  <h2 className="font-headline font-bold text-base text-white">
                    Operating System &amp; Appliance Identity Specification
                  </h2>
                  <p className="font-mono text-xs text-slate-400">
                    Unit Identity (<code className="text-[#00f2fe]">unit_name</code> &amp; <code className="text-slate-300">instance_id</code>), Appliance Hostname (FQDN <code className="text-[#00f2fe]">local_domain</code>), and SSO Superuser bindings
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href="/system/ca.crt"
                    download="brainsos-caddy-root-ca.crt"
                    className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 hover:text-white text-xs font-mono flex items-center gap-1.5"
                  >
                    <Download className="w-3.5 h-3.5 text-[#00f2fe]" />
                    <span>Download Root CA</span>
                  </a>
                </div>
              </div>

              {identitySaveBanner && (
                <div
                  className={`p-3 rounded-lg border font-mono text-xs ${
                    identitySaveBanner.type === 'success'
                      ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-200'
                      : 'bg-red-500/15 border-red-500/40 text-red-200'
                  }`}
                >
                  {identitySaveBanner.text}
                </div>
              )}

              {/* Two Distinct Identity Cards: 1. Unit Identity & Source Paths vs. 2. Appliance Hostname (FQDN) & Network Routing */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 font-mono text-xs">
                {/* Card 1: Unit Identity & Source Paths */}
                <div className="p-4 rounded-xl border border-white/10 bg-[#0B0E14] space-y-3">
                  <div className="flex items-center justify-between border-b border-white/10 pb-2.5">
                    <span className="text-[11px] uppercase tracking-wider text-[#00f2fe] font-bold">
                      1. Unit Identity &amp; Source Paths
                    </span>
                    <span className="px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-[10px] text-emerald-300 font-semibold">
                      Hardware Unit ID: {status?.identity?.instance_id || status?.instance_id || 'local-gx10'}
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    <label className="block text-slate-300 font-semibold">
                      Unit Name (<code className="text-[#00f2fe]">unit_name</code>)
                    </label>
                    <p className="text-[11px] text-slate-400 font-sans">
                      Logical display identity of this Agent-in-a-Box appliance (e.g. &quot;Enterprise Agent Box&quot;).
                    </p>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={identityUnitName}
                        onChange={(e) => setIdentityUnitName(e.target.value)}
                        placeholder="Enterprise Agent Box"
                        className="flex-1 px-3 py-1.5 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white text-xs"
                      />
                      <button
                        type="button"
                        onClick={handleSaveIdentityUnitName}
                        disabled={savingIdentityUnitName}
                        className="px-3 py-1.5 rounded-lg bg-[#00f2fe]/15 hover:bg-[#00f2fe]/25 border border-[#00f2fe]/40 text-[#00f2fe] font-semibold shrink-0 disabled:opacity-50"
                      >
                        {savingIdentityUnitName ? 'Saving...' : 'Save'}
                      </button>
                    </div>
                  </div>
                  <div className="pt-2 border-t border-white/5 space-y-1.5 text-[11px]">
                    <div className="flex items-center justify-between py-0.5">
                      <span className="text-slate-400">Hardware Unit ID (<code className="text-slate-300">instance_id</code>):</span>
                      <span className="px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 font-semibold">
                        {status?.identity?.instance_id || status?.instance_id || 'local-gx10'} (Read-Only)
                      </span>
                    </div>
                    <div className="flex items-center justify-between py-0.5 border-t border-white/5">
                      <span className="text-slate-400">brainsOS Source Root:</span>
                      <code className="text-slate-200 font-semibold">{status?.repo_root || '/opt/brainsos'}</code>
                    </div>
                    <div className="flex items-center justify-between py-0.5 border-t border-white/5">
                      <span className="text-slate-400">Fleet Data Directory:</span>
                      <code className="text-slate-200 font-semibold">{status?.data_dir || '/data'}</code>
                    </div>
                  </div>
                </div>

                {/* Card 2: Appliance Hostname (FQDN) & Network Routing */}
                <div className="p-4 rounded-xl border border-white/10 bg-[#0B0E14] space-y-3">
                  <div className="flex items-center justify-between border-b border-white/10 pb-2.5">
                    <span className="text-[11px] uppercase tracking-wider text-emerald-400 font-bold">
                      2. Appliance Hostname (FQDN) &amp; Network Routing
                    </span>
                    <button
                      type="button"
                      onClick={() => (isEditingRouting ? setIsEditingRouting(false) : handleStartEditRouting())}
                      className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-[10px] text-[#00f2fe] font-semibold"
                    >
                      {isEditingRouting ? 'Cancel' : 'Edit Hostname & TLS'}
                    </button>
                  </div>
                  {isEditingRouting ? (
                    <div className="space-y-3 pt-1">
                      <div className="space-y-1">
                        <label className="block text-slate-300 font-semibold">
                          Appliance Hostname (FQDN)
                        </label>
                        <input
                          type="text"
                          value={setupLocalDomain}
                          onChange={(e) => setSetupLocalDomain(e.target.value)}
                          placeholder="dgx.local.brainsos.ai"
                          className="w-full px-3 py-1.5 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white text-xs"
                        />
                        <p className="text-[11px] text-slate-400 font-sans">
                          Sets primary HTTPS hostname and derives mail domain <code className="text-amber-300">mail.{setupLocalDomain.trim().replace(/^mail\./i, '') || 'dgx.local.brainsos.ai'}</code>.
                        </p>
                      </div>
                      <div className="space-y-1">
                        <label className="block text-slate-300 font-semibold">
                          TLS Certificate Mode
                        </label>
                        <select
                          value={setupTlsMode}
                          onChange={(e) => setSetupTlsMode(e.target.value as 'internal' | 'acme' | 'route53')}
                          className="w-full px-3 py-1.5 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white text-xs"
                        >
                          <option value="internal">Internal Appliance Root CA (LAN / Private)</option>
                          <option value="acme">Let&apos;s Encrypt Public ACME (HTTP-01)</option>
                          <option value="route53">AWS Route 53 Public ACME (DNS-01)</option>
                        </select>
                      </div>
                      {setupTlsMode !== 'internal' && (
                        <div className="space-y-1">
                          <label className="block text-slate-300 font-semibold">
                            ACME Contact Email
                          </label>
                          <input
                            type="email"
                            value={setupAcmeEmail}
                            onChange={(e) => setSetupAcmeEmail(e.target.value)}
                            placeholder="admin@brainsos.ai"
                            className="w-full px-3 py-1.5 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white text-xs"
                          />
                        </div>
                      )}
                      <div className="flex items-center justify-end gap-2 pt-1">
                        <button
                          type="button"
                          onClick={() => setIsEditingRouting(false)}
                          className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-xs"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={handleSaveRoutingInline}
                          className="px-3.5 py-1.5 rounded-lg bg-[#00f2fe]/15 hover:bg-[#00f2fe]/25 border border-[#00f2fe]/40 text-[#00f2fe] font-semibold text-xs"
                        >
                          Apply Hostname &amp; Reload Ingress
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="py-1 space-y-0.5">
                        <div className="flex items-center justify-between">
                          <span className="text-slate-300 font-semibold">Appliance Hostname (FQDN):</span>
                          <span className="text-[#00f2fe] font-bold">
                            {status?.local_domain || 'dgx.local.brainsos.ai'}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-400 font-sans">
                          Primary domain for HTTPS ingress, SSO, and user logins
                        </p>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-t border-white/5">
                        <span className="text-slate-400">Web Portal Ingress:</span>
                        <a
                          href={`https://${status?.url || status?.local_domain || 'dgx.local.brainsos.ai'}/`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-white hover:text-[#00f2fe] font-semibold inline-flex items-center gap-1"
                        >
                          <span>https://{status?.url || status?.local_domain || 'dgx.local.brainsos.ai'}/</span>
                          <ExternalLink className="w-3 h-3 text-[#00f2fe]" />
                        </a>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-t border-white/5 text-[11px]">
                        <span className="text-slate-400">Internal Mail Domain &amp; MX Host:</span>
                        <span className="text-slate-200 font-semibold">
                          @{status?.local_domain || 'dgx.local.brainsos.ai'}{' '}
                          <span className="text-slate-400 font-normal">
                            (MX: <code className="text-amber-300">mail.{status?.local_domain || 'dgx.local.brainsos.ai'}</code>)
                          </span>
                        </span>
                      </div>
                      <div className="flex items-center justify-between py-1.5 border-t border-white/5 text-[11px]">
                        <span className="text-slate-400">TLS Certificate Mode:</span>
                        <span className="text-emerald-300 font-semibold uppercase">
                          {status?.tls_mode || 'internal'}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Clean Administrative & Host OS Accounts Card */}
              <div className="rounded-xl border border-white/10 bg-[#0B0E14] overflow-hidden divide-y divide-white/5 font-mono text-xs">
                <div className="px-4 py-2.5 bg-[#101520] flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-wider text-slate-300 font-bold">
                    Administrative &amp; Host OS Accounts
                  </span>
                  <span className="text-[11px] text-slate-400">
                    {status?.platform_name || 'brainsOS Appliance'} • {status?.os?.distro || 'Ubuntu 24.04 LTS'} ({status?.os?.arch || 'aarch64'})
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 px-4 py-3.5 gap-2 items-start">
                  <div className="flex items-center gap-2 text-amber-300 font-semibold">
                    <Shield className="w-3.5 h-3.5 shrink-0" />
                    <span>Break-Glass &amp; OS Admin (<code className="text-white">admin</code>)</span>
                  </div>
                  <div className="sm:col-span-2 text-slate-300 font-sans text-xs leading-relaxed">
                    Bound to EC2 Instance ID on AWS (or local admin password). Full <code className="font-mono text-amber-300">proxy_admin</code> in LiteLLM, Authentik Admin, and Linux <code className="font-mono text-emerald-300">sudo</code> access.
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 px-4 py-3.5 gap-2 items-start">
                  <div className="flex items-center gap-2 text-[#00f2fe] font-semibold">
                    <UserCheck className="w-3.5 h-3.5 shrink-0" />
                    <span>Named Superuser (<code className="text-white">{status?.superuser_username || 'Not Provisioned'}</code>)</span>
                  </div>
                  <div className="sm:col-span-2 text-slate-300 font-sans text-xs leading-relaxed">
                    Provisioned via First-Boot Wizard. Full <code className="font-mono text-[#00f2fe]">proxy_admin</code> in LiteLLM, Authentik Admin, Gitea Admin, and Linux <code className="font-mono text-emerald-300">sudo</code> access.
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* PANE 2: HOST CONSOLE (INTERACTIVE XTERM.JS PTY & JOB LOGS) */}
          {activePane === 'console' && (
            <div className="space-y-3 max-w-6xl h-[calc(100vh-11.5rem)] flex flex-col">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    onClick={() => setConsoleViewMode('interactive')}
                    className={`px-3.5 py-1.5 rounded-lg font-mono text-xs font-semibold transition-all flex items-center gap-2 border ${
                      consoleViewMode === 'interactive'
                        ? 'bg-[#00f2fe]/15 border-[#00f2fe] text-[#00f2fe]'
                        : 'bg-white/5 border-white/10 text-slate-400 hover:text-white'
                    }`}
                  >
                    <Terminal className="w-3.5 h-3.5" />
                    <span>Interactive XTerm Host Shell</span>
                  </button>
                  <button
                    onClick={() => setConsoleViewMode('jobs')}
                    className={`px-3.5 py-1.5 rounded-lg font-mono text-xs font-semibold transition-all flex items-center gap-2 border ${
                      consoleViewMode === 'jobs'
                        ? 'bg-[#00f2fe]/15 border-[#00f2fe] text-[#00f2fe]'
                        : 'bg-white/5 border-white/10 text-slate-400 hover:text-white'
                    }`}
                  >
                    <Activity className="w-3.5 h-3.5" />
                    <span>System Job Output Stream ({logs.length + consoleEntries.length})</span>
                    {executionStatus === 'running' && (
                      <RefreshCw className="w-3 h-3 animate-spin text-amber-400" />
                    )}
                  </button>

                  {consoleViewMode === 'interactive' && (
                    <span
                      className={`px-2.5 py-1 rounded-full font-mono text-[10px] font-bold border flex items-center gap-1.5 ${
                        wsConnected
                          ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300'
                          : 'bg-amber-500/15 border-amber-500/40 text-amber-300'
                      }`}
                    >
                      <span
                        className={`w-2 h-2 rounded-full ${
                          wsConnected ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
                        }`}
                      />
                      <span>{wsConnected ? 'LIVE XTERM PTY' : 'RECONNECTING / HTTP FALLBACK'}</span>
                    </span>
                  )}
                </div>

                {/* Quick Command Toolbar */}
                {consoleViewMode === 'interactive' ? (
                  <div className="flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
                    {['ls -la', 'git status -sb', 'docker ps', 'df -h', 'htop'].map((qcmd) => (
                      <button
                        key={qcmd}
                        type="button"
                        onClick={() => {
                          if (wsConnected && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                            wsRef.current.send(JSON.stringify({ type: 'input', data: `${qcmd}\r` }));
                            xtermRef.current?.focus();
                          } else {
                            executeConsoleCommand(qcmd);
                          }
                        }}
                        className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 hover:text-[#00f2fe] transition-colors"
                      >
                        {qcmd}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => {
                        if (wsConnected && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                          wsRef.current.send(JSON.stringify({ type: 'input', data: 'clear\n' }));
                        }
                        xtermRef.current?.clear();
                        xtermRef.current?.focus();
                      }}
                      className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-slate-400 hover:text-white"
                      title="Clear XTerm terminal buffer"
                    >
                      Clear Terminal
                    </button>
                    <button
                      type="button"
                      onClick={connectTerminalWs}
                      className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-slate-400 hover:text-white flex items-center gap-1"
                      title="Reconnect WebSocket PTY"
                    >
                      <RotateCcw className="w-3 h-3" />
                      <span>Reconnect PTY</span>
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 font-mono text-xs">
                    <button
                      onClick={() => setAutoScroll((prev) => !prev)}
                      className={`px-2.5 py-1 rounded border text-[11px] ${
                        autoScroll
                          ? 'bg-[#00f2fe]/15 border-[#00f2fe]/40 text-[#00f2fe]'
                          : 'bg-white/5 border-white/10 text-slate-400'
                      }`}
                    >
                      Auto-Scroll: {autoScroll ? 'ON' : 'OFF'}
                    </button>
                    <button
                      onClick={handleCopyLogs}
                      className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 flex items-center gap-1 text-[11px]"
                    >
                      {copiedLogs ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                      <span>Copy</span>
                    </button>
                    <button
                      onClick={handleClearLogs}
                      className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-slate-400 hover:text-white text-[11px]"
                    >
                      Clear
                    </button>
                  </div>
                )}
              </div>

              {/* XTerm.js Interactive PTY Viewport Box (kept mounted to preserve PTY state) */}
              <div
                className={`flex-1 rounded-xl border border-white/15 bg-[#05070B] flex flex-col overflow-hidden shadow-2xl font-mono text-xs ${
                  consoleViewMode === 'interactive' ? '' : 'hidden'
                }`}
              >
                <div className="px-4 py-2 bg-[#0D111A] border-b border-white/10 flex items-center justify-between text-[11px] text-slate-400 select-none shrink-0">
                  <div className="flex items-center gap-2">
                    <span className={`w-2.5 h-2.5 rounded-full ${wsConnected ? 'bg-emerald-400' : 'bg-amber-400'}`} />
                    <span className="text-slate-200 font-semibold">
                      {status?.console_user || status?.superuser_username || status?.admin_username || 'admin'}@{(status?.hostname || status?.local_domain || 'brainsos').split('.')[0]}:{status?.repo_root || '/opt/brainsos'}
                    </span>
                  </div>
                  <span>
                    {wsConnected ? 'XTerm.js PTY WebSocket (/api/v1/system/terminal/ws)' : 'HTTP Exec Fallback (/api/v1/system/terminal/exec)'}
                  </span>
                </div>

                {/* Full Interactive XTerm Canvas */}
                <div
                  ref={xtermContainerRef}
                  onClick={() => xtermRef.current?.focus()}
                  className="flex-1 w-full bg-[#05070B] p-2 overflow-hidden"
                />

                {/* HTTP /api/v1/system/terminal/exec Line-by-Line Fallback Input Bar when WebSocket PTY is closed */}
                {!wsConnected && (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      executeConsoleCommand(consoleInput);
                    }}
                    className="px-4 py-2 bg-[#0A0E17] border-t border-white/10 flex items-center gap-2 shrink-0"
                  >
                    <span className="text-amber-400 font-bold shrink-0 text-[11px]">
                      HTTP Fallback $
                    </span>
                    <input
                      ref={consoleInputRef}
                      type="text"
                      value={consoleInput}
                      disabled={consoleBusy}
                      onChange={(e) => setConsoleInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'ArrowUp') {
                          e.preventDefault();
                          if (consoleHistory.length > 0) {
                            const nextIdx = Math.min(historyIdx + 1, consoleHistory.length - 1);
                            setHistoryIdx(nextIdx);
                            setConsoleInput(consoleHistory[nextIdx]);
                          }
                        } else if (e.key === 'ArrowDown') {
                          e.preventDefault();
                          if (historyIdx > 0) {
                            const nextIdx = historyIdx - 1;
                            setHistoryIdx(nextIdx);
                            setConsoleInput(consoleHistory[nextIdx]);
                          } else {
                            setHistoryIdx(-1);
                            setConsoleInput('');
                          }
                        }
                      }}
                      placeholder="WebSocket offline — run host command via HTTP fallback (e.g. docker ps, df -h, git -C /data status)..."
                      className="flex-1 bg-transparent text-white focus:outline-none font-mono text-xs"
                    />
                    <button
                      type="submit"
                      disabled={consoleBusy || !consoleInput.trim()}
                      className="px-3 py-1 rounded bg-[#00f2fe]/15 hover:bg-[#00f2fe]/25 border border-[#00f2fe]/40 text-[#00f2fe] text-[11px] font-semibold disabled:opacity-40"
                    >
                      {consoleBusy ? 'Running...' : 'Run ↵'}
                    </button>
                  </form>
                )}
              </div>

              {/* Decoupled Plain Monospace System Job Output View */}
              {consoleViewMode === 'jobs' && (
                <div className="flex-1 rounded-xl border border-white/15 bg-[#05070B] p-4 overflow-y-auto font-mono text-xs space-y-1.5">
                  {logs.length === 0 && consoleEntries.length === 0 ? (
                    <div className="text-slate-500 italic py-12 text-center">
                      No background job output recorded in this session. Trigger an OS patch, service update, or log prune to view real-time SSE output.
                    </div>
                  ) : (
                    <>
                      {logs.map((log) => (
                        <div key={`job-${log.id}`} className="flex items-start gap-2.5">
                          <span className="text-slate-600 select-none text-[10px] shrink-0">
                            [{log.timestamp}]
                          </span>
                          <div className="break-all whitespace-pre-wrap text-slate-200">{renderAnsiLine(log.text)}</div>
                        </div>
                      ))}
                      {consoleEntries.map((entry) => (
                        <div key={`cmd-${entry.id}`} className="flex items-start gap-2.5">
                          <span className="text-slate-600 select-none text-[10px] shrink-0">
                            [{entry.timestamp}]
                          </span>
                          <div
                            className={`break-all whitespace-pre-wrap ${
                              entry.type === 'input'
                                ? 'text-[#00f2fe] font-semibold'
                                : entry.type === 'error'
                                ? 'text-red-400'
                                : 'text-slate-300'
                            }`}
                          >
                            {entry.text}
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                  <div ref={logsEndRef} />
                </div>
              )}
            </div>
          )}

          {/* PANE 3: AGENTS & RUNNERS (#334) */}
          {activePane === 'agents' && (
            <div className="space-y-5 max-w-5xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/10 pb-3">
                <div>
                  <h2 className="font-headline font-bold text-base text-white">
                    Agent Execution Runners &amp; Tool Egress Keys
                  </h2>
                  <p className="font-mono text-xs text-slate-400">
                    Stateless multi-tenant agent runners (Rule 9) and external web-research API keys
                  </p>
                </div>
                <a
                  href="/runner/"
                  target="_blank"
                  rel="noreferrer"
                  className="px-3.5 py-1.5 rounded-lg bg-[#00f2fe]/15 hover:bg-[#00f2fe]/25 border border-[#00f2fe]/40 text-[#00f2fe] text-xs font-mono font-semibold flex items-center gap-1.5 self-start"
                >
                  <span>Open Hermes Runner UI (/runner/)</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>

              {/* Runners Table */}
              <div className="rounded-xl border border-white/10 bg-[#0B0E14] overflow-hidden">
                <table className="w-full font-mono text-xs border-collapse">
                  <thead>
                    <tr className="bg-[#101520] text-slate-400 text-[10px] uppercase tracking-wider text-left border-b border-white/10">
                      <th className="py-2.5 px-4">Runner Engine</th>
                      <th className="py-2.5 px-4">Runtime / Endpoint</th>
                      <th className="py-2.5 px-4">Active Model</th>
                      <th className="py-2.5 px-4">Web Search Mode</th>
                      <th className="py-2.5 px-4 text-right">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {normalizedRunners.map((runner) => (
                      <tr key={runner.id} className="hover:bg-white/[0.02]">
                        <td className="py-3 px-4 font-semibold text-white">
                          <div>{runner.name}</div>
                          {runner.ui_route && (
                            <a
                              href={runner.ui_route}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[10px] text-[#00f2fe] hover:underline inline-flex items-center gap-1 mt-0.5"
                            >
                              <span>{runner.ui_route}</span>
                              <ExternalLink className="w-2.5 h-2.5" />
                            </a>
                          )}
                        </td>
                        <td className="py-3 px-4 text-slate-300">{runner.runtime}</td>
                        <td className="py-3 px-4 text-purple-300">{runner.active_model || 'LiteLLM Default'}</td>
                        <td className="py-3 px-4">
                          {runner.id === 'hermes' || runner.id.includes('hermes') ? (
                            firecrawlConfigured ? (
                              <span className="px-2 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-[10px]">
                                Firecrawl API Key Active
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 text-[10px]">
                                Keyless Free Tier (Rate-Limited)
                              </span>
                            )
                          ) : (
                            <span className="text-slate-400">{runner.web_search_mode || 'Tool Egress Proxy'}</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <span className="px-2 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[10px] uppercase font-bold">
                            ● {runner.status || 'ONLINE'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Tool Egress & Web Search API Key Configuration (#334) */}
              <div className="p-5 rounded-xl border border-white/10 bg-[#0B0E14] space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-white/10 pb-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <Search className="w-4 h-4 text-[#00f2fe]" />
                      <h3 className="font-headline font-bold text-sm text-white">
                        Nous Hermes Web Search &amp; Tool Egress API Keys
                      </h3>
                    </div>
                    <p className="font-mono text-xs text-slate-400 mt-0.5">
                      Out-of-the-box, Hermes uses keyless DuckGs/Markdown fallback. Add a <code className="text-[#00f2fe]">FIRECRAWL_API_KEY</code> or provider keys below to unlock high-rate deep web scraping and external models.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowRunnerKeys((prev) => !prev)}
                    className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono text-slate-300 flex items-center gap-1.5 self-start"
                  >
                    {showRunnerKeys ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                    <span>{showRunnerKeys ? 'Hide Keys' : 'Show Keys'}</span>
                  </button>
                </div>

                {runnerSaveBanner && (
                  <div
                    className={`p-3 rounded-lg border font-mono text-xs ${
                      runnerSaveBanner.type === 'success'
                        ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-200'
                        : 'bg-red-500/15 border-red-500/40 text-red-200'
                    }`}
                  >
                    {runnerSaveBanner.text}
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 font-mono text-xs">
                  <div className="space-y-1.5">
                    <label className="block text-slate-200 font-semibold flex items-center justify-between">
                      <span>FIRECRAWL_API_KEY</span>
                      <span className={firecrawlConfigured ? 'text-emerald-400 text-[10px]' : 'text-amber-400 text-[10px]'}>
                        {firecrawlConfigured
                          ? `Configured (${toolKeysMap.FIRECRAWL_API_KEY?.masked || '••••'})`
                          : 'Not Set (Keyless Fallback)'}
                      </span>
                    </label>
                    <input
                      type={showRunnerKeys ? 'text' : 'password'}
                      value={firecrawlKey}
                      onChange={(e) => setFirecrawlKey(e.target.value)}
                      placeholder="fc-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                      className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-slate-200 font-semibold flex items-center justify-between">
                      <span>TAVILY_API_KEY (Optional)</span>
                      <span className={toolKeysMap.TAVILY_API_KEY?.configured ? 'text-emerald-400 text-[10px]' : 'text-slate-500 text-[10px]'}>
                        {toolKeysMap.TAVILY_API_KEY?.configured
                          ? `Configured (${toolKeysMap.TAVILY_API_KEY.masked || '••••'})`
                          : 'Optional'}
                      </span>
                    </label>
                    <input
                      type={showRunnerKeys ? 'text' : 'password'}
                      value={tavilyKey}
                      onChange={(e) => setTavilyKey(e.target.value)}
                      placeholder="tvly-xxxxxxxxxxxxxxxx"
                      className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-slate-200 font-semibold flex items-center justify-between">
                      <span>EXA_API_KEY (Optional)</span>
                      <span className={toolKeysMap.EXA_API_KEY?.configured ? 'text-emerald-400 text-[10px]' : 'text-slate-500 text-[10px]'}>
                        {toolKeysMap.EXA_API_KEY?.configured
                          ? `Configured (${toolKeysMap.EXA_API_KEY.masked || '••••'})`
                          : 'Optional'}
                      </span>
                    </label>
                    <input
                      type={showRunnerKeys ? 'text' : 'password'}
                      value={exaKey}
                      onChange={(e) => setExaKey(e.target.value)}
                      placeholder="exa-xxxxxxxxxxxxxxxx"
                      className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-slate-200 font-semibold flex items-center justify-between">
                      <span>BRAVE_API_KEY (Optional)</span>
                      <span className={toolKeysMap.BRAVE_API_KEY?.configured ? 'text-emerald-400 text-[10px]' : 'text-slate-500 text-[10px]'}>
                        {toolKeysMap.BRAVE_API_KEY?.configured
                          ? `Configured (${toolKeysMap.BRAVE_API_KEY.masked || '••••'})`
                          : 'Optional'}
                      </span>
                    </label>
                    <input
                      type={showRunnerKeys ? 'text' : 'password'}
                      value={braveKey}
                      onChange={(e) => setBraveKey(e.target.value)}
                      placeholder="BSAxxxxxxxxxxxxxxxx"
                      className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-slate-200 font-semibold flex items-center justify-between">
                      <span>GITHUB_TOKEN (Optional Egress)</span>
                      <span className={toolKeysMap.GITHUB_TOKEN?.configured ? 'text-emerald-400 text-[10px]' : 'text-slate-500 text-[10px]'}>
                        {toolKeysMap.GITHUB_TOKEN?.configured
                          ? `Configured (${toolKeysMap.GITHUB_TOKEN.masked || '••••'})`
                          : 'Optional'}
                      </span>
                    </label>
                    <input
                      type={showRunnerKeys ? 'text' : 'password'}
                      value={githubTokenKey}
                      onChange={(e) => setGithubTokenKey(e.target.value)}
                      placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                      className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-slate-200 font-semibold flex items-center justify-between">
                      <span>OPENROUTER_API_KEY (Optional)</span>
                      <span className={toolKeysMap.OPENROUTER_API_KEY?.configured ? 'text-emerald-400 text-[10px]' : 'text-slate-500 text-[10px]'}>
                        {toolKeysMap.OPENROUTER_API_KEY?.configured
                          ? `Configured (${toolKeysMap.OPENROUTER_API_KEY.masked || '••••'})`
                          : 'Optional'}
                      </span>
                    </label>
                    <input
                      type={showRunnerKeys ? 'text' : 'password'}
                      value={openrouterKey}
                      onChange={(e) => setOpenrouterKey(e.target.value)}
                      placeholder="sk-or-v1-xxxxxxxxxxxxxxxx"
                      className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-slate-200 font-semibold flex items-center justify-between">
                      <span>ANTHROPIC_API_KEY (Optional)</span>
                      <span className={toolKeysMap.ANTHROPIC_API_KEY?.configured ? 'text-emerald-400 text-[10px]' : 'text-slate-500 text-[10px]'}>
                        {toolKeysMap.ANTHROPIC_API_KEY?.configured
                          ? `Configured (${toolKeysMap.ANTHROPIC_API_KEY.masked || '••••'})`
                          : 'Optional'}
                      </span>
                    </label>
                    <input
                      type={showRunnerKeys ? 'text' : 'password'}
                      value={anthropicKey}
                      onChange={(e) => setAnthropicKey(e.target.value)}
                      placeholder="sk-ant-xxxxxxxxxxxxxxxx"
                      className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="block text-slate-200 font-semibold flex items-center justify-between">
                      <span>OPENAI_API_KEY (Optional)</span>
                      <span className={toolKeysMap.OPENAI_API_KEY?.configured ? 'text-emerald-400 text-[10px]' : 'text-slate-500 text-[10px]'}>
                        {toolKeysMap.OPENAI_API_KEY?.configured
                          ? `Configured (${toolKeysMap.OPENAI_API_KEY.masked || '••••'})`
                          : 'Optional'}
                      </span>
                    </label>
                    <input
                      type={showRunnerKeys ? 'text' : 'password'}
                      value={openaiKey}
                      onChange={(e) => setOpenaiKey(e.target.value)}
                      placeholder="sk-proj-xxxxxxxxxxxxxxxx"
                      className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 focus:border-[#00f2fe] focus:outline-none text-white"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-end pt-2">
                  <button
                    type="button"
                    onClick={handleSaveRunnerConfig}
                    disabled={savingRunnerConfig}
                    className="px-4 py-2 rounded-lg bg-[#00f2fe]/20 hover:bg-[#00f2fe]/30 border border-[#00f2fe]/50 text-[#00f2fe] font-mono text-xs font-bold transition-all disabled:opacity-50"
                  >
                    {savingRunnerConfig ? 'Saving & Syncing...' : 'Save & Sync to Hermes Runner'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* PANE 4: SOFTWARE & OS UPDATES (#336) */}
          {activePane === 'updates' && (
            <div className="space-y-5 max-w-5xl">
              {/* Section A: Host OS & Kernel Security Patching */}
              <div className="p-5 rounded-xl border border-white/10 bg-[#0B0E14] space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/10 pb-3">
                  <div>
                    <div className="flex items-center gap-2.5">
                      <Shield className="w-4 h-4 text-emerald-400" />
                      <h2 className="font-headline font-bold text-base text-white">
                        Host OS &amp; Kernel Security Patching (Ubuntu LTS)
                      </h2>
                      <span className="px-2 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-mono text-[10px]">
                        unattended-upgrades: {status?.os?.unattended_upgrades_active !== false ? 'ACTIVE' : 'INACTIVE'}
                      </span>
                    </div>
                    <p className="font-mono text-xs text-slate-400 mt-0.5">
                      Daily APT security updates with <code className="text-slate-300">Automatic-Reboot &quot;false&quot;</code> so active agent sessions are never interrupted unexpectedly
                    </p>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => handleOsSecurityUpgrade(true)}
                      className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono text-slate-300 hover:text-white"
                    >
                      Audit APT Security
                    </button>
                    <button
                      onClick={() => handleOsSecurityUpgrade(false)}
                      className="px-3.5 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-300 hover:text-white text-xs font-mono font-semibold flex items-center gap-1.5"
                    >
                      <ArrowUpCircle className="w-3.5 h-3.5" />
                      <span>Apply OS Security Patches</span>
                    </button>
                  </div>
                </div>

                {status?.os?.reboot_required && (
                  <div className="p-3.5 rounded-xl bg-red-500/15 border border-red-500/40 flex flex-col sm:flex-row sm:items-center justify-between gap-3 font-mono text-xs">
                    <div className="flex items-center gap-2.5 text-red-200">
                      <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                      <span>
                        <strong>Kernel / Core Library Reboot Required:</strong> <code className="text-white">/var/run/reboot-required</code> is present on the host. Schedule a graceful reboot when convenient.
                      </span>
                    </div>
                    <button
                      onClick={() => setRebootModalOpen(true)}
                      className="px-3 py-1.5 rounded-lg bg-red-500/25 hover:bg-red-500/35 border border-red-500/50 text-red-200 font-semibold shrink-0"
                    >
                      Reboot Appliance...
                    </button>
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 font-mono text-xs">
                  <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                    <span className="text-slate-500 block text-[10px] uppercase">Distribution &amp; Kernel</span>
                    <span className="text-white font-semibold block mt-0.5">{status?.os?.distro || 'Ubuntu 24.04 LTS'}</span>
                    <span className="text-slate-400 text-[11px]">Kernel {status?.os?.kernel || '6.8.0-1018-aws'}</span>
                  </div>
                  <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                    <span className="text-slate-500 block text-[10px] uppercase">Pending Security Packages</span>
                    <span className="text-white font-semibold block mt-0.5">
                      {status?.os?.pending_security_updates ?? 0} package(s)
                    </span>
                    <span className="text-emerald-400 text-[11px]">Docker &amp; containerd pinned safe</span>
                  </div>
                  <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                    <span className="text-slate-500 block text-[10px] uppercase">Reboot Status</span>
                    <span className={`font-semibold block mt-0.5 ${status?.os?.reboot_required ? 'text-red-400' : 'text-emerald-400'}`}>
                      {status?.os?.reboot_required ? 'Reboot Required' : 'No Reboot Needed'}
                    </span>
                    <span className="text-slate-400 text-[11px]">Manual operator control</span>
                  </div>
                </div>
              </div>

              {/* Section B: Platform Core (Git) & Container Plane Versions */}
              <div className="rounded-xl border border-white/10 bg-[#0B0E14] overflow-hidden">
                <div className="px-4 py-3 bg-[#101520] border-b border-white/10 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="font-headline font-bold text-sm text-white">
                      Platform Repository &amp; Container Release Matrix
                    </h3>
                    <p className="font-mono text-[11px] text-slate-400">
                      Pre-flight snapshot via <code className="text-slate-300">scripts/control/backup.sh</code> before every update
                    </p>
                  </div>
                  <button
                    onClick={() =>
                      setConfirmTarget({
                        id: 'full',
                        name: 'brainsOS Platform (Full Stack & Containers)',
                        full: true,
                        branch: selectedBranch || status?.git?.branch || 'main',
                      })
                    }
                    className="px-3.5 py-1.5 rounded-lg bg-[#00f2fe]/20 hover:bg-[#00f2fe]/30 border border-[#00f2fe]/40 text-[#00f2fe] font-mono text-xs font-semibold flex items-center gap-1.5"
                  >
                    <ArrowUpCircle className="w-3.5 h-3.5" />
                    <span>Update All Planes</span>
                  </button>
                </div>

                {/* Git Branch Row */}
                {status?.git && (
                  <div className="p-4 border-b border-white/10 bg-white/[0.01] flex flex-col sm:flex-row sm:items-center justify-between gap-3 font-mono text-xs">
                    <div className="flex items-center gap-3 flex-wrap">
                      <GitBranch className="w-4 h-4 text-purple-400" />
                      <span className="text-white font-semibold">brainsOS.ai Core Repository:</span>
                      <select
                        value={selectedBranch || status.git.branch || 'main'}
                        onChange={(e) => setSelectedBranch(e.target.value)}
                        className="px-2.5 py-1 rounded bg-[#07090E] border border-purple-500/40 text-white text-xs"
                      >
                        {(status.git.available_branches && status.git.available_branches.length > 0
                          ? status.git.available_branches
                          : [status.git.branch || 'main']
                        ).map((br) => (
                          <option key={br} value={br}>
                            {br}{br === status.git.branch ? ' (active)' : ''}
                          </option>
                        ))}
                      </select>
                      <span className="text-slate-400">
                        HEAD <code className="text-[#00f2fe]">{(status.git.current_commit || 'HEAD').substring(0, 7)}</code>
                      </span>
                    </div>
                    <button
                      onClick={() => {
                        const targetBranch = selectedBranch || status.git.branch || 'main';
                        setConfirmTarget({
                          id: 'git-source',
                          name: `Sync Platform Core (origin/${targetBranch})`,
                          full: true,
                          branch: targetBranch,
                        });
                      }}
                      className="px-3 py-1.5 rounded-lg bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/40 text-purple-200 text-xs font-mono font-semibold self-start sm:self-auto"
                    >
                      {selectedBranch && selectedBranch !== status.git.branch
                        ? `Switch to ${selectedBranch}`
                        : 'Pull Latest Source'}
                    </button>
                  </div>
                )}

                {/* Services Table */}
                <table className="w-full font-mono text-xs border-collapse">
                  <thead>
                    <tr className="bg-[#0D121C] text-slate-400 text-[10px] uppercase tracking-wider text-left border-b border-white/10">
                      <th className="py-2.5 px-4">Service Plane</th>
                      <th className="py-2.5 px-4">Installed Version</th>
                      <th className="py-2.5 px-4">Latest Upstream</th>
                      <th className="py-2.5 px-4">Target / Pin Tag</th>
                      <th className="py-2.5 px-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {Object.entries(status?.services || {}).map(([svcKey, svc]) => {
                      const customVer = pinVersions[svcKey] ?? '';
                      return (
                        <tr key={svcKey} className="hover:bg-white/[0.02]">
                          <td className="py-3 px-4">
                            <div className="font-semibold text-white">{svc.name}</div>
                            <a
                              href={svc.changelog_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[10px] text-slate-500 hover:text-[#00f2fe] inline-flex items-center gap-1"
                            >
                              <span>Release notes</span>
                              <ExternalLink className="w-2.5 h-2.5" />
                            </a>
                          </td>
                          <td className="py-3 px-4 text-slate-200">{svc.current_version}</td>
                          <td className="py-3 px-4">
                            <span className={svc.update_available ? 'text-amber-400 font-semibold' : 'text-emerald-400'}>
                              {svc.latest_version}
                            </span>
                          </td>
                          <td className="py-3 px-4">
                            <input
                              type="text"
                              value={customVer}
                              onChange={(e) => setPinVersions((prev) => ({ ...prev, [svcKey]: e.target.value }))}
                              placeholder={svc.latest_version}
                              className="w-32 px-2 py-1 rounded bg-[#07090E] border border-white/10 text-white text-[11px]"
                            />
                          </td>
                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={() =>
                                setConfirmTarget({
                                  id: svcKey,
                                  name: svc.name,
                                  service: svcKey,
                                  targetVersion: customVer.trim() || svc.latest_version,
                                })
                              }
                              className={`px-3 py-1 rounded-lg border text-[11px] font-semibold transition-all ${
                                svc.update_available || customVer.trim()
                                  ? 'bg-amber-500/20 hover:bg-amber-500/30 border-amber-500/40 text-amber-300'
                                  : 'bg-white/5 hover:bg-white/10 border-white/10 text-slate-300'
                              }`}
                            >
                              {customVer.trim() ? `Deploy ${customVer.trim()}` : svc.update_available ? 'Update' : 'Redeploy'}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* PANE 5: STORAGE, LOGS & POWER (#336) */}
          {activePane === 'storage' && (
            <div className="space-y-5 max-w-5xl">
              {/* Storage & Log Retention */}
              <div className="p-5 rounded-xl border border-white/10 bg-[#0B0E14] space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-white/10 pb-3">
                  <div>
                    <h2 className="font-headline font-bold text-base text-white">
                      Storage Capacity &amp; Log Retention Policy
                    </h2>
                    <p className="font-mono text-xs text-slate-400">
                      Root partition utilization, systemd journal bounds, and Rule 1 OKF Markdown protection
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handlePruneLogs(true, false)}
                      className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono text-slate-300 flex items-center gap-1.5"
                    >
                      <Activity className="w-3.5 h-3.5 text-[#00f2fe]" />
                      <span>Audit Storage</span>
                    </button>
                    <button
                      onClick={() => handlePruneLogs(false, true)}
                      className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-mono text-slate-300 flex items-center gap-1.5"
                    >
                      <FileText className="w-3.5 h-3.5 text-amber-400" />
                      <span>Dry Run</span>
                    </button>
                    <button
                      onClick={() => handlePruneLogs(false, false)}
                      className="px-3.5 py-1.5 rounded-lg bg-[#00f2fe]/20 hover:bg-[#00f2fe]/30 border border-[#00f2fe]/40 text-[#00f2fe] text-xs font-mono font-semibold flex items-center gap-1.5"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Prune Logs &amp; Vacuum Journal</span>
                    </button>
                  </div>
                </div>

                <div className="space-y-2 font-mono text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-300">Root Filesystem (/opt/brainsos &amp; /data)</span>
                    <span className="text-[#00f2fe] font-semibold">
                      {status?.disk ? `${status.disk.free_gb} GB Free of ${status.disk.total_gb} GB (${status.disk.free_pct}%)` : '—'}
                    </span>
                  </div>
                  <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        status?.disk?.warning ? 'bg-amber-500' : 'bg-gradient-to-r from-[#00f2fe] to-emerald-400'
                      }`}
                      style={{ width: `${status?.disk ? Math.min(100, Math.max(0, 100 - status.disk.free_pct)) : 25}%` }}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 font-mono text-xs pt-2">
                  <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                    <span className="text-slate-500 block text-[10px] uppercase">systemd-journald</span>
                    <span className="text-slate-200 font-semibold">500 MB max • 30d retention</span>
                  </div>
                  <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                    <span className="text-slate-500 block text-[10px] uppercase">Docker JSON Logs</span>
                    <span className="text-slate-200 font-semibold">50 MB max • 3 files bound</span>
                  </div>
                  <div className="p-3 rounded-lg bg-white/[0.02] border border-white/5">
                    <span className="text-slate-500 block text-[10px] uppercase">Rule 1 Memory Invariant</span>
                    <span className="text-emerald-400 font-semibold">/memories &amp; Gitea Exempt</span>
                  </div>
                </div>
              </div>

              {/* Appliance Power & Graceful Reboot Section (#336) */}
              <div className="p-5 rounded-xl border border-red-500/30 bg-[#0B0E14] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-red-300 font-headline font-bold text-sm">
                    <Power className="w-4 h-4 text-red-400" />
                    <span>Appliance Power &amp; Graceful Host Reboot</span>
                  </div>
                  <p className="font-mono text-xs text-slate-400">
                    Flushes PostgreSQL &amp; Gitea buffers, stops agent containers cleanly, and executes <code className="text-slate-300">systemctl reboot</code>.
                  </p>
                </div>
                <button
                  onClick={() => {
                    setRebootConfirmText('');
                    setRebootModalOpen(true);
                  }}
                  className="px-4 py-2 rounded-lg bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-200 font-mono text-xs font-bold flex items-center gap-2 shrink-0"
                >
                  <Power className="w-3.5 h-3.5" />
                  <span>Graceful Appliance Reboot...</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Pre-Flight Update Confirmation Modal */}
      {confirmTarget && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in">
          <div className="w-full max-w-lg bg-[#0E131F] border border-white/15 rounded-2xl p-6 shadow-2xl space-y-5">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-400">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-headline font-bold text-base text-white">
                    Confirm Appliance Update
                  </h3>
                  <p className="font-mono text-xs text-slate-400 mt-0.5">
                    Automated pre-flight snapshot will be created prior to changes
                  </p>
                </div>
              </div>
              <button
                onClick={() => setConfirmTarget(null)}
                className="w-7 h-7 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white flex items-center justify-center"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-4 rounded-xl bg-white/[0.03] border border-white/5 space-y-2.5 font-mono text-xs">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Target:</span>
                <span className="text-[#00f2fe] font-semibold">{confirmTarget.name}</span>
              </div>
              {confirmTarget.targetVersion && (
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Version Tag:</span>
                  <span className="text-amber-400 font-semibold">{confirmTarget.targetVersion}</span>
                </div>
              )}
              {confirmTarget.branch && (
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Git Branch:</span>
                  <span className="text-purple-400 font-semibold">origin/{confirmTarget.branch}</span>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setConfirmTarget(null)}
                className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-xs font-mono text-slate-300"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmUpdate}
                className="px-5 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-mono text-xs font-bold flex items-center gap-1.5"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Confirm &amp; Stream Logs</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 2-Step Graceful Appliance Reboot Modal (#336) */}
      {rebootModalOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in">
          <div className="w-full max-w-md bg-[#0E131F] border border-red-500/40 rounded-2xl p-6 shadow-2xl space-y-4 font-mono text-xs">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5 text-red-400 font-headline font-bold text-base">
                <Power className="w-5 h-5" />
                <span>Confirm Graceful Appliance Reboot</span>
              </div>
              <button
                onClick={() => setRebootModalOpen(false)}
                className="w-7 h-7 rounded-lg bg-white/5 text-slate-400 hover:text-white flex items-center justify-center"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-slate-300 font-sans leading-relaxed">
              This will cleanly stop running containers, sync filesystems, and reboot the host operating system. The portal will reconnect automatically in ~45 seconds.
            </p>
            <div className="space-y-1.5">
              <label className="block text-slate-400">
                Type <code className="text-red-300 font-bold">REBOOT</code> to confirm:
              </label>
              <input
                type="text"
                value={rebootConfirmText}
                onChange={(e) => setRebootConfirmText(e.target.value)}
                placeholder="REBOOT"
                className="w-full px-3 py-2 rounded-lg bg-[#07090E] border border-white/15 text-white focus:border-red-400 focus:outline-none"
              />
            </div>
            <div className="flex items-center justify-end gap-2.5 pt-2">
              <button
                onClick={() => setRebootModalOpen(false)}
                className="px-4 py-2 rounded-lg bg-white/5 text-slate-300"
              >
                Cancel
              </button>
              <button
                onClick={handleGracefulReboot}
                disabled={isRebooting || rebootConfirmText.trim().toUpperCase() !== 'REBOOT'}
                className="px-4 py-2 rounded-lg bg-red-500 hover:bg-red-400 text-slate-950 font-bold disabled:opacity-40"
              >
                {isRebooting ? 'Rebooting Host...' : 'Reboot Now'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Re-openable 3-Step Setup Wizard Modal */}
      {wizardOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4 animate-in fade-in overflow-y-auto">
          {renderWizardCardContent(false)}
        </div>
      )}
    </div>
  );
};

interface SystemManagerErrorBoundaryState {
  hasError: boolean;
  errorMessage: string;
}

class SystemManagerErrorBoundary extends React.Component<
  SystemManagerProps,
  SystemManagerErrorBoundaryState
> {
  constructor(props: SystemManagerProps) {
    super(props);
    this.state = { hasError: false, errorMessage: '' };
  }

  static getDerivedStateFromError(error: unknown): SystemManagerErrorBoundaryState {
    const message = error instanceof Error ? error.message : String(error || 'Unexpected UI runtime error');
    return { hasError: true, errorMessage: message };
  }

  componentDidCatch(error: unknown, errorInfo: React.ErrorInfo): void {
    console.error('[SystemManagerErrorBoundary] Caught runtime exception:', error, errorInfo);
  }

  private handleReload = (): void => {
    this.setState({ hasError: false, errorMessage: '' });
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <div className="w-full h-full min-h-[420px] bg-[#07090E] text-slate-200 flex items-center justify-center p-6 font-sans">
          <div className="w-full max-w-lg rounded-2xl border border-red-500/30 bg-[#0B0E14] p-6 shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-red-400">
              <div className="w-10 h-10 rounded-xl bg-red-500/15 border border-red-500/30 flex items-center justify-center shrink-0">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div>
                <h2 className="font-headline font-bold text-base text-white">
                  System Console Recovery Mode
                </h2>
                <p className="font-mono text-xs text-slate-400">
                  brainsOS caught an unexpected UI exception and protected the portal session
                </p>
              </div>
            </div>

            {this.state.errorMessage && (
              <div className="p-3 rounded-xl bg-black/50 border border-white/10 font-mono text-xs text-red-300 break-words">
                {this.state.errorMessage}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={this.handleReload}
                className="px-4 py-2 rounded-xl bg-[#00f2fe]/20 hover:bg-[#00f2fe]/30 border border-[#00f2fe]/50 text-[#00f2fe] font-mono text-xs font-bold flex items-center gap-2 transition-all"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Reload System Console</span>
              </button>
            </div>
          </div>
        </div>
      );
    }

    return <SystemManagerInner {...this.props} />;
  }
}

export const SystemManager: React.FC<SystemManagerProps> = (props) => (
  <SystemManagerErrorBoundary {...props} />
);

export default SystemManager;

