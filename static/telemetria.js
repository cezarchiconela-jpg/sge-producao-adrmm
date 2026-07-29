(() => {
  const page = document.querySelector('.telemetry-page');
  if (!page) return;

  const els = {
    device: document.getElementById('telemetryDevice'),
    refresh: document.getElementById('telemetryRefresh'),
    export: document.getElementById('telemetryExport'),
    error: document.getElementById('telemetryError'),
    kpis: document.getElementById('telemetryKpis'),
    table: document.getElementById('telemetryTable'),
    state: document.getElementById('deviceState'),
    stateDot: document.getElementById('deviceStateDot'),
    lastMeasurement: document.getElementById('deviceLastMeasurement'),
    configWarning: document.getElementById('telemetryConfigWarning'),
    local: document.getElementById('deviceLocal'),
    manufacturer: document.getElementById('deviceManufacturer'),
    model: document.getElementById('deviceModel'),
    protocol: document.getElementById('deviceProtocol'),
    ip: document.getElementById('deviceIp'),
    remoteIp: document.getElementById('deviceRemoteIp'),
    warnings: document.getElementById('deviceWarnings'),
    logs: document.getElementById('ingestLogs'),
    period: document.getElementById('historyPeriod'),
    channelButtons: document.getElementById('historyChannelButtons'),
    chartCanvas: document.getElementById('telemetryChart'),
    chartEmpty: document.getElementById('chartEmpty')
  };

  let currentDevice = els.device?.value || page.dataset.device;
  let overviewData = null;
  let chart = null;
  let selectedChannels = ['tensao_ab_kv', 'tensao_bc_kv', 'tensao_ca_kv'];
  const chartPalette = ['#0d6efd', '#198754', '#fd7e14', '#6f42c1', '#dc3545', '#20c997'];

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const formatDate = value => {
    if (!value) return '—';
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return value;
    return new Intl.DateTimeFormat('pt-PT', {dateStyle:'short', timeStyle:'medium'}).format(dt);
  };
  const formatValue = (value, code) => {
    if (value === null || value === undefined) return '—';
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    let digits = 2;
    if (code.includes('factor_potencia')) digits = 3;
    if (code === 'frequencia_hz') digits = 2;
    if (code.includes('relacao_')) digits = 1;
    return new Intl.NumberFormat('pt-PT', {minimumFractionDigits:digits, maximumFractionDigits:digits}).format(n);
  };
  const stateLabel = state => ({online:'ONLINE', atrasado:'DADOS ATRASADOS', offline:'SEM COMUNICAÇÃO'}[state] || state?.toUpperCase() || '—');
  const showError = message => {
    els.error.textContent = message;
    els.error.classList.remove('d-none');
  };
  const clearError = () => els.error.classList.add('d-none');

  function renderDevice(device) {
    els.state.textContent = stateLabel(device.state);
    els.stateDot.className = `telemetry-status-dot is-${device.state || 'offline'}`;
    els.lastMeasurement.textContent = formatDate(device.last_measurement_at);
    els.local.textContent = device.local_name || 'Não associado';
    els.manufacturer.textContent = device.manufacturer || '—';
    els.model.textContent = [device.model, device.firmware ? `v${device.firmware}` : ''].filter(Boolean).join(' · ') || '—';
    els.protocol.textContent = device.protocol || '—';
    els.ip.textContent = device.local_ip || '—';
    els.remoteIp.textContent = device.last_remote_ip || '—';
    els.warnings.textContent = String(device.warning_count || 0);
    els.configWarning.classList.toggle('d-none', Boolean(device.token_configured));
  }

  function renderKpis(channels) {
    const visible = channels.filter(c => Number(c.show_dashboard) === 1);
    if (!visible.length) {
      els.kpis.innerHTML = '<div class="col-12"><div class="telemetry-empty"><strong>Sem grandezas configuradas para o painel.</strong></div></div>';
      return;
    }
    els.kpis.innerHTML = visible.map(c => `
      <div class="col-sm-6 col-lg-4 col-xxl-3">
        <article class="card telemetry-kpi shadow-sm ${c.state === 'normal' ? '' : `is-${c.state}`}">
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-center gap-2">
              <div class="telemetry-kpi-label">${escapeHtml(c.name)}</div>
              <span class="telemetry-kpi-state" title="${escapeHtml(c.state)}"></span>
            </div>
            <div class="telemetry-kpi-value">${formatValue(c.value, c.code)} <span class="fs-6 fw-semibold text-muted">${escapeHtml(c.unit || '')}</span></div>
            <div class="telemetry-kpi-time">${c.measured_at ? `Medido em ${formatDate(c.measured_at)}` : 'Aguardando primeira leitura'}</div>
          </div>
        </article>
      </div>`).join('');
  }

  function renderTable(channels) {
    els.table.innerHTML = channels.map(c => `
      <tr>
        <td><div class="fw-semibold">${escapeHtml(c.name)}</div><div class="small text-muted font-monospace">${escapeHtml(c.code)}</div></td>
        <td class="text-end fw-bold">${formatValue(c.value, c.code)}</td>
        <td>${escapeHtml(c.unit || '—')}</td>
        <td><span class="telemetry-quality ${escapeHtml(c.state)}">${escapeHtml(c.state === 'normal' ? 'Normal' : c.state === 'warning' ? 'Atenção' : c.state === 'bad' ? 'Má' : 'Sem dados')}</span></td>
        <td>${formatDate(c.measured_at)}</td>
      </tr>`).join('');
  }

  function renderChannelButtons(channels) {
    const candidates = channels.filter(c => Number(c.show_dashboard) === 1);
    if (!candidates.some(c => selectedChannels.includes(c.code))) {
      selectedChannels = candidates.slice(0, 3).map(c => c.code);
    }
    els.channelButtons.innerHTML = candidates.map(c => `
      <button type="button" class="telemetry-channel-btn ${selectedChannels.includes(c.code) ? 'active' : ''}" data-channel="${escapeHtml(c.code)}">
        ${escapeHtml(c.name)}
      </button>`).join('');
    els.channelButtons.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
      const code = btn.dataset.channel;
      if (selectedChannels.includes(code)) {
        if (selectedChannels.length > 1) selectedChannels = selectedChannels.filter(x => x !== code);
      } else if (selectedChannels.length < 6) {
        selectedChannels.push(code);
      }
      renderChannelButtons(overviewData?.channels || []);
      loadHistory();
    }));
  }

  async function loadOverview() {
    clearError();
    const response = await fetch(`/telemetria/api/overview?device=${encodeURIComponent(currentDevice)}`, {headers:{'Accept':'application/json'}});
    if (!response.ok) throw new Error('Não foi possível carregar o estado da telemetria.');
    overviewData = await response.json();
    renderDevice(overviewData.device);
    renderKpis(overviewData.channels);
    renderTable(overviewData.channels);
    renderChannelButtons(overviewData.channels);
  }

  async function loadLogs() {
    const response = await fetch(`/telemetria/api/ingest-status?device=${encodeURIComponent(currentDevice)}`, {headers:{'Accept':'application/json'}});
    if (!response.ok) return;
    const data = await response.json();
    if (!data.logs?.length) {
      els.logs.innerHTML = '<div class="text-muted small">Ainda não existem transmissões registadas.</div>';
      return;
    }
    els.logs.innerHTML = data.logs.map(log => `
      <div class="telemetry-log-item ${Number(log.rejected) > 0 ? 'is-warning' : ''}">
        <div class="telemetry-log-time">${formatDate(log.received_at)} · ${escapeHtml(log.remote_ip || 'origem não registada')}</div>
        <div class="telemetry-log-counts"><strong>${Number(log.accepted) || 0}</strong> aceites · ${Number(log.duplicates) || 0} duplicados · ${Number(log.rejected) || 0} rejeitados</div>
      </div>`).join('');
  }

  async function loadHistory() {
    const hours = els.period.value;
    els.export.href = `/telemetria/export.csv?device=${encodeURIComponent(currentDevice)}&hours=${hours}`;
    const channels = selectedChannels.join(',');
    const response = await fetch(`/telemetria/api/history?device=${encodeURIComponent(currentDevice)}&hours=${hours}&channels=${encodeURIComponent(channels)}`, {headers:{'Accept':'application/json'}});
    if (!response.ok) throw new Error('Não foi possível carregar o histórico.');
    const data = await response.json();
    const hasPoints = data.series?.some(s => s.points?.length);
    els.chartCanvas.classList.toggle('d-none', !hasPoints);
    els.chartEmpty.classList.toggle('d-none', Boolean(hasPoints));
    if (chart) chart.destroy();
    if (!hasPoints) return;
    const datasets = data.series.map((serie, index) => ({
      label: `${serie.name}${serie.unit ? ` (${serie.unit})` : ''}`,
      data: serie.points.map(point => ({x:new Date(point[0]), y:Number(point[1])})),
      borderColor: chartPalette[index % chartPalette.length],
      backgroundColor: chartPalette[index % chartPalette.length],
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: .18,
      spanGaps: true
    }));
    chart = new Chart(els.chartCanvas, {
      type:'line',
      data:{datasets},
      options:{
        responsive:true,
        maintainAspectRatio:false,
        interaction:{mode:'index', intersect:false},
        plugins:{legend:{position:'bottom'}, tooltip:{callbacks:{title:items => items[0] ? formatDate(items[0].parsed.x) : ''}}},
        scales:{x:{type:'linear', ticks:{callback:value => new Intl.DateTimeFormat('pt-PT',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value)), maxTicksLimit:10}, grid:{display:false}},y:{beginAtZero:false, ticks:{maxTicksLimit:8}}}
      }
    });
  }

  async function refreshAll() {
    els.refresh.disabled = true;
    els.refresh.querySelector('i')?.classList.add('telemetry-spin');
    try {
      await loadOverview();
      await Promise.all([loadHistory(), loadLogs()]);
    } catch (error) {
      showError(error.message || 'Falha ao actualizar a telemetria.');
    } finally {
      els.refresh.disabled = false;
      els.refresh.querySelector('i')?.classList.remove('telemetry-spin');
    }
  }

  els.device?.addEventListener('change', () => {
    currentDevice = els.device.value;
    history.replaceState({}, '', `/telemetria?device=${encodeURIComponent(currentDevice)}`);
    refreshAll();
  });
  els.refresh?.addEventListener('click', refreshAll);
  els.period?.addEventListener('change', loadHistory);

  refreshAll();
  window.setInterval(() => { loadOverview().catch(() => {}); loadLogs().catch(() => {}); }, 30000);
})();
