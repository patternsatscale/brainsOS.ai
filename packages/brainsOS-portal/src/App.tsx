import { useState, useCallback, useEffect } from 'react';
import { ThinSpine } from './components/ThinSpine';
import { SubsystemsDrawer } from './components/SubsystemsDrawer';
import { ViewportFrame } from './components/ViewportFrame';
import { UserProfileModal } from './components/UserProfileModal';
import { SystemManager } from './components/SystemManager';
import { SUBSYSTEMS } from './data/subsystems';
import { useHotkeys } from './hooks/useHotkeys';
import { CheckCircle2, RefreshCw } from 'lucide-react';
import { AuthenticatedUser, DEFAULT_USER } from './types/user';

const getInitialKey = (): string => {
  if (typeof window === 'undefined') return 'comms';
  const path = window.location.pathname.replace(/\/$/, '');
  const hash = window.location.hash.replace(/^#/, '');
  if (hash && SUBSYSTEMS[hash]) return hash;
  if (path === '/system') return 'system';
  if (path === '/docs') return 'help';
  if (path === '/editor') return 'console';
  if (path === '/git' || path.startsWith('/git/')) return 'git';
  if (path === '/mail' || path.startsWith('/mail/') || path === '/kurrier') return 'comms';
  if (path === '/proxy' || path.startsWith('/proxy/ui')) return 'security';
  if (path === '/efw') return 'network';
  if (path === '/langfuse') return 'trace';
  if (path === '/auth' || path.startsWith('/auth/if')) return 'users';
  return 'comms';
};

export function App() {
  const [activeKey, setActiveKey] = useState<string>(getInitialKey);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [profileModalOpen, setProfileModalOpen] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [user, setUser] = useState<AuthenticatedUser>(DEFAULT_USER);
  const [customUrls, setCustomUrls] = useState<Record<string, string>>({});
  const [hasUpdateAvailable, setHasUpdateAvailable] = useState<boolean>(false);

  // Live mode is enabled by default across all hosts (localhost, LAN IPs, custom domains)
  // Mock mode is only active when explicitly requested via ?mock=true
  const isMockMode = typeof window !== 'undefined' && window.location.search.includes('mock=true');
  const isLiveHost = !isMockMode;
  const [wizardGate, setWizardGate] = useState<'checking' | 'required' | 'completed'>(
    isMockMode || import.meta.env.DEV ? 'completed' : 'checking'
  );

  // Enforce obsidian dark theme across appliance and same-origin frames
  useEffect(() => {
    try {
      localStorage.setItem('theme', 'dark');
      document.documentElement.classList.add('dark');
      document.documentElement.setAttribute('data-theme', 'dark');
      document.documentElement.style.colorScheme = 'dark';
    } catch {}
  }, []);

  // Gate the entire Portal on First-Boot Setup Wizard completion (#333)
  useEffect(() => {
    if (isMockMode) {
      setWizardGate('completed');
      return;
    }
    let cancelled = false;
    let attempts = 0;

    const checkWizardState = async () => {
      while (!cancelled && attempts < 30) {
        attempts += 1;
        try {
          const identRes = await fetch('/api/v1/system/identity', { credentials: 'include' });
          if (identRes.ok) {
            const ident = await identRes.json();
            if (cancelled) return;
            if (ident && ident.firstboot_wizard_completed === false) {
              setWizardGate('required');
            } else {
              setWizardGate('completed');
            }
            return;
          }
          const res = await fetch('/api/v1/system/status', { credentials: 'include' });
          if (res.ok) {
            const data = await res.json();
            if (cancelled) return;
            if (data && typeof data.overall_update_available === 'boolean') {
              setHasUpdateAvailable(data.overall_update_available);
            }
            if (data && data.firstboot_wizard_completed === false) {
              setWizardGate('required');
            } else {
              setWizardGate('completed');
            }
            return;
          }
        } catch {
          // System API may still be warming up on first boot
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
      if (!cancelled) {
        setWizardGate('completed');
      }
    };

    checkWizardState();
    return () => {
      cancelled = true;
    };
  }, [isMockMode]);

  // Keep OS update badge synchronized with System API & SystemManager updates
  useEffect(() => {
    if (isMockMode) return;
    fetch('/api/v1/system/status', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && typeof data.overall_update_available === 'boolean') {
          setHasUpdateAvailable(data.overall_update_available);
        }
      })
      .catch(() => {});

    const handleSystemStatusEvent = (ev: Event) => {
      const detail = (ev as CustomEvent<{ overall_update_available?: boolean }>).detail;
      if (detail && typeof detail.overall_update_available === 'boolean') {
        setHasUpdateAvailable(detail.overall_update_available);
      }
    };
    window.addEventListener('brainsos:system-status', handleSystemStatusEvent);
    return () => {
      window.removeEventListener('brainsos:system-status', handleSystemStatusEvent);
    };
  }, [isMockMode]);

  // Fetch real authenticated user identity from Authentik API (with System API fallback) once wizard is completed
  useEffect(() => {
    if (wizardGate !== 'completed') return;
    const applyUserPayload = (raw: any) => {
      const u = raw?.user && typeof raw.user === 'object' ? raw.user : raw;
      if (u && typeof u.username === 'string' && u.username.trim()) {
        const uname = u.username.trim();
        setUser({
          username: uname,
          name: u.name || (uname.toLowerCase() === 'admin' ? 'Appliance Administrator' : uname),
          email: u.email || `${uname}@brainsos.ai`,
          isSuperuser: u.is_superuser !== undefined ? Boolean(u.is_superuser) : true,
          lastLogin: u.last_login
            ? new Date(u.last_login).toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              })
            : 'Active SSO Session',
          avatarUrl: u.avatar || undefined,
        });
        return true;
      }
      return false;
    };

    fetch('/api/v3/core/users/me/', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (applyUserPayload(data)) return null;
        return fetch('/api/v1/system/me', { credentials: 'include' }).then((r) => (r.ok ? r.json() : null));
      })
      .then((fallbackData) => {
        if (fallbackData) applyUserPayload(fallbackData);
      })
      .catch(() => {
        // Fallback gracefully on local preview or connection error
      });
  }, [wizardGate]);

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((current) => (current === msg ? null : current));
    }, 2200);
  }, []);

  const handleSelectSubsystem = useCallback((key: string) => {
    if (SUBSYSTEMS[key]) {
      setActiveKey(key);
      setCustomUrls((prev) => {
        if (!prev[key]) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      });
      showToast(`Switched to ${SUBSYSTEMS[key].title}`);
    }
  }, [showToast]);

  const handleOpenProfileSettings = useCallback(() => {
    setProfileModalOpen(false);
    setDrawerOpen(false);
    setCustomUrls((prev) => ({
      ...prev,
      users: '/if/flow/default-user-settings-flow/?next=/if/flow/default-user-settings-flow/',
    }));
    setActiveKey('users');
    showToast('Opened Profile Settings');
  }, [showToast]);

  const handleToggleDrawer = useCallback(() => {
    setDrawerOpen((prev) => !prev);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setDrawerOpen(false);
  }, []);

  const handleToggleProfile = useCallback(() => {
    setProfileModalOpen((prev) => !prev);
  }, []);

  const handleCloseProfile = useCallback(() => {
    setProfileModalOpen(false);
  }, []);

  const handleToggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
      showToast('Full Screen Mode (F11)');
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
    }
  }, [showToast]);

  useHotkeys({
    onSelectSubsystem: handleSelectSubsystem,
    onToggleDrawer: handleToggleDrawer,
    onCloseDrawer: handleCloseDrawer,
    drawerOpen,
    onToggleFullscreen: handleToggleFullscreen,
    onToggleProfile: handleToggleProfile,
    onCloseProfile: handleCloseProfile,
    profileOpen: profileModalOpen,
  });

  const activeSubsystem = SUBSYSTEMS[activeKey] || SUBSYSTEMS.console;

  if (wizardGate === 'checking') {
    return (
      <div className="w-screen h-screen flex flex-col items-center justify-center bg-[#07090E] text-slate-200 font-mono select-none">
        <div className="flex items-center gap-3 px-5 py-3.5 rounded-2xl bg-[#0D111A] border border-white/10 shadow-2xl">
          <RefreshCw className="w-4 h-4 text-[#00f2fe] animate-spin" />
          <span className="text-xs text-slate-300">Connecting to brainsOS Appliance...</span>
        </div>
      </div>
    );
  }

  if (wizardGate === 'required') {
    return (
      <div className="w-screen h-screen bg-[#07090E] overflow-y-auto antialiased selection:bg-[#00f2fe] selection:text-black">
        <SystemManager standaloneWizard={true} />
      </div>
    );
  }

  return (
    <div className="w-screen h-screen flex relative antialiased selection:bg-[#00f2fe] selection:text-black overflow-hidden bg-[#07090E]">
      {/* 1. Thin Spine (56px) with User Account trigger */}
      <ThinSpine
        activeKey={activeKey}
        onSelectSubsystem={handleSelectSubsystem}
        onToggleDrawer={handleToggleDrawer}
        onToggleFullscreen={handleToggleFullscreen}
        onOpenProfile={() => setProfileModalOpen(true)}
        isProfileOpen={profileModalOpen}
        user={user}
        hasUpdateAvailable={hasUpdateAvailable}
      />

      {/* 2. Slide-Over Frosted Glass HUD Drawer */}
      <SubsystemsDrawer
        isOpen={drawerOpen}
        onClose={handleCloseDrawer}
        onSelectSubsystem={handleSelectSubsystem}
        onOpenProfile={() => setProfileModalOpen(true)}
        user={user}
      />

      {/* 3. Full-Bleed 100% iFrame Viewport Area */}
      <ViewportFrame
        subsystem={activeSubsystem}
        useLiveUrl={isLiveHost}
        customUrls={customUrls}
      />

      {/* 4. Google-Style User Account & SSO Session Popout */}
      <UserProfileModal
        isOpen={profileModalOpen}
        onClose={handleCloseProfile}
        user={user}
        onOpenSettings={handleOpenProfileSettings}
      />

      {/* Toast Notification */}
      {toastMessage && (
        <div
          id="toast"
          className="fixed bottom-6 right-6 z-50 bg-[#111622] border border-[#00f2fe]/40 px-5 py-2.5 rounded-xl shadow-2xl text-xs font-mono text-white flex items-center gap-2.5 animate-in fade-in"
          role="status"
        >
          <CheckCircle2 className="w-4 h-4 text-[#00f2fe]" />
          <span>{toastMessage}</span>
        </div>
      )}
    </div>
  );
}

export default App;
