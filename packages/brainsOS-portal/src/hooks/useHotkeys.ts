import { useEffect } from 'react';

interface HotkeyOptions {
  onSelectSubsystem: (id: string) => void;
  onToggleDrawer: () => void;
  onCloseDrawer: () => void;
  drawerOpen: boolean;
  onToggleFullscreen: () => void;
  onToggleProfile?: () => void;
  onCloseProfile?: () => void;
  profileOpen?: boolean;
}

export function useHotkeys({
  onSelectSubsystem,
  onToggleDrawer,
  onCloseDrawer,
  drawerOpen,
  onToggleFullscreen,
  onToggleProfile,
  onCloseProfile,
  profileOpen = false,
}: HotkeyOptions) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // ⌘K or ⌘B toggles drawer
      if ((e.metaKey || e.ctrlKey) && (e.key.toLowerCase() === 'k' || e.key.toLowerCase() === 'b')) {
        e.preventDefault();
        onToggleDrawer();
        return;
      }

      // ⌘U toggles Operator Profile Modal
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'u') {
        e.preventDefault();
        onToggleProfile?.();
        return;
      }

      // Escape closes profile modal or drawer
      if (e.key === 'Escape') {
        if (profileOpen) {
          e.preventDefault();
          onCloseProfile?.();
          return;
        }
        if (drawerOpen) {
          e.preventDefault();
          onCloseDrawer();
          return;
        }
      }

      // F11 toggles fullscreen
      if (e.key === 'F11') {
        e.preventDefault();
        onToggleFullscreen();
        return;
      }

      // Subsystem number hotkeys: Alt+1 through Alt+9 (plus ⌘/Ctrl+1..9, I, and H)
      if (e.altKey || e.metaKey || e.ctrlKey) {
        const keyMap: Record<string, string> = {
          '1': 'mail',
          '2': 'auth',
          '3': 'gateway',
          '4': 'telemetry',
          '5': 'egress',
          '6': 'editor',
          '7': 'git',
          '8': 'system',
          '9': 'help',
          '0': 'system',
          'i': 'auth',
          'h': 'help',
        };

        const target = keyMap[e.key.toLowerCase()];
        if (target) {
          e.preventDefault();
          onSelectSubsystem(target);
          if (drawerOpen) {
            onCloseDrawer();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    onSelectSubsystem,
    onToggleDrawer,
    onCloseDrawer,
    drawerOpen,
    onToggleFullscreen,
    onToggleProfile,
    onCloseProfile,
    profileOpen,
  ]);
}
