import React from 'react';
import {
  Menu,
  Terminal,
  Mail,
  Shield,
  Network,
  Activity,
  Users,
  HelpCircle,
  Maximize2
} from 'lucide-react';
import { SUBSYSTEMS, Subsystem } from '../data/subsystems';
import { AuthenticatedUser, getInitials } from '../types/user';

interface ThinSpineProps {
  activeKey: string;
  onSelectSubsystem: (key: string) => void;
  onToggleDrawer: () => void;
  onToggleFullscreen: () => void;
  onOpenProfile: () => void;
  isProfileOpen?: boolean;
  user?: AuthenticatedUser;
}

export const ThinSpine: React.FC<ThinSpineProps> = ({
  activeKey,
  onSelectSubsystem,
  onToggleDrawer,
  onToggleFullscreen,
  onOpenProfile,
  isProfileOpen = false,
  user
}) => {
  const renderIcon = (sub: Subsystem) => {
    switch (sub.id) {
      case 'console':
        return <Terminal className="w-5 h-5" />;
      case 'comms':
        return <Mail className="w-5 h-5" />;
      case 'security':
        return <Shield className="w-5 h-5" />;
      case 'network':
        return <Network className="w-5 h-5" />;
      case 'trace':
        return <Activity className="w-5 h-5" />;
      case 'users':
        return <Users className="w-5 h-5" />;
      case 'help':
        return <HelpCircle className="w-5 h-5" />;
      default:
        return <Terminal className="w-5 h-5" />;
    }
  };

  return (
    <aside
      className="w-14 sm:w-16 h-screen bg-[#0B0E14] border-r border-white/10 flex flex-col justify-between items-center py-3.5 z-40 shrink-0 select-none shadow-2xl"
      aria-label="brainsOS Thin Spine"
    >
      {/* Top: Hamburger Menu Button */}
      <div className="flex flex-col items-center">
        <button
          onClick={onToggleDrawer}
          id="btn-hamburger"
          className="w-8 h-8 rounded-lg bg-white/5 hover:bg-white/10 hover:border-white/20 border border-white/10 flex items-center justify-center text-slate-400 hover:text-white transition-all group"
          title="Toggle Subsystems Overlay (⌘K / ⌘B / ☰)"
        >
          <Menu className="w-4 h-4 group-hover:scale-110 transition-transform" />
        </button>
      </div>

      {/* Center: The 6 Subsystem Squircle Buttons */}
      <nav className="flex flex-col items-center gap-2.5 my-2">
        {Object.values(SUBSYSTEMS).map((sub) => {
          const isActive = activeKey === sub.id;
          const isHelp = sub.id === 'help';

          return (
            <React.Fragment key={sub.id}>
              {isHelp && <div className="w-6 h-px bg-white/10 my-0.5" />}
              <button
                onClick={() => onSelectSubsystem(sub.id)}
                id={`spine-btn-${sub.id}`}
                className={`relative w-9 h-9 sm:w-10 sm:h-10 rounded-xl flex items-center justify-center transition-all duration-200 group ${
                  isActive
                    ? 'bg-white/[0.08] shadow-[0_0_12px_rgba(0,0,0,0.5)]'
                    : 'bg-white/[0.04] border-white/10 hover:bg-white/[0.08]'
                }`}
                style={{
                  borderColor: isActive ? sub.color : 'rgba(255, 255, 255, 0.1)',
                  borderWidth: '1px',
                  color: isActive ? sub.color : 'rgba(148, 163, 184, 0.8)'
                }}
                title={`${sub.title} • ${sub.hotkey}`}
              >
                <div
                  className="transition-transform group-hover:scale-110"
                  style={{ color: isActive ? sub.color : undefined }}
                >
                  {renderIcon(sub)}
                </div>
              </button>
            </React.Fragment>
          );
        })}
      </nav>

      {/* Vertical Brand Spine: BRAINSOS.AI */}
      <div className="my-auto py-4 flex items-center justify-center select-none pointer-events-none">
        <span className="font-mono text-[11px] tracking-[0.32em] text-slate-500 font-semibold uppercase [writing-mode:vertical-rl] rotate-180 transition-colors">
          BRAINSOS<span className="text-[#00f2fe]">.AI</span>
        </span>
      </div>

      {/* Bottom: Fullscreen & Operator Profile Trigger */}
      <div className="flex flex-col items-center gap-2.5 text-slate-400 pb-2">
        <button
          onClick={onToggleFullscreen}
          id="btn-fullscreen"
          className="w-8 h-8 rounded-lg hover:bg-white/5 hover:text-[#00f2fe] flex items-center justify-center text-xs transition-colors"
          title="Toggle Full Screen (F11)"
        >
          <Maximize2 className="w-4 h-4" />
        </button>

        {/* User Account & SSO Session Trigger */}
        <button
          onClick={onOpenProfile}
          id="btn-user-profile"
          className={`relative w-9 h-9 sm:w-10 sm:h-10 rounded-xl flex items-center justify-center transition-all duration-200 group border ${
            isProfileOpen
              ? 'bg-[#00f2fe]/20 border-[#00f2fe] shadow-[0_0_15px_rgba(0,242,254,0.35)]'
              : 'bg-white/[0.04] border-white/10 hover:bg-white/[0.08] hover:border-[#00f2fe]/40'
          }`}
          title={`${user?.name || user?.username || 'Account'} (@${user?.username || 'admin'})`}
          aria-label="User Account and SSO Session"
        >
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#00f2fe]/20 to-emerald-500/20 flex items-center justify-center text-[#00f2fe] font-mono text-[11px] font-bold tracking-tight">
            {getInitials(user?.name, user?.username)}
          </div>
          {/* Active Session Status Indicator on the avatar */}
          <span
            className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 ring-2 ring-[#0B0E14] shadow-[0_0_6px_#10b981] animate-pulse"
            title={`Appliance Active • @${user?.username || 'admin'}`}
          />
        </button>
      </div>
    </aside>
  );
};
