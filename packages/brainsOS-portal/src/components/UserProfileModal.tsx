import React, { useState, useEffect } from 'react';
import {
  X,
  LogOut,
  Settings,
  AlertTriangle,
  RefreshCw
} from 'lucide-react';
import { AuthenticatedUser, DEFAULT_USER, getInitials } from '../types/user';

interface UserProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  user?: AuthenticatedUser;
  onLogout?: () => void;
  onOpenSettings?: () => void;
}

export const UserProfileModal: React.FC<UserProfileModalProps> = ({
  isOpen,
  onClose,
  user: initialUser,
  onLogout,
  onOpenSettings
}) => {
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [internalUser, setInternalUser] = useState<AuthenticatedUser>(initialUser || DEFAULT_USER);

  // Sync internal user if prop updates
  useEffect(() => {
    if (initialUser) {
      setInternalUser(initialUser);
    }
  }, [initialUser]);

  // If user prop was not provided, fetch user directly
  useEffect(() => {
    if (!isOpen || initialUser) return;

    fetch('/api/v3/core/users/me/', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && data.username) {
          setInternalUser({
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
        // Keep default user on preview / error
      });
  }, [isOpen, initialUser]);

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

  // Reset confirmation state when popout closes
  useEffect(() => {
    if (!isOpen) {
      setConfirmLogout(false);
      setLoggingOut(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const activeUser = initialUser || internalUser;

  const handleExecuteLogout = () => {
    setLoggingOut(true);
    if (onLogout) {
      onLogout();
      return;
    }

    const isLive = typeof window !== 'undefined' && (
      window.location.hostname.includes('brainsos') ||
      window.location.search.includes('live=true')
    );

    setTimeout(() => {
      if (isLive) {
        window.location.href = '/flows/-/default/invalidation/?next=/flows/-/default/authentication/';
      } else {
        window.location.href = window.location.port === '3034' 
          ? 'http://localhost:3033/login.html'
          : '/login.html';
      }
    }, 500);
  };

  return (
    <>
      {/* 1. Transparent Backdrop: dismisses popout when clicking anywhere outside */}
      <div
        className="fixed inset-0 z-40 bg-black/25 backdrop-blur-[1px] transition-opacity duration-150"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* 2. Anchored Popout Card (Google-style bottom-left spine popout) */}
      <div
        className="fixed left-3 sm:left-20 bottom-16 sm:bottom-3.5 z-50 w-[calc(100vw-1.5rem)] sm:w-[350px] max-w-[360px] bg-[#121620] border border-white/10 rounded-3xl shadow-[0_20px_50px_rgba(0,0,0,0.85)] p-4 text-slate-200 animate-in fade-in zoom-in-95 duration-150 select-none"
        role="dialog"
        aria-modal="true"
        aria-label="User Account Popout"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header Row with Close 'X' */}
        <div className="flex items-center justify-between mb-3 px-1">
          <div className="flex items-center gap-1.5 font-mono text-[11px] text-slate-400">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_6px_#10b981]" />
            <span className="font-semibold text-slate-300">brainsOS Account</span>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white flex items-center justify-center transition-colors"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Hero User Identity Box (Google Style) */}
        <div className="p-3.5 rounded-2xl bg-[#1a2130] border border-white/5 flex items-center gap-3.5 shadow-inner">
          <div className="relative shrink-0">
            <div className="w-13 h-13 rounded-full bg-gradient-to-br from-[#00f2fe]/20 to-emerald-500/20 border-2 border-[#00f2fe]/40 flex items-center justify-center text-[#00f2fe] font-mono text-base font-bold shadow-[0_0_15px_rgba(0,242,254,0.15)]">
              {getInitials(activeUser.name, activeUser.username)}
            </div>
            <span
              className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-500 ring-2 ring-[#1a2130] shadow-[0_0_8px_#10b981] animate-pulse"
              title="Active Authentik SSO Session"
            />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-headline font-bold text-sm text-white truncate">
              {activeUser.name || activeUser.username}
            </div>
            <div className="font-mono text-xs text-slate-400 truncate mt-0.5">
              {activeUser.email}
            </div>
            <div className="flex items-center gap-1.5 mt-1.5 font-mono">
              <span className="text-[11px] text-[#00f2fe] font-medium">
                @{activeUser.username}
              </span>
              <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-[#00f2fe]/10 text-[#00f2fe] border border-[#00f2fe]/20 font-semibold">
                {activeUser.isSuperuser ? 'ADMIN' : 'OPERATOR'}
              </span>
            </div>
          </div>
        </div>

        {/* Action Rows Container */}
        <div className="mt-3 rounded-2xl bg-[#1a2130] overflow-hidden border border-white/5">
          {/* Sign out */}
          {!confirmLogout ? (
            <button
              onClick={() => setConfirmLogout(true)}
              id="btn-logout-init"
              className="w-full px-4 py-3 flex items-center gap-3 hover:bg-red-500/10 text-slate-300 hover:text-red-300 transition-colors text-left group"
            >
              <div className="w-7 h-7 rounded-full bg-white/5 group-hover:bg-red-500/20 flex items-center justify-center text-slate-300 group-hover:text-red-400 shrink-0 transition-colors">
                <LogOut className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium text-white group-hover:text-red-300 transition-colors">
                  Sign out
                </div>
                <div className="text-[10px] font-mono text-slate-500 group-hover:text-red-400/80">
                  End session for @{activeUser.username}
                </div>
              </div>
            </button>
          ) : (
            <div className="p-3 bg-red-950/30 space-y-2.5 animate-in fade-in">
              <div className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                <div className="text-[11px] text-slate-300 leading-snug">
                  <span className="font-semibold text-red-300 block">Sign out of Authentik SSO?</span>
                  This will invalidate active tokens for @{activeUser.username}.
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleExecuteLogout}
                  disabled={loggingOut}
                  id="btn-confirm-logout"
                  className="flex-1 py-1.5 px-3 rounded-lg bg-red-600 hover:bg-red-500 text-white font-medium text-xs flex items-center justify-center gap-1.5 transition-colors shadow-lg disabled:opacity-50"
                >
                  {loggingOut ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Signing out...</span>
                    </>
                  ) : (
                    <>
                      <LogOut className="w-3.5 h-3.5" />
                      <span>Confirm Sign Out</span>
                    </>
                  )}
                </button>
                <button
                  onClick={() => setConfirmLogout(false)}
                  disabled={loggingOut}
                  className="py-1.5 px-3 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 text-xs transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Profile Settings Pill Button: Loads settings directly into portal iframe */}
        <button
          onClick={() => {
            onClose();
            onOpenSettings?.();
          }}
          id="btn-profile-settings"
          className="mt-3 w-full py-2.5 px-4 rounded-full bg-[#1a2130] hover:bg-[#232b3d] border border-white/10 hover:border-[#00f2fe]/40 text-white font-medium text-xs flex items-center justify-center gap-2 transition-all shadow-md group cursor-pointer"
          title="Open Profile Settings in Viewport"
        >
          <Settings className="w-3.5 h-3.5 text-[#00f2fe] group-hover:rotate-45 transition-transform" />
          <span>Profile Settings</span>
        </button>

        {/* Footer Note */}
        <div className="mt-3 pt-2 text-center text-[10.5px] font-mono text-slate-500 flex items-center justify-center gap-2 border-t border-white/5">
          <span>brainsOS Appliance</span>
          <span>•</span>
          <span className="text-slate-400">
            {typeof window !== 'undefined' ? window.location.hostname : 'local.brainsos.ai'}
          </span>
        </div>
      </div>
    </>
  );
};
