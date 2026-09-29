"""Comprado x faturado x chegou x vendido x sobrou — coleções de Inverno 2025 e 2026.

Fonte: dashboard-data.json do artefato "Painel Americas Shopping" (extração ZZNet, loja 322685).
Uso: python3 analise_inverno.py caminho/dashboard-data.json
"""
import csv, json, sys, collections
from datetime import datetime

ESTACOES = ['INVERNO 2025', 'INVERNO 2026']


def sku_norm(p):
    return f'A.{p[1:6]}.{p[6:10]}.{p[10:14]}'


def valor(s):
    return float(s.replace('.', '').replace(',', '.')) if s else 0.0


def data(s):
    return datetime.strptime(s, '%d/%m/%Y') if s else None


def grupo(l):
    """Estação/coleção de inverno da linha, ou None. Atemporais comprados na temporada entram à parte."""
    if l['estacao'] in ESTACOES:
        return l['estacao'], l['colecao']
    if l['estacao'] == 'ATEMPORAIS' and l['colecao'] in ESTACOES:
        return l['colecao'], 'ATEMPORAIS'
    return None


def main(path):
    d = json.load(open(path, encoding='utf-8'))
    linhas = d['linhasPedidos']
    # O relatorio de estoque so traz SKUs com saldo; SKU ausente = estoque zero (esgotado).
    estoque = collections.defaultdict(int, {e['sku']: max(0, e['estoqueAtual']) for e in d['estoqueVendido']})

    # Pecas que chegaram na loja por SKU (todas as colecoes), para ratear o estoque atual.
    chegadas = collections.defaultdict(list)
    for i, l in enumerate(linhas):
        if l['pecasFaturadas'] > 0 and l['dataChegouLoja']:
            chegadas[sku_norm(l['produto'])].append((data(l['dataChegouLoja']), i, l['pecasFaturadas']))

    # Estoque do SKU fica com as chegadas mais recentes (o que saiu primeiro foi o mais antigo).
    sobra_linha, vendido_linha = {}, {}
    for sku, ch in chegadas.items():
        resto = min(estoque[sku], sum(q for _, _, q in ch))
        for _, i, q in sorted(ch, reverse=True):
            s = min(q, resto)
            resto -= s
            sobra_linha[i] = s
            vendido_linha[i] = q - s

    agg = collections.defaultdict(lambda: collections.Counter())
    pedidos = collections.defaultdict(set)
    skus = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
    info = {}
    for i, l in enumerate(linhas):
        g = grupo(l)
        if not g:
            continue
        a = agg[g]
        sku = sku_norm(l['produto'])
        if l['status'] == 'Cancelado':
            a['cancelado'] += l['qtde']
            continue
        pedidos[g].add(l['pedido'])
        a['comprado'] += l['qtde']
        a['faturado'] += l['pecasFaturadas']
        a['valor'] += valor(l['valorFaturado'])
        s = skus[g][sku]
        s['comprado'] += l['qtde']
        s['faturado'] += l['pecasFaturadas']
        if i in sobra_linha:
            a['chegou'] += l['pecasFaturadas']
            a['vendido'] += vendido_linha[i]
            a['sobrou'] += sobra_linha[i]
            s['chegou'] += l['pecasFaturadas']
            s['vendido'] += vendido_linha[i]
            s['sobrou'] += sobra_linha[i]
        else:
            a['a_caminho'] += l['pecasFaturadas']
        info[sku] = {'categoria': l['categoria'], 'cor': l['cor'], 'material': l['material']}

    out = {'geradoEm': d['geradoEm'], 'estacoes': []}
    for est in ESTACOES:
        cols = []
        for (e, c), a in agg.items():
            if e != est:
                continue
            lista = []
            for sku, s in skus[(e, c)].items():
                lista.append({'sku': sku, **info.get(sku, {}), **{k: s[k] for k in ('comprado', 'faturado', 'chegou', 'vendido', 'sobrou')}})
            lista.sort(key=lambda x: (-x['sobrou'], -x['vendido']))
            cols.append({'colecao': c, 'pedidos': len(pedidos[(e, c)]),
                         **{k: round(a[k], 2) if k == 'valor' else a[k]
                            for k in ('comprado', 'cancelado', 'faturado', 'valor', 'chegou', 'vendido', 'sobrou', 'a_caminho')},
                         'skus': lista})
        cols.sort(key=lambda c: -c['comprado'])
        out['estacoes'].append({'estacao': est, 'colecoes': cols})
    return out


if __name__ == '__main__':
    res = main(sys.argv[1])
    json.dump(res, open('inverno.json', 'w', encoding='utf-8'), ensure_ascii=False)
    with open('inverno_por_colecao.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Estação', 'Coleção', 'Pedidos', 'Comprado', 'Cancelado', 'Faturado', 'Valor faturado (R$)',
                    'Chegou na loja', 'Vendido (est.)', 'Sobrou (estoque)', 'Sell-through %'])
        for e in res['estacoes']:
            for c in e['colecoes']:
                st = round(100 * c['vendido'] / c['chegou']) if c['chegou'] else ''
                w.writerow([e['estacao'], c['colecao'], c['pedidos'], c['comprado'], c['cancelado'], c['faturado'],
                            f"{c['valor']:.2f}".replace('.', ','), c['chegou'], c['vendido'], c['sobrou'], st])
    with open('inverno_por_sku.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Estação', 'Coleção', 'SKU', 'Categoria', 'Cor', 'Comprado', 'Faturado', 'Chegou', 'Vendido (est.)', 'Sobrou'])
        for e in res['estacoes']:
            for c in e['colecoes']:
                for s in c['skus']:
                    w.writerow([e['estacao'], c['colecao'], s['sku'], s.get('categoria', ''), s.get('cor', ''),
                                s['comprado'], s['faturado'], s['chegou'], s['vendido'], s['sobrou']])
    for e in res['estacoes']:
        print('==', e['estacao'])
        for c in e['colecoes']:
            print(f"  {c['colecao']:22} ped {c['pedidos']:3} comp {c['comprado']:5} canc {c['cancelado']:4} fat {c['faturado']:5} "
                  f"R$ {c['valor']:>11,.2f} chegou {c['chegou']:5} vend {c['vendido']:5} sobrou {c['sobrou']:4} faturado s/ chegada {c['a_caminho']}")
