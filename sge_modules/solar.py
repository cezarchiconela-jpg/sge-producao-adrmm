"""Domínio solar extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

@app.route('/solar', methods=['GET'])
def solar_home():
    """Centro unificado de Energia Solar.
    Mantém o dimensionamento FV e lâmpadas solares como submódulos, sem apagar as rotas antigas.
    """
    stats = {
        'projetos_fv': 0,
        'projetos_lampadas': 0,
        'itens_catalogo': 0,
        'kwp_total': 0.0,
        'economia_mensal_total': 0.0,
        'co2_total': 0.0,
        'ultimos_fv': [],
        'ultimos_lampadas': []
    }
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            row = c.execute("SELECT COUNT(*) AS n FROM solar_projetos").fetchone()
            stats['projetos_fv'] = int(row['n'] or 0) if row else 0
            rows = c.execute("SELECT id, created_at, nome_projeto, resultado_json FROM solar_projetos ORDER BY id DESC LIMIT 5").fetchall()
            for r in rows:
                try:
                    data = json.loads(r['resultado_json'] or '{}')
                except Exception:
                    data = {}
                stats['ultimos_fv'].append({
                    'id': r['id'],
                    'created_at': r['created_at'],
                    'nome': r['nome_projeto'] or data.get('local_nome') or 'Projeto fotovoltaico',
                    'kwp': float(data.get('kwp_real') or 0),
                    'payback': data.get('payback_anos'),
                    'economia': float(data.get('economia_mensal') or 0)
                })
                stats['kwp_total'] += float(data.get('kwp_real') or 0)
                stats['economia_mensal_total'] += float(data.get('economia_mensal') or 0)
                stats['co2_total'] += float(data.get('co2_t_ano') or 0)
        except Exception:
            pass
        try:
            row = c.execute("SELECT COUNT(*) AS n FROM solar_lampadas").fetchone()
            stats['projetos_lampadas'] = int(row['n'] or 0) if row else 0
            rows = c.execute("SELECT id, created_at, nome, resultado_json FROM solar_lampadas ORDER BY id DESC LIMIT 5").fetchall()
            for r in rows:
                try:
                    data = json.loads(r['resultado_json'] or '{}')
                except Exception:
                    data = {}
                stats['ultimos_lampadas'].append({
                    'id': r['id'],
                    'created_at': r['created_at'],
                    'nome': r['nome'] or 'Projeto de iluminação solar',
                    'painel_wp': data.get('painel_wp'),
                    'bateria_wh': data.get('bateria_wh_bruto'),
                    'capex': data.get('capex_estimado')
                })
        except Exception:
            pass
        try:
            row = c.execute("SELECT COUNT(*) AS n FROM solar_lampadas_catalogo").fetchone()
            stats['itens_catalogo'] = int(row['n'] or 0) if row else 0
        except Exception:
            pass
        conn.close()
    except Exception:
        pass
    return render_template('solar_home.html', stats=stats)



# === Energia Solar Expert: consumo robusto a partir das Leituras Mensais ===
def solar_consumo_mensal_robusto(local_nome, mes, ano, fator_mult=1.0):
    """Calcula consumo mensal para dimensionamento solar sem duplicar o factor multiplicativo."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT data, ativa, anterior, atual, diferenca
              FROM leituras_mensais
             WHERE local=? AND mes=? AND ano=?
             ORDER BY data ASC
        """, (local_nome, str(mes).zfill(2), int(ano))).fetchall()
        conn.close()
    except Exception:
        return 0.0, 0, 'sem dados'
    if not rows:
        return 0.0, 0, 'sem dados'
    def fv(x, default=None):
        try:
            if x is None or x == '': return default
            return float(str(x).replace(',', '.'))
        except Exception:
            return default
    difs_valid = []
    for r in rows:
        d = fv(r['diferenca'], None)
        if d is not None and d >= 0:
            difs_valid.append(d)
    soma_dif = sum(difs_valid)
    if soma_dif > 0:
        return float(soma_dif), len(difs_valid), 'soma das diferenças diárias faturáveis'
    bases = []
    atuais = []
    for r in rows:
        b = fv(r['anterior'], None)
        a = fv(r['atual'], None)
        if b is not None: bases.append(b)
        if a is not None: atuais.append(a)
    if bases and atuais and max(atuais) >= bases[0]:
        return float(max(atuais) - bases[0]), len(atuais), 'diferença leitura final - leitura base'
    ativas = []
    for r in rows:
        a = fv(r['ativa'], None)
        if a is not None: ativas.append(a)
    if ativas:
        return float(sum(ativas) * float(fator_mult or 1.0)), len(ativas), 'fallback: soma ativa lida x factor multiplicativo'
    return 0.0, 0, 'sem dados úteis'


def solar_irr(fluxos, low=-0.9, high=1.5, iterations=80):
    """IRR simples por bissecção; retorna None quando não há raiz coerente."""
    def npv_rate(rate):
        total = 0.0
        for i, cf in enumerate(fluxos):
            total += cf / ((1 + rate) ** i)
        return total
    try:
        f_low, f_high = npv_rate(low), npv_rate(high)
        if f_low * f_high > 0:
            return None
        for _ in range(iterations):
            mid = (low + high) / 2
            f_mid = npv_rate(mid)
            if abs(f_mid) < 1e-6:
                return mid
            if f_low * f_mid <= 0:
                high = mid; f_high = f_mid
            else:
                low = mid; f_low = f_mid
        return (low + high) / 2
    except Exception:
        return None
@app.route('/solar/dimensionamento', methods=['GET'])
@app.route('/solar/fotovoltaico', methods=['GET'])
def solar_form():
    # precisa existir a lista de locais
    locais = get_locais()
    hoje = datetime.now()
    default_periodo = hoje.strftime('%Y-%m')

    defaults = {
        "psh": 5.0,
        "derate": 0.77,
        "panel_wp": 550,
        "panel_area": 2.2,
        "tarifa_kwh": 4.78,
        "inv_dcac": 1.2,
        "autonomy_days": 1.0,
        "battery_dod": 0.8,
        "battery_eff": 0.9,
        "system_voltage": 48,
        "battery_module_kwh": 5.12,
        "capex_kwp": 90000.0,
        "opex_pct": 1.0,
        "tarifa_esc": 0.0,
        "desconto": 10.0,
        "anos_analise": 20,
        "co2_factor": 0.6,
        "cobertura_pct": 80.0,
        "autoconsumo_pct": 90.0,
        "crescimento_carga_pct": 0.0,
        "pico_kw": 0.0,
        "reserva_inversor_pct": 15.0,
        "area_disponivel": 0.0,
        "sombreamento_pct": 0.0,
        "perdas_cabos_pct": 2.0,
        "perdas_sujidade_pct": 3.0,
        "perdas_temp_pct": 8.0,
    }

    perfil_sazonal = [1.00, 1.02, 1.05, 1.08, 1.10, 1.05,
                      0.98, 0.95, 0.97, 0.99, 1.01, 1.03]

    # ATENÇÃO: o template solar.html deve usar {{ url_for('solar_projetos') }}
    # e como esta rota está logo abaixo, agora o Flask já conhece o endpoint
    return render_template(
        'solar.html',
        locais=locais,
        periodo=default_periodo,
        defaults=defaults,
        perfil_sazonal=perfil_sazonal
    )


@app.route('/solar/calcular', methods=['POST'])
def solar_calcular():
    def f(nome, default=0.0):
        v = request.form.get(nome, "")
        if v is None:
            return float(default)
        v = str(v).strip().replace(' ', '').replace(',', '.')
        if v == "":
            return float(default)
        try:
            return float(v)
        except ValueError:
            return float(default)

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    modo = request.form.get('modo', 'manual')
    local_id = request.form.get('local_id')
    periodo = request.form.get('periodo')
    tipo = request.form.get('tipo_sistema', 'ongrid')

    psh = max(f('psh', 5.0), 0.1)
    derate = clamp(f('derate', 0.77), 0.30, 0.98)
    panel_wp = max(f('panel_wp', 550), 1.0)
    panel_area = max(f('panel_area', 2.2), 0.1)
    inv_dcac = max(f('inv_dcac', 1.2), 0.1)
    fator_mult = max(f('fator_mult', 1.0), 0.0001)
    cobertura_pct = clamp(f('cobertura_pct', 80.0), 1.0, 150.0)
    autoconsumo_pct = clamp(f('autoconsumo_pct', 90.0), 0.0, 100.0)
    crescimento_carga_pct = f('crescimento_carga_pct', 0.0)
    pico_kw = max(f('pico_kw', 0.0), 0.0)
    reserva_inversor_pct = clamp(f('reserva_inversor_pct', 15.0), 0.0, 100.0)
    area_disponivel = max(f('area_disponivel', 0.0), 0.0)
    sombreamento_pct = clamp(f('sombreamento_pct', 0.0), 0.0, 60.0)
    perdas_cabos_pct = clamp(f('perdas_cabos_pct', 2.0), 0.0, 15.0)
    perdas_sujidade_pct = clamp(f('perdas_sujidade_pct', 3.0), 0.0, 20.0)
    perdas_temp_pct = clamp(f('perdas_temp_pct', 8.0), 0.0, 30.0)
    derate_expert = derate * (1 - sombreamento_pct/100.0) * (1 - perdas_cabos_pct/100.0) * (1 - perdas_sujidade_pct/100.0) * (1 - perdas_temp_pct/100.0)
    derate_expert = clamp(derate_expert, 0.20, 0.98)

    tarifa_kwh = f('tarifa_kwh', 4.78)
    capex_kwp = f('capex_kwp', 90000)
    opex_pct = f('opex_pct', 1.0)
    tarifa_esc = f('tarifa_esc', 0.0)
    desconto = f('desconto', 10.0)
    anos_analise = int(max(1, f('anos_analise', 20)))
    co2_factor = f('co2_factor', 0.6)

    autonomy_days = f('autonomy_days', 1.0)
    battery_dod = clamp(f('battery_dod', 0.8), 0.05, 1.0)
    battery_eff = clamp(f('battery_eff', 0.9), 0.05, 1.0)
    system_voltage = f('system_voltage', 48)
    battery_module_kwh = max(f('battery_module_kwh', 5.12), 0.1)

    perfil_sazonal_raw = request.form.get('perfil_sazonal_json')
    try:
        perfil_sazonal = json.loads(perfil_sazonal_raw) if perfil_sazonal_raw else None
    except Exception:
        perfil_sazonal = None
    if not perfil_sazonal or len(perfil_sazonal) != 12:
        perfil_sazonal = [1.00,1.02,1.05,1.08,1.10,1.05,0.98,0.95,0.97,0.99,1.01,1.03]

    consumo_metodo = 'manual'
    local_nome = request.form.get('local_nome_manual', 'Sem Local') or 'Sem Local'
    mes = ano = None
    dias_utilizados = None
    if modo == 'manual':
        daily_kwh_base = max(f('daily_kwh', 0), 0.0)
        total_mes_kwh = daily_kwh_base * 30.0
    else:
        total_mes_kwh = 0.0
        daily_kwh_base = 0.0
        dias_utilizados = 0
        if local_id and periodo:
            local_row = get_local_by_id(int(local_id))
            local_nome = local_row[1] if local_row else 'Sem Local'
            try:
                cfg = get_local_cfg_full(int(local_id))
                fator_mult = float(cfg.get('fator_mult') or fator_mult)
                tarifa_kwh = float(cfg.get('tarifa_ativa') or tarifa_kwh)
                if not pico_kw:
                    pico_kw = float(cfg.get('pot_contratada') or 0)
            except Exception:
                pass
            ano = int(periodo.split('-')[0]); mes = periodo.split('-')[1]
            total_mes_kwh, dias_utilizados, consumo_metodo = solar_consumo_mensal_robusto(local_nome, mes, ano, fator_mult)
            nd = calendar.monthrange(ano, int(mes))[1]
            daily_kwh_base = (total_mes_kwh / dias_utilizados) if dias_utilizados else (total_mes_kwh / nd if nd else 0.0)
        else:
            consumo_metodo = 'local não selecionado'

    daily_kwh_corrigido = daily_kwh_base * (1 + crescimento_carga_pct/100.0)
    total_mes_corrigido = total_mes_kwh * (1 + crescimento_carga_pct/100.0)
    daily_kwh_solar = daily_kwh_corrigido * (cobertura_pct/100.0)
    consumo_anual_estimado = daily_kwh_corrigido * 365.0

    kwp_necessario = daily_kwh_solar / (psh * derate_expert) if psh > 0 and derate_expert > 0 else 0.0
    n_paineis = math.ceil((kwp_necessario * 1000.0) / panel_wp) if panel_wp > 0 else 0
    kwp_real = (n_paineis * panel_wp) / 1000.0
    area_total = n_paineis * panel_area
    inversor_por_dcac = kwp_real / inv_dcac if inv_dcac > 0 else kwp_real
    inversor_por_pico = pico_kw * (1 + reserva_inversor_pct/100.0) if pico_kw > 0 else 0.0
    inversor_kw = max(inversor_por_dcac, inversor_por_pico)
    cabivel_area = True if area_disponivel <= 0 else area_total <= area_disponivel
    area_excedente = max(area_total - area_disponivel, 0.0) if area_disponivel > 0 else 0.0

    bateria_kwh_util = daily_kwh_corrigido * autonomy_days if tipo in ['offgrid','hibrido','hybrid'] else 0.0
    bateria_kwh_bruta = bateria_kwh_util / (battery_dod * battery_eff) if bateria_kwh_util > 0 else 0.0
    n_modulos_bateria = math.ceil(bateria_kwh_bruta / battery_module_kwh) if bateria_kwh_bruta > 0 else 0

    prod_mensal = []
    prod_anual = 0.0
    ano_ref = ano or datetime.now().year
    for m in range(1, 13):
        dias_m = calendar.monthrange(ano_ref, m)[1]
        psh_m = psh * float(perfil_sazonal[m-1])
        e_m = kwp_real * derate_expert * psh_m * dias_m
        prod_mensal.append(round(e_m, 2))
        prod_anual += e_m
    prod_anual = round(prod_anual, 2)
    limite_cobertura = consumo_anual_estimado * (cobertura_pct/100.0 if cobertura_pct <= 100 else 1.0)
    energia_util_anual = min(prod_anual * (autoconsumo_pct/100.0), limite_cobertura) if consumo_anual_estimado > 0 else 0.0
    cobertura_real_pct = (energia_util_anual / consumo_anual_estimado * 100.0) if consumo_anual_estimado > 0 else 0.0
    economia_anual = energia_util_anual * tarifa_kwh
    economia_mensal = economia_anual / 12.0

    capex_baterias = n_modulos_bateria * battery_module_kwh * capex_kwp * 0.15 if n_modulos_bateria else 0.0
    capex_total = kwp_real * capex_kwp + capex_baterias
    opex_anual = capex_total * (opex_pct / 100.0)

    r_desc = desconto / 100.0 if desconto > 0 else 0.0
    g = tarifa_esc / 100.0
    npv = -capex_total
    cumul = -capex_total
    payback_anos = None
    fluxos = [-capex_total]
    tarifa_t = tarifa_kwh
    energia_desc_total = 0.0
    custo_desc_total = capex_total
    for t in range(1, anos_analise + 1):
        receita_t = energia_util_anual * tarifa_t
        cf_t = receita_t - opex_anual
        fluxos.append(cf_t)
        fator_desc = ((1 + r_desc) ** t) if r_desc > 0 else 1.0
        npv += cf_t / fator_desc
        energia_desc_total += energia_util_anual / fator_desc
        custo_desc_total += opex_anual / fator_desc
        cumul += cf_t
        if payback_anos is None and cumul >= 0:
            prev_cumul = cumul - cf_t
            frac = 0 if cf_t == 0 else (0 - prev_cumul) / cf_t
            payback_anos = (t - 1) + max(0, min(1, frac))
        tarifa_t *= (1 + g)
    irr = solar_irr(fluxos)
    lcoe = (custo_desc_total / energia_desc_total) if energia_desc_total > 0 else None
    co2_t_ano = (energia_util_anual / 1000.0) * co2_factor

    alertas = []
    if daily_kwh_corrigido <= 0:
        alertas.append(('danger', 'Consumo não informado', 'Informe consumo diário ou selecione um local com leituras mensais gravadas.'))
    if not cabivel_area:
        alertas.append(('warning', 'Área disponível insuficiente', f'Área necessária {area_total:.1f} m²; área disponível {area_disponivel:.1f} m².'))
    if derate_expert < 0.65:
        alertas.append(('warning', 'Perdas elevadas', 'As perdas combinadas reduzem bastante a produção. Rever sombreamento, sujidade, cabos e temperatura.'))
    if tipo in ['offgrid','hibrido','hybrid'] and autonomy_days > 0 and n_modulos_bateria == 0:
        alertas.append(('info', 'Baterias não dimensionadas', 'Verifique o valor do módulo de bateria e a autonomia pretendida.'))
    if payback_anos is None and capex_total > 0:
        alertas.append(('warning', 'Payback não atingido no período', 'Rever CAPEX, tarifa, cobertura pretendida ou autoconsumo.'))

    r_dict = {
        'modo': modo, 'local_nome': local_nome, 'periodo': periodo, 'mes': mes, 'ano': ano,
        'dias_utilizados': dias_utilizados, 'consumo_metodo': consumo_metodo,
        'daily_kwh': daily_kwh_corrigido, 'daily_kwh_base': daily_kwh_base,
        'total_mes_kwh': total_mes_corrigido, 'total_mes_base_kwh': total_mes_kwh,
        'consumo_anual_estimado': consumo_anual_estimado,
        'psh': psh, 'derate': derate, 'derate_expert': derate_expert,
        'panel_wp': panel_wp, 'panel_area': panel_area, 'n_paineis': n_paineis,
        'kwp_necessario': kwp_necessario, 'kwp_real': kwp_real, 'area_total': area_total,
        'area_disponivel': area_disponivel, 'cabivel_area': cabivel_area, 'area_excedente': area_excedente,
        'inv_dcac': inv_dcac, 'inversor_kw': inversor_kw, 'inversor_por_dcac': inversor_por_dcac,
        'inversor_por_pico': inversor_por_pico, 'pico_kw': pico_kw, 'reserva_inversor_pct': reserva_inversor_pct,
        'tipo_sistema': tipo, 'tarifa_kwh': tarifa_kwh, 'economia_mensal': economia_mensal,
        'economia_anual': economia_anual, 'energia_util_anual': energia_util_anual,
        'cobertura_pct': cobertura_pct, 'cobertura_real_pct': cobertura_real_pct,
        'autoconsumo_pct': autoconsumo_pct, 'crescimento_carga_pct': crescimento_carga_pct,
        'sombreamento_pct': sombreamento_pct, 'perdas_cabos_pct': perdas_cabos_pct,
        'perdas_sujidade_pct': perdas_sujidade_pct, 'perdas_temp_pct': perdas_temp_pct,
        'autonomy_days': autonomy_days, 'battery_dod': battery_dod, 'battery_eff': battery_eff,
        'system_voltage': system_voltage, 'battery_module_kwh': battery_module_kwh,
        'bateria_kwh_util': bateria_kwh_util, 'bateria_kwh_bruta': bateria_kwh_bruta,
        'n_modulos_bateria': n_modulos_bateria, 'fator_mult': fator_mult,
        'producao_mensal': prod_mensal, 'producao_anual': prod_anual,
        'capex_kwp': capex_kwp, 'capex_baterias': capex_baterias, 'capex_total': capex_total,
        'opex_pct': opex_pct, 'opex_anual': opex_anual, 'tarifa_esc': tarifa_esc, 'desconto': desconto,
        'anos_analise': anos_analise, 'payback_anos': payback_anos,
        'npv': npv, 'irr': irr, 'lcoe': lcoe, 'co2_factor': co2_factor, 'co2_t_ano': co2_t_ano,
        'perfil_sazonal': perfil_sazonal, 'alertas': alertas
    }
    params = dict(r_dict)
    params['local_id'] = int(local_id) if local_id else None
    return render_template('solar_resultado.html', r=r_dict, params=params)


# === SALVAR PROJETO SOLAR ===

@app.route('/solar/salvar', methods=['POST'])
def solar_salvar():
    import sqlite3, json, time
    from datetime import datetime

    # dados que vieram escondidos do formulário
    r_json = request.form.get('r_json', '{}')
    params_json = request.form.get('params_json', '{}')

    # NOVOS CAMPOS visíveis no formulário
    nome_projeto = request.form.get('nome_projeto') or None
    obs = request.form.get('obs') or None

    # parse seguro
    try:
        r = json.loads(r_json) if r_json else {}
    except Exception:
        r = {}
    try:
        params = json.loads(params_json) if params_json else {}
    except Exception:
        params = {}

    agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    local_id = params.get('local_id')
    local_nome = r.get('local_nome') or params.get('local_nome') or None
    periodo = r.get('periodo')
    modo = r.get('modo')
    tipo = r.get('tipo_sistema')

    # (resto da função continua aqui…)


    # parte comum a qualquer versão da tabela
    comuns = [
        local_id, local_nome, periodo, modo, tipo,
        r.get('daily_kwh'), r.get('total_mes_kwh'), r.get('psh'), r.get('derate'),
        r.get('panel_wp'), r.get('panel_area'), r.get('n_paineis'),
        r.get('kwp_necessario'), r.get('kwp_real'), r.get('area_total'),
        r.get('inv_dcac'), r.get('inversor_kw'), r.get('tarifa_kwh'),
        r.get('economia_mensal'),
        r.get('autonomy_days'), r.get('battery_dod'), r.get('battery_eff'),
        r.get('system_voltage'), r.get('battery_module_kwh'),
        r.get('bateria_kwh_util'), r.get('bateria_kwh_bruta'),
        r.get('n_modulos_bateria'), r.get('mes'), r.get('ano'),
        r.get('dias_utilizados'), r.get('fator_mult'),
        json.dumps(r, ensure_ascii=False),
        json.dumps(params, ensure_ascii=False),
        r.get('capex_kwp'), r.get('capex_total'), r.get('opex_pct'), r.get('opex_anual'),
        r.get('tarifa_esc'), r.get('desconto'), r.get('anos_analise'),
        r.get('payback_anos'), r.get('npv'), r.get('co2_factor'), r.get('co2_t_ano'),
        r.get('producao_anual'),
        json.dumps(r.get('producao_mensal'), ensure_ascii=False),
        json.dumps(r.get('perfil_sazonal'), ensure_ascii=False),
        nome_projeto,
        obs,
    ]

    # tua tabela antiga tinha created_at
    colunas_old = [
        'created_at','local_id','local_nome','periodo','modo','tipo_sistema',
        'daily_kwh','total_mes_kwh','psh','derate','panel_wp','panel_area',
        'n_paineis','kwp_necessario','kwp_real','area_total','inv_dcac','inversor_kw',
        'tarifa_kwh','economia_mensal','autonomy_days','battery_dod','battery_eff',
        'system_voltage','battery_module_kwh','bateria_kwh_util','bateria_kwh_bruta',
        'n_modulos_bateria','mes','ano','dias_utilizados','fator_mult',
        'resultado_json','params_json',
        'capex_kwp','capex_total','opex_pct','opex_anual','tarifa_esc','desconto','anos_analise',
        'payback_anos','npv','co2_factor','co2_t_ano','producao_anual_kwh',
        'producao_mensal_json','perfil_sazonal_json',
        'nome_projeto','obs'
    ]
    valores_old = [agora] + comuns

    # nossa tabela nova usa criado_em
    colunas_new = colunas_old.copy()
    colunas_new[0] = 'criado_em'
    valores_new = [agora] + comuns

    def tentar_criar_colunas_extra(conn):
        """cria nome_projeto e obs se não existirem (ignora erro)"""
        try:
            conn.execute("ALTER TABLE solar_projetos ADD COLUMN nome_projeto TEXT;")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE solar_projetos ADD COLUMN obs TEXT;")
        except Exception:
            pass

    def do_insert(colunas, valores):
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        try:
            conn.execute("PRAGMA busy_timeout=10000;")
            # garante que a tabela existe (sem as colunas novas ainda)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS solar_projetos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT
                )
            """)
            # tenta criar as colunas novas (se já existem, ignora)
            tentar_criar_colunas_extra(conn)

            placeholders = ",".join(["?"] * len(valores))
            sql = f"INSERT INTO solar_projetos ({','.join(colunas)}) VALUES ({placeholders})"
            cur = conn.cursor()
            cur.execute(sql, valores)
            conn.commit()
        finally:
            conn.close()

    # vamos tentar até 5 vezes por causa de "database is locked"
    ultimo_erro = None
    for _ in range(5):
        try:
            try:
                # tenta com o nome que o teu banco já tinha
                do_insert(colunas_old, valores_old)
            except sqlite3.OperationalError as e:
                # se for erro de coluna, tenta com o outro nome
                if "no such column" in str(e).lower():
                    do_insert(colunas_new, valores_new)
                else:
                    raise
            ultimo_erro = None
            break
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                ultimo_erro = e
                time.sleep(0.5)
                continue
            else:
                ultimo_erro = e
                break
        except sqlite3.IntegrityError as e:
            # se foi NOT NULL em created_at, tenta com criado_em
            if "created_at" in str(e):
                do_insert(colunas_new, valores_new)
                ultimo_erro = None
                break
            else:
                ultimo_erro = e
                break

    if ultimo_erro is not None:
        raise ultimo_erro

    flash("Projeto solar salvo.", "success")
    return redirect(url_for('solar_projetos'))

# === LISTAR PROJETOS SALVOS ===
@app.route('/solar/projetos', methods=['GET'])
def solar_projetos():
    import sqlite3
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000;")
    c = conn.cursor()
    # tenta trazer também nome_projeto e obs; se não existir, fica NULL
    c.execute("""
        SELECT
            id,
            criado_em,
            created_at,
            local_nome,
            periodo,
            tipo_sistema,
            kwp_real,
            n_paineis,
            inversor_kw,
            economia_mensal,
            payback_anos,
            co2_t_ano,
            nome_projeto,
            obs
        FROM solar_projetos
        ORDER BY id DESC
    """)
    rows = c.fetchall()
    conn.close()
    return render_template('solar_projetos.html', projetos=rows)


# === DETALHAR PROJETO SALVO ===
@app.route('/solar/projeto/<int:pid>', methods=['GET'])
def solar_projeto_detalhe(pid):
    import sqlite3, json

    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000;")
    c = conn.cursor()
    # vamos tentar pegar tudo que pode existir
    c.execute("""
        SELECT
            resultado_json,
            params_json,
            nome_projeto,
            obs,
            local_nome,
            periodo,
            tipo_sistema,
            kwp_real,
            economia_mensal,
            payback_anos,
            co2_t_ano
        FROM solar_projetos
        WHERE id=?
    """, (pid,))
    row = c.fetchone()
    conn.close()

    if not row:
        return "Projeto não encontrado.", 404

    resultado_json = row[0]
    params_json = row[1]
    nome_projeto = row[2]
    obs = row[3]
    local_nome = row[4]
    periodo = row[5]
    tipo_sistema = row[6]
    kwp_real = row[7]
    economia_mensal = row[8]
    payback_anos = row[9]
    co2_t_ano = row[10]

    # parse do resultado salvo
    try:
        r = json.loads(resultado_json) if resultado_json else {}
    except Exception:
        r = {}
    try:
        params = json.loads(params_json) if params_json else {}
    except Exception:
        params = {}

    # caso o nome/local não estejam no JSON, usa os da tabela
    if nome_projeto and not r.get("nome_projeto"):
        r["nome_projeto"] = nome_projeto
    if local_nome and not r.get("local_nome"):
        r["local_nome"] = local_nome
    if periodo and not r.get("periodo"):
        r["periodo"] = periodo
    if obs:
        r["obs"] = obs

    # alguns campos podem não existir no JSON antigo
    if kwp_real and not r.get("kwp_real"):
        r["kwp_real"] = kwp_real
    if economia_mensal and not r.get("economia_mensal"):
        r["economia_mensal"] = economia_mensal
    if payback_anos is not None and not r.get("payback_anos"):
        r["payback_anos"] = payback_anos
    if co2_t_ano and not r.get("co2_t_ano"):
        r["co2_t_ano"] = co2_t_ano
    if tipo_sistema and not r.get("tipo_sistema"):
        r["tipo_sistema"] = tipo_sistema

    return render_template(
        'solar_projeto_detalhe.html',
        pid=pid,
        r=r,
        params=params
    )



# === EXPORTAR PRODUÇÃO MENSAL DE UM PROJETO (CSV) ===
@app.route('/solar/export/<int:pid>.csv')
def solar_export_csv(pid):
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000;")
    c = conn.cursor()
    c.execute("SELECT producao_mensal_json FROM solar_projetos WHERE id=?", (pid,))
    row = c.fetchone()
    conn.close()

    if not row or not row[0]:
        return Response("Projeto/produção não encontrada.", status=404)

    try:
        serie = json.loads(row[0])
    except Exception:
        return Response("Formato inválido.", status=400)

    si = StringIO()
    w = csv.writer(si, delimiter=';')
    w.writerow(["Mes", "Producao_kWh"])
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
             "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
    for i, val in enumerate(serie):
        mes = meses[i] if i < len(meses) else f"M{i+1}"
        w.writerow([mes, val])

    output = si.getvalue()
    filename = f"producao_mensal_projeto_{pid}.csv"
    return Response(
        output,
        mimetype='text/csv',
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )
# ==============================
# === DIMENSIONAMENTO LÂMPADAS SOLARES
# ==============================

import math, json, sqlite3, csv, io
from io import StringIO
from datetime import datetime
from flask import (
    render_template, render_template_string, request, redirect,
    url_for, Response, flash, abort
)

# ---------- Conexão robusta ----------
def _db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

# --- Catálogo padrão (mantido como no teu código) ---
def _catalogo_lampadas_padrao():
    return [
        {"modelo": "SL-30W", "potencia_w": 30, "fluxo_lm": 4200, "bateria_wh": 192, "autonomia_h": 12, "altura_poste_m": 4},
        {"modelo": "SL-50W", "potencia_w": 50, "fluxo_lm": 7000, "bateria_wh": 384, "autonomia_h": 12, "altura_poste_m": 6},
        {"modelo": "SL-80W", "potencia_w": 80, "fluxo_lm": 11000, "bateria_wh": 480, "autonomia_h": 12, "altura_poste_m": 8},
    ]

# ---------- Tabela de catálogo (garantia) ----------
def _ensure_lamp_catalog_table():
    with _db_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS solar_lampadas_catalogo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            modelo TEXT UNIQUE,
            potencia_w REAL,
            fluxo_lm REAL,
            bateria_wh REAL,
            autonomia_h REAL,
            altura_poste_m REAL,
            fabricante TEXT,
            preco_mt REAL,
            nota TEXT
        )
        """)

# ---------- Catálogo via BD com fallback ----------
def _catalogo_lampadas_from_db():
    """
    Lê catálogo da BD; caso esteja vazio, devolve o catálogo padrão.
    """
    _ensure_lamp_catalog_table()
    with _db_conn() as conn:
        rows = conn.execute("""
            SELECT modelo, potencia_w, fluxo_lm, bateria_wh, autonomia_h, altura_poste_m
            FROM solar_lampadas_catalogo
            ORDER BY fluxo_lm ASC
        """).fetchall()
    if rows:
        return [
            {
                "modelo": r["modelo"],
                "potencia_w": r["potencia_w"] or 0.0,
                "fluxo_lm": r["fluxo_lm"] or 0.0,
                "bateria_wh": r["bateria_wh"] or 0.0,
                "autonomia_h": r["autonomia_h"] or 0.0,
                "altura_poste_m": r["altura_poste_m"] or 0.0,
            }
            for r in rows
        ]
    return _catalogo_lampadas_padrao()

# ---------- FORM (GET) ----------
@app.route('/solar/lampadas', methods=['GET'], endpoint='solar_lampadas_form')
def solar_lampadas_form():
    """Centro expert de dimensionamento de lâmpadas solares/autónomas."""
    catalogo = _catalogo_lampadas_from_db()
    altura_qs = request.args.get('altura', type=float)
    return render_template('solar_lampadas.html', resultado=None, catalogo=catalogo, sugestoes=[], altura_qs=altura_qs)

@app.route('/solar/lampadas/usar/<int:cat_id>', methods=['GET'])
def solar_lampadas_usar(cat_id):
    _ensure_lamp_catalog_table()
    with _db_conn() as conn:
        row = conn.execute("SELECT altura_poste_m FROM solar_lampadas_catalogo WHERE id=?",(cat_id,)).fetchone()
    altura = float(row["altura_poste_m"]) if row and row["altura_poste_m"] is not None else 5.0
    return redirect(url_for('solar_lampadas_form', altura=altura))

def _solar_float(form, nome, default=0.0):
    v = (form.get(nome) or '').strip()
    if v == '':
        return float(default)
    try:
        return float(v.replace(' ', '').replace(',', '.'))
    except Exception:
        return float(default)

def _solar_int(form, nome, default=0):
    try:
        return int(round(_solar_float(form, nome, default)))
    except Exception:
        return int(default)

def _lampadas_classe_presets():
    return {
        'vias_pedonais': {'nome':'Vias pedonais / passeios', 'lux': 7.5, 'altura': 4.0, 'shr': 4.0},
        'parques': {'nome':'Parques / jardins', 'lux': 15.0, 'altura': 5.0, 'shr': 4.0},
        'rua_local': {'nome':'Rua local / residencial', 'lux': 12.0, 'altura': 6.0, 'shr': 4.8},
        'rua_coletora': {'nome':'Rua coletora', 'lux': 20.0, 'altura': 8.0, 'shr': 5.5},
        'estacionamento': {'nome':'Estacionamento / pátio', 'lux': 12.0, 'altura': 6.0, 'shr': 4.5},
        'armazem_ext': {'nome':'Recinto industrial exterior', 'lux': 20.0, 'altura': 8.0, 'shr': 5.0},
        'seguranca': {'nome':'Segurança perimetral', 'lux': 10.0, 'altura': 5.0, 'shr': 4.5},
    }

def _lampadas_numero_postes(modo, area_m2, comprimento_via, largura_via, altura_poste, classe, dupla_fileira, qtd_manual):
    presets = _lampadas_classe_presets()
    shr = presets.get(classe, {}).get('shr', 5.0)
    espacamento_m = max(altura_poste * shr, 1.0)
    if modo == 'manual' and qtd_manual > 0:
        qtd = qtd_manual
    elif modo == 'via':
        fileiras = 2 if dupla_fileira else 1
        qtd = max(int(math.ceil(max(comprimento_via, 0) / espacamento_m)) + 1, 1) * fileiras
        area_m2 = max(area_m2, comprimento_via * max(largura_via, 1.0))
    else:
        # Estimativa por área: área de influência aproximada por poste.
        area_por_poste = max((espacamento_m * espacamento_m * 0.55), 1.0)
        qtd = max(int(math.ceil(max(area_m2, 1.0) / area_por_poste)), 1)
    return int(qtd), float(espacamento_m), float(area_m2)

@app.route('/solar/lampadas/calcular', methods=['POST'])
def solar_lampadas_calcular():
    """Dimensionamento expert de iluminação solar autónoma."""
    form = request.form
    classe = (form.get('classe') or '').strip()
    modo_implantacao = (form.get('modo_implantacao') or 'area').strip()
    nome_projeto = (form.get('nome_projeto') or '').strip()

    presets = _lampadas_classe_presets()
    preset = presets.get(classe, {})

    area_m2 = _solar_float(form, 'area_m2', 200)
    comprimento_via_m = _solar_float(form, 'comprimento_via_m', 100)
    largura_via_m = _solar_float(form, 'largura_via_m', 6)
    iluminancia_lux = _solar_float(form, 'iluminancia_lux', preset.get('lux', 10))
    altura_poste = _solar_float(form, 'altura_poste', preset.get('altura', 5))
    if not (form.get('iluminancia_lux') or '').strip() and preset:
        iluminancia_lux = preset['lux']
    if not (form.get('altura_poste') or '').strip() and preset:
        altura_poste = preset['altura']

    qtd_manual = _solar_int(form, 'qtd_manual', 0)
    dupla_fileira = (form.get('dupla_fileira') == '1')
    qtd_postes, espacamento_m, area_corrigida = _lampadas_numero_postes(
        modo_implantacao, area_m2, comprimento_via_m, largura_via_m, altura_poste,
        classe, dupla_fileira, qtd_manual
    )
    area_por_luminaria = area_corrigida / max(qtd_postes, 1)

    autonomia_h = _solar_float(form, 'autonomia_h', 12)
    autonomia_dias = _solar_float(form, 'autonomia_dias', 2)
    psh = _solar_float(form, 'horas_carga', 5)
    fator_util = _solar_float(form, 'fator_util', 0.80)
    fator_man = _solar_float(form, 'fator_man', 0.90)
    fator_seg = _solar_float(form, 'fator_seg', 1.20)
    lm_por_w = _solar_float(form, 'lm_por_w', 150)

    dim_0_6 = _solar_float(form, 'dim_0_6', 100)
    dim_6_12 = _solar_float(form, 'dim_6_12', 50)
    dim_extra = _solar_float(form, 'dim_extra', 30)

    dod = _solar_float(form, 'dod', 0.80)
    eficiencia_bateria = _solar_float(form, 'eficiencia_bateria', 0.90)
    eficiencia_controlador = _solar_float(form, 'eficiencia_controlador', 0.92)
    bateria_v = _solar_float(form, 'bateria_v', 12)
    margem_painel = _solar_float(form, 'margem_painel', 1.25)

    custo_luminaria = _solar_float(form, 'custo_luminaria', 15000)
    custo_painel_w = _solar_float(form, 'custo_painel_w', 30)
    custo_bateria_wh = _solar_float(form, 'custo_bateria_wh', 12)
    custo_poste = _solar_float(form, 'custo_poste', 18000)
    custo_instalacao = _solar_float(form, 'custo_instalacao', 8000)
    opex_pct = _solar_float(form, 'opex_pct', 2.0)
    tarifa_kwh = _solar_float(form, 'tarifa_kwh', 8.0)

    # Fluxo e potência por luminária
    fluxo_min_lm = (iluminancia_lux * area_por_luminaria) / max(fator_util * fator_man, 1e-6)
    fluxo_projeto_lm = fluxo_min_lm * max(fator_seg, 1.0)
    potencia_led_w_nom = fluxo_projeto_lm / max(lm_por_w, 1e-6)

    # Perfil noturno com dimerização em três blocos
    h1 = min(autonomia_h, 6.0)
    h2 = min(max(autonomia_h - h1, 0.0), 6.0)
    h3 = max(autonomia_h - h1 - h2, 0.0)
    energia_noite_wh = potencia_led_w_nom * ((dim_0_6/100.0)*h1 + (dim_6_12/100.0)*h2 + (dim_extra/100.0)*h3)
    potencia_media_w = energia_noite_wh / max(autonomia_h, 1e-6)

    # Painel, bateria e controlador por poste
    painel_wp = energia_noite_wh / max(psh * eficiencia_controlador, 1e-6) * margem_painel
    bateria_wh_util = energia_noite_wh * max(autonomia_dias, 1.0)
    bateria_wh_nominal = bateria_wh_util / max(dod * eficiencia_bateria, 1e-6)
    bateria_ah = bateria_wh_nominal / max(bateria_v, 1e-6)
    controlador_a = max((painel_wp / max(bateria_v, 1e-6)) * 1.25, 5.0)

    energia_noite_total_kwh = (energia_noite_wh * qtd_postes) / 1000.0
    energia_anual_kwh = energia_noite_total_kwh * 365.0
    economia_anual_mt = energia_anual_kwh * tarifa_kwh

    custo_unit = (custo_luminaria + painel_wp*custo_painel_w + bateria_wh_nominal*custo_bateria_wh + custo_poste + custo_instalacao)
    capex_total = custo_unit * qtd_postes
    opex_anual = capex_total * (opex_pct/100.0)
    economia_liquida_anual = max(economia_anual_mt - opex_anual, 0)
    payback = capex_total / economia_liquida_anual if economia_liquida_anual > 0 else 0
    co2_t_ano = energia_anual_kwh * 0.0007

    # Catálogo e seleção inteligente
    catalogo = _catalogo_lampadas_from_db()
    sugestoes = []
    for item in catalogo:
        fluxo = float(item.get('fluxo_lm') or 0)
        pot = float(item.get('potencia_w') or 0)
        bat = float(item.get('bateria_wh') or 0)
        aut = float(item.get('autonomia_h') or 0)
        alt = float(item.get('altura_poste_m') or 0)
        atende_fluxo = fluxo >= fluxo_projeto_lm
        atende_pot = pot >= potencia_led_w_nom * 0.85
        atende_bateria = bat >= bateria_wh_util
        atende_autonomia = aut >= autonomia_h
        altura_ok = abs(alt - altura_poste) <= 2.0 if alt else True
        score = 0
        score += 35 if atende_fluxo else max(0, 20 * fluxo / max(fluxo_projeto_lm, 1))
        score += 25 if atende_bateria else max(0, 15 * bat / max(bateria_wh_util, 1))
        score += 15 if atende_autonomia else 0
        score += 15 if altura_ok else 5
        score += 10 if atende_pot else 3
        sugestoes.append({
            'item': item, 'score': round(min(score, 100), 1),
            'atende_fluxo': atende_fluxo, 'atende_bateria': atende_bateria,
            'atende_autonomia': atende_autonomia, 'altura_ok': altura_ok,
            'margem_fluxo': round(fluxo - fluxo_projeto_lm, 1)
        })
    sugestoes.sort(key=lambda x: (-x['score'], abs((x['item'].get('fluxo_lm') or 0)-fluxo_projeto_lm)))

    alertas = []
    if psh < 4.0: alertas.append('PSH baixo: aumentar painel ou autonomia para garantir carga em dias críticos.')
    if bateria_ah > 250: alertas.append('Banco de baterias elevado por poste: considerar tensão maior, bateria modular ou reduzir potência/dimerização.')
    if painel_wp > 350: alertas.append('Painel por poste elevado: verificar sombreamento, PSH e potência da luminária.')
    if fluxo_projeto_lm < 1500: alertas.append('Fluxo baixo: confirme se a aplicação permite este nível de iluminação.')
    if payback and payback > 10: alertas.append('Payback elevado: validar custos unitários, tarifa evitada e necessidade operacional do projecto.')

    resultado = {
        'nome_projeto': nome_projeto,
        'classe': classe,
        'classe_nome': preset.get('nome', classe or 'Personalizado'),
        'modo_implantacao': modo_implantacao,
        'area_m2': round(area_corrigida, 2),
        'comprimento_via_m': round(comprimento_via_m, 2),
        'largura_via_m': round(largura_via_m, 2),
        'qtd_postes': qtd_postes,
        'espacamento_m': round(espacamento_m, 2),
        'area_por_luminaria': round(area_por_luminaria, 2),
        'dupla_fileira': dupla_fileira,
        'iluminancia_lux': round(iluminancia_lux, 2),
        'altura_poste': round(altura_poste, 2),
        'autonomia_h': round(autonomia_h, 2),
        'autonomia_dias': round(autonomia_dias, 2),
        'horas_carga': round(psh, 2),
        'fator_util': round(fator_util, 3),
        'fator_man': round(fator_man, 3),
        'fator_seg': round(fator_seg, 2),
        'lm_por_w': round(lm_por_w, 1),
        'dim_0_6': round(dim_0_6, 1), 'dim_6_12': round(dim_6_12, 1), 'dim_extra': round(dim_extra, 1),
        'fluxo_min_lm': round(fluxo_min_lm, 1),
        'fluxo_projeto_lm': round(fluxo_projeto_lm, 1),
        'potencia_led_w': round(potencia_led_w_nom, 1),
        'potencia_media_w': round(potencia_media_w, 1),
        'energia_noite_wh': round(energia_noite_wh, 1),
        'painel_wp': round(painel_wp, 1),
        'bateria_wh_util': round(bateria_wh_util, 1),
        'bateria_wh_bruto': round(bateria_wh_nominal, 1),
        'bateria_ah': round(bateria_ah, 1),
        'bateria_v': round(bateria_v, 1),
        'controlador_a': round(controlador_a, 1),
        'energia_noite_total_kwh': round(energia_noite_total_kwh, 2),
        'energia_anual_kwh': round(energia_anual_kwh, 2),
        'tarifa_kwh': round(tarifa_kwh, 2),
        'economia_anual_mt': round(economia_anual_mt, 2),
        'capex_unitario': round(custo_unit, 2),
        'capex_estimado': round(capex_total, 2),
        'opex_anual': round(opex_anual, 2),
        'payback_anos': round(payback, 2),
        'co2_t_ano': round(co2_t_ano, 2),
        'custo_luminaria': round(custo_luminaria, 2),
        'custo_painel_w': round(custo_painel_w, 2),
        'custo_bateria_wh': round(custo_bateria_wh, 2),
        'custo_poste': round(custo_poste, 2),
        'custo_instalacao': round(custo_instalacao, 2),
        'alertas': alertas,
    }
    return render_template('solar_lampadas.html', resultado=resultado, catalogo=[s['item'] for s in sugestoes], sugestoes=sugestoes, altura_qs=None)

@app.route('/solar/lampadas/espacamento', methods=['POST'])
def solar_lampadas_espacamento():
    classe = (request.form.get('classe') or '').strip()
    try:
        altura = float((request.form.get('altura_poste') or '0').replace(',','.'))
        comp_via = float((request.form.get('comprimento_via_m') or '0').replace(',','.'))
    except Exception:
        return {"ok": False, "erro": "altura/comprimento inválidos"}, 400
    if altura <= 0 or comp_via <= 0:
        return {"ok": False, "erro": "altura/comprimento inválidos"}, 400
    shr = _lampadas_classe_presets().get(classe, {}).get('shr', 5.0)
    espac_m = max(altura * shr, 1.0)
    fileiras = 2 if (request.form.get('dupla_fileira') == '1') else 1
    qtd = max(int(math.ceil(comp_via / espac_m)) + 1, 1) * fileiras
    return {"ok": True, "espac_m": round(espac_m, 2), "qtd_postes": int(qtd)}

@app.route('/solar/lampadas/orcamento', methods=['POST'])
def solar_lampadas_orcamento():
    _ensure_lamp_catalog_table()
    modelo = (request.form.get('modelo') or '').strip()
    try:
        qtd = int((request.form.get('qtd') or '0').strip())
    except Exception:
        qtd = 0
    if not modelo or qtd <= 0:
        return {"ok": False, "erro": "modelo/quantidade inválidos"}, 400
    with _db_conn() as conn:
        row = conn.execute("SELECT preco_mt FROM solar_lampadas_catalogo WHERE modelo=?", (modelo,)).fetchone()
    if not row or row["preco_mt"] is None:
        return {"ok": False, "erro": "modelo sem preço"}, 400
    preco = float(row["preco_mt"])
    total = preco * qtd
    return {"ok": True, "preco_unit": round(preco,2), "qtd": qtd, "total": round(total,2)}

@app.route('/solar/lampadas/salvar', methods=['POST'])
def solar_lampadas_salvar():
    r_json = request.form.get('r_json', '{}')
    nome_projeto = request.form.get('nome_projeto') or None
    obs = request.form.get('obs') or None
    try:
        r = json.loads(r_json) if r_json else {}
    except Exception:
        r = {}
    with _db_conn() as conn:
        conn.execute("""
          CREATE TABLE IF NOT EXISTS solar_lampadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            nome TEXT,
            obs TEXT,
            resultado_json TEXT NOT NULL
          )
        """)
        conn.execute(
            "INSERT INTO solar_lampadas (created_at, nome, obs, resultado_json) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), nome_projeto, obs, json.dumps(r, ensure_ascii=False))
        )
    flash("Projeto de iluminação solar salvo.", "success")
    return redirect(url_for('solar_lampadas_projetos'))

# ==============================
# === CATÁLOGO: LÂMPADAS SOLARES (CRUD) ===
# ==============================

@app.route('/solar/lampadas/catalogo', methods=['GET'])
def solar_lampadas_catalogo_list():
    _ensure_lamp_catalog_table()
    with _db_conn() as conn:
        rows = conn.execute("""
            SELECT id, modelo, fabricante, potencia_w, fluxo_lm, bateria_wh,
                   autonomia_h, altura_poste_m, preco_mt, nota
            FROM solar_lampadas_catalogo
            ORDER BY fluxo_lm DESC, potencia_w DESC
        """).fetchall()
    return render_template('solar_lampadas_catalogo_list.html', items=rows)

@app.route('/api/solar/lampadas/catalogo.json')
def api_solar_lampadas_catalogo():
    _ensure_lamp_catalog_table()
    with _db_conn() as conn:
        rows = conn.execute("""
            SELECT id, modelo, fabricante, fluxo_lm, potencia_w, preco_mt
            FROM solar_lampadas_catalogo
            ORDER BY modelo ASC
        """).fetchall()
    data = []
    for r in rows:
        data.append({"id": r["id"], "modelo": r["modelo"], "fabricante": r["fabricante"],
                     "fluxo_lm": float(r["fluxo_lm"] or 0), "potencia_w": float(r["potencia_w"] or 0),
                     "preco_mt": float(r["preco_mt"] or 0)})
    return {"ok": True, "itens": data}

@app.route('/solar/lampadas/catalogo/novo', methods=['GET','POST'])
def solar_lampadas_catalogo_novo():
    _ensure_lamp_catalog_table()
    if request.method == 'POST':
        modelo = (request.form.get('modelo') or '').strip()
        fabricante = (request.form.get('fabricante') or '').strip()
        potencia_w = _solar_float(request.form, 'potencia_w', 0)
        fluxo_lm = _solar_float(request.form, 'fluxo_lm', 0)
        bateria_wh = _solar_float(request.form, 'bateria_wh', 0)
        autonomia_h = _solar_float(request.form, 'autonomia_h', 0)
        altura_poste_m = _solar_float(request.form, 'altura_poste_m', 0)
        preco_mt = _solar_float(request.form, 'preco_mt', 0)
        nota = (request.form.get('nota') or '').strip()
        if not modelo:
            flash("Informe o modelo.", "warning")
            return redirect(url_for('solar_lampadas_catalogo_novo'))
        try:
            with _db_conn() as conn:
                conn.execute("""INSERT INTO solar_lampadas_catalogo
                                (modelo, fabricante, potencia_w, fluxo_lm, bateria_wh, autonomia_h, altura_poste_m, preco_mt, nota)
                                VALUES (?,?,?,?,?,?,?,?,?)""",
                             (modelo, fabricante, potencia_w, fluxo_lm, bateria_wh, autonomia_h, altura_poste_m, preco_mt, nota))
            flash("Modelo adicionado.", "success")
        except sqlite3.IntegrityError:
            flash("Modelo já existente.", "danger")
        return redirect(url_for('solar_lampadas_catalogo_list'))
    return render_template('solar_lampadas_catalogo_form.html', item=None)

@app.route('/solar/lampadas/catalogo/<int:cat_id>/editar', methods=['GET','POST'])
def solar_lampadas_catalogo_editar(cat_id):
    _ensure_lamp_catalog_table()
    with _db_conn() as conn:
        if request.method == 'POST':
            modelo = (request.form.get('modelo') or '').strip()
            fabricante = (request.form.get('fabricante') or '').strip()
            potencia_w = _solar_float(request.form, 'potencia_w', 0)
            fluxo_lm = _solar_float(request.form, 'fluxo_lm', 0)
            bateria_wh = _solar_float(request.form, 'bateria_wh', 0)
            autonomia_h = _solar_float(request.form, 'autonomia_h', 0)
            altura_poste_m = _solar_float(request.form, 'altura_poste_m', 0)
            preco_mt = _solar_float(request.form, 'preco_mt', 0)
            nota = (request.form.get('nota') or '').strip()
            try:
                conn.execute("""UPDATE solar_lampadas_catalogo
                                SET modelo=?, fabricante=?, potencia_w=?, fluxo_lm=?, bateria_wh=?,
                                    autonomia_h=?, altura_poste_m=?, preco_mt=?, nota=?
                                WHERE id=?""",
                             (modelo, fabricante, potencia_w, fluxo_lm, bateria_wh, autonomia_h, altura_poste_m, preco_mt, nota, cat_id))
                flash("Modelo atualizado.", "success")
            except sqlite3.IntegrityError:
                flash("Modelo duplicado.", "danger")
            return redirect(url_for('solar_lampadas_catalogo_list'))
        row = conn.execute("""SELECT id, modelo, fabricante, potencia_w, fluxo_lm, bateria_wh,
                                     autonomia_h, altura_poste_m, preco_mt, nota
                              FROM solar_lampadas_catalogo WHERE id=?""", (cat_id,)).fetchone()
    if not row:
        flash("Modelo não encontrado.", "warning")
        return redirect(url_for('solar_lampadas_catalogo_list'))
    return render_template('solar_lampadas_catalogo_form.html', item=row)

@app.route('/solar/lampadas/catalogo/<int:cat_id>/apagar', methods=['POST'])
def solar_lampadas_catalogo_apagar(cat_id):
    _ensure_lamp_catalog_table()
    with _db_conn() as conn:
        conn.execute("DELETE FROM solar_lampadas_catalogo WHERE id=?", (cat_id,))
    flash("Modelo removido.", "info")
    return redirect(url_for('solar_lampadas_catalogo_list'))

@app.route('/solar/lampadas/catalogo/export.csv', methods=['GET'])
def solar_lampadas_catalogo_export():
    _ensure_lamp_catalog_table()
    with _db_conn() as conn:
        rows = conn.execute("""SELECT modelo, fabricante, potencia_w, fluxo_lm, bateria_wh,
                                      autonomia_h, altura_poste_m, preco_mt, nota
                               FROM solar_lampadas_catalogo
                               ORDER BY modelo ASC""").fetchall()
    si = io.StringIO(); w = csv.writer(si, delimiter=';')
    w.writerow(["modelo","fabricante","potencia_w","fluxo_lm","bateria_wh","autonomia_h","altura_poste_m","preco_mt","nota"])
    for r in rows:
        w.writerow([r["modelo"], r["fabricante"], r["potencia_w"], r["fluxo_lm"], r["bateria_wh"], r["autonomia_h"], r["altura_poste_m"], r["preco_mt"], r["nota"]])
    return Response(si.getvalue(), mimetype='text/csv', headers={"Content-Disposition": "attachment;filename=catalogo_lampadas.csv"})

@app.route('/solar/lampadas/catalogo/import', methods=['GET','POST'])
def solar_lampadas_catalogo_import():
    _ensure_lamp_catalog_table()
    if request.method == 'POST':
        data = request.form.get('csv_text', '').strip()
        delim = request.form.get('delim', ';')
        if not data:
            flash("Cole o conteúdo CSV.", "warning")
            return redirect(url_for('solar_lampadas_catalogo_import'))
        reader = csv.DictReader(io.StringIO(data), delimiter=delim)
        inseridos = atualizados = 0
        with _db_conn() as conn:
            for row in reader:
                modelo = (row.get('modelo') or '').strip()
                if not modelo: continue
                def _flt(x):
                    try: return float((x or '0').replace(',','.'))
                    except: return 0.0
                vals = ((row.get('fabricante') or '').strip(), _flt(row.get('potencia_w')), _flt(row.get('fluxo_lm')), _flt(row.get('bateria_wh')), _flt(row.get('autonomia_h')), _flt(row.get('altura_poste_m')), _flt(row.get('preco_mt')), (row.get('nota') or '').strip())
                ex = conn.execute("SELECT id FROM solar_lampadas_catalogo WHERE modelo=?", (modelo,)).fetchone()
                if ex:
                    conn.execute("""UPDATE solar_lampadas_catalogo SET fabricante=?, potencia_w=?, fluxo_lm=?, bateria_wh=?, autonomia_h=?, altura_poste_m=?, preco_mt=?, nota=? WHERE modelo=?""", vals + (modelo,))
                    atualizados += 1
                else:
                    conn.execute("""INSERT INTO solar_lampadas_catalogo (modelo, fabricante, potencia_w, fluxo_lm, bateria_wh, autonomia_h, altura_poste_m, preco_mt, nota) VALUES (?,?,?,?,?,?,?,?,?)""", (modelo,) + vals)
                    inseridos += 1
        flash(f"Importação concluída. Inseridos: {inseridos}, Atualizados: {atualizados}", "success")
        return redirect(url_for('solar_lampadas_catalogo_list'))
    return render_template('solar_lampadas_catalogo_import.html')

@app.route('/solar/lampadas/projetos', methods=['GET'])
def solar_lampadas_projetos():
    with _db_conn() as conn:
        rows = conn.execute("SELECT id, created_at, nome, obs, resultado_json FROM solar_lampadas ORDER BY id DESC").fetchall()
    projetos=[]
    for r in rows:
        try: data=json.loads(r['resultado_json'] or '{}')
        except Exception: data={}
        projetos.append({'id':r['id'], 'created_at':r['created_at'], 'nome':r['nome'], 'obs':r['obs'], 'r':data})
    return render_template('solar_lampadas_projetos.html', projetos=projetos)

@app.route('/solar/lampadas/projeto/<int:pid>', methods=['GET'])
def solar_lampadas_projeto(pid):
    with _db_conn() as conn:
        row = conn.execute("SELECT id, created_at, nome, obs, resultado_json FROM solar_lampadas WHERE id=?", (pid,)).fetchone()
    if not row:
        return Response("Projeto não encontrado", status=404)
    try: r = json.loads(row["resultado_json"] or '{}')
    except Exception: r = {}
    return render_template('solar_lampadas_projeto_detalhe.html', pid=row['id'], criado=row['created_at'], nome=row['nome'], obs=row['obs'], r=r)

@app.route('/solar/lampadas/export/<int:pid>.csv')
def solar_lampadas_export(pid):
    with _db_conn() as conn:
        row = conn.execute("SELECT resultado_json FROM solar_lampadas WHERE id=?", (pid,)).fetchone()
    if not row: return Response("Projeto não encontrado.", status=404)
    try: r = json.loads(row["resultado_json"])
    except Exception: return Response("Formato inválido.", status=400)
    si = StringIO(); w = csv.writer(si, delimiter=';')
    w.writerow(["campo","valor"])
    for k in sorted(r.keys()):
        val = r.get(k)
        if isinstance(val, (dict, list)): val = json.dumps(val, ensure_ascii=False)
        w.writerow([k, val])
    return Response(si.getvalue(), mimetype='text/csv', headers={"Content-Disposition": f"attachment;filename=lampadas_projeto_{pid}.csv"})



# ==============================
# === SOLAR: PORTFÓLIO, COMPARAÇÃO E RELATÓRIO CONSOLIDADO ===
# ==============================

def _solar_num(v, default=0.0):
    try:
        if v is None or v == '':
            return float(default)
        return float(str(v).replace(',', '.'))
    except Exception:
        return float(default)

def _solar_json_load(txt):
    try:
        return json.loads(txt or '{}')
    except Exception:
        return {}

def _solar_fmt_mt(v):
    try:
        return ("{:,.2f}".format(float(v or 0))).replace(',', 'X').replace('.', ',').replace('X', '.') + ' MT'
    except Exception:
        return '0,00 MT'

def _solar_get_fv_projects(limit=None):
    with _db_conn() as conn:
        try:
            sql = "SELECT * FROM solar_projetos ORDER BY id DESC"
            if limit:
                sql += " LIMIT " + str(int(limit))
            rows = conn.execute(sql).fetchall()
        except Exception:
            rows = []
    projetos = []
    for row in rows:
        keys = row.keys()
        r = _solar_json_load(row['resultado_json'] if 'resultado_json' in keys else '{}')
        nome = (row['nome_projeto'] if 'nome_projeto' in keys else None) or r.get('nome_projeto') or f"Projeto FV #{row['id']}"
        criado = (row['criado_em'] if 'criado_em' in keys else None) or (row['created_at'] if 'created_at' in keys else '')
        def col(name, fallback=0):
            try:
                return row[name] if name in keys and row[name] not in [None, ''] else r.get(name, fallback)
            except Exception:
                return r.get(name, fallback)
        projetos.append({
            'tipo': 'FV', 'uid': f"fv:{row['id']}", 'id': row['id'], 'nome': nome, 'criado': criado,
            'local': col('local_nome', r.get('local_nome','')), 'sistema': col('tipo_sistema', r.get('tipo_sistema','')),
            'kwp': _solar_num(col('kwp_real', r.get('kwp_real',0))), 'paineis': int(_solar_num(col('n_paineis', r.get('n_paineis',0)),0)),
            'inversor_kw': _solar_num(col('inversor_kw', r.get('inversor_kw',0))), 'capex': _solar_num(col('capex_total', r.get('capex_total',0))),
            'economia_mensal': _solar_num(col('economia_mensal', r.get('economia_mensal',0))),
            'economia_anual': _solar_num(col('economia_mensal', r.get('economia_mensal',0))) * 12,
            'payback': _solar_num(col('payback_anos', r.get('payback_anos',0))), 'co2': _solar_num(col('co2_t_ano', r.get('co2_t_ano',0))),
            'energia_anual': _solar_num(col('producao_anual_kwh', r.get('producao_anual',0))),
            'url': url_for('solar_projeto_detalhe', pid=row['id']),
            'csv_url': url_for('solar_export_csv', pid=row['id'])
        })
    return projetos

def _solar_get_lamp_projects(limit=None):
    with _db_conn() as conn:
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS solar_lampadas (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, nome TEXT, obs TEXT, resultado_json TEXT NOT NULL
            )""")
            sql = "SELECT id, created_at, nome, obs, resultado_json FROM solar_lampadas ORDER BY id DESC"
            if limit:
                sql += " LIMIT " + str(int(limit))
            rows = conn.execute(sql).fetchall()
        except Exception:
            rows = []
    projetos=[]
    for row in rows:
        r = _solar_json_load(row['resultado_json'])
        projetos.append({
            'tipo': 'Iluminação', 'uid': f"lamp:{row['id']}", 'id': row['id'], 'nome': row['nome'] or r.get('nome_projeto') or f"Projeto Iluminação #{row['id']}",
            'criado': row['created_at'], 'local': r.get('classe_nome') or r.get('modo_implantacao') or '', 'sistema': 'Lâmpadas solares autónomas',
            'kwp': 0.0, 'paineis': int(_solar_num(r.get('qtd_postes'),0)), 'postes': int(_solar_num(r.get('qtd_postes'),0)),
            'painel_wp': _solar_num(r.get('painel_wp')), 'bateria_wh': _solar_num(r.get('bateria_wh_bruto')), 'capex': _solar_num(r.get('capex_estimado')),
            'economia_mensal': _solar_num(r.get('economia_anual_mt')) / 12 if _solar_num(r.get('economia_anual_mt')) else 0,
            'economia_anual': _solar_num(r.get('economia_anual_mt')), 'payback': _solar_num(r.get('payback_anos')), 'co2': _solar_num(r.get('co2_t_ano')),
            'energia_anual': _solar_num(r.get('energia_anual_kwh')),
            'url': url_for('solar_lampadas_projeto', pid=row['id']),
            'csv_url': url_for('solar_lampadas_export', pid=row['id'])
        })
    return projetos

def _solar_portfolio_data():
    fv = _solar_get_fv_projects()
    lamps = _solar_get_lamp_projects()
    todos = fv + lamps
    stats = {
        'total': len(todos), 'fv_count': len(fv), 'lamp_count': len(lamps),
        'kwp_total': sum(p.get('kwp',0) for p in fv),
        'postes_total': sum(p.get('postes',0) for p in lamps),
        'capex_total': sum(p.get('capex',0) for p in todos),
        'economia_anual_total': sum(p.get('economia_anual',0) for p in todos),
        'co2_total': sum(p.get('co2',0) for p in todos),
        'energia_anual_total': sum(p.get('energia_anual',0) for p in todos),
    }
    stats['payback_medio'] = (stats['capex_total'] / stats['economia_anual_total']) if stats['economia_anual_total'] > 0 else 0
    ranking = sorted(todos, key=lambda x: x.get('economia_anual',0), reverse=True)[:10]
    alertas=[]
    if stats['total'] == 0:
        alertas.append(('info','Ainda não existem simulações solares guardadas.'))
    if any((p.get('capex',0) <= 0) for p in todos):
        alertas.append(('warning','Existem projectos sem CAPEX informado; isso reduz a precisão financeira do portfólio.'))
    if any((p.get('payback',0) > 10) for p in todos if p.get('payback',0)):
        alertas.append(('warning','Há projectos com payback superior a 10 anos; convém rever custos, tarifa evitada e cobertura solar.'))
    if stats['economia_anual_total'] > 0 and stats['payback_medio'] <= 5:
        alertas.append(('success','O portfólio apresenta retorno global atractivo pela simulação guardada.'))
    return {'fv': fv, 'lamps': lamps, 'todos': todos, 'stats': stats, 'ranking': ranking, 'alertas': alertas}

@app.route('/solar/portfolio')
def solar_portfolio():
    data = _solar_portfolio_data()
    return render_template('solar_portfolio.html', **data)

@app.route('/solar/relatorio')
def solar_relatorio_consolidado():
    data = _solar_portfolio_data()
    return render_template('solar_relatorio_consolidado.html', **data, gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'))

@app.route('/solar/portfolio/export.csv')
def solar_portfolio_export_csv():
    data = _solar_portfolio_data()
    si = StringIO(); w = csv.writer(si, delimiter=';')
    w.writerow(['tipo','id','nome','local/classe','sistema','potencia_kWp','postes_ou_paineis','energia_anual_kWh','economia_anual_MT','capex_MT','payback_anos','co2_t_ano'])
    for p in data['todos']:
        w.writerow([p.get('tipo'), p.get('id'), p.get('nome'), p.get('local'), p.get('sistema'), p.get('kwp',0), p.get('postes') or p.get('paineis'), p.get('energia_anual',0), p.get('economia_anual',0), p.get('capex',0), p.get('payback',0), p.get('co2',0)])
    return Response(si.getvalue(), mimetype='text/csv', headers={'Content-Disposition':'attachment;filename=portfolio_solar.csv'})

@app.route('/solar/comparador')
def solar_comparador():
    data = _solar_portfolio_data()
    opcoes = data['todos']
    a_uid = request.args.get('a') or (opcoes[0]['uid'] if opcoes else '')
    b_uid = request.args.get('b') or (opcoes[1]['uid'] if len(opcoes) > 1 else '')
    mapa = {p['uid']: p for p in opcoes}
    a = mapa.get(a_uid)
    b = mapa.get(b_uid)
    metricas = [
        ('Energia anual', 'energia_anual', 'kWh/ano'),
        ('Economia anual', 'economia_anual', 'MT/ano'),
        ('CAPEX', 'capex', 'MT'),
        ('Payback', 'payback', 'anos'),
        ('CO₂ evitado', 'co2', 't/ano'),
        ('Potência FV', 'kwp', 'kWp'),
        ('Postes', 'postes', 'un'),
    ]
    return render_template('solar_comparador.html', opcoes=opcoes, a=a, b=b, a_uid=a_uid, b_uid=b_uid, metricas=metricas)



# === Energia Solar: decisão executiva, premissas e proposta técnica ===
def _solar_to_float(v, default=0.0):
    try:
        if v is None or v == '':
            return default
        return float(str(v).replace(' ', '').replace(',', '.'))
    except Exception:
        return default

def _solar_decision_data():
    data = _solar_portfolio_data()
    projetos = []
    max_economia = max([_solar_to_float(p.get('economia_anual')) for p in data.get('todos', [])] + [1.0])
    max_co2 = max([_solar_to_float(p.get('co2')) for p in data.get('todos', [])] + [1.0])
    for p in data.get('todos', []):
        payback = _solar_to_float(p.get('payback'))
        economia = _solar_to_float(p.get('economia_anual'))
        co2 = _solar_to_float(p.get('co2'))
        capex = _solar_to_float(p.get('capex'))
        energia = _solar_to_float(p.get('energia_anual'))
        score = 0
        # retorno financeiro
        if payback > 0:
            if payback <= 3: score += 35
            elif payback <= 5: score += 28
            elif payback <= 7: score += 20
            elif payback <= 10: score += 12
            else: score += 5
        # impacto económico relativo
        score += min(25, 25 * (economia / max_economia if max_economia else 0))
        # impacto ambiental relativo
        score += min(15, 15 * (co2 / max_co2 if max_co2 else 0))
        # qualidade dos dados
        if capex > 0: score += 10
        if energia > 0: score += 10
        if p.get('tipo') == 'Fotovoltaico' and _solar_to_float(p.get('kwp')) > 0: score += 5
        if p.get('tipo') != 'Fotovoltaico' and _solar_to_float(p.get('postes')) > 0: score += 5
        score = round(min(100, score), 1)
        if score >= 75:
            classe = 'Prioridade alta'
            decisao = 'Avançar para estudo executivo / proposta comercial'
        elif score >= 55:
            classe = 'Prioridade média'
            decisao = 'Rever premissas e validar custos antes de avançar'
        elif score >= 35:
            classe = 'Prioridade baixa'
            decisao = 'Manter em carteira; optimizar CAPEX, autonomia ou cobertura'
        else:
            classe = 'Incompleto'
            decisao = 'Completar dados técnicos e financeiros'
        riscos=[]
        if capex <= 0: riscos.append('CAPEX não informado')
        if payback <= 0: riscos.append('Payback não calculado')
        if payback > 10: riscos.append('Payback elevado')
        if energia <= 0: riscos.append('Energia anual não estimada')
        if p.get('tipo') == 'Fotovoltaico' and _solar_to_float(p.get('kwp')) <= 0: riscos.append('Potência FV não calculada')
        if p.get('tipo') != 'Fotovoltaico' and _solar_to_float(p.get('postes')) <= 0: riscos.append('Quantidade de postes não definida')
        pp = dict(p)
        pp.update({'score': score, 'classe': classe, 'decisao': decisao, 'riscos': riscos})
        projetos.append(pp)
    projetos.sort(key=lambda x: x.get('score',0), reverse=True)
    data['projetos_decisao'] = projetos
    data['score_medio'] = round(sum([p.get('score',0) for p in projetos]) / len(projetos), 1) if projetos else 0
    data['alta_prioridade'] = len([p for p in projetos if p.get('score',0) >= 75])
    data['incompletos'] = len([p for p in projetos if p.get('score',0) < 35])
    data['gerado_em'] = datetime.now().strftime('%d/%m/%Y %H:%M')
    return data

@app.route('/solar/decisao')
def solar_decisao():
    data = _solar_decision_data()
    return render_template('solar_decisao.html', **data)

@app.route('/solar/premissas')
def solar_premissas():
    return render_template('solar_premissas.html', gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'))

@app.route('/solar/proposta')
def solar_proposta():
    data = _solar_decision_data()
    return render_template('solar_proposta_executiva.html', **data)

@app.route('/solar/portfolio/export.json')
def solar_portfolio_export_json():
    data = _solar_portfolio_data()
    payload = {
        'gerado_em': datetime.now().isoformat(timespec='seconds'),
        'stats': data.get('stats', {}),
        'projetos': data.get('todos', [])
    }
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype='application/json', headers={'Content-Disposition':'attachment;filename=portfolio_solar_sge.json'})

# === API: config por local (JSON) (mantida) ===
