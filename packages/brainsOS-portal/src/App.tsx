import { useState, useCallback } from 'react';
import { ThinSpine } from './components/ThinSpine';
import { SubsystemsDrawer } from './components/SubsystemsDrawer';
import { ViewportFrame } from './components/ViewportFrame';
import { UserProfileModal } from './components/UserProfileModal';
import { SUBSYSTEMS } from './data/subsystems';
import { useHotkeys } from './hooks/useHotkeys';
import { CheckCircle2 } from 'lucide-react';

export function App() {
  const [activeKey, setActiveKey] = useState<string>('console');
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);
  const [profileModalOpen, setProfileModalOpen] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Auto-detect live mode if hostname is a brainsos domain or live=true query param
  const isLiveHost = typeof window !== 'undefined' && (
    window.location.search.includes('live=true') ||
    window.location.hostname.includes('brainsos')
  );

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((current) => (current === msg ? null : current));
    }, 2200);
  }, []);

  const handleSelectSubsystem = useCallback((key: string) => {
    if (SUBSYSTEMS[key]) {
      setActiveKey(key);
      showToast(`Switched to ${SUBSYSTEMS[key].title}`);
    }
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
      {/* 1. Thin Spine (56px) with Operator Profile trigger */}
      <ThinSpine
        activeKey={activeKey}
        onSelectSubsystem={handleSelectSubsystem}
        onToggleDrawer={handleToggleDrawer}
        onToggleFullscreen={handleToggleFullscreen}
        onOpenProfile={() => setProfileModalOpen(true)}
        isProfileOpen={profileModalOpen}
      />

      {/* 2. Slide-Over Frosted Glass HUD Drawer */}
      <SubsystemsDrawer
        isOpen={drawerOpen}
        onClose={handleCloseDrawer}
        onSelectSubsystem={handleSelectSubsystem}
        onOpenProfile={() => setProfileModalOpen(true)}
      />

      {/* 3. Full-Bleed 100% iFrame Viewport Area */}
      <ViewportFrame
        subsystem={activeSubsystem}
        useLiveUrl={isLiveHost}
      />

      {/* 4. Operator Profile & SSO Session Modal */}
      <UserProfileModal
        isOpen={profileModalOpen}
        onClose={handleCloseProfile}
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
