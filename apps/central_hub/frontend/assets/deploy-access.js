(function () {
  const deployLinks = Array.from(document.querySelectorAll('[data-deploy-link]'));
  const currentPath = (window.location.pathname || '').replace(/\/+$/, '') || '/';

  if (!deployLinks.length && currentPath !== '/pages/deploy.html') {
    return;
  }

  function setDeployLinkVisibility(isVisible) {
    deployLinks.forEach((link) => {
      link.classList.toggle('hidden', !isVisible);
    });
  }

  async function applyDeployAccess() {
    setDeployLinkVisibility(false);

    try {
      const response = await fetch('/api/deploy/access', { cache: 'no-store' });
      if (!response.ok) {
        return;
      }

      const payload = await response.json();
      const allowed = Boolean(payload && payload.allowed);
      setDeployLinkVisibility(allowed);

      if (!allowed && currentPath === '/pages/deploy.html') {
        window.location.replace('/static/index.html#rig-overview');
      }
    } catch (_) {
      // Keep deploy links hidden if the access check fails.
    }
  }

  applyDeployAccess();
})();
