(function () {
  const root = document.querySelector('.registry-page');
  if (!root) return;

  const selectAll = root.querySelector('[data-select-all]');
  const itemChecks = Array.from(root.querySelectorAll('input[name="ids"]'));
  const counter = root.querySelector('[data-selection-count]');

  function refreshSelection() {
    const selected = itemChecks.filter((input) => input.checked).length;
    if (counter) {
      counter.textContent = selected === 1
        ? '1 equipamento seleccionado'
        : `${selected} equipamentos seleccionados`;
    }
    if (selectAll) {
      selectAll.checked = itemChecks.length > 0 && selected === itemChecks.length;
      selectAll.indeterminate = selected > 0 && selected < itemChecks.length;
    }
  }

  if (selectAll) {
    selectAll.addEventListener('change', function () {
      itemChecks.forEach((input) => { input.checked = selectAll.checked; });
      refreshSelection();
    });
  }

  itemChecks.forEach((input) => input.addEventListener('change', refreshSelection));
  refreshSelection();
})();
