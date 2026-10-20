import argparse
import csv
import json
from pathlib import Path

import gurobipy as gp
from gurobipy import GRB
 
from data.instancias import cargar_instancia
from src.model import build_model
 
OUT = Path(__file__).resolve().parent / "results"
INF = 1e20
TOL = 1e-6

# Se lee la mejor solución guardada por experiments.py (o None si es que no existe)
def cargar_solucion(instancia):
    ruta = OUT / f"mejor_instancia_{instancia}.json"
    if not ruta.exists():
        return None
    return json.loads(ruta.read_text(encoding="utf-8"))

# Se carga la parte entera de la solución como MIP start
def aplicar_start(X, Z, sol):
    arcos = {(a["i"], a["j"], a["dia"], a["vehiculo"]) for a in sol["arcos"]}
    asign = {(a["cliente"], a["vehiculo"]) for a in sol["asignaciones"]}
    for k, var in X.items():
        var.Start = 1.0 if k in arcos else 0.0
    for k, var in Z.items():
        var.Start = 1.0 if k in asign else 0.0
 
# Devuelve un modelo entero con una solución cargada
# Con sol, usa el MIP start y se detiene en la primera solución
# Sin sol, se resuelve el MIP completo

def modelo_con_incumbente(data, sol=None, tiempo=600):
    model, X, Z, W, dW, rW = build_model(data, relaxation=False)
    model.Params.Threads = 1
    model.Params.Seed = 0
    model.Params.LogToConsole = 0
 
    if sol is not None:
        aplicar_start(X, Z, sol)
        model.Params.SolutionLimit = 1
    else:
        model.Params.TimeLimit = tiempo
 
    model.optimize()
    if model.SolCount == 0:
        raise RuntimeError("No se obtuvo ninguna solución entera; no se puede fijar el modelo.")
    return model
 
# Modelo fijo y analisis sde sensibilidad
def resolver_modelo_fijo(model):
    """Model.fixed(): X, Z quedan continuas con lb = ub = valor de la solución."""
    fixed = model.fixed()
    fixed.Params.SolutionLimit = GRB.MAXINT   
    fixed.Params.Method = 1                  
    fixed.Params.LogToConsole = 0
    fixed.optimize()
    if fixed.Status != GRB.OPTIMAL:
        raise RuntimeError(f"El modelo fijo no es óptimo (status={fixed.Status}).")
    return fixed
 
 
def _fmt(v):
    return float("inf") if v >= INF else (float("-inf") if v <= -INF else v)
 
 
def analizar_capacidad(fixed, data):
    """Una fila por restricción Cap_r{r}_t{t}: carga, holgura, Pi y rango SARHS."""
    filas = []
    for r in data["rutas"]:
        for t in data["dias"]:
            c = fixed.getConstrByName(f"Cap_r{r}_t{t}")
            carga = c.RHS - c.Slack
            filas.append({
                "instancia": data["instancia_id"],
                "ruta": r,
                "dia": t,
                "Q": c.RHS,
                "carga": carga,
                "holgura": c.Slack,
                "activa": abs(c.Slack) < TOL,
                "precio_sombra_Pi": c.Pi,
                "SARHSLow": _fmt(c.SARHSLow),
                "SARHSUp": _fmt(c.SARHSUp),
            })
    return filas
 
 # Se comprueba con el LP que Q = q_min es factible y que Q = q_min - 0.5 no lo es, 
 # es decir, que SARHSLow corresponde a la menor Q que mantiene la solución
def verificar_rango(fixed, data, q_min):
    caps = [fixed.getConstrByName(f"Cap_r{r}_t{t}")
            for r in data["rutas"] for t in data["dias"]]
    q0 = caps[0].RHS
    fixed.Params.DualReductions = 0     # distingue INFEASIBLE de INF_OR_UNBD
    estados = {}
    for etiqueta, q in (("Q_min", q_min), ("Q_min - 0.5", q_min - 0.5)):
        for c in caps:
            c.RHS = q
        fixed.optimize()
        estados[etiqueta] = fixed.Status
    for c in caps:                      # restaura Q original
        c.RHS = q0
    fixed.update()
    return estados
 
#Re optimización entera con otros valores de Q
def reoptimizar(data, sol, deltas, tiempo):
    """Re-resuelve el MIP completo con Q' = Q + delta (comparación con la lectura local)."""
    base = sol["objetivo"] if sol else None
    filas = []
    for d in deltas:
        q_nuevo = data["Q"] + d
        model, X, Z, *_ = build_model(dict(data, Q=q_nuevo), relaxation=False)
        model.Params.Threads = 1
        model.Params.Seed = 0
        model.Params.TimeLimit = tiempo
        model.Params.LogToConsole = 0
        if sol is not None:
            aplicar_start(X, Z, sol)    # si es infactible para Q', Gurobi lo ignora
        model.optimize()
 
        ok = model.SolCount > 0
        obj = model.ObjVal if ok else None
        filas.append({
            "instancia": data["instancia_id"],
            "Q": q_nuevo,
            "delta_Q": d,
            "status": model.Status,
            "objetivo": obj,
            "cota": model.ObjBound if model.Status != GRB.INFEASIBLE else None,
            "gap": model.MIPGap if ok else None,
            "tiempo_s": model.Runtime,
            "delta_objetivo": (obj - base) if (ok and base is not None) else None,
            "delta_obj_por_unidad_Q": ((obj - base) / d) if (ok and base is not None and d) else None,
        })
        print(f"   Q={q_nuevo:6.1f} | status={model.Status} | obj={obj} | "
              f"gap={filas[-1]['gap']} | t={model.Runtime:.1f}s", flush=True)
        model.dispose()
    return filas
 
 
# Utilidades de salida
def guardar_csv(nombre, filas):
    if not filas:
        return
    with (OUT / nombre).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
 
 
def imprimir_tabla(filas):
    print(f"{'ruta':>4} {'día':>3} {'carga':>7} {'Q':>7} {'holgura':>8} "
          f"{'Pi':>8} {'SARHSLow':>9} {'SARHSUp':>9}  activa")
    for f in filas:
        print(f"{f['ruta']:>4} {f['dia']:>3} {f['carga']:>7.1f} {f['Q']:>7.1f} "
              f"{f['holgura']:>8.1f} {f['precio_sombra_Pi']:>8.3f} "
              f"{f['SARHSLow']:>9.1f} {f['SARHSUp']:>9.1f}  {'SÍ' if f['activa'] else ''}")
 
 
def analizar_instancia(k, args):
    data = cargar_instancia(k)
    sol = None if args.resolver else cargar_solucion(k)
    origen = "solución guardada (MIP start)" if sol else f"MIP resuelto desde cero ({args.tiempo}s)"
 
    print("=" * 78)
    print(f" INSTANCIA {k}  |  Q = {data['Q']}  |  origen de la solución: {origen}")
    print("=" * 78)
 
    model = modelo_con_incumbente(data, sol, args.tiempo)
    print(f"Objetivo incumbente: {model.ObjVal:.2f}", end="")
    if sol is not None:
        print(f"  (guardado en la Parte 3: {sol['objetivo']:.2f})", end="")
        if abs(model.ObjVal - sol["objetivo"]) > 1e-3:
            print("  <-- ¡NO COINCIDE!", end="")
    print()
 
    fixed = resolver_modelo_fijo(model)
    print(f"Modelo fijo: {fixed.NumVars} vars, {fixed.NumConstrs} restr., "
          f"IsMIP={fixed.IsMIP}, objetivo LP = {fixed.ObjVal:.2f}\n")
 
    filas = analizar_capacidad(fixed, data)
    imprimir_tabla(filas)
 
    q_min = max(f["carga"] for f in filas)
    pi_total = sum(f["precio_sombra_Pi"] for f in filas)
    sar_low_max = max(f["SARHSLow"] for f in filas)
    estados = verificar_rango(fixed, data, q_min)
 
    ok_min = estados["Q_min"] == GRB.OPTIMAL
    ok_bajo = estados["Q_min - 0.5"] == GRB.INFEASIBLE
    print(f"\nPrecio sombra agregado de Q (suma de Pi, Q común a las 9 restricciones): {pi_total:.4f}")
    print(f"Q mínima que conserva la solución fija = carga máxima = {q_min:.1f} "
          f"(Q actual {data['Q']:.1f}; margen {data['Q'] - q_min:.1f})")
    print(f"Verificación LP: Q={q_min:.1f} -> {'factible' if ok_min else 'REVISAR'} | "
          f"Q={q_min - 0.5:.1f} -> {'infactible' if ok_bajo else 'REVISAR'} "
          f"(max SARHSLow = {sar_low_max:.1f})")
 
    guardar_csv(f"sensibilidad_capacidad_inst{k}.csv", filas)
    resumen = {
        "instancia": k, "Q": data["Q"], "objetivo_entero": model.ObjVal,
        "carga_maxima_Q_min": q_min, "margen_Q": data["Q"] - q_min,
        "precio_sombra_agregado": pi_total,
        "restricciones_activas": sum(f["activa"] for f in filas),
        "verificacion_Qmin_factible": ok_min, "verificacion_bajo_Qmin_infactible": ok_bajo,
    }
 
    reopt = []
    if args.reoptimizar:
        print(f"\nRe-optimización entera (TimeLimit={args.tiempo}s por valor de Q):")
        reopt = reoptimizar(data, sol, args.deltas, args.tiempo)
        guardar_csv(f"sensibilidad_reoptimizacion_inst{k}.csv", reopt)
 
    fixed.dispose()
    model.dispose()
    return resumen, reopt
 
 
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    p = argparse.ArgumentParser(description="Sensibilidad de la capacidad Q con Model.fixed()")
    p.add_argument("--instancia", type=int, choices=[1, 2], help="Una sola instancia (por defecto ambas)")
    p.add_argument("--resolver", action="store_true",
                   help="Resolver el MIP desde cero en vez de usar results/mejor_instancia_<k>.json")
    p.add_argument("--reoptimizar", action="store_true",
                   help="Re-resolver el MIP completo con Q' = Q + delta")
    p.add_argument("--deltas", type=float, nargs="+", default=[-5, 5, 10],
                   help="Variaciones de Q para --reoptimizar (por defecto: -5 5 10)")
    p.add_argument("--tiempo", type=float, default=600,
                   help="TimeLimit (s) para resolver/re-optimizar (por defecto 600)")
    args = p.parse_args()
 
    resumenes = []
    for k in ([args.instancia] if args.instancia else [1, 2]):
        resumen, _ = analizar_instancia(k, args)
        resumenes.append(resumen)
        print()
 
    guardar_csv("sensibilidad_resumen.csv", resumenes)
    print("Resultados guardados en", OUT.resolve())
 
 
if __name__ == "__main__":
    main()
 