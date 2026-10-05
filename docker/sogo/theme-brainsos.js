// brainsOS Obsidian Dark Theme Injector for SOGo Webmail
(function() {
  function applyBrainsOSTheme() {
    var cssId = 'brainsos-sogo-theme';
    if (!document.getElementById(cssId)) {
      var head = document.getElementsByTagName('head')[0] || document.documentElement;
      var link = document.createElement('link');
      link.id = cssId;
      link.rel = 'stylesheet';
      link.type = 'text/css';
      link.href = '/SOGo.woa/WebServerResources/css/theme-brainsos.css';
      link.media = 'all';
      head.appendChild(link);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyBrainsOSTheme);
  } else {
    applyBrainsOSTheme();
  }
})();
