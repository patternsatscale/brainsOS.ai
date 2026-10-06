import { useState, useCallback, useEffect } from 'react';
import { ThinSpine } from './components/ThinSpine';
import { SubsystemsDrawer } from './components/SubsystemsDrawer';
import { ViewportFrame } from './components/ViewportFrame';
import { UserProfileModal } from './components/UserProfileModal';
import { SUBSYSTEMS } from './data/subsystems';
import { useHotkeys } from './hooks/useHotkeys';
import { CheckCircle2 } from 'lucide-react';
import { AuthenticatedUser, DEFAULT_USER } from './types/user';

const getInitialKey = (): string => {
  if (typeof window === 'undefined') return 'comms';
  const path = window.location.pathname.replace(/\/$/, '');
  const hash = window.location.hash.replace(/^#/, '');
  if (hash && SUBSYSTEMS[hash]) return hash;
  if (path === '/docs') return 'help';
  if (path === '/editor') return 'console';
  if (path === '/mail' || path === '/SOGo') return 'comms';
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

  // Auto-detect live mode if hostname is a brainsos domain or live=true query param
  const isLiveHost = typeof window !== 'undefined' && (
    window.location.search.includes('live=true') ||
    window.location.hostname.includes('brainsos')
  );

  // Fetch real authenticated user identity from Authentik API immediately on load
  useEffect(() => {
    fetch('/api/v3/core/users/me/', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && data.username) {
          setUser({
            username: data.username,
            name: data.name || (data.username.toLowerCase() === 'admin' ? 'Appliance Administrator' : data.username),
            email: data.email || `${data.username}@brainsos.ai`,
            isSuperuser: Boolean(data.is_superuser),
            lastLogin: data.last_login
              ? new Date(data.last_login).toLocaleString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : 'Active SSO Session',
            avatarUrl: data.avatar || undefined,
          });
        }
      })
      .catch(() => {
        // Fallback gracefully on local preview or connection error
      });
  }, []);

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
