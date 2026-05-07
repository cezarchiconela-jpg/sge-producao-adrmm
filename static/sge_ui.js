(function(){
  document.documentElement.classList.add('sge-js-ready');
  const path = (window.location.pathname || '/').replace(/\/$/, '') || '/';
  document.body.dataset.route = path.split('/')[1] || 'inicio';

  // Reforça uso de tela cheia em páginas antigas com wrappers centralizados.
  document.querySelectorAll('main.sge-shell .container, main.sge-shell .container-lg, main.sge-shell .container-xl, main.sge-shell .container-xxl').forEach(el => {
    el.classList.add('sge-container-fluidized');
  });

  // Envolve tabelas antigas em área rolável quando ainda não estiverem dentro de .table-responsive.
  document.querySelectorAll('main.sge-shell table.table').forEach(tbl => {
    if (!tbl.closest('.table-responsive') && !tbl.closest('.sge-table-scroll')) {
      const wrap = document.createElement('div');
      wrap.className = 'sge-table-scroll';
      tbl.parentNode.insertBefore(wrap, tbl);
      wrap.appendChild(tbl);
    }
  });
})();
