import argparse
import csv
import json
from pathlib import Path

from gurobipy import GRB
from data.instancias import cargar_instancia
from src.model import build_model


OUT = Path(__file__).resolve().parent / "results"

CONFIGS = [
    ("default", {}),
    ("cuts_0", {"Cuts": 0}),
    ("presolve_0", {"Presolve": 0}),
    ("mipfocus_1", {"MIPFocus": 1}),
    ("mipfocus_3", {"MIPFocus": 3}),
    ("heuristics_0", {"Heuristics": 0}),
]


def run_case(data, name, params, relaxation=False, prm=None):
    model, X, Z, W, dW, rW = build_model(
        data, relaxation=relaxation
    )

    if prm is not None:
        model.read(str(prm))

    model.Params.Threads = 1
    model.Params.TimeLimit = 600
    model.Params.Seed = 0

    for param, value in params.items():
        model.setParam(param, value)

    model.optimize()

    feasible = model.SolCount > 0
    obj = float(model.ObjVal) if feasible else None

    bound = None
    if not relaxation and model.Status not in (
        GRB.INFEASIBLE, GRB.INF_OR_UNBD, GRB.UNBOUNDED
    ):
        bound = float(model.ObjBound)

    gap = float(model.MIPGap) if feasible and not relaxation else None

    row = {
        "instancia": data["instancia_id"],
        "configuracion": name,
        "parametros": json.dumps(params),
        "relajacion": relaxation,
        "status": model.Status,
        "soluciones": model.SolCount,
        "objetivo": obj,
        "cota": bound,
        "gap": gap,
        "tiempo_s": float(model.Runtime),
        "nodos": float(model.NodeCount),
    }

    solution = None

    if feasible and not relaxation:
        solution = {
            "instancia": data["instancia_id"],
            "configuracion": name,
            "objetivo": obj,
            "status": model.Status,
            "gap": gap,
            "arcos": [
                {"i": i, "j": j, "dia": t, "vehiculo": r}
                for (i, j, t, r), var in X.items()
                if var.X > 0.5
            ],
            "asignaciones": [
                {"cliente": i, "vehiculo": r}
                for (i, r), var in Z.items()
                if var.X > 0.5
            ],
        }

    model.dispose()
    return row, solution


def guardar_resultados(rows):
    with (OUT / "comparacion.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def tune_model(data):
    instancia = data["instancia_id"]

    model, X, Z, W, dW, rW = build_model(
        data, relaxation=False
    )

    model.Params.Threads = 1
    model.Params.TimeLimit = 600
    model.Params.Seed = 0
    model.Params.TuneTimeLimit = 600
    model.Params.TuneTrials = 1

    print(f"Calibrando instancia {instancia}...")
    model.tune()

    if model.TuneResultCount > 0:
        model.getTuneResult(0)
        model.write(str(OUT / f"tuned_inst{instancia}.prm"))
        print("Parámetros guardados.")
    else:
        print("No se encontraron parámetros ajustados.")

    model.dispose()


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fase",
        choices=["experimentos", "tune", "tuned"],
        default="experimentos"
    )
    args = parser.parse_args()

    if args.fase == "tune":
        for instancia in (1, 2):
            tune_model(cargar_instancia(instancia))
        return

    if args.fase == "tuned":
        ruta_csv = OUT / "comparacion.csv"

        with ruta_csv.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        # Evitar duplicar resultados de calibraciones anteriores
        rows = [r for r in rows if r["configuracion"] != "tuned"]

        for instancia in (1, 2):
            data = cargar_instancia(instancia)
            prm = OUT / f"tuned_inst{instancia}.prm"

            if not prm.exists():
                print(f"No existe {prm}")
                continue

            row, solution = run_case(data, "tuned", {}, prm=prm)
            rows.append(row)
            guardar_resultados(rows)

        return

    rows = []

    for instancia in (1, 2):
        data = cargar_instancia(instancia)
        best = None

        pruebas = [("lp_relaxation", {}, True)]

        for name, params in CONFIGS:
            pruebas.append((name, params, False))

        for name, params, relaxation in pruebas:
            print(f"Instancia {instancia} / {name}", flush=True)

            row, solution = run_case(
                data, name, params, relaxation
            )

            rows.append(row)
            guardar_resultados(rows)

            if solution is not None and (
                best is None
                or solution["objetivo"] < best["objetivo"]
            ):
                best = solution

                ruta = OUT / f"mejor_instancia_{instancia}.json"
                ruta.write_text(
                    json.dumps(best, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )

        print(f"Instancia {instancia}: terminada")

    print("Resultados guardados en", OUT.resolve())


if __name__ == "__main__":
    main()
