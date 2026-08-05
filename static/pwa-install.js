(function () {
  let deferredPrompt = null;
  const buttons = () => document.querySelectorAll('[data-pwa-install]');
  const status = document.querySelector('[data-pwa-status]');

  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  }

  function setState(message, canInstall) {
    if (status && message) status.textContent = message;
    buttons().forEach(button => {
      button.hidden = !canInstall;
      button.disabled = !canInstall;
    });
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js'));
  }

  if (isStandalone()) {
    setState('O SGE já está instalado neste dispositivo.', false);
  }

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    deferredPrompt = event;
    setState('O aplicativo está pronto para instalar.', true);
  });

  buttons().forEach(button => button.addEventListener('click', async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    setState('Se confirmou a instalação, o ícone do SGE aparecerá no seu telemóvel.', false);
  }));

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    setState('Instalação concluída. O SGE já está disponível como aplicativo.', false);
  });
})();
