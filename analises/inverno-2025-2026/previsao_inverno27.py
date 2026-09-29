"""Previsão de compra do Inverno 2027 a partir dos Invernos 2025 e 2026.

Junta, para cada estação de inverno:
  - o que foi comprado e faturado (pedidos do painel),
  - a venda real de jan a jun (base "sell out" do ZZNet),
  - a venda da temporada inteira, estimada por faturado − estoque atual do SKU
    (o estoque fica com as chegadas mais recentes) e calibrada contra a venda real de 30/06/2026.

Demanda prevista por categoria = venda real jan–jun (média ponderada 2025/2026, mesma janela nos dois anos)
× multiplicador da temporada da categoria (venda total do Inverno 2026 ÷ venda jan–jun 2026 da categoria,
puxado pela metade para o multiplicador geral, para não oscilar em categorias pequenas).
Compra sugerida = demanda prevista ÷ sell-through alvo.

Saída: demanda e compra sugerida por categoria, curva de numeração, modelos para repetir ou cortar,
cores, faixas de preço e o calendário de venda.

Uso:
  python3 previsao_inverno27.py dashboard-data.json sell_out_2025.xlsx sell_out_2026.xlsx \
      --catalogo catalogo_estoque_02-07-2026.json --estoque-0207 estoque_02-07-2026.json
"""
import argparse, collections, csv, json
from datetime import datetime, timedelta

import pandas as pd

ESTACOES = {'2025': '254', '2026': '264'}
TAMANHOS = ['34', '35', '36', '37', '38', '39']
PESO_2026 = 0.6       # peso do ano mais recente na demanda prevista
ST_ALVO = 0.85        # parte da compra que se espera vender na temporada
HOJE = datetime(2026, 9, 29)


def sku_norm(p):
    return f'A.{p[1:6]}.{p[6:10]}.{p[10:14]}'


def data(s):
    return datetime.strptime(s, '%d/%m/%Y') if s else None


def chegada(l):
    """Data em que a peça entrou na loja; sem confirmação, usa o despacho ou faturamento + 5 dias."""
    return (data(l['dataChegouLoja']) or data(l['dataEntregueTransportadora'])
            or (data(l['dataFaturado']) + timedelta(days=5) if l['dataFaturado'] else None))


def rotulo_categoria(grupo, categoria):
    g, c = (grupo or '').upper(), (categoria or '').upper()
    if g == 'CALÇADOS' or any(c.startswith(x) for x in ('BOTA', 'FECHADO', 'SANDÁLIA', 'TÊNIS', 'MULE')):
        return c.capitalize()
    if g == 'BOLSAS' or c in ('GRANDE', 'MÉDIA', 'PEQUENA', 'MINI'):
        return 'Bolsa ' + c.lower()
    if g == 'CARTEIRAS' or c.startswith(('LOW', 'NEUTRAL')):
        return 'Carteiras'
    if g == 'CINTOS' or c in ('FINO', 'LARGO', 'MÉDIO'):
        return 'Cintos'
    return 'Acessórios'


def familia(cat):
    for f in ('Bota', 'Fechado', 'Sandália'):
        if cat.startswith(f):
            return f
    return None


def faixa_preco(v):
    for lim, nome in ((300, 'até R$ 299'), (400, 'R$ 300–399'), (500, 'R$ 400–499'), (700, 'R$ 500–699')):
        if v < lim:
            return nome
    return 'R$ 700+'


def vendido_por_linha(linhas, estoque, corte):
    """Peças vendidas por linha de pedido: chegou até o corte − estoque do SKU (estoque fica com o mais recente)."""
    ch = collections.defaultdict(list)
    for i, l in enumerate(linhas):
        c = chegada(l)
        if l['pecasFaturadas'] > 0 and c and c <= corte:
            ch[sku_norm(l['produto'])].append((c, i, l['pecasFaturadas']))
    vend = {}
    for s, xs in ch.items():
        resto = min(max(0, estoque.get(s, 0)), sum(q for _, _, q in xs))
        for _, i, q in sorted(xs, reverse=True):
            k = min(q, resto)
            resto -= k
            vend[i] = q - k
    return vend


def main(a):
    d = json.load(open(a.dados, encoding='utf-8'))
    linhas = d['linhasPedidos']
    catalogo = json.load(open(a.catalogo, encoding='utf-8'))
    so = {}
    for ano, arq in (('2025', a.sellout_2025), ('2026', a.sellout_2026)):
        x = pd.read_excel(arq)
        x['sku'] = x['SKU'].str.replace(' ', '.', regex=False)
        x['mes'] = pd.to_datetime(x['Data'], format='%d/%m/%Y').dt.month
        so[ano] = x

    # Atributos de cada SKU: base de sell out > catálogo do estoque > linha de pedido
    attr = {}
    for l in linhas:
        s = sku_norm(l['produto'])
        attr.setdefault(s, {'grupo': None, 'categoria': l['categoria'], 'cor': l['cor'], 'material': l['material'], 'pvl': None})
    for s, c in catalogo.items():
        attr.setdefault(s, {})
        attr[s].update({k: c[k] for k in ('grupo', 'categoria', 'cor', 'material') if c.get(k)})
        attr[s]['pvl'] = c['pvl'] or attr[s].get('pvl')
    for x in so.values():
        for r in x[['sku', 'Grupo produto', 'Categoria', 'PVL catálogo']].drop_duplicates('sku').itertuples(index=False):
            attr.setdefault(r[0], {})
            attr[r[0]].update({'grupo': r[1], 'categoria': r[2], 'pvl': float(r[3])})
    cat_de = lambda s: rotulo_categoria(attr.get(s, {}).get('grupo'), attr.get(s, {}).get('categoria'))
    for x in so.values():
        x['cat'] = x['sku'].map(cat_de)
        x['md'] = (x['Full price'] == 'Mark down').astype(int) * x['Qtde líquida']

    # Calibração: estimativa pelo estoque de 02/07/2026 × venda real até 30/06/2026
    est0207 = json.load(open(a.estoque_0207, encoding='utf-8'))
    v0207 = vendido_por_linha(linhas, est0207, datetime(2026, 7, 2))
    skus26 = {sku_norm(l['produto']) for l in linhas if l['estacaoCod'] == '264' and l['status'] != 'Cancelado'}
    estimado = sum(v for i, v in v0207.items() if linhas[i]['estacaoCod'] == '264' and linhas[i]['status'] != 'Cancelado')
    real = int(so['2026'].loc[so['2026']['sku'].isin(skus26), 'Qtde líquida'].clip(lower=None).sum())
    calib = real / estimado if estimado else 1.0

    estoque_hoje = {e['sku']: e['estoqueAtual'] for e in d['estoqueVendido']}
    vhoje = vendido_por_linha(linhas, estoque_hoje, HOJE)

    # ---- Por estação e categoria
    por_cat = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    por_modelo = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    por_cor = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    por_preco = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    modelo_info = {}
    for i, l in enumerate(linhas):
        ano = next((k for k, v in ESTACOES.items() if v == l['estacaoCod']), None)
        if not ano or l['status'] == 'Cancelado':
            continue
        s = sku_norm(l['produto'])
        cat = cat_de(s)
        vend = min(l['pecasFaturadas'], round(vhoje.get(i, 0) * calib))
        mod = s[2:7]
        modelo_info.setdefault(mod, {'categoria': cat, 'material': attr[s].get('material'), 'cores': set(), 'pvl': attr[s].get('pvl')})
        modelo_info[mod]['cores'].add(attr[s].get('cor') or '')
        for dic, chave in ((por_cat, cat), (por_modelo, mod), (por_cor, (attr[s].get('cor') or '—').strip()),
                           (por_preco, faixa_preco(attr[s].get('pvl') or 0))):
            c = dic[chave][ano]
            c['comprado'] += l['qtde']
            c['faturado'] += l['pecasFaturadas']
            c['vendido'] += vend
    for ano, x in so.items():
        for chave, g in x.groupby('cat'):
            por_cat[chave][ano]['jan_jun'] += int(g['Qtde líquida'].sum())
            por_cat[chave][ano]['jan_jun_md'] += int(g['md'].sum())
        x['mod'] = x['sku'].str[2:7]
        for chave, g in x.groupby('mod'):
            por_modelo[chave][ano]['jan_jun'] += int(g['Qtde líquida'].sum())
            por_modelo[chave][ano]['jan_jun_md'] += int(g['md'].sum())
        x['faixa'] = x['PVL catálogo'].map(faixa_preco)
        for chave, g in x.groupby('faixa'):
            por_preco[chave][ano]['jan_jun'] += int(g['Qtde líquida'].sum())
            por_preco[chave][ano]['jan_jun_md'] += int(g['md'].sum())

    # Multiplicador da temporada: venda total do Inverno 2026 (até hoje) ÷ venda real jan–jun 2026
    v26_total = sum(v['2026']['vendido'] for v in por_cat.values() if '2026' in v)
    jj26_total = sum(v['2026']['jan_jun'] for v in por_cat.values() if '2026' in v)
    mult = v26_total / jj26_total

    def linha_cat(nome, anos):
        a25, a26 = anos.get('2025', collections.Counter()), anos.get('2026', collections.Counter())
        jj = (1 - PESO_2026) * a25['jan_jun'] + PESO_2026 * a26['jan_jun']
        m_cat = a26['vendido'] / a26['jan_jun'] if a26['jan_jun'] >= 15 else mult
        m = (m_cat + mult) / 2
        demanda = jj * m if a25['jan_jun'] + a26['jan_jun'] >= 15 else (1 - PESO_2026) * a25['vendido'] + PESO_2026 * a26['vendido']
        return {'categoria': nome, 'familia': familia(nome),
                '2025': dict(a25), '2026': dict(a26), 'sobra26': a26['faturado'] - a26['vendido'],
                'jj': round(jj, 1), 'mult': round(m, 3), 'demanda': round(demanda), 'compra': round(demanda / ST_ALVO)}
    categorias = sorted((linha_cat(k, v) for k, v in por_cat.items()), key=lambda r: -r['compra'])

    # ---- Curva de numeração (calçados): venda jan–jun dos dois anos e sobra de hoje
    curva = {}
    for fam in ('Bota', 'Fechado', 'Sandália', None):
        venda = {}
        for ano, x in so.items():
            y = x[x['cat'].map(familia).notna()] if fam is None else x[x['cat'].map(familia) == fam]
            y = y[y['Numeração'].astype(str).isin(TAMANHOS)]
            t = y.groupby(y['Numeração'].astype(str))['Qtde líquida'].sum()
            venda[ano] = {tm: int(t.get(tm, 0)) for tm in TAMANHOS}
        sobra = collections.Counter()
        for e in d['estoqueVendido']:
            if not e.get('detalheTamanhos') or '2026' not in (e.get('estacao') or '') or 'INVERNO' not in (e.get('estacao') or ''):
                continue
            f = familia(cat_de(e['sku']))
            if f is None or (fam is not None and f != fam):
                continue
            for t in e['detalheTamanhos']:
                if t['tamanho'] in TAMANHOS:
                    sobra[t['tamanho']] += max(0, t['estoqueAtual'])
        tot = {ano: sum(v.values()) or 1 for ano, v in venda.items()}
        share = {tm: (1 - PESO_2026) * venda['2025'][tm] / tot['2025'] + PESO_2026 * venda['2026'][tm] / tot['2026'] for tm in TAMANHOS}
        curva[fam or 'Calçados'] = {'venda': venda, 'sobra_hoje': dict(sobra), 'curva': {k: round(v, 4) for k, v in share.items()}}

    # ---- Modelos
    modelos = []
    for mod, anos in por_modelo.items():
        a25, a26 = anos.get('2025', collections.Counter()), anos.get('2026', collections.Counter())
        if not (a25['faturado'] or a26['faturado']):
            continue
        inf = modelo_info.get(mod, {})
        modelos.append({'modelo': mod, 'categoria': inf.get('categoria'), 'material': inf.get('material'),
                        'pvl': inf.get('pvl'), 'cores': sorted(c for c in inf.get('cores', ()) if c)[:6],
                        '2025': dict(a25), '2026': dict(a26)})

    cores = [{'cor': k, '2025': dict(v.get('2025', {})), '2026': dict(v.get('2026', {}))} for k, v in por_cor.items()]
    precos = [{'faixa': k, '2025': dict(v.get('2025', {})), '2026': dict(v.get('2026', {}))} for k, v in por_preco.items()]
    meses = {ano: {int(m): int(q) for m, q in x.groupby('mes')['Qtde líquida'].sum().items()} for ano, x in so.items()}

    ja27 = collections.Counter()
    for l in linhas:
        if l['estacao'] == 'INVERNO 2027' and l['status'] != 'Cancelado':
            ja27[cat_de(sku_norm(l['produto']))] += l['qtde']

    return {'geradoEm': d['geradoEm'], 'calibracao': round(calib, 3), 'multiplicador': round(mult, 3), 'peso2026': PESO_2026, 'stAlvo': ST_ALVO,
            'categorias': categorias, 'curva': curva, 'modelos': modelos, 'cores': cores, 'precos': precos,
            'meses': meses, 'jaPedido2027': dict(ja27)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dados')
    ap.add_argument('sellout_2025')
    ap.add_argument('sellout_2026')
    ap.add_argument('--catalogo', required=True)
    ap.add_argument('--estoque-0207', required=True)
    ap.add_argument('--saida', default='previsao_inverno27')
    a = ap.parse_args()
    r = main(a)
    json.dump(r, open(f'{a.saida}.json', 'w', encoding='utf-8'), ensure_ascii=False)
    with open(f'{a.saida}_categorias.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Categoria', 'Comprado 2025', 'Vendido 2025 (temporada)', 'Comprado 2026', 'Vendido 2026 (temporada)',
                    'Demanda prevista 2027', 'Compra sugerida 2027', 'Já pedido 2027'])
        for c in r['categorias']:
            w.writerow([c['categoria'], c['2025'].get('comprado', 0), c['2025'].get('vendido', 0),
                        c['2026'].get('comprado', 0), c['2026'].get('vendido', 0), c['demanda'], c['compra'],
                        r['jaPedido2027'].get(c['categoria'], 0)])
    print('calibração', r['calibracao'], 'multiplicador temporada', r['multiplicador'])
    for c in r['categorias']:
        a25, a26 = c['2025'], c['2026']
        print(f"{c['categoria']:26} 25: comp {a25.get('comprado',0):4} vend {a25.get('vendido',0):4} jj {a25.get('jan_jun',0):4} md {a25.get('jan_jun_md',0):4} | "
              f"26: comp {a26.get('comprado',0):4} vend {a26.get('vendido',0):4} jj {a26.get('jan_jun',0):4} md {a26.get('jan_jun_md',0):4} sobra {c['sobra26']:4} | dem {c['demanda']:4} compra {c['compra']:4}")
    for k, v in r['curva'].items():
        print(k, v['curva'], 'sobra', v['sobra_hoje'])
    print('meses', r['meses'], 'ja 27', r['jaPedido2027'])
