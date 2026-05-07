
/*! SGE MT – Cálculo de Fatura (EDM) – drop‑in para módulo 'Leituras Mensais'
 *  Regras:
 *    ER_exced = max(0, ER_total - α * EA_total)   (α=0.50 por padrão)
 *    P_fat    = 0.2 * Pc + 0.8 * Dmax
 *    IVA      = 0.16 * 0.62 * Subtotal
 *  O script tenta detectar automaticamente as colunas 'Ativa', 'Reativa' e 'Ponta'.
 *  Sem alterar teu HTML, basta incluir este ficheiro e garantir que há um botão com
 *  id='btnCalcularFatura' (ou com texto 'Calcular Fatura').
 */
(function(){
  function num(v){ if(v==null) return 0; v = (""+v).replace(/\./g,'').replace(',','.'); var n=parseFloat(v); return isNaN(n)?0:n; }
  function fmt(n, d){ d = d==null?2:d; return (n||0).toLocaleString('pt-PT',{minimumFractionDigits:d, maximumFractionDigits:d}); }

  // Lê config da página (ids opcionais); senão aplica defaults EDM MT
  function readCfg(){
    function val(id, d){ var el=document.getElementById(id); return el? num(el.value || el.textContent): d; }
    // tentar vários ids conhecidos no teu módulo
    const fm = val('fator_multiplicativo', val('fm', val('fatorMult', 1.0)));
    const pc = val('potencia_contratada', val('pc', 0.0));
    const alfa = val('alfa_reativa', 0.50);
    const tarifaAtiva = val('tarifa_ativa', 4.780);
    const tarifaReativa = val('tarifa_reativa', 1.430);
    const tarifaPot = val('tarifa_potencia', 497.000);
    // IVA
    const ivaTaxa = val('iva_taxa', 0.16);
    const ivaBase = val('iva_base_factor', val('iva_base', 0.62));
    return {fm, pc, alfa, tarifaAtiva, tarifaReativa, tarifaPot, ivaTaxa, ivaBase};
  }

  // Detecta a tabela principal pelas colunas
  function findTable(){
    const tables = Array.from(document.querySelectorAll('table'));
    const wanted = ['Ativa','Reativa','Ponta'];
    for(const t of tables){
      const ths = Array.from(t.querySelectorAll('thead th')).map(th=>th.textContent.trim());
      const ok = wanted.every(w => ths.some(h => h.toLowerCase().includes(w.toLowerCase())));
      if(ok) return {el:t, headers:ths};
    }
    return null;
  }

  function headerIndex(headers, key){
    key = key.toLowerCase();
    for(let i=0;i<headers.length;i++){
      const h = headers[i].toLowerCase();
      if(h.includes(key)) return i;
    }
    return -1;
  }

  // Extrai linhas (inputs ou células editáveis)
  function readRows(tblInfo){
    const {el, headers} = tblInfo;
    const ixA = headerIndex(headers, 'Ativa');
    const ixR = headerIndex(headers, 'Reativa');
    const ixP = headerIndex(headers, 'Ponta'); // assumimos kVA; se for kW, o valor vem como digitado
    const rows = Array.from(el.querySelectorAll('tbody tr'));
    const out = [];
    rows.forEach(tr=>{
      const tds = Array.from(tr.children);
      function getCell(ix){
        if(ix<0 || ix>=tds.length) return null;
        const td = tds[ix];
        const inp = td.querySelector('input,textarea');
        return inp ? inp.value : td.textContent;
      }
      const ea = num(getCell(ixA));
      const er = num(getCell(ixR));
      const ponta = num(getCell(ixP));
      if(isFinite(ea+er+ponta)){
        out.push({ea, er, ponta, tr});
      }
    });
    return out;
  }

  // Painel de resumo (cria se não existir)
  function ensureSummary(){
    let box = document.getElementById('mt-resumo');
    if(!box){
      box = document.createElement('div');
      box.id = 'mt-resumo';
      box.className = 'card mt-3';
      box.innerHTML = '<div class="card-body"><h5 class="card-title">Resumo MT (EDM)</h5><div id="mt-resumo-body" class="row g-3"></div></div>';
      // inserir antes da tabela, se possível
      const anchor = document.querySelector('table');
      (anchor && anchor.parentElement) ? anchor.parentElement.insertBefore(box, anchor) : document.body.prepend(box);
    }
    return document.getElementById('mt-resumo-body');
  }

  function renderResumo(r){
    const body = ensureSummary();
    body.innerHTML = `
      <div class="col-md-3"><div><div class="small text-muted">Energia Ativa total</div><div class="h5">${fmt(r.EA_total,3)} kWh</div><div class="small">Custo: <strong>${fmt(r.C_ativo)} MZN</strong></div></div></div>
      <div class="col-md-3"><div><div class="small text-muted">Energia Reativa total</div><div class="h5">${fmt(r.ER_total,3)} kVArh</div><div class="small">Excedente: <strong>${fmt(r.ER_exced,3)} kVArh</strong></div><div class="small">Custo: <strong>${fmt(r.C_reativa)} MZN</strong></div></div></div>
      <div class="col-md-3"><div><div class="small text-muted">Demanda</div><div class="h5">Dmax: ${fmt(r.Dmax,3)} kVA</div><div class="small">P_fat: <strong>${fmt(r.P_fat,3)} kVA</strong></div><div class="small">Custo potência: <strong>${fmt(r.C_pot)} MZN</strong></div></div></div>
      <div class="col-md-3"><div><div class="small text-muted">Totais</div><div class="small">Subtotal: <strong>${fmt(r.subtotal)} MZN</strong></div><div class="small">IVA (${fmt(r.ivaTaxa*100,2)}% de ${fmt(r.ivaBase*100,0)}%): <strong>${fmt(r.iva)} MZN</strong></div><div class="h5">Total: ${fmt(r.total)} MZN</div></div></div>
    `;
  }

  function calcular(){
    const cfg = readCfg();
    const tbl = findTable();
    if(!tbl){ console.warn('Tabela de leituras não encontrada.'); return; }
    const rows = readRows(tbl);

    let EA_total = 0, ER_total = 0, Dmax = 0;
    rows.forEach(r=>{
      // aplica FM se o operador estiver digitando valores "do mostrador" (caso teu módulo já aplique FM, setar fm=1.0)
      const ea = r.ea * cfg.fm;
      const er = r.er * cfg.fm;
      const d = r.ponta * cfg.fm;
      EA_total += ea;
      ER_total += er;
      if(d > Dmax) Dmax = d;
    });

    const ER_exced = Math.max(0, ER_total - cfg.alfa * EA_total);
    const C_ativo = EA_total * cfg.tarifaAtiva;
    const C_reativa = ER_exced * cfg.tarifaReativa;
    const P_fat = 0.2 * cfg.pc + 0.8 * Dmax;
    const C_pot = P_fat * cfg.tarifaPot;
    const subtotal = C_ativo + C_reativa + C_pot;
    const iva = cfg.ivaTaxa * cfg.ivaBase * subtotal;
    const total = subtotal + iva;

    renderResumo({
      EA_total, ER_total, ER_exced,
      C_ativo, C_reativa,
      Dmax, P_fat, C_pot,
      subtotal, iva, total,
      ivaTaxa: cfg.ivaTaxa, ivaBase: cfg.ivaBase
    });
  }

  // Auto-binder no botão "Calcular Fatura" existente
  function bind(){
    // procurar pelo id
    let btn = document.getElementById('btnCalcularFatura');
    if(!btn){
      // procurar pelo texto
      const cands = Array.from(document.querySelectorAll('button, a.btn'));
      btn = cands.find(b => (b.textContent||'').trim().toLowerCase() === 'calcular fatura');
    }
    if(btn){
      btn.addEventListener('click', function(ev){
        try{ ev.preventDefault(); }catch(_){}
        calcular();
      });
    }
    // cálculo inicial opcional quando a página carrega
    setTimeout(calcular, 300);
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', bind);
  }else{
    bind();
  }
})();
