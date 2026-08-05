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
      button.hidden = false;
      button.disabled = false;
      button.dataset.promptReady = canInstall ? 'true' : 'false';
    });
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', async () => {
      try {
        const registration = await navigator.serviceWorker.register('/service-worker.js', {
          scope: '/',
          updateViaCache: 'none'
        });
        await registration.update();
        await navigator.serviceWorker.ready;
        if (!isStandalone() && !deferredPrompt) {
          setState('Aplicativo preparado. Toque no botão abaixo; se o aviso do Android ainda não aparecer, recarregue esta página uma vez.', false);
        }
      } catch (error) {
        console.error('Falha ao ativar o aplicativo SGE:', error);
        setState('Não foi possível ativar a instalação neste carregamento. Verifique a internet e recarregue a página.', false);
      }
    });
  } else {
    setState('Este navegador não suporta instalação de aplicativos web. Abra o endereço no Google Chrome.', false);
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
    if (!deferredPrompt) {
      setState('No Chrome, abra o menu ⋮ e escolha “Instalar app” ou “Adicionar ao ecrã principal”. Se a opção não aparecer, recarregue a página e tente novamente.', false);
      return;
    }
    deferredPrompt.prompt();
    const choice = await deferredPrompt.userChoice;
    deferredPrompt = null;
    setState(choice.outcome === 'accepted'
      ? 'Instalação confirmada. O ícone do SGE aparecerá no seu telemóvel.'
      : 'A instalação foi cancelada. Pode voltar a tentar quando desejar.', false);
  }));

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    setState('Instalação concluída. O SGE já está disponível como aplicativo.', false);
  });
})();
