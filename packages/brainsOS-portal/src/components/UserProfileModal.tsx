import React, { useState, useEffect } from 'react';
import {
  X,
  LogOut,
  Shield,
  CheckCircle2,
  Lock,
  AlertTriangle,
  RefreshCw
} from 'lucide-react';

interface UserProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  onLogout?: () => void;
}

export const UserProfileModal: React.FC<UserProfileModalProps> = ({
  isOpen,
  onClose,
  onLogout
}) => {
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        if (confirmLogout) {
          setConfirmLogout(false);
        } else {
          onClose();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, confirmLogout, onClose]);

  // Reset confirmation when closed
  useEffect(() => {
    if (!isOpen) {
      setConfirmLogout(false);
      setLoggingOut(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleExecuteLogout = () => {
    setLoggingOut(true);
    if (onLogout) {
      onLogout();
      return;
    }

    // Default logout flow:
    // In live deployment: redirect to Authentik sign-out flow
    // In local preview: redirect to login.html
    const isLive = typeof window !== 'undefined' && (
      window.location.hostname.includes('brainsos') ||
      window.location.search.includes('live=true')
    );

    setTimeout(() => {
      if (isLive) {
        window.location.href = '/outpost.goauthentik.io/sign_out';
      } else {
        // Local preview redirect to Authentik mockup login page
        window.location.href = window.location.port === '3034' 
          ? 'http://localhost:3033/login.html'
          : '/login.html';
      }
    }, 700);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-in fade-in duration-150"
      role="dialog"
      aria-modal="true"
      aria-labelledby="profile-modal-title"
    >
      {/* Click outside backdrop */}
      <div
        className="fixed inset-0 -z-10"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Card */}
      <div
        className="relative w-full max-w-md bg-[#0B0E14] border border-white/10 rounded-2xl shadow-2xl overflow-hidden text-slate-200 border-t-2 border-t-[#00f2fe]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header Bar */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10 bg-white/[0.02]">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-[#00f2fe]" />
            <span
              id="profile-modal-title"
              className="font-headline font-bold text-sm tracking-tight text-white"
            >
              Operator Identity & SSO
            </span>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white flex items-center justify-center transition-colors"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 space-y-4">
          {/* Identity Header Card */}
          <div className="flex items-center gap-3.5 p-3.5 rounded-xl bg-white/[0.03] border border-white/5">
            <div className="relative shrink-0">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-[#00f2fe]/20 to-emerald-500/20 border border-[#00f2fe]/40 flex items-center justify-center text-[#00f2fe] font-mono text-base font-bold shadow-[0_0_15px_rgba(0,242,254,0.15)]">
                OP
              </div>
              <span
                className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-500 ring-2 ring-[#0B0E14] shadow-[0_0_8px_#10b981] animate-pulse"
                title="Active Session"
              />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-headline font-bold text-sm text-white truncate">
                  brainsOS Operator
                </span>
                <span className="font-mono text-[9px] uppercase px-1.5 py-0.5 rounded bg-[#00f2fe]/10 text-[#00f2fe] border border-[#00f2fe]/20 font-semibold shrink-0">
                  ROOT
                </span>
              </div>
              <div className="font-mono text-xs text-slate-400 mt-0.5">
                @operator
              </div>
              <div className="font-mono text-[10px] text-slate-500 mt-0.5">
                operator@brainsos.ai
              </div>
            </div>
          </div>

          {/* Authentik SSO Credential Status */}
          <div className="rounded-xl bg-[#121620] border border-white/5 p-3.5 space-y-2.5">
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2 text-slate-300 font-medium">
                <Lock className="w-3.5 h-3.5 text-emerald-400" />
                <span>Authentik SSO Ingress Status</span>
              </div>
              <span className="font-mono text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-semibold">
                FORWARD_AUTH OK
              </span>
            </div>

            <div className="font-mono text-[10.5px] space-y-1.5 pt-1 text-slate-400 border-t border-white/5">
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Injected Header:</span>
                <code className="text-[#00f2fe] bg-black/30 px-1.5 py-0.5 rounded">Remote-User: operator</code>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Identity Provider:</span>
                <span className="text-slate-300">Authentik Core (v2024.8)</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-500">Appliance Target:</span>
                <span className="text-slate-300">ASUS Ascent GX10 (ARM64)</span>
              </div>
            </div>
          </div>

          {/* Subsystem Credential Propagation */}
          <div className="space-y-1.5">
            <div className="font-mono text-[10px] uppercase tracking-wider text-slate-400 font-semibold px-0.5">
              Subsystem Delegation
            </div>
            <div className="grid grid-cols-2 gap-2 font-mono text-[11px]">
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/5 flex items-center gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="text-slate-300 truncate">Cloud IDE (code-server)</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/5 flex items-center gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="text-slate-300 truncate">SOGo Mail / Comms</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/5 flex items-center gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="text-slate-300 truncate">Hermes Runner UI</span>
              </div>
              <div className="p-2 rounded-lg bg-white/[0.02] border border-white/5 flex items-center gap-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="text-slate-300 truncate">LiteLLM Gateway</span>
              </div>
            </div>
          </div>

          {/* Logout / Session Termination Section */}
          <div className="pt-2 border-t border-white/10">
            {!confirmLogout ? (
              <button
                onClick={() => setConfirmLogout(true)}
                id="btn-logout-init"
                className="w-full py-2.5 px-4 rounded-xl bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 hover:border-red-500/50 text-red-400 hover:text-red-300 font-medium text-xs flex items-center justify-center gap-2 transition-all group shadow-lg"
              >
                <LogOut className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
                <span>Log Out of Appliance (@operator)</span>
              </button>
            ) : (
              <div className="p-3.5 rounded-xl bg-red-950/30 border border-red-500/40 space-y-3 animate-in fade-in">
                <div className="flex items-start gap-2.5">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                  <div className="text-xs text-slate-300 leading-snug">
                    <span className="font-semibold text-red-300 block">End Active SSO Session?</span>
                    This will invalidate your Authentik session tokens and forward-auth headers across all appliance subsystems.
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleExecuteLogout}
                    disabled={loggingOut}
                    id="btn-confirm-logout"
                    className="flex-1 py-2 px-3 rounded-lg bg-red-600 hover:bg-red-500 text-white font-medium text-xs flex items-center justify-center gap-1.5 transition-colors shadow-lg disabled:opacity-50"
                  >
                    {loggingOut ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        <span>Signing out...</span>
                      </>
                    ) : (
                      <>
                        <LogOut className="w-3.5 h-3.5" />
                        <span>Confirm Log Out</span>
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => setConfirmLogout(false)}
                    disabled={loggingOut}
                    className="py-2 px-3 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-xs transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
