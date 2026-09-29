"""Inverno 2026: comprado x vendido real (base de sell out do ZZNet).

Cruza os pedidos da estação 264 (painel) com a base "sell out" exportada do ZZNet.
A venda de cada SKU é atribuída à coleção do PEDIDO (não à do cadastro do produto),
consumindo primeiro as peças que chegaram antes.

Uso:
  python3 analise_sellout.py dashboard-data.json sell_out.xlsx --estacao-estoque estacao_0207.json
A base de sell out tem CPF de cliente: ela não é salva aqui, só os totais.
"""
import argparse, collections, csv, json
from datetime import datetime

import pandas as pd

NOMES = {'A01': 'INVERNO COLEÇÃO 1', 'A02': 'INVERNO COLEÇÃO 2', 'A03': 'INVERNO COLEÇÃO 3',
         'A04': 'REPOSIÇÃO GA', 'A05': 'CICLOS'}
CORTE = datetime(2026, 6, 30)


def sku_norm(p):
    return f'A.{p[1:6]}.{p[6:10]}.{p[10:14]}'


def data(s):
    return datetime.strptime(s, '%d/%m/%Y') if s else None


def valor(s):
    return float(s.replace('.', '').replace(',', '.')) if s else 0.0


def main(dados, sellout, estacao_estoque=None):
    d = json.load(open(dados, encoding='utf-8'))
    so = pd.read_excel(sellout)
    so['sku'] = so['SKU'].str.replace(' ', '.', regex=False)
    dt = pd.to_datetime(so['Data'], format='%d/%m/%Y')
    so['mes'] = dt.dt.month
    periodo = (dt.min().strftime('%d/%m/%Y'), dt.max().strftime('%d/%m/%Y'))

    linhas = [l for l in d['linhasPedidos'] if l['estacaoCod'] == '264' and l['status'] != 'Cancelado']
    info, por_sku = {}, collections.defaultdict(list)
    for l in linhas:
        s = sku_norm(l['produto'])
        quando = data(l['dataChegouLoja']) or data(l['dataFaturado']) or data(l['dataEmissaoPedido'])
        por_sku[s].append((quando, l))
        info[s] = {'categoria': l['categoria'], 'cor': l['cor'], 'material': l['material']}

    vend = so.groupby('sku').agg(qtd=('Qtde líquida', 'sum'), valor=('Valor liquido', 'sum'),
                                 trocas=('Qtde trocada', 'sum'))
    vend_mes = so.groupby(['sku', 'mes'])['Qtde líquida'].sum()

    col = collections.defaultdict(collections.Counter)
    skus = collections.defaultdict(dict)
    meses = collections.defaultdict(collections.Counter)
    pedidos = collections.defaultdict(set)
    for s, ls in por_sku.items():
        ls.sort(key=lambda x: x[0] or CORTE)
        v = vend.loc[s] if s in vend.index else None
        restante = max(0, int(v['qtd'])) if v is not None else 0
        total_vendido = restante
        for i, (_, l) in enumerate(ls):
            c = NOMES.get(l['colecaoCod'], l['colecao'])
            pedidos[c].add(l['pedido'])
            fat_ate = l['pecasFaturadas'] if l['dataFaturado'] and data(l['dataFaturado']) <= CORTE else 0
            usa = min(restante, l['pecasFaturadas'])
            if i == len(ls) - 1:
                usa = restante  # venda acima do faturado fica com o último pedido
            restante -= usa
            share = usa / total_vendido if total_vendido else 0
            a = col[c]
            a['comprado'] += l['qtde']
            a['faturado'] += l['pecasFaturadas']
            a['faturado_ate_jun'] += fat_ate
            a['custo'] += valor(l['valorFaturado'])
            a['vendido'] += usa
            a['venda_valor'] += float(v['valor']) * share if v is not None else 0
            k = skus[c].setdefault(s, collections.Counter())
            k['comprado'] += l['qtde']
            k['faturado'] += l['pecasFaturadas']
            k['vendido'] += usa
            if v is not None and share:
                for m, q in vend_mes.loc[s].items():
                    meses[c][int(m)] += q * share

    # Venda de produtos Inverno 2026 que não vieram de pedido Inverno 2026 (compras de temporadas anteriores)
    fora = so[~so['sku'].isin(por_sku.keys())]
    estacao = json.load(open(estacao_estoque, encoding='utf-8')) if estacao_estoque else {}
    sem_venda_reclass = [s for s in por_sku if s not in vend.index and (estacao.get(s) or '').startswith('272')]

    out = {'periodo': periodo, 'colecoes': [], 'precos': None, 'fora_pedido': {
        'pecas': int(fora['Qtde líquida'].sum()), 'valor': round(float(fora['Valor liquido'].sum()), 2),
        'skus': int(fora['sku'].nunique())},
        'reclass_verao27': {'skus': len(sem_venda_reclass),
                            'pecas': sum(l['pecasFaturadas'] for s in sem_venda_reclass for _, l in por_sku[s])},
        'total_base': {'pecas': int(so['Qtde líquida'].sum()), 'valor': round(float(so['Valor liquido'].sum()), 2),
                       'markdown': int(so['Qtde mark down'].sum()), 'trocas': int(so['Qtde trocada'].sum()),
                       'desconto_valor': round(float(((so['PVL catálogo'] - so['PVL loja']) * so['Qtde líquida']).sum()), 2),
                       'desconto_50': int(so.loc[so['% desconto'] >= 0.5, 'Qtde líquida'].sum()),
                       'desconto_100': int(so.loc[so['% desconto'] >= 0.99, 'Qtde líquida'].sum())}}
    # Preco cheio x mark down (classificacao da propria base; coleção do cadastro do produto)
    so['tipo'] = so['Full price'].map({'Sim': 'cheio', 'Mark down': 'markdown'}).fillna('cheio')
    so['catalogo'] = so['PVL catálogo'] * so['Qtde líquida']
    faixa = pd.cut(so['% desconto'], [-1, 0, .1, .2, .3, .49, .99, 1.0],
                   labels=['0', 'até 10%', '10–20%', '20–30%', '30–49%', '50–99%', '100%'])

    def quebra(chave):
        g = so.groupby([chave, 'tipo'], observed=True).agg(pecas=('Qtde líquida', 'sum'), venda=('Valor liquido', 'sum'),
                                                           catalogo=('catalogo', 'sum'))
        r = collections.defaultdict(dict)
        for (k, t), v in g.iterrows():
            r[str(k)][t] = {'pecas': int(v['pecas']), 'venda': round(float(v['venda']), 2),
                            'desconto': round(float(v['catalogo'] - v['venda']), 2)}
        return r
    so['_total'] = 'total'
    so['_faixa'] = faixa
    out_precos = {'total': quebra('_total')['total'], 'colecao_cadastro': quebra('Coleção'), 'mes': quebra('mes'),
                  'grupo': quebra('Grupo produto'),
                  'faixa': {k: v['markdown'] for k, v in quebra('_faixa').items() if 'markdown' in v}}

    for c, a in sorted(col.items(), key=lambda x: -x[1]['comprado']):
        lista = [{'sku': s, **info[s], **{k: int(v) for k, v in k_.items()}} for s, k_ in skus[c].items()]
        lista.sort(key=lambda x: (x['vendido'] - x['faturado'], -x['faturado']))
        out['colecoes'].append({'colecao': c, 'pedidos': len(pedidos[c]),
                                **{k: round(v, 2) if isinstance(v, float) else v for k, v in a.items()},
                                'meses': {m: round(q) for m, q in sorted(meses[c].items())},
                                'skus': lista})
    out['precos'] = out_precos
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('dados')
    ap.add_argument('sellout')
    ap.add_argument('--estacao-estoque')
    ap.add_argument('--saida', default='inverno26_sellout')
    a = ap.parse_args()
    res = main(a.dados, a.sellout, a.estacao_estoque)
    json.dump(res, open(f'{a.saida}.json', 'w', encoding='utf-8'), ensure_ascii=False)
    with open(f'{a.saida}_por_colecao.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Coleção', 'Pedidos', 'Comprado', 'Faturado', 'Vendido jan-jun', '% vendido do faturado',
                    'Sobra (faturado - vendido)', 'Custo NF (R$)', 'Venda líquida (R$)'])
        for c in res['colecoes']:
            st = round(100 * c['vendido'] / c['faturado']) if c['faturado'] else ''
            w.writerow([c['colecao'], c['pedidos'], c['comprado'], c['faturado'], c['vendido'], st,
                        c['faturado'] - c['vendido'], f"{c['custo']:.2f}".replace('.', ','),
                        f"{c['venda_valor']:.2f}".replace('.', ',')])
    with open(f'{a.saida}_por_sku.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Coleção', 'SKU', 'Categoria', 'Cor', 'Comprado', 'Faturado', 'Vendido jan-jun', 'Sobra'])
        for c in res['colecoes']:
            for s in c['skus']:
                w.writerow([c['colecao'], s['sku'], s['categoria'], s['cor'], s['comprado'], s['faturado'],
                            s['vendido'], s['faturado'] - s['vendido']])
    print('Período', res['periodo'], '| base total', res['total_base'])
    for c in res['colecoes']:
        print(f"  {c['colecao']:20} ped {c['pedidos']:3} comp {c['comprado']:5} fat {c['faturado']:5} "
              f"(até jun {c['faturado_ate_jun']:5}) vend {c['vendido']:5} R$ {c['venda_valor']:>11,.2f} "
              f"custo R$ {c['custo']:>11,.2f} meses {c['meses']}")
    print('fora de pedido Inverno 2026:', res['fora_pedido'], '| reclass Verão 27 sem venda:', res['reclass_verao27'])
