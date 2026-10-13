# Optimización de Ruteo Consistente con Ventanas de Tiempo (conVRP) en Gurobi

Proyecto de optimización combinatoria basado en el modelo de programación lineal entera mixta (PLEM) de **Campelo et al. (2019)** (*European Journal of Operational Research*). El objetivo es modelar, implementar y analizar el comportamiento computacional de rutas de distribución consistentes bajo diferentes configuraciones del solver Gurobi (`gurobipy`).

---

## 1. Contexto del Negocio y Justificación de la Consistencia

En la logística de distribución de **insumos farmacéuticos y hospitalarios**, la puntualidad y la confianza operativa son críticas. A diferencia de un esquema de ruteo dinámico diario (donde las rutas cambian libremente según los pedidos del día), este sistema implementa un **Ruteo Consistente de Conductores (Driver Consistency)**:

- **Mismo conductor por cliente:** Cada cliente tiene asignado un único vehículo/conductor fijo a lo largo de todo el horizonte de planificación de 3 días.
- **Ventajas operacionales:**
  - Familiaridad con el cliente, zonas de descarga y normativas de recepción en farmacias/clínicas.
  - Reducción de tiempos de servicio ($st_{it}$) y fricción en la entrega de medicamentos controlados o cadena de frío.
  - Predictibilidad para el receptor mediante el cumplimiento de ventanas de tiempo estrictas ($[a_i, b_i]$).
- **Costo del compromiso (Trade-off):** La consistencia restringe los grados de libertad del ruteo multi-día, incrementando ligeramente la distancia total recorrida frente a un modelo dinámico, pero asegurando una mayor calidad de servicio y estabilidad operacional.

---

## 2. Alcance y Formulación Matemática Reducida

Se implementa una versión reducida y compacta del modelo de Campelo et al. (2019), conservando las restricciones estructurales del problema.

### Conjuntos e Índices
- $\mathcal{D} = \{1, 2, 3\}$: Conjunto de días de planificación.
- $\mathcal{R} = \{1, 2, 3\}$: Flota de vehículos homogéneos disponibles.
- $\mathcal{N}_C = \{1, \dots, 15\}$: Nodos clientes.
- $\mathcal{N}_{TW} \subseteq \mathcal{N}_C$: Subconjunto de clientes con ventana de tiempo estricta.
- $\mathcal{N} = \mathcal{N}_C \cup \{0, n+1\}$: Nodos totales (0 = salida depósito, $n+1$ = retorno al depósito).
- $\mathcal{A}$: Conjunto de arcos factibles $(i, j, t)$ para cada día $t \in \mathcal{D}$.

### Variables de Decisión
- $X_{ijt}^r \in \{0, 1\}$: Vale $1$ si la ruta $r$ recorre el arco $(i, j)$ en el día $t$.
- $Z_i^r \in \{0, 1\}$: Vale $1$ si el cliente $i$ queda asignado de manera consistente a la ruta $r$.
- $W_{it} \ge 0$: Momento de inicio de servicio en el nodo $i$ durante el día $t$.
- $dW^r \ge 0$: Hora de salida del depósito de la ruta $r$.
- $rW_t^r \ge 0$: Hora de retorno al depósito de la ruta $r$ en el día $t$.

### Formulación
$$\min \sum_{(i,j,t) \in \mathcal{A}} \sum_{r \in \mathcal{R}} td_{ij} X_{ijt}^r \quad \text{(1)}$$

Sujeto a:
- **Asignación única consistente:**
  $$\sum_{r \in \mathcal{R}} Z_i^r = 1 \quad \forall i \in \mathcal{N}_C \quad \text{(2)}$$
- **Conservación de flujo y acoplamiento:**
  $$\sum_{i \in \mathcal{N} \mid (i,j,t) \in \mathcal{A}} X_{ijt}^r = Z_j^r \quad \forall j \in \mathcal{N}_C, t \in \mathcal{D}, r \in \mathcal{R} \quad \text{(3)}$$
  $$\sum_{k \in \mathcal{N} \mid (j,k,t) \in \mathcal{A}} X_{jkt}^r = Z_j^r \quad \forall j \in \mathcal{N}_C, t \in \mathcal{D}, r \in \mathcal{R} \quad \text{(4)}$$
- **Salida del depósito:**
  $$\sum_{j \in \mathcal{N} \mid (0,j,t) \in \mathcal{A}} X_{0jt}^r = 1 \quad \forall t \in \mathcal{D}, r \in \mathcal{R} \quad \text{(5)}$$
- **Propagación temporal y eliminación de subtours (Big-M):**
  $$W_{it} + st_{it} + tt_{ij} \le W_{jt} + M(1 - X_{ijt}^r) \quad \forall (i,j,t) \in \mathcal{A}, i,j \in \mathcal{N}_C, r \in \mathcal{R} \quad \text{(7)}$$
- **Ventanas de tiempo:**
  $$a_i \le W_{it} \le b_i \quad \forall i \in \mathcal{N}_{TW}, t \in \mathcal{D} \text{ tal que } q_{it} > 0 \quad \text{(8)}$$
- **Sincronización con el depósito:**
  $$dW^r + tt_{0j} \le W_{jt} + M(1 - X_{0jt}^r) \quad \forall (0,j,t) \in \mathcal{A}, r \in \mathcal{R} \quad \text{(9)}$$
  $$W_{it} + st_{it} + tt_{i,n+1} \le rW_t^r + M(1 - X_{i,n+1,t}^r) \quad \forall (i,n+1,t) \in \mathcal{A}, r \in \mathcal{R} \quad \text{(10)}$$
- **Horario de operación del depósito:**
  $$dW^r \ge aW \quad \forall r \in \mathcal{R} \quad \text{(11)}$$
  $$rW_t^r \le bW \quad \forall r \in \mathcal{R}, t \in \mathcal{D} \quad \text{(12)}$$
- **Capacidad diaria de vehículo:**
  $$\sum_{i \in \mathcal{N}_C} q_{it} Z_i^r \le Q \quad \forall r \in \mathcal{R}, t \in \mathcal{D} \quad \text{(14)}$$
- **Dominios:**
  $$X_{ijt}^r, Z_i^r \in \{0, 1\}, \quad W_{it}, dW^r, rW_t^r \ge 0 \quad \text{(16)}$$

*Elementos excluidos del alcance:* Fechas de liberación de pedidos ($rd_i$), despachos múltiples diarios por cliente y restricción de duración máxima de ruta ($MD$).

---

## 3. Plan de Trabajo y Roles del Equipo

El proyecto se divide en 4 etapas técnicas secuenciales y una etapa final grupal de síntesis:

| Etapa | Responsable | Entregable Clave |
| :--- | :--- | :--- |
| **Parte 1: Negocio e Instancias** | **Javier Torres** | `README.md`, `data/instancias.py` con dos instancias calibradas (no triviales). |
| **Parte 2: Modelación en Gurobi** | **Braian Urra** | `src/model.py` con función modular `build_model(data, relaxation=False)`. |
| **Parte 3: Experimentación** | **Joaquin Sandoval** | `src/experiments.py`: Relajación LP, tabla de parámetros (`Cuts`, `Presolve`, `MIPFocus`, `Heuristics`) y `model.tune()`. |
| **Parte 4: Sensibilidad Dual** | **Ignacio Jara** | `src/sensitivity.py`: `model.fixed()`, precios sombra de capacidad $Q$ e intervalos `SARHS`. |
| **Parte 5: Pitch Ejecutivo** | **Todo el Grupo** | Diapositivas y guion de 5 minutos cronometrados en `presentation/`. |

---

## 4. Instalación y Ejecución Rápida

1. Clonar el repositorio:
   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd convrp-gurobi-opt
   ```
2. Crear un entorno virtual e instalar dependencias:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # En Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Validar las instancias (Parte 1):
   ```bash
   python data/instancias.py
   ```