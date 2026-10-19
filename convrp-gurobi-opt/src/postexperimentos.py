"""Completa la Parte 3 sin repetir las 22 corridas.
Ejecutar: python -m src.postexperimentos --fase recuperar
          python -m src.postexperimentos --fase tune
          python -m src.postexperimentos --fase tuned
"""

import sys
sys.path.append("..")

import argparse
import csv
import json
from pathlib import Path

from gurobipy import GRB
from data.instancias import cargar_instancia
from model import build_model

OUT = Path('results')
OUT.mkdir(exist_ok=True)
TIME_LIMIT = 600


def construir(instancia):
    data = cargar_instancia(instancia)
    model, X, Z, W, dW, rW = build_model(data, relaxation=False)
    model.Params.Threads = 1
    model.Params.TimeLimit = TIME_LIMIT
    model.Params.Seed = 0
    return model, X, Z


def guardar_solucion(model, X, Z, instancia, nombre):
    if model.SolCount == 0:
        print('No se encontró solución factible; no se exporta.')
        return
    result = {
        'instancia': instancia, 'configuracion': nombre,
        'objetivo': float(model.ObjVal), 'status': int(model.Status),
        'gap': float(model.MIPGap), 'cota': float(model.ObjBound),
        'tiempo_s': float(model.Runtime),
        'arcos': [{'i': i, 'j': j, 'dia': t, 'vehiculo': r}
                  for (i, j, t, r), var in X.items() if var.X > 0.5],
        'asignaciones': [{'cliente': i, 'vehiculo': r}
                         for (i, r), var in Z.items() if var.X > 0.5],
    }
    (OUT / f'mejor_instancia_{instancia}_certificada.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    model.write(str(OUT / f'mejor_instancia_{instancia}_certificada.sol'))
    print('Solución exportada:', result['objetivo'], 'estado:', result['status'])


def recuperar():
    # Mejor configuración certificada en cada instancia, según el CSV original.
    for instancia, nombre, params in [(1, 'cuts_2', {'Cuts': 2}),
                                      (2, 'mipfocus_2', {'MIPFocus': 2})]:
        model, X, Z = construir(instancia)
        model.Params.LogFile = str(OUT / f'recuperar_inst{instancia}.log')
        for k, v in params.items():
            model.setParam(k, v)
        model.optimize()
        if model.Status != GRB.OPTIMAL:
            print(f'AVISO: instancia {instancia} no certificó optimalidad; revisa el log.')
        guardar_solucion(model, X, Z, instancia, nombre)
        model.dispose()


def tune():
    for instancia in (1, 2):
        model, _, _ = construir(instancia)
        model.Params.LogFile = str(OUT / f'tune_inst{instancia}.log')
        model.Params.TuneTimeLimit = 600  # Presupuesto global de tuning, en segundos.
        model.Params.TuneTrials = 1
        model.tune()
        if model.TuneResultCount > 0:
            model.getTuneResult(0)
            model.write(str(OUT / f'tuned_inst{instancia}.prm'))
            print(f'Instancia {instancia}: parámetros guardados.')
        else:
            print(f'Instancia {instancia}: no se obtuvo configuración ajustada.')
        model.dispose()


def tuned():
    path = OUT / 'comparacion.csv'
    if not path.exists():
        raise FileNotFoundError('Coloca comparacion.csv dentro de results/')
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0].keys())
    for instancia in (1, 2):
        prm = OUT / f'tuned_inst{instancia}.prm'
        if not prm.exists():
            print(f'No existe {prm}; se omite.')
            continue
        model, X, Z = construir(instancia)
        model.read(str(prm))
        # Fijar nuevamente las condiciones controladas incluso si .prm las modifica.
        model.Params.Threads = 1
        model.Params.TimeLimit = TIME_LIMIT
        model.Params.Seed = 0
        model.Params.LogFile = str(OUT / f'inst{instancia}_tuned.log')
        model.optimize()
        feasible = model.SolCount > 0
        row = {
            'instancia': str(instancia), 'configuracion': 'tuned',
            'parametros': json.dumps({'archivo': str(prm)}),
            'relajacion': 'False', 'status': str(model.Status),
            'soluciones': str(model.SolCount),
            'objetivo': str(model.ObjVal) if feasible else '',
            'cota': str(model.ObjBound) if model.Status not in (GRB.INFEASIBLE, GRB.INF_OR_UNBD, GRB.UNBOUNDED) else '',
            'gap': str(model.MIPGap) if feasible else '',
            'tiempo_s': str(model.Runtime), 'nodos': str(model.NodeCount),
        }
        rows = [r for r in rows if not (r['instancia'] == str(instancia) and r['configuracion'] == 'tuned')]
        rows.append(row)
        # Se exporta por separado: no reemplazar una solución certificada por otra peor.
        if feasible:
            model.write(str(OUT / f'inst{instancia}_tuned.sol'))
        model.dispose()
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print('Comparación actualizada:', path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--fase', choices=['recuperar', 'tune', 'tuned'], required=True)
    args = parser.parse_args()
    {'recuperar': recuperar, 'tune': tune, 'tuned': tuned}[args.fase]()
