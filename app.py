import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
import math

st.set_page_config(page_title="Spatial Delta & Topology Engine", layout="wide")

st.title("⚡ Spatial Delta & Topology Engine (Production Data Validator)")
st.markdown("Automated **As-Built QA/QC** pipeline: ingests Master vs. Field datasets into **O(1) Hash Maps**, detects 3D geometric/spec deltas, and traces topological **Blast-Radius** impact.")

# --- GENERADOR DE DATASETS REALISTAS (O SUBIDA DE CSV REALES) ---
def generate_realistic_datasets(num_pipes=500):
    np.random.seed(42)
    master_rows = []
    cols = int(math.sqrt(num_pipes))
    
    for i in range(num_pipes):
        r, c = divmod(i, cols)
        aid = f"P-{1000 + i}"
        start_node = f"MH-{r}_{c}"
        end_node = f"MH-{r}_{c+1}"
        x0, y0, z0 = float(c * 15), float(r * 15), 0.0
        x1, y1, z1 = float((c + 1) * 15), float(r * 15), 0.0
        diam = int(np.random.choice([150, 200, 300, 400]))
        mat = str(np.random.choice(["Steel", "HDPE", "Ductile Iron"]))
        master_rows.append([aid, start_node, end_node, x0, y0, z0, x1, y1, z1, diam, mat])
        
    columns = ["ASSET_ID", "START_NODE", "END_NODE", "X0", "Y0", "Z0", "X1", "Y1", "Z1", "DIAMETER", "MATERIAL"]
    df_master = pd.DataFrame(master_rows, columns=columns)
    
    # Crear Layer B con ruido GPS realista, desviaciones reales, cambios de material, altas y bajas
    df_field = df_master.copy()
    
    # 1. Ruido GPS milimétrico (1-3 cm) en el 20% de los elementos (debe ser filtrado por tolerancia)
    noise_idx = np.random.choice(df_field.index, size=int(num_pipes * 0.2), replace=False)
    df_field.loc[noise_idx, "Y0"] += np.random.uniform(-0.02, 0.02, size=len(noise_idx))
    df_field.loc[noise_idx, "Y1"] += np.random.uniform(-0.02, 0.02, size=len(noise_idx))
    
    # 2. Desviaciones reales de trazado (> 0.5m) en 4 elementos
    shift_idx = df_field.index[5:9]
    df_field.loc[shift_idx, "Y0"] += 1.5
    df_field.loc[shift_idx, "Y1"] += 1.5
    
    # 3. Sustituciones silenciosas de diámetro/material en 3 elementos
    spec_idx = df_field.index[12:15]
    df_field.loc[spec_idx, "DIAMETER"] = 500
    df_field.loc[spec_idx, "MATERIAL"] = "Copper"
    
    # 4. Eliminar 2 elementos (Decommissioned)
    df_field = df_field.drop(df_field.index[20:22]).reset_index(drop=True)
    
    # 5. Añadir 3 elementos nuevos (New Installations)
    new_rows = [
        ["P-9901", "MH-0_0", "MH-1_0", 0.0, 0.0, 0.0, 0.0, 15.0, 0.0, 250, "Steel"],
        ["P-9902", "MH-1_1", "MH-2_1", 15.0, 15.0, 0.0, 15.0, 30.0, 0.0, 250, "Steel"],
        ["P-9903", "MH-2_2", "MH-3_2", 30.0, 30.0, 0.0, 30.0, 45.0, 0.0, 300, "HDPE"],
    ]
    df_field = pd.concat([df_field, pd.DataFrame(new_rows, columns=columns)], ignore_index=True)
    
    return df_master, df_field

# --- SIDEBAR: INGESTA DE DATOS ---
st.sidebar.header("1. Data Ingestion Source")
data_mode = st.sidebar.radio("Select input mode:", ["Benchmark Dataset (Synthetic CAD/GIS)", "Upload Real CSV Files"])

if data_mode == "Benchmark Dataset (Synthetic CAD/GIS)":
    n_elements = st.sidebar.select_slider("Network size (elements):", options=[100, 500, 1500, 5000], value=500)
    df_master, df_field = generate_realistic_datasets(n_elements)
else:
    st.sidebar.info("Required columns: ASSET_ID, START_NODE, END_NODE, X0, Y0, Z0, X1, Y1, Z1, DIAMETER, MATERIAL")
    file_master = st.sidebar.file_uploader("Upload Master_Network.csv", type=["csv"])
    file_field = st.sidebar.file_uploader("Upload Field_Layer_B.csv", type=["csv"])
    if file_master and file_field:
        df_master = pd.read_csv(file_master)
        df_field = pd.read_csv(file_field)
    else:
        st.warning("👈 Upload both Master and Field CSV files in the sidebar (or switch to Benchmark Dataset to test immediately).")
        st.stop()

st.sidebar.header("2. QA/QC Tolerance Rules")
gps_tolerance = st.sidebar.slider("3D Euclidean GPS Tolerance (m):", 0.00, 0.25, 0.05, step=0.01)

# --- MOTOR PYTHON SPATIAL DELTA (LÓGICA EXACTA DE PRODUCCIÓN) ---
t_start = time.perf_counter()

# 1. Cargar en Hash Maps O(1)
master_map = df_master.set_index("ASSET_ID").to_dict("index")
field_map = df_field.set_index("ASSET_ID").to_dict("index")

results = []
primary_affected_nodes = set()
primary_changed_ids = set()

# 2. Multi-Criteria Diff (CREATE & UPDATE)
for aid, f_row in field_map.items():
    if aid not in master_map:
        results.append({
            "ASSET_ID": aid, "ACTION": "CREATE", "REASON": "New field installation",
            "DELTA_DIST_M": 0.0, "OLD_SPEC": "-", "NEW_SPEC": f"DN{f_row['DIAMETER']} {f_row['MATERIAL']}"
        })
        primary_changed_ids.add(aid)
        primary_affected_nodes.update([f_row["START_NODE"], f_row["END_NODE"]])
    else:
        m_row = master_map[aid]
        # Distancia Euclidiana 3D en extremos
        d0 = math.dist((m_row["X0"], m_row["Y0"], m_row["Z0"]), (f_row["X0"], f_row["Y0"], f_row["Z0"]))
        d1 = math.dist((m_row["X1"], m_row["Y1"], m_row["Z1"]), (f_row["X1"], f_row["Y1"], f_row["Z1"]))
        max_shift = round(max(d0, d1), 3)
        
        geom_changed = max_shift > gps_tolerance
        spec_changed = (m_row["DIAMETER"] != f_row["DIAMETER"]) or (m_row["MATERIAL"] != f_row["MATERIAL"])
        
        if geom_changed or spec_changed:
            reasons = []
            if geom_changed: reasons.append(f"3D Shift ({max_shift}m)")
            if spec_changed: reasons.append("Spec/Material Diff")
            
            results.append({
                "ASSET_ID": aid, "ACTION": "UPDATE / REPLACE", "REASON": " + ".join(reasons),
                "DELTA_DIST_M": max_shift,
                "OLD_SPEC": f"DN{m_row['DIAMETER']} {m_row['MATERIAL']}",
                "NEW_SPEC": f"DN{f_row['DIAMETER']} {f_row['MATERIAL']}"
            })
            primary_changed_ids.add(aid)
            primary_affected_nodes.update([m_row["START_NODE"], m_row["END_NODE"]])

# 3. Detectar DELETED
for aid, m_row in master_map.items():
    if aid not in field_map:
        results.append({
            "ASSET_ID": aid, "ACTION": "DELETE", "REASON": "Missing in Field Layer B",
            "DELTA_DIST_M": 0.0, "OLD_SPEC": f"DN{m_row['DIAMETER']} {m_row['MATERIAL']}", "NEW_SPEC": "-"
        })
        primary_changed_ids.add(aid)
        primary_affected_nodes.update([m_row["START_NODE"], m_row["END_NODE"]])

# 4. Topological Blast-Radius Tracing (BOUNDARY_TOUCHES equivalente)
blast_radius_ids = set()
for aid, m_row in master_map.items():
    if aid not in primary_changed_ids:
        if m_row["START_NODE"] in primary_affected_nodes or m_row["END_NODE"] in primary_affected_nodes:
            blast_radius_ids.add(aid)
            results.append({
                "ASSET_ID": aid, "ACTION": "BLAST_RADIUS_CHECK",
                "REASON": f"Connected to modified node ({m_row['START_NODE']}/{m_row['END_NODE']})",
                "DELTA_DIST_M": 0.0,
                "OLD_SPEC": f"DN{m_row['DIAMETER']} {m_row['MATERIAL']}",
                "NEW_SPEC": f"DN{m_row['DIAMETER']} {m_row['MATERIAL']}"
            })

exec_time_ms = (time.perf_counter() - t_start) * 1000
df_triage = pd.DataFrame(results)

# --- MÉTRICAS DE RENDIMIENTO ---
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Elements Audited", f"{len(master_map):,}")
c2.metric("🟢 CREATE", len(df_triage[df_triage["ACTION"] == "CREATE"]) if not df_triage.empty else 0)
c3.metric("🔴 UPDATE / DELETE", len(df_triage[df_triage["ACTION"].isin(["UPDATE / REPLACE", "DELETE"])]) if not df_triage.empty else 0)
c4.metric("🟠 BLAST RADIUS", len(blast_radius_ids))
c5.metric("⚡ Hash-Map Exec Time", f"{exec_time_ms:.2f} ms")

# --- VISUALIZACIÓN ESPACIAL + TABLA DE TRIAGE ---
tab1, tab2 = st.tabs(["📋 Actionable Triage Report (Exportable)", "🗺️ Spatial Viewport Preview"])

with tab1:
    st.subheader("Automated Engineering Triage Log")
    if df_triage.empty:
        st.success("Zero deltas detected above GPS tolerance threshold. Digital Twin is 100% synchronized.")
    else:
        st.dataframe(df_triage, use_container_width=True, hide_index=True)
        csv_export = df_triage.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Actionable Triage CSV (For Field / Power BI)",
            data=csv_export,
            file_name="spatial_delta_triage_report.csv",
            mime="text/csv"
        )

with tab2:
    st.subheader("Spatial Delta Map (Highlighting Flagged & Blast-Radius Assets)")
    fig = go.Figure()
    
    # Mostrar muestra espacial (hasta 300 elementos para fluidez en navegador)
    plot_master = df_master.head(300)
    
    # Tuberías sin cambios
    unchanged = plot_master[~plot_master["ASSET_ID"].isin(primary_changed_ids | blast_radius_ids)]
    ux, uy = [], []
    for _, r in unchanged.iterrows():
        ux.extend([r["X0"], r["X1"], None])
        uy.extend([r["Y0"], r["Y1"], None])
    fig.add_trace(go.Scatter(x=ux, y=uy, mode="lines", line=dict(color="rgba(150,150,150,0.35)", width=1.5), name="Unchanged (OK)"))
    
    # Blast radius (Ámbar)
    br_df = df_master[df_master["ASSET_ID"].isin(blast_radius_ids)]
    bx, by = [], []
    for _, r in br_df.iterrows():
        bx.extend([r["X0"], r["X1"], None])
        by.extend([r["Y0"], r["Y1"], None])
    fig.add_trace(go.Scatter(x=bx, y=by, mode="lines", line=dict(color="#FFA15A", width=4), name="Blast Radius (Review)"))
    
    # Modificados / Eliminados (Rojo)
    upd_df = df_master[df_master["ASSET_ID"].isin(primary_changed_ids)]
    rx, ry = [], []
    for _, r in upd_df.iterrows():
        rx.extend([r["X0"], r["X1"], None])
        ry.extend([r["Y0"], r["Y1"], None])
    fig.add_trace(go.Scatter(x=rx, y=ry, mode="lines", line=dict(color="#FF4B4B", width=4, dash="dash"), name="Master Removed/Replaced"))
    
    # Nuevas posiciones / Nuevos elementos (Verde)

