(() => {
  const page = document.querySelector('.telemetry-page');
  if (!page) return;

  const els = {
    device: document.getElementById('telemetryDevice'),
    refresh: document.getElementById('telemetryRefresh'),
    export: document.getElementById('telemetryExport'),
    report: document.getElementById('telemetryReport'),
    error: document.getElementById('telemetryError'),
    alertBanner: document.getElementById('telemetryAlertBanner'),
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
    activeAlerts: document.getElementById('deviceActiveAlerts'),
    logs: document.getElementById('ingestLogs'),
    period: document.getElementById('historyPeriod'),
    dateWrap: document.getElementById('historyDateWrap'),
    date: document.getElementById('historyDate'),
    periodLabel: document.getElementById('analysisPeriodLabel'),
    tariffContext: document.getElementById('tariffContext'),
    financeCards: document.getElementById('energyFinanceCards'),
    monthFinance: document.getElementById('monthFinanceSummary'),
    energyChartCanvas: document.getElementById('energyCostChart'),
    energyChartEmpty: document.getElementById('energyChartEmpty'),
    energyChartSubtitle: document.getElementById('energyChartSubtitle'),
    channelButtons: document.getElementById('historyChannelButtons'),
    presetButtons: [...document.querySelectorAll('.telemetry-preset')],
    chartCanvas: document.getElementById('telemetryChart'),
    chartEmpty: document.getElementById('chartEmpty'),
    analysisState: document.getElementById('analysisState'),
    analysisCards: document.getElementById('analysisCards'),
    analysisDiagnosis: document.getElementById('analysisDiagnosis'),
    recommendations: document.getElementById('analysisRecommendations'),
    stats: document.getElementById('analysisStats'),
    alertsList: document.getElementById('telemetryAlertsList'),
    alertCounts: document.getElementById('alertCounts')
  };

  const presets = {
    voltage: ['tensao_ab_kv', 'tensao_bc_kv', 'tensao_ca_kv'],
    current: ['corrente_fase_a_a', 'corrente_fase_b_a', 'corrente_fase_c_a'],
    power: ['potencia_activa_total_mw', 'potencia_reactiva_total_mvar'],
    quality: ['factor_potencia_total', 'frequencia_hz']
  };
  const chartPalette = ['#0d6efd', '#198754', '#fd7e14', '#6f42c1', '#dc3545', '#20c997'];
  let currentDevice = els.device?.value || page.dataset.device;
  let currentPreset = 'voltage';
  let selectedChannels = [...presets.voltage];
  let overviewData = null;
  let chart = null;
  let energyChart = null;

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
  }[c]));

  const formatDate = value => {
    if (!value) return '—';
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return String(value);
    return new Intl.DateTimeFormat('pt-PT', {dateStyle:'short', timeStyle:'medium'}).format(dt);
  };

  const formatNumber = (value, digits = 2) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return new Intl.NumberFormat('pt-PT', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    }).format(n);
  };

  const formatCurrency = value => {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return `${new Intl.NumberFormat('pt-PT', {minimumFractionDigits:2, maximumFractionDigits:2}).format(n)} MZN`;
  };

  const maputoToday = () => {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone:'Africa/Maputo', year:'numeric', month:'2-digit', day:'2-digit'
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  };

  const periodQuery = () => {
    const period = els.period?.value || 'today';
    const params = new URLSearchParams({period});
    if (period === 'day') params.set('date', els.date?.value || maputoToday());
    return params.toString();
  };

  function syncPeriodControls() {
    const specificDay = els.period?.value === 'day';
    els.dateWrap?.classList.toggle('d-none', !specificDay);
    if (specificDay && els.date && !els.date.value) els.date.value = maputoToday();
  }

  const formatValue = (value, code) => {
    let digits = 2;
    if (String(code).includes('factor_potencia')) digits = 3;
    if (code === 'frequencia_hz') digits = 2;
    if (String(code).includes('relacao_')) digits = 1;
    return formatNumber(value, digits);
  };

  const formatDuration = seconds => {
    let total = Math.max(0, Number(seconds) || 0);
    const days = Math.floor(total / 86400); total %= 86400;
    const hours = Math.floor(total / 3600); total %= 3600;
    const minutes = Math.floor(total / 60);
    if (days) return `${days} d ${hours} h`;
    if (hours) return `${hours} h ${minutes} min`;
    if (minutes) return `${minutes} min`;
    return `${Math.floor(total)} s`;
  };

  const stateLabel = state => ({
    online:'ONLINE', atrasado:'DADOS ATRASADOS', offline:'SEM COMUNICAÇÃO'
  }[state] || state?.toUpperCase() || '—');

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
    els.activeAlerts.textContent = String(device.active_alert_count || 0);
    els.activeAlerts.className = Number(device.critical_alert_count) > 0 ? 'text-danger' : '';
    els.configWarning.classList.toggle('d-none', Boolean(device.token_configured));
  }

  function renderKpis(channels) {
    const visible = channels.filter(c => Number(c.show_dashboard) === 1);
    if (!visible.length) {
      els.kpis.innerHTML = '<div class="col-12"><div class="telemetry-empty"><strong>Sem grandezas configuradas para o painel.</strong></div></div>';
      return;
    }
    els.kpis.innerHTML = visible.map(c => {
      const direction = c.direction === 'reverso'
        ? '<div class="telemetry-kpi-note">Sinal bruto reverso · consumo apresentado em módulo</div>'
        : '';
      return `
        <div class="col-sm-6 col-lg-4 col-xxl-3">
          <article class="card telemetry-kpi shadow-sm ${c.state === 'normal' ? '' : `is-${c.state}`}">
            <div class="card-body">
              <div class="d-flex justify-content-between align-items-center gap-2">
                <div class="telemetry-kpi-label">${escapeHtml(c.name)}</div>
                <span class="telemetry-kpi-state" title="${escapeHtml(c.state)}"></span>
              </div>
              <div class="telemetry-kpi-value">${formatValue(c.value, c.code)} <span class="fs-6 fw-semibold text-muted">${escapeHtml(c.unit || '')}</span></div>
              <div class="telemetry-kpi-time">${c.measured_at ? `Medido em ${formatDate(c.measured_at)}` : 'Aguardando primeira leitura'}</div>
              ${direction}
            </div>
          </article>
        </div>`;
    }).join('');
  }

  function renderTable(channels) {
    els.table.innerHTML = channels.map(c => {
      const rawDiffers = c.raw_value !== null && c.raw_value !== undefined && Number(c.raw_value) !== Number(c.value);
      return `
        <tr>
          <td><div class="fw-semibold">${escapeHtml(c.name)}</div><div class="small text-muted font-monospace">${escapeHtml(c.code)}</div></td>
          <td class="text-end fw-bold">
            ${formatValue(c.value, c.code)}
            ${rawDiffers ? `<div class="small text-muted fw-normal">bruto: ${formatValue(c.raw_value, c.code)}</div>` : ''}
          </td>
          <td>${escapeHtml(c.unit || '—')}</td>
          <td><span class="telemetry-quality ${escapeHtml(c.state)}">${escapeHtml(c.state === 'normal' ? 'Normal' : c.state === 'warning' ? 'Atenção' : c.state === 'bad' ? 'Má' : 'Sem dados')}</span></td>
          <td>${formatDate(c.measured_at)}</td>
        </tr>`;
    }).join('');
  }

  function markPreset() {
    els.presetButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.preset === currentPreset));
  }

  function renderChannelButtons(channels) {
    const candidates = channels.filter(c => Number(c.show_dashboard) === 1);
    const validCodes = new Set(candidates.map(c => c.code));
    selectedChannels = selectedChannels.filter(code => validCodes.has(code));
    if (!selectedChannels.length) selectedChannels = candidates.slice(0, 3).map(c => c.code);
    els.channelButtons.innerHTML = candidates.map(c => `
      <button type="button" class="telemetry-channel-btn ${selectedChannels.includes(c.code) ? 'active' : ''}" data-channel="${escapeHtml(c.code)}">
        ${escapeHtml(c.name)}
      </button>`).join('');
    els.channelButtons.querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
      const code = btn.dataset.channel;
      currentPreset = null;
      markPreset();
      if (selectedChannels.includes(code)) {
        if (selectedChannels.length > 1) selectedChannels = selectedChannels.filter(item => item !== code);
      } else if (selectedChannels.length < 6) {
        selectedChannels.push(code);
      }
      renderChannelButtons(overviewData?.channels || []);
      loadHistory().catch(error => showError(error.message));
    }));
  }

  function applyPreset(name) {
    currentPreset = name;
    selectedChannels = [...(presets[name] || presets.voltage)];
    markPreset();
    renderChannelButtons(overviewData?.channels || []);
    loadHistory().catch(error => showError(error.message));
  }

  function renderEnergyChart(analysis) {
    const profile = analysis.energy_profile || {bucket:'hour', points:[]};
    const points = profile.points || [];
    const hasPoints = points.some(point => Number(point.active_energy_kwh) > 0);
    els.energyChartCanvas?.classList.toggle('d-none', !hasPoints);
    els.energyChartEmpty?.classList.toggle('d-none', hasPoints);
    if (energyChart) energyChart.destroy();
    if (els.energyChartSubtitle) {
      els.energyChartSubtitle.textContent = profile.bucket === 'hour'
        ? 'Consumo e custo activo distribuídos por hora.'
        : 'Consumo e custo activo distribuídos por dia.';
    }
    if (!hasPoints || !els.energyChartCanvas) return;

    energyChart = new Chart(els.energyChartCanvas, {
      data:{
        labels:points.map(point => new Date(point.start_at)),
        datasets:[
          {
            type:'bar',
            label:'Energia activa (kWh)',
            data:points.map(point => Number(point.active_energy_kwh)),
            yAxisID:'yEnergy',
            backgroundColor:'rgba(13, 110, 253, .55)',
            borderColor:'#0d6efd',
            borderWidth:1,
            borderRadius:4
          },
          {
            type:'line',
            label:'Custo activo (MZN)',
            data:points.map(point => Number(point.active_cost_mzn)),
            yAxisID:'yCost',
            borderColor:'#198754',
            backgroundColor:'#198754',
            pointRadius:2,
            pointHoverRadius:4,
            borderWidth:2,
            tension:.2
          }
        ]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        interaction:{mode:'index', intersect:false},
        plugins:{
          legend:{position:'bottom'},
          tooltip:{
            callbacks:{
              title:items => items[0] ? new Intl.DateTimeFormat('pt-PT', {
                dateStyle:'short',
                timeStyle:profile.bucket === 'hour' ? 'short' : undefined
              }).format(new Date(points[items[0].dataIndex].start_at)) : ''
            }
          }
        },
        scales:{
          x:{
            ticks:{
              maxTicksLimit:10,
              callback:(value, index) => new Intl.DateTimeFormat('pt-PT', profile.bucket === 'hour'
                ? {day:'2-digit', month:'2-digit', hour:'2-digit'}
                : {day:'2-digit', month:'2-digit'}
              ).format(points[index] ? new Date(points[index].start_at) : new Date())
            },
            grid:{display:false}
          },
          yEnergy:{
            type:'linear', position:'left', beginAtZero:true,
            title:{display:true, text:'kWh'}
          },
          yCost:{
            type:'linear', position:'right', beginAtZero:true,
            title:{display:true, text:'MZN'},
            grid:{drawOnChartArea:false}
          }
        }
      }
    });
  }

  function renderFinance(analysis) {
    const finance = analysis.finance || {};
    const comparison = finance.comparison || {};
    const projection = finance.projection || {};
    const month = finance.month_to_date || {};
    const tariffs = finance.tariffs || {};
    const summary = analysis.summary || {};
    if (els.periodLabel) els.periodLabel.textContent = analysis.period?.label || 'Período seleccionado';
    if (els.tariffContext) {
      els.tariffContext.textContent = `Tarifa activa: ${formatNumber(tariffs.tarifa_ativa, 4)} MZN/kWh · ${tariffs.source || 'SGE'}`;
    }

    const changeValue = comparison.cost_change_pct;
    const changeText = changeValue === null || changeValue === undefined
      ? 'Sem base comparável'
      : `${changeValue > 0 ? '+' : ''}${formatNumber(changeValue, 1)}%`;
    const changeNote = changeValue === null || changeValue === undefined
      ? 'Ainda não há dados no período anterior equivalente'
      : `${changeValue > 0 ? 'Aumento' : changeValue < 0 ? 'Redução' : 'Sem variação'} face ao período anterior`;
    const projectionValue = projection.available ? formatCurrency(projection.energy_cost_mzn) : '—';
    const projectionNote = projection.available
      ? `${projection.reliable ? 'Projecção com boa cobertura' : 'Projecção indicativa: cobertura incompleta'}`
      : 'Período fechado ou janela móvel';
    const cards = [
      ['Energia activa', `${formatNumber(finance.active_energy_kwh, 1)} kWh`, 'Integrada pelos intervalos reais', 'bi-lightning-charge'],
      ['Custo energético', formatCurrency(finance.energy_cost_mzn), `Activa ${formatCurrency(finance.active_cost_mzn)}`, 'bi-cash-coin'],
      ['Custo no regime actual', formatCurrency(finance.current_cost_rate_mzn_per_hour), finance.current_cost_rate_state === 'online' ? 'Por hora, se a potência actual se mantiver' : 'Indisponível enquanto os dados não estão online', 'bi-speedometer2'],
      ['Pico de potência', `${formatNumber(summary.peak_mw, 3)} MW`, summary.peak_at ? formatDate(summary.peak_at) : 'Sem pico registado', 'bi-graph-up-arrow'],
      ['Energia reactiva', `${formatNumber(finance.reactive_energy_kvarh, 1)} kVArh`, `Excedente: ${formatNumber(finance.reactive_excess_kvarh, 1)} kVArh`, 'bi-activity'],
      ['Custo de reactiva', formatCurrency(finance.reactive_cost_mzn), finance.reactive_excess_kvarh > 0 ? 'Há excedente no período' : 'Sem excedente calculado', 'bi-exclamation-circle'],
      ['Comparação de custo', changeText, changeNote, 'bi-arrow-left-right'],
      ['Projecção do período', projectionValue, projectionNote, 'bi-calendar2-check']
    ];
    if (els.financeCards) {
      els.financeCards.innerHTML = cards.map(([label, value, note, icon]) => `
        <div class="col-sm-6 col-xl-3">
          <article class="telemetry-finance-card h-100">
            <div class="d-flex justify-content-between gap-2">
              <div class="telemetry-mini-label">${escapeHtml(label)}</div>
              <i class="bi ${escapeHtml(icon)} text-primary"></i>
            </div>
            <div class="telemetry-finance-value">${escapeHtml(value)}</div>
            <div class="telemetry-analysis-note">${escapeHtml(note)}</div>
          </article>
        </div>`).join('');
    }

    const invoice = month.invoice_estimate || {};
    const coverageWarning = Number(month.coverage_pct) < 90
      ? `<div class="telemetry-finance-warning"><i class="bi bi-exclamation-triangle me-1"></i>Cobertura mensal: ${formatNumber(month.coverage_pct, 1)}%. Projecção indicativa.</div>`
      : `<div class="telemetry-finance-ok"><i class="bi bi-check-circle me-1"></i>Cobertura mensal: ${formatNumber(month.coverage_pct, 1)}%</div>`;
    if (els.monthFinance) {
      els.monthFinance.innerHTML = `
        <div class="telemetry-month-row"><span>Energia até agora</span><strong>${formatNumber(month.active_energy_kwh, 1)} kWh</strong></div>
        <div class="telemetry-month-row"><span>Custo energético</span><strong>${formatCurrency(month.energy_cost_mzn)}</strong></div>
        <div class="telemetry-month-row"><span>Estimativa da factura até agora</span><strong>${formatCurrency(invoice.estimated_total_mzn)}</strong></div>
        <hr>
        <div class="telemetry-month-row"><span>Energia projectada</span><strong>${formatNumber(month.projected_active_energy_kwh, 1)} kWh</strong></div>
        <div class="telemetry-month-row"><span>Custo energético projectado</span><strong>${formatCurrency(month.projected_energy_cost_mzn)}</strong></div>
        <div class="telemetry-month-row is-total"><span>Factura mensal projectada</span><strong>${formatCurrency(month.projected_invoice_estimate_mzn)}</strong></div>
        ${coverageWarning}
        ${invoice.contracted_power_configured ? '' : '<div class="small text-muted mt-2">Potência contratada não configurada; validar a componente de demanda.</div>'}`;
    }
    renderEnergyChart(analysis);
  }

  function renderAnalysis(analysis) {
    const summary = analysis.summary;
    const stateClass = summary.operational_state === 'Crítico'
      ? 'is-critical'
      : summary.operational_state === 'Atenção'
        ? 'is-warning'
        : summary.operational_state === 'Normal' ? 'is-normal' : 'is-neutral';
    els.analysisState.className = `telemetry-analysis-state ${stateClass}`;
    els.analysisState.textContent = summary.operational_state;
    renderFinance(analysis);

    const voltageRange = summary.voltage_min_kv !== null && summary.voltage_max_kv !== null
      ? `${formatNumber(summary.voltage_min_kv, 2)}–${formatNumber(summary.voltage_max_kv, 2)} kV`
      : '—';
    const cards = [
      ['Energia estimada', `${formatNumber(summary.energy_kwh, 1)} kWh`, 'Integração da potência activa'],
      ['Pico de potência', `${formatNumber(summary.peak_mw, 3)} MW`, summary.peak_at ? formatDate(summary.peak_at) : 'Sem pico registado'],
      ['Factor de potência médio', formatNumber(summary.power_factor_avg, 3), 'Avaliado pelo módulo do FP'],
      ['Faixa de tensão', voltageRange, `Desequilíbrio máx. ${formatNumber(summary.voltage_unbalance_max_pct, 2)}%`],
      ['Corrente máxima', summary.current_max_a === null ? '—' : `${formatNumber(summary.current_max_a, 1)} A`, `Desequilíbrio máx. ${formatNumber(summary.current_unbalance_max_pct, 1)}%`],
      ['Cobertura de dados', `${formatNumber(summary.data_coverage_pct, 1)}%`, `${summary.ignored_data_gaps || 0} lacuna(s) longa(s)`],
      ['Disponibilidade de energia', `${formatNumber(summary.energy_availability_pct, 2)}%`, `Cortes: ${formatDuration(summary.outage_duration_seconds)}`],
      ['Disponibilidade da comunicação', `${formatNumber(summary.communication_availability_pct, 2)}%`, `Falhas/atrasos: ${formatDuration(summary.communication_gap_seconds)}`]
    ];
    els.analysisCards.innerHTML = cards.map(([label, value, note]) => `
      <div class="col-sm-6 col-xl-3">
        <div class="telemetry-analysis-card">
          <div class="telemetry-mini-label">${escapeHtml(label)}</div>
          <div class="telemetry-analysis-value">${escapeHtml(value)}</div>
          <div class="telemetry-analysis-note">${escapeHtml(note)}</div>
        </div>
      </div>`).join('');

    const direction = summary.measured_flow_direction === 'reverso'
      ? 'O relé mede o fluxo com sinal reverso; o SGE preserva esse valor bruto e apresenta o consumo em módulo.'
      : 'O sentido medido pelo relé está directo.';
    const coverage = summary.data_coverage_pct < 90
      ? ` A cobertura do período é de ${formatNumber(summary.data_coverage_pct, 1)}%, por isso a energia estimada deve ser interpretada com cautela.`
      : ' A cobertura do período é adequada para análise operacional.';
    const financial = ` No período, o consumo calculado foi ${formatNumber(analysis.finance?.active_energy_kwh, 1)} kWh, com custo energético de ${formatCurrency(analysis.finance?.energy_cost_mzn)}.`;
    els.analysisDiagnosis.textContent = `${direction}${coverage}${financial}`;
    els.recommendations.innerHTML = analysis.recommendations.map(item => `<li>${escapeHtml(item)}</li>`).join('');

    if (!analysis.stats.length) {
      els.stats.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">Sem dados no período seleccionado.</td></tr>';
    } else {
      els.stats.innerHTML = analysis.stats.map(row => `
        <tr>
          <td class="fw-semibold">${escapeHtml(row.name)}</td>
          <td class="text-end">${formatValue(row.minimum, row.code)} ${escapeHtml(row.unit || '')}</td>
          <td class="text-end fw-semibold">${formatValue(row.average, row.code)} ${escapeHtml(row.unit || '')}</td>
          <td class="text-end">${formatValue(row.maximum, row.code)} ${escapeHtml(row.unit || '')}</td>
          <td class="text-end text-muted">${Number(row.samples) || 0}</td>
        </tr>`).join('');
    }
  }

  function renderAlerts(data) {
    const alerts = data.alerts || [];
    const active = alerts.filter(item => item.status === 'open' || item.status === 'acknowledged');
    const critical = active.filter(item => item.severity === 'critical');
    els.alertCounts.innerHTML = `<strong>${active.length}</strong> activos · <strong class="text-danger">${critical.length}</strong> críticos · ${data.counts?.resolved || 0} resolvidos`;

    if (!alerts.length) {
      els.alertsList.innerHTML = '<div class="text-muted small">Ainda não existem ocorrências registadas neste período.</div>';
    } else {
      els.alertsList.innerHTML = alerts.map(item => {
        const activeItem = item.status === 'open' || item.status === 'acknowledged';
        const statusLabel = item.status === 'open' ? 'Activo' : item.status === 'acknowledged' ? 'Reconhecido' : 'Resolvido';
        const value = item.value === null || item.value === undefined
          ? ''
          : `<span class="telemetry-alert-value">${formatNumber(item.value, item.unit === '%' ? 2 : 3)} ${escapeHtml(item.unit || '')}</span>`;
        const acknowledge = item.status === 'open'
          ? `<button type="button" class="btn btn-sm btn-outline-secondary telemetry-ack" data-alert-id="${Number(item.id)}">Reconhecer</button>`
          : '';
        return `
          <article class="telemetry-alert-item is-${escapeHtml(item.severity)} ${activeItem ? 'is-active' : ''}">
            <div class="d-flex flex-wrap justify-content-between gap-2">
              <div>
                <div class="d-flex flex-wrap align-items-center gap-2">
                  <span class="telemetry-alert-severity">${item.severity === 'critical' ? 'Crítico' : 'Atenção'}</span>
                  <span class="telemetry-alert-status">${escapeHtml(statusLabel)}</span>
                  ${value}
                </div>
                <h3 class="h6 mb-1 mt-2">${escapeHtml(item.title)}</h3>
                <p class="small text-muted mb-1">${escapeHtml(item.message)}</p>
                <div class="small text-muted">Início: ${formatDate(item.started_at)} · Duração: ${formatDuration(item.duration_seconds)}${item.resolved_at ? ` · Fim: ${formatDate(item.resolved_at)}` : ''}</div>
              </div>
              <div>${acknowledge}</div>
            </div>
          </article>`;
      }).join('');
    }

    const bannerItem = critical[0] || active[0];
    if (!bannerItem) {
      els.alertBanner.className = 'telemetry-alert-banner d-none';
      els.alertBanner.innerHTML = '';
    } else {
      els.alertBanner.className = `telemetry-alert-banner is-${bannerItem.severity}`;
      els.alertBanner.innerHTML = `
        <i class="bi ${bannerItem.severity === 'critical' ? 'bi-exclamation-octagon-fill' : 'bi-exclamation-triangle-fill'}"></i>
        <div><strong>${escapeHtml(bannerItem.title)}</strong><span>${escapeHtml(bannerItem.message)}</span></div>
        <a href="#telemetryAlertsCard" class="btn btn-sm btn-light ms-auto">Ver ocorrência</a>`;
    }

    els.alertsList.querySelectorAll('.telemetry-ack').forEach(button => button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const response = await fetch(`/telemetria/api/alerts/${button.dataset.alertId}/acknowledge`, {
          method: 'POST',
          headers: {'Accept':'application/json', 'X-Requested-With':'XMLHttpRequest'}
        });
        if (!response.ok) throw new Error('Não foi possível reconhecer o alerta.');
        await Promise.all([loadAlerts(), loadAnalysis(), loadOverview()]);
      } catch (error) {
        showError(error.message);
      } finally {
        button.disabled = false;
      }
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

  async function loadAnalysis() {
    const query = periodQuery();
    els.export.href = `/telemetria/export.csv?device=${encodeURIComponent(currentDevice)}&${query}`;
    els.report.href = `/telemetria/relatorio.pdf?device=${encodeURIComponent(currentDevice)}&${query}`;
    const response = await fetch(`/telemetria/api/analysis?device=${encodeURIComponent(currentDevice)}&${query}`, {headers:{'Accept':'application/json'}});
    if (!response.ok) throw new Error('Não foi possível calcular os indicadores do período.');
    const data = await response.json();
    renderAnalysis(data.analysis);
  }

  async function loadAlerts() {
    const response = await fetch(`/telemetria/api/alerts?device=${encodeURIComponent(currentDevice)}&${periodQuery()}`, {headers:{'Accept':'application/json'}});
    if (!response.ok) throw new Error('Não foi possível carregar os alertas.');
    renderAlerts(await response.json());
  }

  async function loadHistory() {
    const channels = selectedChannels.join(',');
    const response = await fetch(`/telemetria/api/history?device=${encodeURIComponent(currentDevice)}&${periodQuery()}&channels=${encodeURIComponent(channels)}`, {headers:{'Accept':'application/json'}});
    if (!response.ok) throw new Error('Não foi possível carregar o histórico.');
    const data = await response.json();
    const hasPoints = data.series?.some(series => series.points?.length);
    els.chartCanvas.classList.toggle('d-none', !hasPoints);
    els.chartEmpty.classList.toggle('d-none', Boolean(hasPoints));
    if (chart) chart.destroy();
    if (!hasPoints) return;

    const units = [...new Set(data.series.map(series => series.unit || 'sem unidade'))];
    const axes = {};
    units.forEach((unit, index) => {
      axes[`y${index}`] = {
        type:'linear',
        display:true,
        position:index % 2 === 0 ? 'left' : 'right',
        beginAtZero:false,
        title:{display:true, text:unit},
        ticks:{maxTicksLimit:8},
        grid:{drawOnChartArea:index === 0}
      };
    });
    const datasets = data.series.map((series, index) => ({
      label: `${series.name}${series.unit ? ` (${series.unit})` : ''}`,
      data: series.points.map(point => ({x:new Date(point[0]), y:Number(point[1])})),
      borderColor: chartPalette[index % chartPalette.length],
      backgroundColor: chartPalette[index % chartPalette.length],
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: .18,
      spanGaps: true,
      yAxisID: `y${units.indexOf(series.unit || 'sem unidade')}`
    }));
    chart = new Chart(els.chartCanvas, {
      type:'line',
      data:{datasets},
      options:{
        responsive:true,
        maintainAspectRatio:false,
        interaction:{mode:'index', intersect:false},
        plugins:{
          legend:{position:'bottom'},
          tooltip:{callbacks:{title:items => items[0] ? formatDate(items[0].parsed.x) : ''}}
        },
        scales:{
          x:{
            type:'linear',
            ticks:{
              callback:value => new Intl.DateTimeFormat('pt-PT',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value)),
              maxTicksLimit:10
            },
            grid:{display:false}
          },
          ...axes
        }
      }
    });
  }

  async function refreshAll() {
    els.refresh.disabled = true;
    els.refresh.querySelector('i')?.classList.add('telemetry-spin');
    try {
      await loadOverview();
      await Promise.all([loadHistory(), loadLogs(), loadAnalysis(), loadAlerts()]);
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
  els.period?.addEventListener('change', () => {
    syncPeriodControls();
    Promise.all([loadHistory(), loadAnalysis(), loadAlerts()]).catch(error => showError(error.message));
  });
  els.date?.addEventListener('change', () => {
    if (els.period?.value === 'day') {
      Promise.all([loadHistory(), loadAnalysis(), loadAlerts()]).catch(error => showError(error.message));
    }
  });
  els.presetButtons.forEach(button => button.addEventListener('click', () => applyPreset(button.dataset.preset)));

  syncPeriodControls();
  refreshAll();
  window.setInterval(() => {
    Promise.all([loadOverview(), loadAlerts()]).catch(() => {});
  }, 30000);
  window.setInterval(() => {
    Promise.all([loadHistory(), loadAnalysis(), loadLogs()]).catch(() => {});
  }, 60000);
})();
