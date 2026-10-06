export interface AuthenticatedUser {
  username: string;
  name: string;
  email: string;
  isSuperuser: boolean;
  lastLogin: string;
  avatarUrl?: string;
}

export const DEFAULT_USER: AuthenticatedUser = {
  username: 'admin',
  name: 'Appliance Administrator',
  email: 'admin@brainsos.ai',
  isSuperuser: true,
  lastLogin: 'Active SSO Session',
};

export const getInitials = (name?: string, username?: string): string => {
  const target = (name || username || 'AD').trim();
  const parts = target.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  if (target.length >= 2) {
    return target.substring(0, 2).toUpperCase();
  }
  return target.toUpperCase();
};
