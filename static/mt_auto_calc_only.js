
/*! SGE – Leituras Mensais: auto-cálculo baseado em Ativa/Reativa/Ponta/Água
 *  Compatível com o teu HTML atual (.ativa, .reativa, .ponta, .agua, .fp, .anterior, .atual, .diferenca, .esp, .acum, .valor)
 *  Regras:
 *   - Operador digita: Ativa (kWh), Reativa (kVArh), Ponta (kW), Água (m³).
 *   - FP: se vazio/0, calculamos: FP = kWh / sqrt(kWh^2 + kVArh^2).
 *   - Δ Leitura = Ativa (kWh) do dia.
 *   - Leit. Anterior / Atual: cumulativas sintéticas (readonly) a partir de Δ.
 *   - Acum. kWh: soma das Ativas até a linha.
 *   - Valor (MT): (kWh*tarifa_ativa) + (kVArh*tarifa_reativa opcional) + (Ponta*tarifa_ponta opcional).
 *     Detecta tarifas em #tarifa_ativa_top, input[name=tarifa_ativa], #tarifa_reativa_top, input[name=tarifa_reativa], etc.
 */
(function(){
  const tabela = document.getElementById('tabela');
  if(!tabela) return;

  function num(v){
    if(v==null) return 0;
    v = (""+v).trim().replace(/\./g,'').replace(',','.');
    var n = parseFloat(v);
    return isFinite(n) ? n : 0;
  }
  function fmt(n, d){
    d = (d==null)?2:d;
    try { return (n||0).toLocaleString('pt-PT',{minimumFractionDigits:d,maximumFractionDigits:d}); }
    catch(_){ return (Math.round((n||0)*Math.pow(10,d))/Math.pow(10,d)).toString(); }
  }

  function getTarifa(idOrSel, def){
    let el = document.getElementById(idOrSel);
    if(!el) el = document.querySelector(idOrSel);
    if(!el) return def;
    const v = num(el.value || el.textContent);
    return isFinite(v) ? v : def;
  }

  function tarifas(){
    return {
      ativa:   getTarifa('tarifa_ativa_top', getTarifa('input[name=tarifa_ativa]', 0)),
      reativa: getTarifa('tarifa_reativa_top', getTarifa('input[name=tarifa_reativa]', 0)),
      ponta:   getTarifa('tarifa_ponta_top', getTarifa('input[name=tarifa_ponta]', 0)),
      perdas:  getTarifa('tarifa_perdas_top', getTarifa('input[name=tarifa_perdas]', 0)),
    };
  }

  function updateTotals(sum){
  function set(id, v, d){ const el = document.getElementById(id); if(el){ try{ el.value = (v||0).toLocaleString('pt-PT',{minimumFractionDigits:d,maximumFractionDigits:d}); }catch(_){ el.value = (Math.round((v||0)*Math.pow(10,d))/Math.pow(10,d)).toString(); } } }
  set('tot_kwh',  sum.kwh, 2);
  set('tot_kvarh',sum.kvarh, 2);
  set('tot_ponta',sum.ponta, 2);
  set('tot_delta',sum.delta, 2);
  set('tot_agua', sum.agua, 3);
  set('tot_acum', sum.acum, 2);
  set('tot_valor',sum.valor,2);
}
function recomputar(){
    const T = tarifas();
    let acumAtiva = 0;
    let leituraCumul = 0;
    const sums = {kwh:0,kvarh:0,ponta:0,delta:0,agua:0,acum:0,valor:0};

    const rows = Array.from(tabela.querySelectorAll('tbody tr'));
    rows.forEach(tr => {
      const ativa   = num(tr.querySelector('.ativa')?.value);
      const reativa = num(tr.querySelector('.reativa')?.value);
      const ponta   = num(tr.querySelector('.ponta')?.value);
      const agua    = num(tr.querySelector('.agua')?.value);
      const fpIn    = tr.querySelector('.fp');

      // FP automático se vazio/zero
      let fp = num(fpIn?.value);
      if((!fp || fp===0) && (ativa>0 || reativa>0)){
        const s = Math.sqrt(ativa*ativa + reativa*reativa);
        fp = s>0 ? (ativa/s) : 0;
        if(fpIn) fpIn.value = fmt(fp, 3);
      }else if(fpIn && fp){
        fpIn.value = fmt(fp, 3);
      }

      // Δ = Ativa
      const outDelta = tr.querySelector('.diferenca');
      if(outDelta) outDelta.value = fmt(ativa, 2);

      // Leituras cumulativas (sintéticas)
      const outAnt = tr.querySelector('.anterior');
      const outAtu = tr.querySelector('.atual');
      if(outAnt) outAnt.readOnly = true;
      if(outAtu) outAtu.readOnly = true;
      if(outAnt) outAnt.value = fmt(leituraCumul, 2);
      leituraCumul += ativa;
      if(outAtu) outAtu.value = fmt(leituraCumul, 2);

      // Consumo específico kWh/m³
      const outEsp = tr.querySelector('.esp');
      const esp = agua>0 ? (ativa/agua) : 0;
      if(outEsp) outEsp.value = fmt(esp, 3);

      // Acum kWh ao longo do mês
      acumAtiva += ativa;
      sums.kwh += ativa;
      sums.kvarh += reativa;
      sums.ponta += ponta;
      sums.delta += ativa;
      sums.agua += agua;
      const outAcum = tr.querySelector('.acum');
      if(outAcum) outAcum.value = fmt(acumAtiva, 2);

      // Valor (MT) – se existirem tarifas; perdas é proporcional a kWh
      const outVal = tr.querySelector('.valor');
      const valor = (ativa*T.ativa) + (reativa*T.reativa) + (ponta*T.ponta) + (ativa*T.perdas);
      if(outVal) outVal.value = fmt(valor, 2);
      sums.valor += valor;
    });
  }

  // Eventos
  tabela.addEventListener('input', (e)=>{
    if(e.target.matches('.ativa,.reativa,.ponta,.agua,.fp')) recomputar();
  });

  // Inicializa ao carregar
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', recomputar);
  } else {
    recomputar();
  }

  // expõe função global opcional para botão "Recalcular"
  window.SGE_Recalc_LeiturasMensal = recomputar;
})();
