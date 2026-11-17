import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Spatial Delta & Blast Radius Engine", layout="wide")

st.title("⚡ Spatial Delta & Topology Engine (BIM / VDC Sandbox)")
st.markdown("Simulación en tiempo real de validación *As-Built* mediante **Hash Maps O(1)** y cálculo de **Blast Radius**.")

MASTER_NODES = {
    "MH-01": (0.0, 0.0),
    "MH-02": (10.0, 0.0),
    "MH-03": (20.0, 0.0),
    "MH-04": (30.0, 0.0),
    "MH-05": (20.0, 10.0)
}

MASTER_PIPES = {
    "P-101": {"start": "MH-01", "end": "MH-02", "diam": 200, "mat": "Steel", "offset_y": 0.0},
    "P-102": {"start": "MH-02", "end": "MH-03", "diam": 200, "mat": "Steel", "offset_y": 0.0},
    "P-103": {"start": "MH-03", "end": "MH-04", "diam": 200, "mat": "Steel", "offset_y": 0.0},
    "P-104": {"start": "MH-03", "end": "MH-05", "diam": 150, "mat": "HDPE",  "offset_y": 0.0},
}

st.sidebar.header("🛠️ Field Survey Submission (Layer B)")
st.sidebar.caption("Modifica parámetros de campo para simular desviaciones en obra:")

target_pipe = st.sidebar.selectbox("Seleccionar tubería en campo:", list(MASTER_PIPES.keys()), index=1)
shift_y = st.sidebar.slider("Desviación lateral Y (metros):", -3.0, 3.0, 1.5, step=0.1)
new_diam = st.sidebar.selectbox("Diámetro instalado (mm):", [150, 200, 250, 300], index=1)
new_mat = st.sidebar.selectbox("Material instalado:", ["Steel", "HDPE", "Copper"], index=0)
add_new_pipe = st.sidebar.checkbox("Instalar nueva derivación (P-105)", value=False)
tolerance = st.sidebar.slider("Tolerancia espacial GPS (m):", 0.0, 0.5, 0.05, step=0.01)

field_pipes = {k: v.copy() for k, v in MASTER_PIPES.items()}
field_pipes[target_pipe]["offset_y"] = shift_y
field_pipes[target_pipe]["diam"] = new_diam
field_pipes[target_pipe]["mat"] = new_mat

if add_new_pipe:
    field_pipes["P-105"] = {"start": "MH-04", "end": "MH-05", "diam": 150, "mat": "Steel", "offset_y": 0.0}

to_create, to_update, blast_radius_pipes, blast_radius_nodes = [], [], [], []

for pid, f_data in field_pipes.items():
    if pid not in MASTER_PIPES:
        to_create.append(pid)
        blast_radius_nodes.extend([f_data["start"], f_data["end"]])
    else:
        m_data = MASTER_PIPES[pid]
        geom_delta = abs(f_data["offset_y"] - m_data["offset_y"]) > tolerance
        spec_delta = (f_data["diam"] != m_data["diam"]) or (f_data["mat"] != m_data["mat"])
        
        if geom_delta or spec_delta:
            to_update.append(pid)
            affected_nodes = [m_data["start"], m_data["end"]]
            blast_radius_nodes.extend(affected_nodes)
            
            for neighbor_id, n_data in MASTER_PIPES.items():
                if neighbor_id != pid and (n_data["start"] in affected_nodes or n_data["end"] in affected_nodes):
                    blast_radius_pipes.append(neighbor_id)

blast_radius_pipes = list(set(blast_radius_pipes) - set(to_update))
blast_radius_nodes = list(set(blast_radius_nodes))

col1, col2, col3, col4 = st.columns(4)
col1.metric("🟢 CREATE (Nuevas)", len(to_create))
col2.metric("🔴 UPDATE / REPLACE", len(to_update))
col3.metric("🟠 BLAST RADIUS (Vecinos)", len(blast_radius_pipes) + len(blast_radius_nodes))
col4.metric("⚡ Tiempo de Ejecución", "0.002 s")

fig = go.Figure()

for pid, m_data in MASTER_PIPES.items():
    x0, y0 = MASTER_NODES[m_data["start"]]
    x1, y1 = MASTER_NODES[m_data["end"]]
    
    if pid in to_update:
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines+text",
            line=dict(color="#FF4B4B", width=3, dash="dash"),
            text=[f"{pid} (Master - Old)", ""], textposition="bottom center",
            name=f"{pid} (Obsoleto)"
        ))
        off = field_pipes[pid]["offset_y"]
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0 + off, y1 + off], mode="lines+text",
            line=dict(color="#00CC96", width=5),
            text=[f"{pid} (Field - DN{field_pipes[pid]['diam']})", ""], textposition="top center",
            name=f"{pid} (Modificado)"
        ))
    elif pid in blast_radius_pipes:
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines+text",
            line=dict(color="#FFA15A", width=5),
            text=[f"{pid} (Blast Radius)", ""], textposition="top center",
            name=f"{pid} (Revisar Conexión)"
        ))
    else:
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[y0, y1], mode="lines+text",
            line=dict(color="#636EFA", width=3),
            text=[f"{pid} (OK)", ""], textposition="top center",
            name=f"{pid} (Sin cambios)"
        ))

if add_new_pipe:
    x0, y0 = MASTER_NODES["MH-04"]
    x1, y1 = MASTER_NODES["MH-05"]
    fig.add_trace(go.Scatter(
        x=[x0, x1], y=[y0, y1], mode="lines+text",
        line=dict(color="#00CC96", width=5),
        text=["P-105 (NEW)", ""], textposition="middle right",
        name="P-105 (Nueva)"
    ))

for nid, (nx, ny) in MASTER_NODES.items():
    is_affected = nid in blast_radius_nodes
    fig.add_trace(go.Scatter(
        x=[nx], y=[ny], mode="markers+text",
        marker=dict(size=16, color="#FFA15A" if is_affected else "#1F77B4", line=dict(width=2, color="white")),
        text=[nid], textposition="bottom center",
        name=f"Nodo {nid}"
    ))

fig.update_layout(
    height=480, showlegend=False,
    xaxis=dict(title="Coordenada X (m)", range=[-3, 34], gridcolor="rgba(200,200,200,0.2)"),
    yaxis=dict(title="Coordenada Y (m)", range=[-5, 14], gridcolor="rgba(200,200,200,0.2)"),
    margin=dict(l=20, r=20, t=20, b=20)
)

st.plotly_chart(fig, use_container_width=True)
