import React from 'react';
import { X, ExternalLink, LogOut } from 'lucide-react';
import { SUBSYSTEMS } from '../data/subsystems';

interface SubsystemsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectSubsystem: (key: string) => void;
  onOpenProfile?: () => void;
}

export const SubsystemsDrawer: React.FC<SubsystemsDrawerProps> = ({
  isOpen,
  onClose,
  onSelectSubsystem,
  onOpenProfile,
}) => {
  const handleOpenExternal = (e: React.MouseEvent, route: string) => {
    e.stopPropagation();
    window.open(route, '_blank');
  };

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/60 backdrop-blur-[2px] transition-opacity duration-200 z-[45]"
          aria-hidden="true"
        />
      )}

      {/* Slide-out Frosted Glass HUD Drawer */}
      <div
        id="subsystems-drawer"
        className={`frosted-drawer fixed top-0 left-14 sm:left-16 w-72 sm:w-76 max-w-[calc(100vw-4rem)] h-screen z-50 flex flex-col justify-between p-4 ${
          isOpen ? 'drawer-open' : 'drawer-closed'
        }`}
        role="dialog"
        aria-modal="true"
        aria-label="Appliance Subsystems Overlay"
      >
        {/* Drawer Header */}
        <div>
          <div className="flex items-center justify-between border-b border-white/10 pb-3 mb-3.5">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-headline font-bold text-sm tracking-tight text-white">
                  brainsOS.AI
                </span>
                <span className="font-mono text-[9px] text-[#00f2fe] px-1.5 py-0.5 rounded bg-[#00f2fe]/10 border border-[#00f2fe]/20">
                  APPLIANCE
                </span>
              </div>
              <p className="font-mono text-[10px] tracking-wider uppercase text-slate-500 mt-0.5 font-medium">
                SUBSYSTEMS
              </p>
            </div>
            <button
              onClick={onClose}
              className="w-6 h-6 rounded-md bg-white/5 hover:bg-white/10 flex items-center justify-center text-slate-400 hover:text-white transition-colors"
              title="Close Menu (Esc)"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Subsystem Launch Cards */}
          <div className="space-y-2">
            {Object.values(SUBSYSTEMS).map((sub) => (
              <div
                key={sub.id}
                onClick={() => {
                  onSelectSubsystem(sub.id);
                  onClose();
                }}
                className="p-2.5 rounded-xl bg-[#151a26]/80 hover:bg-[#151a26] border border-white/5 hover:border-white/20 cursor-pointer transition-all flex items-center justify-between group"
              >
                <div className="pr-2 min-w-0">
                  <div
                    className="font-headline font-semibold text-xs transition-colors"
                    style={{ color: sub.color }}
                  >
                    {sub.title}
                  </div>
                  <div className="font-mono text-[10px] text-slate-400 leading-tight mt-0.5 truncate">
                    {sub.desc}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <kbd className="font-mono text-[9px] text-slate-500 bg-white/5 border border-white/5 px-1 py-0.5 rounded">
                    {sub.hotkey}
                  </kbd>
                  <button
                    onClick={(e) => handleOpenExternal(e, sub.route)}
                    className="w-6 h-6 rounded-md bg-white/5 hover:bg-white/15 border border-white/10 text-slate-400 hover:text-white flex items-center justify-center transition-all"
                    title={`Open ${sub.title} in New Tab`}
                  >
                    <ExternalLink className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Drawer Footer: Operator Profile & Sign Out Bar + Appliance Info */}
        <div className="pt-3 border-t border-white/10 space-y-2.5">
          {onOpenProfile && (
            <button
              onClick={() => {
                onClose();
                onOpenProfile();
              }}
              id="drawer-btn-operator"
              className="w-full p-2 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/5 flex items-center justify-between text-left transition-all group"
              title="Operator Identity & SSO Session"
            >
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-md bg-[#00f2fe]/20 text-[#00f2fe] font-mono text-[10px] font-bold flex items-center justify-center">
                  OP
                </div>
                <div>
                  <div className="font-headline font-semibold text-xs text-white group-hover:text-[#00f2fe] transition-colors">
                    brainsOS Operator
                  </div>
                  <div className="font-mono text-[9px] text-slate-400">@operator • Authentik SSO</div>
                </div>
              </div>
              <LogOut className="w-3.5 h-3.5 text-slate-500 group-hover:text-red-400 transition-colors" />
            </button>
          )}

          <div className="font-mono text-[10.5px] text-slate-400 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Appliance Host:</span>
              <span className="text-[#00f2fe] font-medium">ASUS Ascent GX10</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">BrainsOS Version:</span>
              <span className="text-white/90">v1.0.0-arm64</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};
