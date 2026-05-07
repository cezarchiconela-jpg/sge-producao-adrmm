(function(){
  "use strict";

  function $(sel, root){ return (root||document).querySelector(sel); }
  function $all(sel, root){ return Array.from((root||document).querySelectorAll(sel)); }

  // Conversão robusta para número (pt-PT / pt-BR friendly)
  function toNum(v){
    if (v === undefined || v === null) return 0;
    let s = String(v).trim();
    if (!s) return 0;

    if (s.includes(",")) {
      // Formatos tipo "1.234,56" ou "4,78"
      s = s.replace(/\./g, "").replace(",", ".");
    } else {
      // Formatos tipo "4.7800" (decimal com ponto)
      s = s.replace(/[^0-9.\-]/g, "");
    }

    const n = parseFloat(s);
    return isFinite(n) ? n : 0;
  }

  function fmt2(x){ return Number(x || 0).toFixed(2); }
  function fmt3(x){ return Math.max(0, Math.min(1, x || 0)).toFixed(3); }

  const tabela     = $("#tabela[data-tipo='leituras_mensais'], #tabela");
  const localSel   = $("#select_local");
  const btnFat     = $("#btnCalcularFatura"); // botão do topo

  // topo
  const fatorMultTopEl     = $("#fator_mult_top");
  const fatorMultHiddenEl  = $("#fator_mult_hidden");
  const potContratadaTopEl = $("#pot_contratada_top");
  const potInstaladaTopEl  = $("#pot_instalada_top");
  const tarifaAtivaEl      = $("#tarifa_ativa_top");
  const tarifaReativaEl    = $("#tarifa_reativa_top");
  const tarifaPontaEl      = $("#tarifa_ponta_top");
  const tarifaPerdasEl     = $("#tarifa_perdas_top");
  const taxaFixaEl         = $("#taxa_fixa_top");
  const taxaRadioEl        = $("#taxa_radio_top");
  const taxaLixoEl         = $("#taxa_lixo_top");
  const ivaEl              = $("#iva_top");

  function getLocalKey(){
    if(!localSel) return "";
    const opt = localSel.options[localSel.selectedIndex];
    let key = localSel.value;
    if (!key || /^\d+$/.test(key)) {
      const name = opt && opt.text ? opt.text.trim() : "";
      if (name) key = name;
    }
    return key;
  }

  async function fetchCfg(localKey){
    if(!localKey) return null;
    const tries = [
      `/api/local_cfg/${encodeURIComponent(localKey)}`,
      `/api/local_cfg?local=${encodeURIComponent(localKey)}`
    ];
    for (const url of tries){
      try {
        const r = await fetch(url, { headers:{"Accept":"application/json"}, cache:"no-cache" });
        if(r.ok) return await r.json();
      } catch(e){}
    }
    console.warn("fetchCfg: nenhuma rota funcionou para", localKey);
    return null;
  }

  function applyCfg(cfg){
    if(!cfg) return;
    if (fatorMultTopEl)    fatorMultTopEl.value    = cfg.fator_mult ?? fatorMultTopEl.value ?? 1;
    if (fatorMultHiddenEl) fatorMultHiddenEl.value = cfg.fator_mult ?? fatorMultHiddenEl.value ?? 1;
    if (potContratadaTopEl) potContratadaTopEl.value = cfg.pot_contratada ?? potContratadaTopEl.value ?? 0;
    if (potInstaladaTopEl)  potInstaladaTopEl.value  = cfg.pot_instalada ?? potInstaladaTopEl.value ?? 0;

    // Preenche e bloqueia a coluna "Pot. Contratada" na grelha
    if (tabela && cfg.pot_contratada !== undefined && cfg.pot_contratada !== null){
      const rows = $all("tbody tr", tabela);
      rows.forEach(tr=>{
        const I = getInputs(tr);
        if (I.potc){
          I.potc.value = cfg.pot_contratada;
          I.potc.readOnly = true;
          I.potc.classList.add("bg-light");
        }
      });
    }

    if (tarifaAtivaEl)    tarifaAtivaEl.value    = (cfg.tarifa_ativa   ?? tarifaAtivaEl.value   ?? 0).toFixed(4);
    if (tarifaReativaEl)  tarifaReativaEl.value  = (cfg.tarifa_reativa ?? tarifaReativaEl.value ?? 0).toFixed(4);
    if (tarifaPontaEl)    tarifaPontaEl.value    = (cfg.tarifa_ponta   ?? tarifaPontaEl.value   ?? 0).toFixed(4);
    if (tarifaPerdasEl)   tarifaPerdasEl.value   = (cfg.tarifa_perdas  ?? tarifaPerdasEl.value  ?? 0).toFixed(4);
    if (taxaFixaEl)       taxaFixaEl.value       = (cfg.taxa_fixa  ?? taxaFixaEl.value  ?? 0).toFixed(2);
    if (taxaRadioEl)      taxaRadioEl.value      = (cfg.taxa_radio ?? taxaRadioEl.value ?? 0).toFixed(2);
    if (taxaLixoEl)       taxaLixoEl.value       = (cfg.taxa_lixo  ?? taxaLixoEl.value  ?? 0).toFixed(2);
    if (ivaEl)            ivaEl.value            = (cfg.iva        ?? ivaEl.value       ?? 0).toFixed(3); // pode ser 16.000 ou 0.160
  }

  function getInputs(tr){
    const inps = tr.querySelectorAll("input");
    return {
      hora:      inps[1],
      ativa:     inps[2],
      reativa:   inps[3],
      ponta:     inps[4],
      fp:        inps[5],
      potc:      inps[6],
      anterior:  inps[7],
      atual:     inps[8],
      delta:     inps[9],
      agua:      inps[10],
      esp:       inps[11],
      acum:      inps[12],
      valor:     inps[13],
    };
  }

  function recalcRow(tr, idx, acumAnterior){
    const I = getInputs(tr);

    // FP diário por (kWh, kVArh) - nunca mexe em "Ativa"
    const kwh   = toNum(I.ativa?.value);
    const kvarh = toNum(I.reativa?.value);
    const fpDia = (kwh || kvarh) ? (kwh / Math.hypot(kwh, kvarh)) : 0;
    if (I.fp && !I.fp.dataset.manualFp){
      I.fp.value = fmt3(fpDia);
    }

    const anterior = toNum(I.anterior?.value);
    let atual    = toNum(I.atual?.value);

    let delta = 0;

    if (kwh > 0){
      // Tratamos Ativa como o Δ de leitura.
      delta = kwh;

      // Enquanto o operador não marcar o campo "Leit. Atual" como manual,
      // recalcula Atual = Anterior + Ativa
      if (I.atual && !I.atual.dataset.manualAtual && anterior >= 0){
        atual = anterior + kwh;
        I.atual.value = fmt2(atual);
      }
    } else {
      // Sem Ativa: se existir Leit. Atual, delta = Atual - Anterior
      delta = Math.max(atual - anterior, 0);
    }

    if (I.delta) I.delta.value = fmt2(delta);

    // === Consumo específico (kWh/m³) ===
    const aguaDia = toNum(I.agua?.value);
    let esp = 0;
    if (aguaDia > 0 && kwh > 0){
      esp = kwh / aguaDia;
    }
    if (I.esp){
      I.esp.value = esp > 0 ? fmt3(esp) : "";
    }

    // Acumulado = acumAnterior + kwh
    const acum = (acumAnterior || 0) + kwh;
    if (I.acum) I.acum.value = fmt2(acum);

    return {kwh, acum};
  }

  function recalcAll(){
    if(!tabela) return;

    let somaKwh=0, somaKvarh=0, somaPonta=0, somaDelta=0, somaAgua=0, somaValor=0;
    let maxPonta = 0;  // ponta máxima do mês
    let acumulado = 0;

    // fator multiplicativo (com fallback para hidden)
    const fatorMult = (toNum(fatorMultTopEl?.value) || toNum(fatorMultHiddenEl?.value) || 1);
    const potContratada = toNum(potContratadaTopEl?.value);

    const rows = $all("tbody tr", tabela);
    rows.forEach((tr, idx)=>{
      const I = getInputs(tr);
      const res = recalcRow(tr, idx, acumulado);
      acumulado = res.acum;

      const ativa   = toNum(I.ativa?.value);
      const reativa = toNum(I.reativa?.value);
      const ponta   = toNum(I.ponta?.value);
      const anterior= toNum(I.anterior?.value);
      const atual   = toNum(I.atual?.value);
      const delta   = Math.max(atual - anterior, 0);

      const tarifaAtiva    = toNum(tarifaAtivaEl?.value);
      const tarifaReativa  = toNum(tarifaReativaEl?.value);
      const tarifaPonta    = toNum(tarifaPontaEl?.value);

      // === ENERGIA REAL DO DIA (após fator multiplicativo) ===
      const kwhRealDia   = ativa   * fatorMult;
      const kvarhRealDia = reativa * fatorMult;

      // Reativa excedente diária (em kVArh reais)
      const limiteReatDia      = 0.75 * kwhRealDia;
      const reativaExcRealDia  = Math.max(kvarhRealDia - limiteReatDia, 0);

      // Ponta diária: usa a mesma fórmula da demanda de ponta,
      // mas com a potência lida desse dia (ajustada ao fator mult)
      const pontaLidaRealDia   = ponta * fatorMult;
      const demandaPontaDia    =
        (ponta > 0 || potContratada > 0)
          ? (0.20 * potContratada + 0.80 * pontaLidaRealDia)
          : 0;

      // CUSTO DIÁRIO = Ativa_real + Reativa_exced_real + DemandaPonta_dia
      const custoDia =
          (kwhRealDia          * tarifaAtiva)   +
          (reativaExcRealDia   * tarifaReativa) +
          (demandaPontaDia     * tarifaPonta);

      if (I.valor) I.valor.value = fmt2(custoDia);

      somaKwh   += ativa;
      somaKvarh += reativa;
      somaPonta += ponta;
      somaDelta += delta;
      somaAgua  += toNum(I.agua?.value);
      somaValor += custoDia;

      // ponta máxima do mês (potência lida)
      if (ponta > maxPonta){
        maxPonta = ponta;
      }
    });

    const setVal = (id,v)=>{ const el=$(id); if(el) el.value=fmt2(v); };
    setVal("#tot_kwh",   somaKwh);
    setVal("#tot_kvarh", somaKvarh);
    // total de ponta = PONTA MÁXIMA lida
    setVal("#tot_ponta", maxPonta);
    setVal("#tot_delta", somaDelta);
    setVal("#tot_agua",  somaAgua);
    setVal("#tot_acum",  acumulado);
    setVal("#tot_valor", somaValor);

    // === Consumo específico médio do mês (kWh/m³) ===
    const kwhRealTotal = somaKwh * fatorMult;
    let espMedioMes = 0;
    if (somaAgua > 0 && kwhRealTotal > 0){
      espMedioMes = kwhRealTotal / somaAgua;
    }
    const espTotEl = $("#tot_esp") || $("#tot_esp_medio");
    if (espTotEl){
      espTotEl.value = espMedioMes > 0 ? fmt3(espMedioMes) : "";
    }

    // === Pré-visualização em tempo real do Resumo da Fatura ===
    const tAtiva   = toNum(tarifaAtivaEl?.value);
    const tReativa = toNum(tarifaReativaEl?.value);
    const tPonta   = toNum(tarifaPontaEl?.value);
    const tPerdas  = toNum(tarifaPerdasEl?.value); // não entra no custo

    const taxaFixa  = toNum(taxaFixaEl?.value);
    const taxaRadio = toNum(taxaRadioEl?.value);
    const taxaLixo  = toNum(taxaLixoEl?.value);

    // IVA configurado: aceita 16 ou 0.16, default 0.16
    let ivaCfg = toNum(ivaEl?.value);
    if (!ivaCfg) ivaCfg = 0.16;
    let ivaFrac = ivaCfg;
    if (ivaFrac > 1) ivaFrac = ivaFrac / 100;

    // Energias / potências reais (após fator multiplicativo)
    const kwhAtivaReal       = somaKwh   * fatorMult;
    const kvarhReativaReal   = somaKvarh * fatorMult;
    const kW_PontaLidaReal   = maxPonta  * fatorMult; // PONTA MÁXIMA real
    const kwhPerdasReal      = somaDelta * fatorMult; // info apenas

    // Reativa excedente faturável (mensal)
    const limiteReativa  = 0.75 * kwhAtivaReal;
    const kvarhExcedente = Math.max(kvarhReativaReal - limiteReativa, 0);

    // Demanda de ponta faturável (mensal)
    const potPontaFaturavel = 0.20 * potContratada + 0.80 * kW_PontaLidaReal;

    // Custos (mensais)
    const cAtiva   = kwhAtivaReal      * tAtiva;
    const cReativa = kvarhExcedente    * tReativa;
    const cPonta   = potPontaFaturavel * tPonta;
    const cPerdas  = 0; // retirado do cálculo

    const energiaSubtotal = cAtiva + cReativa + cPonta;
    const taxasSubtotal   = taxaFixa + taxaRadio + taxaLixo;

    // IVA: 16% aplicado sobre 62% do SUBTOTAL DE ENERGIA
    const IVA_BASE_FRAC = 0.62;        // 62% da energia
    const baseIVA       = energiaSubtotal * IVA_BASE_FRAC;
    const valorIva      = baseIVA * ivaFrac;

    // Subtotal mostrado na coluna "Subtotal + IVA":
    // energia + IVA (sem taxas)
    const subtotalComIva = energiaSubtotal + valorIva;

    // Total da fatura = energia + IVA + taxas
    const total = subtotalComIva + taxasSubtotal;

    // escreve "valor (energia unidade)" quando há energia associada
    function putEnergia(id, energia, money, unidade){
      const el = document.getElementById(id);
      if (!el) return;
      if (energia > 0){
        el.textContent = `${fmt2(money)} (${fmt2(energia)} ${unidade})`;
      } else {
        el.textContent = fmt2(money);
      }
    }

    // Ativa: kWh reais
    putEnergia("res_custo_ativa",   kwhAtivaReal,      cAtiva,   "kWh");
    // Reativa: excedente faturável
    putEnergia("res_custo_reativa", kvarhExcedente,    cReativa, "kVArh");
    // Ponta: demanda faturável (20% contratada + 80% PONTA MÁXIMA real)
    putEnergia("res_custo_ponta",   potPontaFaturavel, cPonta,   "kW");
    // Perdas: sempre 0
    putEnergia("res_custo_perdas",  0,                 cPerdas,  "kWh");

    // Taxas e totais
    const put = (id, v) => {
      const el = document.getElementById(id);
      if (el) el.textContent = fmt2(v);
    };
    put("res_subtotal_energia", energiaSubtotal);
    put("res_taxa_fixa",        taxaFixa);
    put("res_taxa_radio",       taxaRadio);
    put("res_taxa_lixo",        taxaLixo);
    put("res_subtotal",         subtotalComIva);
    put("res_iva",              valorIva);
    put("res_total",            total);
  }

  async function calcFaturaMensal(){
    // Mantemos o botão "Calcular fatura" para confirmar com a API (se quiseres)
    recalcAll();
    function gv(id){ const el=$(id); return el ? toNum(el.value) : 0; }
    const payload = {
      kwh_ativa:      gv("#tot_kwh"),
      kwh_reativa:    gv("#tot_kvarh"),
      kwh_ponta:      gv("#tot_ponta"),
      kwh_perdas:     gv("#tot_delta"),
      fator_mult:     toNum(fatorMultTopEl?.value),
      tarifa_ativa:   toNum(tarifaAtivaEl?.value),
      tarifa_reativa: toNum(tarifaReativaEl?.value),
      tarifa_ponta:   toNum(tarifaPontaEl?.value),
      tarifa_perdas:  toNum(tarifaPerdasEl?.value),
      taxa_fixa:      toNum(taxaFixaEl?.value),
      taxa_radio:     toNum(taxaRadioEl?.value),
      taxa_lixo:      toNum(taxaLixoEl?.value),
      iva:            toNum(ivaEl?.value)
    };

    try {
      const r = await fetch("/api/leituras_mensal/calc_fatura", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error("HTTP "+r.status);
      const x = await r.json();
      const put = (sel,v) => { const el=$(sel); if(el) el.textContent = fmt2(v); };
      put("#res_custo_ativa",    x.custos.ativa);
      put("#res_custo_reativa",  x.custos.reativa);
      put("#res_custo_ponta",    x.custos.ponta);
      put("#res_custo_perdas",   x.custos.perdas);
      put("#res_subtotal_energia", x.energia_subtotal);
      put("#res_taxa_fixa",   x.taxas.fixa);
      put("#res_taxa_radio",  x.taxas.radio);
      put("#res_taxa_lixo",   x.taxas.lixo);
      put("#res_subtotal",    x.subtotal);
      put("#res_iva",         x.iva);
      put("#res_total",       x.total);
    } catch(e){
      console.error(e);
      alert("Falha no cálculo da fatura.");
    }
  }

  // Exporta o resumo da fatura para CSV (lado cliente)
  function exportResumoCSV(){
    recalcAll(); // garante valores atualizados

    function txt(id){
      const el = document.getElementById(id);
      return el ? el.textContent.trim() : "";
    }

    const linhas = [
      ["Campo","Valor"],
      ["Energia Ativa", txt("res_custo_ativa")],
      ["Energia Reativa", txt("res_custo_reativa")],
      ["Energia Ponta", txt("res_custo_ponta")],
      ["Perdas", txt("res_custo_perdas")],
      ["Subtotal Energia", txt("res_subtotal_energia")],
      ["Taxa Fixa", txt("res_taxa_fixa")],
      ["Taxa Rádio", txt("res_taxa_radio")],
      ["Taxa Lixo", txt("res_taxa_lixo")],
      ["Subtotal (com IVA, sem taxas)", txt("res_subtotal")],
      ["IVA", txt("res_iva")],
      ["Total (com taxas)", txt("res_total")]
    ];

    const csv = linhas.map(cols =>
      cols.map(c => `"${String(c).replace(/"/g,'""')}"`).join(";")
    ).join("\r\n");

    const blob = new Blob([csv], {type:"text/csv;charset=utf-8;"});
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url;
    a.download = "resumo_fatura_mensal.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function cascadeAnteriorFromRow(rowIdx){
    const rows = $all("tbody tr", tabela);
    for (let i=rowIdx+1; i<rows.length; i++){
      const prev = getInputs(rows[i-1]);
      const cur  = getInputs(rows[i]);
      if (!cur.anterior) break;
      if (cur.anterior.value && cur.anterior.value.trim()!=="") break;
      if (prev.atual && prev.atual.value){
        cur.anterior.value = prev.atual.value;
      } else {
        break;
      }
    }
  }

  function wireRowEvents(){
    const rows = $all("tbody tr", tabela);
    rows.forEach((tr, idx)=>{
      const I = getInputs(tr);

      // marca FP manual
      if (I.fp){
        I.fp.addEventListener("input", ()=>{
          if (I.fp.value && I.fp.value.trim() !== ""){
            I.fp.dataset.manualFp = "1";
          } else {
            delete I.fp.dataset.manualFp;
          }
        });
      }

      // marca Leit. Atual manual
      if (I.atual){
        I.atual.addEventListener("input", ()=>{
          if (I.atual.value && I.atual.value.trim() !== ""){
            I.atual.dataset.manualAtual = "1";
          } else {
            delete I.atual.dataset.manualAtual;
          }
        });
      }

      const onChange = ()=>{
        recalcAll();
        cascadeAnteriorFromRow(idx);
      };
      ["input","change","blur"].forEach(ev => {
        I.ativa   && I.ativa.addEventListener(ev, onChange);
        I.reativa && I.reativa.addEventListener(ev, onChange);
        I.ponta   && I.ponta.addEventListener(ev, onChange);
        I.anterior&& I.anterior.addEventListener(ev, onChange);
        I.atual   && I.atual.addEventListener(ev, onChange);
        I.agua    && I.agua.addEventListener(ev, onChange);
      });
    });
  }

  async function start(){
    // semente da 1ª 'Leit. Anterior'
    (function seedPrimeiraAnterior(){
      const seedEl = document.getElementById('seed_anterior_primeiro_dia');
      if (!seedEl || !tabela) return;
      const seed = parseFloat(String(seedEl.value||"").replace(",", "."));
      if (!isFinite(seed)) return;
      const firstRow = tabela.querySelector("tbody tr");
      if (!firstRow) return;
      const inps = firstRow.querySelectorAll("input");
      const anterior = inps[7];
      if (anterior && (!anterior.value || anterior.value.trim()==="")) {
        anterior.value = (Math.max(seed,0)).toFixed(2);
      }
    })();

    if(!tabela) return;

    if (localSel){
      const key = getLocalKey();
      const cfg = await fetchCfg(key);
      applyCfg(cfg || {});
    }

    wireRowEvents();
    recalcAll();

    if (localSel){
      localSel.addEventListener("change", async ()=>{
        const key2 = getLocalKey();
        const cfg2 = await fetchCfg(key2);
        applyCfg(cfg2 || {});
        recalcAll();
      });
    }

    // botão do topo
    if (btnFat){
      btnFat.addEventListener("click", (e)=>{
        e.preventDefault();
        calcFaturaMensal();
      });
    }

    // botão dentro do card "Resumo da Fatura"
    const btnCalcResumo = document.getElementById("btn_calc_fatura");
    if (btnCalcResumo){
      btnCalcResumo.addEventListener("click", function(e){
        e.preventDefault();
        calcFaturaMensal();
      });
    }

    // botão Exportar CSV do card
    const btnExportCsv = document.getElementById("btn_export_csv");
    if (btnExportCsv){
      btnExportCsv.addEventListener("click", function(e){
        e.preventDefault();
        exportResumoCSV();
      });
    }
  }

  if (document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
