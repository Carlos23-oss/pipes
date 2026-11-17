import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import time
import math

st.set_page_config(page_title="Spatial Delta & Topology Engine", layout="wide")

st.title("⚡ Spatial Delta & Topology Engine (Production Data Validator)")
st.markdown("Automated **As-Built QA/QC** pipeline: ingests Master vs. Field datasets into **O(1) Hash Maps**, detects 3D geometric/spec deltas, and traces topological **Blast-Radius** impact.")

# --- 1. GENERADOR DE DATASETS SINTÉTICOS ---
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
        diam = int(np.random.choice([150, 200, 250, 300]))
        mat = str(np.random.choice(["Steel", "HDPE", "Ductile Iron"]))
        master_rows.append([aid, start_node, end_node, x0, y0, z0, x1, y1, z1, diam, mat])
        
    columns = ["ASSET_ID", "START_NODE", "END_NODE", "X0", "Y0", "Z0", "X1", "Y1", "Z1", "DIAMETER", "MATERIAL"]
    df_master = pd.DataFrame(master_rows, columns=columns)
    df_field = df_master.copy()
    
    # Ruido GPS milimétrico (1-2 cm) en el 20% de los elementos
    noise_idx = np.random.choice(df_field.index, size=int(num_pipes * 0.2), replace=False)
    df_field.loc[noise_idx, "Y0"] += np.random.uniform(-0.02, 0.02, size=len(noise_idx))
    df_field.loc[noise_idx, "Y1"] += np.random.uniform(-0.02, 0.02, size=len(noise_idx))
    
    # Desviaciones reales de trazado (1.5m)
    shift_idx = df_field.index[5:9]
    df_field.loc[shift_idx, "Y0"] += 1.5
    df_field.loc[shift_idx, "Y1"] += 1.5
    
    # Sustituciones silenciosas de diámetro/material
    spec_idx = df_field.index[12:15]
    df_field.loc[spec_idx, "DIAMETER"] = 500
    df_field.loc[spec_idx, "MATERIAL"] = "Copper"
    
    # Eliminar 2 elementos (Decommissioned)
    df_field = df_field.drop(df_field.index[20:22]).reset_index(drop=True)
    
    # Añadir 3 elementos nuevos (New Installations)
    new_rows = [
        ["P-9901", "MH-0_0", "MH-1_0", 0.0, 0.0, 0.0, 0.0, 15.0, 0.0, 250, "Steel"],
        ["P-9902", "MH-1_1", "MH-2_1", 15.0, 15.0, 0.0, 15.0, 30.0, 0.0, 250, "Steel"],
        ["P-9903", "MH-2_2", "MH-3_2", 30.0, 30.0, 0.0, 30.0, 45.0, 0.0, 300, "HDPE"],
    ]
    df_field = pd.concat([df_field, pd.DataFrame(new_rows, columns=columns)], ignore_index=True)
    return df_master, df_field

# --- 2. BARRA LATERAL: INGESTA DE DATOS ---
st.sidebar.header("1. Data Ingestion Source")
data_mode = st.sidebar.radio("Select input mode:", ["Benchmark Dataset (Synthetic CAD/GIS)", "Upload Real CSV Files"])

if data_mode == "Benchmark Dataset (Synthetic CAD/GIS)":
    n_elements = st.sidebar.select_slider("Network size (elements):", options=[100, 500, 1000, 2500, 5000], value=500)
    df_master, df_field = generate_realistic_datasets(n_elements)
else:
    st.sidebar.info("Required columns: ASSET_ID, START_NODE, END_NODE, X0, Y0, Z0, X1, Y1, Z1, DIAMETER, MATERIAL")
    file_master = st.sidebar.file_uploader("Upload Master_Network.csv", type=["csv"])
    file_field = st.sidebar.file_uploader("Upload Field_Layer_B.csv", type=["csv"])
    if file_master and file_field:
        try:
            raw_head = file_master.read(10)
            file_master.seek(0)
            if b"{\\rtf" in raw_head:
                st.error("⚠️ Uploaded file is a Mac Rich Text (.rtf) file renamed as .csv. Please upload a plain-text CSV.")
                st.stop()
                
            df_master = pd.read_csv(file_master, encoding="utf-8-sig")
            df_field = pd.read_csv(file_field, encoding="utf-8-sig")
            
            df_master.columns = df_master.columns.str.strip().str.upper()
            df_field.columns = df_field.columns.str.strip().str.upper()
            
            required_cols = {"ASSET_ID", "START_NODE", "END_NODE", "X0", "Y0", "Z0", "X1", "Y1", "Z1", "DIAMETER", "MATERIAL"}
            if not required_cols.issubset(set(df_master.columns)) or not required_cols.issubset(set(df_field.columns)):
                st.error(f"❌ Missing required columns. Found in Master: {list(df_master.columns)}")
                st.stop()
        except Exception as e:
            st.error(f"❌ Error reading CSV files: {e}")
            st.stop()
    else:
        st.warning("👈 Upload both Master_Network.csv and Field_Layer_B.csv in the sidebar (or switch to Benchmark Dataset).")
        st.stop()

st.sidebar.header("2. QA/QC Tolerance Rules")
gps_tolerance = st.sidebar.slider("3D Euclidean GPS Tolerance (m):", 0.00, 0.25, 0.05, step=0.01)

# --- 3. MOTOR PYTHON SPATIAL DELTA ---
t_start = time.perf_counter()

master_map = df_master.set_index("ASSET_ID").to_dict("index")
field_map = df_field.set_index("ASSET_ID").to_dict("index")

results = []
primary_affected_nodes = set()
primary_changed_ids = set()

# Multi-Criteria Diff (CREATE & UPDATE)
for aid, f_row in field_map.items():
    if aid not in master_map:
        results.append({
            "ASSET_ID": aid, "ACTION": "CREATE", "REASON": "New field installation",
            "DELTA_DIST_M": 0.0, "OLD_SPEC": "-", "NEW_SPEC": f"DN{f_row['DIAMETER']} {f_row['MATERIAL']}"
        })
        primary_changed_ids.add(aid)
        primary_affected_nodes.update([str(f_row["START_NODE"]), str(f_row["END_NODE"])])
    else:
        m_row = master_map[aid]
        d0 = math.dist((float(m_row["X0"]), float(m_row["Y0"]), float(m_row["Z0"])), (float(f_row["X0"]), float(f_row["Y0"]), float(f_row["Z0"])))
        d1 = math.dist((float(m_row["X1"]), float(m_row["Y1"]), float(m_row["Z1"])), (float(f_row["X1"]), float(f_row["Y1"]), float(f_row["Z1"])))
        max_shift = round(max(d0, d1), 3)
        
        geom_changed = max_shift > gps_tolerance
        spec_changed = (str(m_row["DIAMETER"]) != str(f_row["DIAMETER"])) or (str(m_row["MATERIAL"]).strip() != str(f_row["MATERIAL"]).strip())
        
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
            primary_affected_nodes.update([str(m_row["START_NODE"]), str(m_row["END_NODE"])])

# Detectar DELETED
for aid, m_row in master_map.items():
    if aid not in field_map:
        results.append({
            "ASSET_ID": aid, "ACTION": "DELETE", "REASON": "Missing in Field Layer B",
            "DELTA_DIST_M": 0.0, "OLD_SPEC": f"DN{m_row['DIAMETER']} {m_row['MATERIAL']}", "NEW_SPEC": "-"
        })
        primary_changed_ids.add(aid)
        primary_affected_nodes.update([str(m_row["START_NODE"]), str(m_row["END_NODE"])])

# Topological Blast-Radius Tracing
blast_radius_ids = set()
for aid, m_row in master_map.items():
    if aid not in primary_changed_ids:
        if str(m_row["START_NODE"]) in primary_affected_nodes or str(m_row["END_NODE"]) in primary_affected_nodes:
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

# --- 4. MÉTRICAS SUPERIORES ---
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Elements Audited", f"{len(master_map):,}")
c2.metric("🟢 CREATE", len(df_triage[df_triage["ACTION"] == "CREATE"]) if not df_triage.empty else 0)
c3.metric("🔴 UPDATE / DELETE", len(df_triage[df_triage["ACTION"].isin(["UPDATE / REPLACE", "DELETE"])]) if not df_triage.empty else 0)
c4.metric("🟠 BLAST RADIUS", len(blast_radius_ids))
c5.metric("⚡ Hash-Map Exec Time", f"{exec_time_ms:.2f} ms")

st.divider()

# --- 5. SELECTOR DE VISTAS ---
view_mode = st.radio(
    "Select View:",
    ["📋 Actionable Triage Report", "🗺️ Spatial Viewport Preview", "🐍 Live Python Engine Code"],
    horizontal=True,
    label_visibility="collapsed"
)

if view_mode == "📋 Actionable Triage Report":
    st.subheader("Automated Engineering Triage Log")
    if df_triage.empty:
        st.success("✅ Zero deltas detected above GPS tolerance threshold. Digital Twin is 100% synchronized.")
    else:
        st.dataframe(df_triage, use_container_width=True, hide_index=True)
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            csv_export = df_triage.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download Triage CSV (Field / Power BI)",
                data=csv_export,
                file_name="spatial_delta_triage_report.csv",
                mime="text/csv"
            )
        with col_btn2:
            commit_clicked = st.button("🚀 Approve & Commit Changes to Master Model", type="primary")
            
        if commit_clicked:
            updated_master_map = master_map.copy()
            for _, row in df_triage.iterrows():
                aid = row["ASSET_ID"]
                act = row["ACTION"]
                if act in ["CREATE", "UPDATE / REPLACE"]:
                    updated_master_map[aid] = field_map[aid]
                elif act == "DELETE" and aid in updated_master_map:
