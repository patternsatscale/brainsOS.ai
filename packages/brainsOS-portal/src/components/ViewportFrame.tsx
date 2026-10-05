import React, { useState, useRef } from 'react';
import {
  ExternalLink,
  RotateCw,
  Terminal,
  Mail,
  Shield,
  Network,
  Activity,
  HelpCircle,
  Radio
} from 'lucide-react';
import { Subsystem, SUBSYSTEMS } from '../data/subsystems';

interface ViewportFrameProps {
  subsystem: Subsystem;
  useLiveUrl?: boolean;
}

export const ViewportFrame: React.FC<ViewportFrameProps> = ({
  subsystem,
  useLiveUrl = false
}) => {
  const iframeRefs = useRef<Record<string, HTMLIFrameElement | null>>({});
  const [visitedKeys, setVisitedKeys] = useState<string[]>(() => [subsystem.id]);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Lazy-mount: Keep track of all visited subsystems so their iframes persist across tab changes
  React.useEffect(() => {
    setVisitedKeys((prev) => (prev.includes(subsystem.id) ? prev : [...prev, subsystem.id]));
  }, [subsystem.id]);

  const renderIcon = (id: string, color: string) => {
    const props = { className: "w-4 h-4", style: { color } };
    switch (id) {
      case 'console':
        return <Terminal {...props} />;
      case 'comms':
        return <Mail {...props} />;
      case 'security':
        return <Shield {...props} />;
      case 'network':
        return <Network {...props} />;
      case 'trace':
        return <Activity {...props} />;
      case 'help':
        return <HelpCircle {...props} />;
      default:
        return <Terminal {...props} />;
    }
  };

  const computeLiveUrl = (item: Subsystem) => {
    if (typeof window === 'undefined') return item.route;
    const host = window.location.hostname;
    const proto = window.location.protocol;
    const port = window.location.port ? `:${window.location.port}` : '';

    if (item.id === 'trace' || item.route === '/langfuse/') {
      if (!host.startsWith('langfuse.')) {
        return `${proto}//langfuse.${host}${port}/`;
      }
    }
    if (item.id === 'security' || item.id === 'control' || item.route === '/proxy/') {
      return `${proto}//${host}${port}/ui/`;
    }
    return item.route;
  };

  const liveUrl = React.useMemo(() => computeLiveUrl(subsystem), [subsystem]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    const activeFrame = iframeRefs.current[subsystem.id];
    if (activeFrame) {
      if (useLiveUrl) {
        activeFrame.src = liveUrl;
      } else {
        activeFrame.srcdoc = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{margin:0;padding:0;background:#0B0E14;overflow:hidden;}</style></head><body>${subsystem.previewHtml}</body></html>`;
      }
    }
    setTimeout(() => setIsRefreshing(false), 500);
  };

  const handleOpenExternal = () => {
    window.open(useLiveUrl ? liveUrl : subsystem.route, '_blank');
  };

  return (
    <main className="flex-1 h-screen flex flex-col bg-[#07090E] relative overflow-hidden">
      {/* Ultra-Slim Subsystem Header Bar (h-10) */}
      <header className="h-10 px-4 border-b border-white/10 bg-[#0B0E14]/90 backdrop-blur-md flex items-center justify-between text-xs font-mono shrink-0 z-10 select-none">
        <div className="flex items-center gap-2.5">
          {renderIcon(subsystem.id, subsystem.color)}
          <span className="font-headline font-bold text-white tracking-tight">
            {subsystem.title}
          </span>
          <span className="text-slate-600">•</span>
          <span className="text-slate-400 text-[11px] truncate max-w-xs sm:max-w-md">
            {useLiveUrl ? liveUrl : subsystem.route}
          </span>
          <span className="text-slate-600 hidden sm:inline">•</span>
          <div className="hidden sm:flex items-center gap-1.5 text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20">
            <Radio className="w-2.5 h-2.5 animate-pulse" />
            <span>NOMINAL</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Reload button */}
          <button
            onClick={handleRefresh}
            className={`p-1 px-2 rounded-lg bg-white/5 hover:bg-white/15 border border-white/10 text-slate-400 hover:text-white transition-all text-xs flex items-center gap-1 ${
              isRefreshing ? 'opacity-50 pointer-events-none' : ''
            }`}
            title="Reload Viewport"
          >
            <RotateCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>

          {/* Open in Clean Tab */}
          <button
            onClick={handleOpenExternal}
            className="p-1 px-2.5 rounded-lg bg-white/5 hover:bg-white/15 border border-white/10 text-slate-400 hover:text-white transition-all text-xs flex items-center gap-1.5"
            title="Open in Clean Browser Tab"
          >
            <ExternalLink className="w-3 h-3" />
            <span className="text-[10px] hidden sm:inline">Open in New Tab</span>
          </button>
        </div>
      </header>

      {/* The Active 100% Full-Bleed iFrame Area (96%+ screen real estate) */}
      <div className="flex-1 w-full h-full relative overflow-hidden bg-[#090C12]">
        {visitedKeys.map((key) => {
          const item = SUBSYSTEMS[key];
          if (!item) return null;
          const isActive = key === subsystem.id;
          const targetUrl = computeLiveUrl(item);

          return (
            <iframe
              key={key}
              ref={(el) => {
                iframeRefs.current[key] = el;
              }}
              id={isActive ? "subsystem-frame" : `subsystem-frame-${key}`}
              name={`subsystem-frame-${key}`}
              className={`absolute inset-0 w-full h-full border-0 block transition-opacity duration-150 ${
                isActive
                  ? 'visible opacity-100 pointer-events-auto z-10'
                  : 'invisible opacity-0 pointer-events-none -z-10'
              }`}
              title={`${item.title} Subsystem Viewport`}
              sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
              src={useLiveUrl ? targetUrl : undefined}
              srcDoc={
                useLiveUrl
                  ? undefined
                  : `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{margin:0;padding:0;background:#0B0E14;overflow:hidden;}</style></head><body>${item.previewHtml}</body></html>`
              }
            />
          );
        })}
      </div>
    </main>
  );
};
