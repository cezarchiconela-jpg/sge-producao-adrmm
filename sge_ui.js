(function(){
  document.documentElement.classList.add('sge-js-ready');
  const path = (window.location.pathname || '/').replace(/\/$/, '') || '/';
  const route = path.split('/')[1] || 'inicio';
  document.body.dataset.route = route;

  const fullRoutes = new Set(['motores', 'alertas', 'solar']);
  if (fullRoutes.has(route)) {
    document.body.classList.add('sge-force-module-full');
  }

  // Reforça uso de tela cheia em páginas antigas com wrappers centralizados.
  document.querySelectorAll('main.sge-shell .container, main.sge-shell .container-sm, main.sge-shell .container-md, main.sge-shell .container-lg, main.sge-shell .container-xl, main.sge-shell .container-xxl').forEach(el => {
    el.classList.add('sge-container-fluidized');
  });

  // Corrige especificamente módulos que ainda tinham wrappers próprios centralizados.
  if (fullRoutes.has(route)) {
    const wrapperNamePattern = /(container|wrapper|wrap|workspace|page|content|layout|shell|solar|motor|motores|alert|alertas)/i;
    document.querySelectorAll('main.sge-shell > div, main.sge-shell > section, main.sge-shell > form, main.sge-shell div[class], main.sge-shell section[class]').forEach(el => {
      const cls = el.className && typeof el.className === 'string' ? el.className : '';
      const id = el.id || '';
      if (wrapperNamePattern.test(cls) || wrapperNamePattern.test(id) || el.parentElement?.matches('main.sge-shell')) {
        el.classList.add('sge-fullwidth-block');
        el.style.maxWidth = 'none';
        el.style.marginLeft = '0';
        el.style.marginRight = '0';
        if (el.parentElement?.matches('main.sge-shell') || wrapperNamePattern.test(cls)) {
          el.style.width = '100%';
        }
      }
    });
  }

  // Envolve tabelas antigas em área rolável quando ainda não estiverem dentro de .table-responsive.
  document.querySelectorAll('main.sge-shell table.table, main.sge-shell table').forEach(tbl => {
    if (!tbl.closest('.table-responsive') && !tbl.closest('.sge-table-scroll') && !tbl.closest('.table-wrap')) {
      const wrap = document.createElement('div');
      wrap.className = 'sge-table-scroll';
      tbl.parentNode.insertBefore(wrap, tbl);
      wrap.appendChild(tbl);
    }
  });
})();
