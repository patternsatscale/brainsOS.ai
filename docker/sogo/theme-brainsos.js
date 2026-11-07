// brainsOS Obsidian Dark Theme & In-App Mailto Handler for SOGo Webmail
(function() {
  function applyBrainsOSTheme() {
    var cssId = 'brainsos-sogo-theme';
    if (!document.getElementById(cssId)) {
      var head = document.getElementsByTagName('head')[0] || document.documentElement;
      var link = document.createElement('link');
      link.id = cssId;
      link.rel = 'stylesheet';
      link.type = 'text/css';
      link.href = '/SOGo.woa/WebServerResources/css/theme-brainsos.css?v=20261107-1';
      link.media = 'all';
      head.appendChild(link);
    }
  }

  function installMailtoInterceptor() {
    if (window.__brainsosMailtoBound) return;
    window.__brainsosMailtoBound = true;

    document.addEventListener(
      'click',
      function(e) {
        var target = e.target;
        var link =
          target && typeof target.closest === 'function'
            ? target.closest('a[href^="mailto:"], a[href^="MAILTO:"]')
            : target && target.tagName === 'A'
              ? target
              : null;
        if (!link) return;

        var href = link.getAttribute('href');
        if (!href || !/^mailto:/i.test(href)) return;

        link.removeAttribute('target');
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') {
          e.stopImmediatePropagation();
        }

        var synthEvent = {
          target: link,
          currentTarget: link,
          stopPropagation: function() {},
          preventDefault: function() {}
        };

        if (window.$messageController && typeof window.$messageController.newMessage === 'function') {
          window.$messageController.newMessage(synthEvent, href);
          return;
        }

        var mbCtrl = window.$mailboxController;
        if (mbCtrl && mbCtrl.account && typeof mbCtrl.account.$newMessage === 'function' && window.angular) {
          var bodyEl = window.angular.element(document.body);
          var injector = bodyEl.injector && bodyEl.injector();
          var scope = bodyEl.scope && bodyEl.scope();
          if (injector) {
            var $mdDialog = injector.get('$mdDialog');
            var $q = injector.get('$q');
            mbCtrl.account.$newMessage({ mailto: href }).then(function(message) {
              var onCompleteDeferred = $q.defer();
              $mdDialog.show({
                parent: bodyEl,
                targetEvent: e,
                clickOutsideToClose: false,
                escapeToClose: false,
                templateUrl: 'UIxMailEditor',
                controller: 'MessageEditorController',
                controllerAs: 'editor',
                onComplete: function(s, el) {
                  return onCompleteDeferred.resolve(el);
                },
                locals: {
                  stateParent: scope,
                  stateAccount: mbCtrl.account,
                  stateMessage: message,
                  onCompletePromise: function() {
                    return onCompleteDeferred.promise;
                  }
                }
              });
            });
          }
        }
      },
      true
    );
  }

  installMailtoInterceptor();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyBrainsOSTheme);
  } else {
    applyBrainsOSTheme();
  }
})();
