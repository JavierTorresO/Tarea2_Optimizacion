import gurobipy as gp
from gurobipy import GRB

def build_model(data, relaxation=False):
    """
    Construye el modelo conVRP utilizando los datos de la instancia.
    
    Parámetros:
        data (dict): Diccionario generado por cargar_instancia().
        relaxation (bool): Si es True, relaja las variables binarias a continuas [0,1].
    """
    # 1. INICIALIZAR EL ENTORNO Y EL MODELO
    model = gp.Model("conVRP_Campelo")
    
    # Si relaxation es True, cambiamos el dominio a continuo
    var_type = GRB.CONTINUOUS if relaxation else GRB.BINARY

    # 2. CREACIÓN DE VARIABLES
    
    # X_ijt^r: 1 si la ruta r transita el arco (i,j) en el día t
    X = {}
    for (i, j, t) in data['A']:
        for r in data['rutas']:
            X[i, j, t, r] = model.addVar(
                vtype=var_type, lb=0.0, ub=1.0, 
                name=f"X_i{i}_j{j}_t{t}_r{r}"
            )
            
    # Z_i^r: 1 si el cliente i es asignado a la ruta r de manera consistente.
    Z = {}
    for i in data['cust_nodes']:
        for r in data['rutas']:
            Z[i, r] = model.addVar(
                vtype=var_type, lb=0.0, ub=1.0, 
                name=f"Z_i{i}_r{r}"
            )

    # W_it: Tiempo de inicio de servicio del nodo i el día t
    W = {}
    for i in data['cust_nodes']:
        for t in data['dias']:
            W[i, t] = model.addVar(vtype=GRB.CONTINUOUS, lb=0.0, name=f"W_i{i}_t{t}")
            
    # dW^r: Hora de salida del depósito de la ruta r
    dW = {}
    for r in data['rutas']:
        dW[r] = model.addVar(vtype=GRB.CONTINUOUS, lb=0.0, name=f"dW_r{r}")
        
    # rW_t^r: Hora de retorno al depósito de la ruta r el día t
    rW = {}
    for r in data['rutas']:
        for t in data['dias']:
            rW[r, t] = model.addVar(vtype=GRB.CONTINUOUS, lb=0.0, name=f"rW_r{r}_t{t}")

    # 3. FUNCIÓN OBJETIVO (1)

    obj = gp.quicksum(
        data['td'][i, j] * X[i, j, t, r] 
        for (i, j, t) in data['A'] for r in data['rutas']
    )
    model.setObjective(obj, GRB.MINIMIZE)

    # 4. RESTRICCIONES
    
    # (2) Asignación única consistente
    for i in data['cust_nodes']:
        model.addConstr(
            gp.quicksum(Z[i, r] for r in data['rutas']) == 1, 
            name=f"Consistencia_{i}"
        )

    # Lógica de Red y Flujo (3, 4 y 5)
    for t in data['dias']:
        for r in data['rutas']:
            # (3 y 4) Conservación de flujo en los clientes
            for j in data['cust_nodes']:
                # Solo forzamos la visita si hay pedido ese día (Si no tiene visita no hay arcos en A)
                if data['q'][j, t] > 0:
                    # Entrar al nodo j
                    model.addConstr(
                        gp.quicksum(X[i, j_A, t_A, r] for (i, j_A, t_A) in data['A'] if j_A == j and t_A == t) == Z[j, r],
                        name=f"Flujo_In_{j}_r{r}_t{t}"
                    )
                    # Salir del nodo j
                    model.addConstr(
                        gp.quicksum(X[j_A, k, t_A, r] for (j_A, k, t_A) in data['A'] if j_A == j and t_A == t) == Z[j, r],
                        name=f"Flujo_Out_{j}_r{r}_t{t}"
                    )

            # (5) Salida del depósito
            model.addConstr(
                gp.quicksum(X[data['depot_start'], j, t_A, r] 
                            for (i_A, j, t_A) in data['A'] 
                            if i_A == data['depot_start'] and t_A == t) == 1,
                name=f"Salida_Depot_r{r}_t{t}"
            )
            
            # Todo vehículo debe regresar al depósito una vez por dia (nodo n+1)
            model.addConstr(
                gp.quicksum(X[i, data['depot_end'], t_A, r] 
                            for (i, j_A, t_A) in data['A'] 
                            if j_A == data['depot_end'] and t_A == t) == 1,
                name=f"Retorno_Depot_r{r}_t{t}"
            )


    # Seguimiento de Tiempos Big-M (7, 9 y 10)
    M = data['M']
    for (i, j, t) in data['A']:
        for r in data['rutas']:
            # (7) Entre clientes
            if i in data['cust_nodes'] and j in data['cust_nodes']:
                model.addConstr(
                    W[i, t] + data['service_time'][i, t] + data['tt'][i, j] <= W[j, t] + M * (1 - X[i, j, t, r]),
                    name=f"BigM_Cliente_{i}_{j}_t{t}_r{r}"
                )
            # (9) Desde el depósito hacia el primer cliente
            elif i == data['depot_start'] and j in data['cust_nodes']:
                model.addConstr(
                    dW[r] + data['tt'][i, j] <= W[j, t] + M * (1 - X[i, j, t, r]),
                    name=f"BigM_Salida_{j}_t{t}_r{r}"
                )
            # (10) Desde el último cliente hacia el depósito
            elif i in data['cust_nodes'] and j == data['depot_end']:
                model.addConstr(
                    W[i, t] + data['service_time'][i, t] + data['tt'][i, j] <= rW[r, t] + M * (1 - X[i, j, t, r]),
                    name=f"BigM_Retorno_{i}_t{t}_r{r}"
                )
            # Arco directo depósito-depósito, si el camión no hace despachos ese día
            elif i == data['depot_start'] and j == data['depot_end']:
                model.addConstr(
                    dW[r] + data['tt'][i, j] <= rW[r, t] + M * (1 - X[i, j, t, r]),
                    name=f"BigM_Directo_t{t}_r{r}"
                )

    # (8) Ventanas de Tiempo
    for i in data['tw_nodes']:
        for t in data['dias']:
            # Solo aplica si el cliente pide ese día
            if data['q'][i, t] > 0:
                model.addConstr(W[i, t] >= data['tw'][i][0], name=f"TW_min_{i}_t{t}")
                model.addConstr(W[i, t] <= data['tw'][i][1], name=f"TW_max_{i}_t{t}")

    # (11) (12) Horarios de operación del depósito
    for r in data['rutas']:
        model.addConstr(dW[r] >= data['aW'], name=f"Apertura_Depot_r{r}")
        for t in data['dias']:
            model.addConstr(rW[r, t] <= data['bW'], name=f"Cierre_Depot_r{r}_t{t}")

    # (14) Capacidad diaria del vehículo
    for r in data['rutas']:
        for t in data['dias']:
            model.addConstr(
                gp.quicksum(data['q'][i, t] * Z[i, r] for i in data['cust_nodes']) <= data['Q'],
                name=f"Cap_r{r}_t{t}"
            )

    model.update()
    
    return model, X, Z, W, dW, rW

if __name__ == "__main__":
    import sys
    sys.path.append('.')
    from data.instancias import cargar_instancia
    
    print("Cargando Instancia 1")
    datos_instancia = cargar_instancia(tipo=1)
    
    print("Construyendo Modelo PLEM")
    modelo, X, Z, W, dW, rW = build_model(datos_instancia, relaxation=False)
    
    print(f"Modelo construido con éxito: {modelo.NumVars} variables y {modelo.NumConstrs} restricciones.")