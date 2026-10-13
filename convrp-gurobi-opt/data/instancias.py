"""
Módulo de generación y validación de instancias para el conVRP.
Parte 1: Integrante 1.

Genera dos instancias no triviales para 15 clientes, 3 días y 3 vehículos:
- Instancia 1: Topología Dispersa (tipo R de Solomon) con Q = 135.
- Instancia 2: Topología Semi-agrupada / Clúster (tipo RC de Solomon) con Q = 125.
"""

import math

def cargar_instancia(tipo=1):
    """
    Retorna un diccionario estructurado con conjuntos, parámetros y matrices
    para construir el modelo PLEM en gurobipy.
    
    Parámetros:
        tipo (int): 1 para Instancia Dispersa, 2 para Instancia Clúster.
    """
    depot_coord = (40.0, 50.0)
    aW, bW = 0.0, 600.0  # Ventana de operación del depósito [0, 10 horas]
    dias = [1, 2, 3]
    rutas = [1, 2, 3]

    if tipo == 1:
        # INSTANCIA 1: Dispersa / R-Type
        Q = 135.0
        # id: (x, y, q_dia1, q_dia2, q_dia3, tiene_tw, a_i, b_i)
        raw_cust = {
            1:  (25, 85, 20,  0, 25, True,   60, 180),
            2:  (22, 75, 15, 20,  0, True,   90, 220),
            3:  (22, 50,  0, 25, 20, True,  120, 260),
            4:  (20, 30, 30, 15, 30, False,   0, 600),
            5:  (10, 20, 25, 25,  0, True,  150, 320),
            6:  (35, 30,  0, 30, 20, False,   0, 600),
            7:  (35, 15, 20, 20, 25, True,  180, 360),
            8:  (50, 20, 25,  0, 20, False,   0, 600),
            9:  (65, 35, 20, 25, 30, True,  100, 240),
            10: (75, 55, 30, 20,  0, True,  140, 300),
            11: (80, 65, 15,  0, 25, False,   0, 600),
            12: (70, 80,  0, 30, 20, True,  200, 380),
            13: (55, 85, 25, 20, 25, False,   0, 600),
            14: (45, 70, 20, 25,  0, True,   80, 210),
            15: (50, 55, 15, 15, 20, False,   0, 600),
        }
    elif tipo == 2:
        # INSTANCIA 2: Semi-agrupada / RC-Type
        Q = 125.0
        raw_cust = {
            1:  (18, 70, 25, 20,  0, True,   70, 190),
            2:  (20, 80, 20, 25, 25, True,   80, 200),
            3:  (15, 65,  0, 20, 30, False,   0, 600),
            4:  (30, 90, 30,  0, 20, True,  110, 240),
            5:  (28, 68, 20, 25, 20, False,   0, 600),
            6:  (60, 75, 25, 20, 25, True,  120, 250),
            7:  (65, 85, 15,  0, 20, True,  150, 280),
            8:  (70, 70, 30, 25,  0, False,   0, 600),
            9:  (58, 60, 20, 20, 25, True,  100, 220),
            10: (20, 20,  0, 30, 20, True,  160, 320),
            11: (30, 15, 25, 25,  0, False,   0, 600),
            12: (25, 30, 20,  0, 25, True,  180, 340),
            13: (65, 25, 20, 25, 20, True,  140, 300),
            14: (75, 30, 25, 20, 25, False,   0, 600),
            15: (70, 15,  0, 25, 20, True,  200, 370),
        }
    else:
        raise ValueError("El parámetro 'tipo' debe ser 1 o 2.")

    cust_nodes = list(raw_cust.keys())
    depot_start = 0
    depot_end = len(cust_nodes) + 1
    all_nodes = [depot_start] + cust_nodes + [depot_end]

    coords = {depot_start: depot_coord, depot_end: depot_coord}
    q = {}
    tw = {}
    tw_nodes = []
    service_time = {}

    for i in cust_nodes:
        x, y, q1, q2, q3, has_tw, ai, bi = raw_cust[i]
        coords[i] = (float(x), float(y))
        q[i, 1] = float(q1)
        q[i, 2] = float(q2)
        q[i, 3] = float(q3)
        if has_tw:
            tw_nodes.append(i)
            tw[i] = (float(ai), float(bi))
        for t in dias:
            # Servicio de 15 min si hay entrega, 0 si no
            service_time[i, t] = 15.0 if q[i, t] > 0 else 0.0

    # Distancias y tiempos euclidianos (1 unidad = 1 minuto de viaje)
    td = {}
    tt = {}
    for i in all_nodes:
        for j in all_nodes:
            d = math.hypot(coords[i][0] - coords[j][0], coords[i][1] - coords[j][1])
            td[i, j] = round(d, 2)
            tt[i, j] = round(d, 2)

    # Arcos diarios válidos
    A = []
    for t in dias:
        activos_t = [i for i in cust_nodes if q[i, t] > 0]
        # Arco directo para rutas que no salen en el día
        A.append((depot_start, depot_end, t))
        for j in activos_t:
            A.append((depot_start, j, t))
            A.append((j, depot_end, t))
        for i in activos_t:
            for j in activos_t:
                if i != j:
                    A.append((i, j, t))

    return {
        'instancia_id': tipo,
        'dias': dias,
        'rutas': rutas,
        'cust_nodes': cust_nodes,
        'depot_start': depot_start,
        'depot_end': depot_end,
        'all_nodes': all_nodes,
        'tw_nodes': tw_nodes,
        'coords': coords,
        'q': q,
        'tw': tw,
        'service_time': service_time,
        'td': td,
        'tt': tt,
        'A': A,
        'Q': Q,
        'aW': aW,
        'bW': bW,
        'M': bW + 200.0  # Big-M ajustado
    }

if __name__ == "__main__":
    for i in [1, 2]:
        data = cargar_instancia(i)
        print(f"==================================================")
        print(f" VALIDACIÓN INSTANCIA {i}")
        print(f"==================================================")
        print(f"Clientes: {len(data['cust_nodes'])} | Rutas: {len(data['rutas'])} | Días: {len(data['dias'])}")
        print(f"Clientes con ventanas de tiempo (N_TW): {len(data['tw_nodes'])}")
        print(f"Capacidad por vehículo Q: {data['Q']}")
        for t in data['dias']:
            demanda_t = sum(data['q'][k, t] for k in data['cust_nodes'])
            cap_total = data['Q'] * len(data['rutas'])
            print(f"  Día {t}: Demanda = {demanda_t:.1f} / {cap_total:.1f} ({demanda_t / cap_total * 100:.1f}%)")
        print(f"Total arcos generados: {len(data['A'])}\n")