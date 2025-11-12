import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
from io import BytesIO
from PIL import Image
from datetime import timedelta, datetime, date
import os, sys
import seaborn as sns
import matplotlib.pyplot as plt
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

import base64, requests, json

def github_get_file(token, repo, path):
    """Lê arquivo direto do GitHub e retorna conteúdo (bytes)."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return base64.b64decode(r.json()["content"])
    return None

def github_put_file(token, repo, path, content_bytes, message="Atualização automática"):
    """Cria ou atualiza arquivo no GitHub."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"token {token}"}
    get_resp = requests.get(url, headers=headers)
    sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

    data = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
    }
    if sha:
        data["sha"] = sha

    put_resp = requests.put(url, headers=headers, data=json.dumps(data))
    return put_resp.status_code, put_resp.json()

def github_list_historico(token, repo):
    """Lista arquivos do histórico do repositório GitHub."""
    url = f"https://api.github.com/repos/{repo}/contents/historico_sadt"
    headers = {"Authorization": f"token {token}"}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        files = [
            {
                "nome": f["name"],
                "path": f["path"],
                "url": f["html_url"],
                "data": f["git_url"]
            }
            for f in r.json() if f["name"].endswith(".xlsx")
        ]
        return files
    return []

# Configuração da página com tema personalizado
st.set_page_config(
    page_title="Dashboard - SADT", 
    page_icon="🏥", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS personalizado para melhor visual
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1f77b4 0%, #2ca02c 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    .metric-card {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 4px solid #1f77b4;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        margin: 0.5rem 0;
    }
    
    .insight-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 1rem;
        border-radius: 10px;
        margin: 1rem 0;
    }
    
    .warning-box {
        background: #fff3cd;
        border: 1px solid #ffeaa7;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
    
    .success-box {
        background: #d1edff;
        border: 1px solid #74b9ff;
        border-radius: 5px;
        padding: 1rem;
        margin: 1rem 0;
    }
    
    .dose-reference {
        background: #f0f2f6;
        border: 1px solid #d0d7de;
        border-radius: 5px;
        padding: 0.8rem;
        margin: 0.5rem 0;
        font-size: 0.85em;
    }
    
    .stTab [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #f0f2f6;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    
    .stTab [aria-selected="true"] {
        background-color: #1f77b4;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# Header principal
st.markdown("""
<div class="main-header">
    <h1>🏥 Relatorio Analitico SADT - Serviço de Apoio Diagnostico e Terapeutico</h1>
    <p>Sistema Avançado de Análise de Dados</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------
# Funções Utilitárias Melhoradas
# ---------------------------
@st.cache_data
def load_excel(file) -> pd.DataFrame:
    """Carrega arquivo Excel com tratamento robusto de colunas"""
    df = pd.read_excel(file, engine="openpyxl")
    
    # Normalização mais robusta de colunas
    cols = (
        pd.Index(df.columns.astype(str))
        .str.replace("\n", " ", regex=False)
        .str.strip()
        .str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("utf-8")
        .str.upper()
        .str.replace(r"[^\w\s]", "_", regex=True)
        .str.replace(r"\s+", "_", regex=True)
    )
    df.columns = cols
    return df

def find_col(df, candidates):
    """Busca mais inteligente de colunas"""
    cols = list(df.columns)
    for cand in candidates:
        cand_norm = cand.upper().replace(" ", "_").replace("\n","_")
        for c in cols:
            if cand_norm in c or any(word in c for word in cand_norm.split("_")):
                return c
    return None

def parse_excel_dates(series):
    """Parser de datas mais robusto"""
    s = series.copy()
    
    # Primeira tentativa: parsing normal
    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
    na_frac = dt.isna().mean() if len(dt) > 0 else 1.0
    
    # Se muitas datas inválidas, tenta parsing de Excel serial
    if na_frac > 0.1:
        try:
            numeric = pd.to_numeric(s, errors="coerce")
            if numeric.notna().any():
                # Excel usa 1900-01-01 como origem, mas tem bug do ano 1900
                dt2 = pd.to_datetime(numeric, unit='D', origin='1899-12-30', errors='coerce')
                dt = dt.combine_first(dt2)
        except Exception:
            pass
    
    return dt

def format_duration(hours):
    """Converte horas em formato dd/hh:mm:ss"""
    if pd.isna(hours) or hours < 0:
        return "N/A"
    
    total_seconds = int(hours * 3600)
    days = total_seconds // 86400
    remaining = total_seconds % 86400
    hours_part = remaining // 3600
    minutes = (remaining % 3600) // 60
    seconds = remaining % 60
    
    if days > 0:
        return f"{days}d/{hours_part:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{hours_part:02d}:{minutes:02d}:{seconds:02d}"

def generate_insights(df, analysis_type="general"):
    """Gera insights inteligentes baseados nos dados"""
    insights = []
    
    if analysis_type == "volume":
        total_exames = len(df)
        media_diaria = df.groupby(df["DATA_REALIZACAO"].dt.date).size().mean()
        
        if media_diaria > 100:
            insights.append("📈 **Alto volume**: Média superior a 100 exames/dia indica centro de alta demanda")
        elif media_diaria < 20:
            insights.append("📉 **Baixo volume**: Média inferior a 20 exames/dia pode indicar subutilização")
            
        # Análise de variabilidade
        cv = df.groupby(df["DATA_REALIZACAO"].dt.date).size().std() / media_diaria
        if cv > 0.3:
            insights.append("⚡ **Alta variabilidade**: Demanda oscila muito entre dias (CV > 30%)")
    
    elif analysis_type == "temporal":
        if "TEMPO_ESTIMADO_HORAS" in df.columns:
            tempo_medio = df["TEMPO_ESTIMADO_HORAS"].median()  # Usar mediana em vez de média
            if tempo_medio > 72:  # 3 dias
                insights.append("⏰ **Tempo de espera elevado**: Mediana superior a 3 dias entre pedido e realização")
            elif tempo_medio < 24:  # 1 dia
                insights.append("⚡ **Resposta rápida**: Tempo mediano inferior a 24 horas é excelente")
    
    elif analysis_type == "efficiency":
        # Análise de eficiência por período
        df_hours = df.copy()
        df_hours["HORA"] = df_hours["DATA_REALIZACAO"].dt.hour
        peak_hours = df_hours.groupby("HORA").size().idxmax()
        
        if peak_hours < 8 or peak_hours > 18:
            insights.append("🌙 **Horário atípico de pico**: Maior demanda fora do horário comercial")
        
        # Concentração de exames
        top_5_percent = df["EXAME_NORM"].value_counts().head(int(len(df["EXAME_NORM"].unique()) * 0.05)).sum()
        concentration = (top_5_percent / len(df)) * 100
        
        if concentration > 50:
            insights.append(f"🎯 **Alta concentração**: {concentration:.1f}% dos exames são de apenas 5% dos tipos")
    
    return insights

def create_advanced_metrics_card(title, value, subtitle, delta=None, color="#1f77b4"):
    """Cria cards de métricas avançados"""
    delta_html = ""
    if delta is not None:
        delta_color = "green" if delta >= 0 else "red"
        delta_symbol = "↗️" if delta >= 0 else "↘️"
        delta_html = f"""<p style="color: {delta_color}; margin: 0; font-size: 0.9em;">{delta_symbol} {delta:+.1f}%</p>"""
    
    return f"""
    <div style="
        background: white;
        padding: 1.2rem;
        border-radius: 10px;
        border-left: 4px solid {color};
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        margin: 0.5rem 0;
    ">
        <h3 style="color: {color}; margin: 0; font-size: 1.1em;">{title}</h3>
        <h2 style="color: #2c3e50; margin: 0.2rem 0; font-size: 2em;">{value}</h2>
        <p style="color: #7f8c8d; margin: 0; font-size: 0.9em;">{subtitle}</p>
        {delta_html}
    </div>
    """

# ---------------------------
# Upload e Processamento
# ---------------------------
uploaded = st.file_uploader(
    "📂 **Selecione o arquivo Excel com dados radiológicos**",
    type=["xlsx", "xls"],
    help="Arquivo deve conter colunas: PACIENTE, DATA_REALIZACAO, EXAME, etc.",
    key="file_upload"
)

if uploaded is not None:
    # Carregamento com feedback visual
    with st.spinner('🔄 Carregando e processando dados...'):
        df_raw = load_excel(uploaded)
    
    # Sucesso no carregamento
    st.success(f"✅ **Arquivo carregado com sucesso!** {uploaded.name} | **{len(df_raw):,}** registros")
    
    st.markdown("### 💾 **Salvar Análise no GitHub**")

    nome_personalizado = st.text_input(
        "Nome do arquivo (opcional)",
        placeholder="Exemplo: 'Outubro_2025_RaioX_Tomografia'"
    )
    salvar_agora = st.button("💾 Salvar Análise", use_container_width=True)

    if salvar_agora:
        try:
            token = st.secrets["GITHUB_TOKEN"]
            repo = st.secrets["GITHUB_REPO"]

            nome_final = nome_personalizado.strip() or datetime.now().strftime("%Y-%m-%d_%H-%M")
            caminho_git = f"historico_sadt/{nome_final}.xlsx"
            arquivo_bytes = uploaded.getvalue()

            with st.spinner("⏫ Enviando análise para o GitHub..."):
                status, resp = github_put_file(
                    token, repo, caminho_git, arquivo_bytes, f"Nova análise adicionada: {nome_final}"
                )

            if status in [200, 201]:
                st.success(f"✅ Arquivo salvo com sucesso! [Abrir no GitHub]({resp['content']['html_url']})")
                st.session_state["atualizar_historico"] = True
            else:
                st.error(f"❌ Erro ao salvar: {resp.json().get('message', 'Falha desconhecida')}")

        except KeyError:
                st.error("⚠️ Token ou repositório GitHub não configurado em `st.secrets`.")

    # Expander para visualizar dados brutos
    with st.expander("🔍 **Visualizar dados brutos**", expanded=False):
        st.dataframe(df_raw.head(1000), use_container_width=True)
        st.caption(f"Mostrando até 1000 primeiras linhas de {len(df_raw):,} total")

    # ---------------------------
    # Mapeamento de Colunas Inteligente
    # ---------------------------
    st.markdown("### 🔧 **Mapeamento de Colunas**")
    
    # Busca automática de colunas
    col_mappings = {
        "ATEND": find_col(df_raw, ["ATEND", "ATENDIMENTO", "NUM_ATEND"]),
        "NOME": find_col(df_raw, ["NOME_DO_PACIENTE", "NOME_PACIENTE", "PACIENTE", "NOME"]),
        "PEDIDO": find_col(df_raw, ["PEDIDO", "NUM_PEDIDO", "NUMERO_PEDIDO"]),
        "DATA_PEDIDO": find_col(df_raw, ["DATA_PEDIDO", "DATA_PED", "DT_PEDIDO"]),
        "DATA_REALIZ": find_col(df_raw, ["DATA_REALIZ", "DATA_REALIZA", "DATA_REALIZAC", "DATA_REALIZACAO", "DT_REALIZACAO"]),
        "EXAME": find_col(df_raw, ["EXAME", "PROCEDIMENTO", "TIPO_EXAME"]),
        "TIPO": find_col(df_raw, ["TIPO", "CATEGORIA", "MODALIDADE"]),
        "ENCAM": find_col(df_raw, ["ENCAMINHAMENTO", "ENCAM", "ORIGEM"]),
        "LOCAL": find_col(df_raw, ["LOCAL", "PROCEDENCIA", "UNIDADE"]),
        "TECNICO": find_col(df_raw, ["TECNICO", "OPERADOR"]),
        "MEDICO": find_col(df_raw, ["MEDICO", "RADIOLOGISTA", "LAUDO"]),
        "TEMPO_ESTIMADO": find_col(df_raw, ["TEMPO ESTIMADO", "TEMPO ESPERA", "TEMPO_PREVISTO"])
    }
    
    # Mostra status do mapeamento
    mapping_cols = st.columns(4)
    for i, (key, col) in enumerate(col_mappings.items()):
        with mapping_cols[i % 4]:
            status = "✅" if col else "❌"
            st.markdown(f"**{key}**: {status} `{col if col else 'Não encontrada'}`")
    
    # Validação de colunas obrigatórias
    required_cols = ["DATA_REALIZ", "EXAME"]
    missing_required = [k for k in required_cols if col_mappings[k] is None]
    
    if missing_required:
        st.error(f"⚠️ **Colunas obrigatórias não encontradas**: {missing_required}")
        st.stop()

    # ---------------------------
    # Pré-processamento Avançado
    # ---------------------------
    @st.cache_data
    def advanced_preprocess(df):
        """Pré-processamento avançado dos dados"""
        d = df.copy()

        # -------------------------------
        # Parse de datas
        if col_mappings["DATA_REALIZ"]:
            d["DATA_REALIZACAO"] = parse_excel_dates(d[col_mappings["DATA_REALIZ"]])
        else:
            d["DATA_REALIZACAO"] = pd.NaT  # garante a coluna mesmo se não existir

        if col_mappings["DATA_PEDIDO"]:
            d["DATA_PEDIDO"] = parse_excel_dates(d[col_mappings["DATA_PEDIDO"]])
        else:
            d["DATA_PEDIDO"] = pd.NaT

        # Tempo estimado já fornecido na planilha
        if col_mappings["TEMPO_ESTIMADO"]:
            d["TEMPO_ESTIMADO_HORAS"] = pd.to_numeric(
                d[col_mappings["TEMPO_ESTIMADO"]], errors="coerce"
            )
        else:
            d["TEMPO_ESTIMADO_HORAS"] = None

        # ID do paciente mais robusto
        if col_mappings["NOME"] and col_mappings["ATEND"]:
            d["PACIENTE_ID"] = (d[col_mappings["ATEND"]].astype(str).str.strip() + 
                               " | " + d[col_mappings["NOME"]].astype(str).str.strip())
        elif col_mappings["NOME"]:
            d["PACIENTE_ID"] = d[col_mappings["NOME"]].astype(str).str.strip()
        elif col_mappings["ATEND"]:
            d["PACIENTE_ID"] = d[col_mappings["ATEND"]].astype(str).str.strip()
        else:
            d["PACIENTE_ID"] = "PACIENTE_" + d.index.astype(str)
        
        # Normalização de exames
        d["EXAME_NORM"] = (d[col_mappings["EXAME"]].astype(str)
                          .str.upper().str.strip()
                          .str.replace(r"[^\w\s]", " ", regex=True)
                          .str.replace(r"\s+", " ", regex=True))
        
        
        # Classificação inteligente de grupos
        def classificar_grupo_avancado(exame):
            exame = str(exame).upper().strip()
            
            # Raio-X
            if any(term in exame for term in ["RX", "RAIO", "RADIO"]):
                return "RAIO-X"
            
            # Tomografia
            if any(term in exame for term in ["TC", "TOMOGRAFIA", "CT"]):
                return "TOMOGRAFIA"
                
            # Ultrassom
            if any(term in exame for term in ["US", "ULTRA", "ECO"]):
                return "ULTRASSOM"
                
            # Ressonância
            if any(term in exame for term in ["RM", "RESSONANCIA", "MAGNETICA", "MRI"]):
                return "RESSONANCIA"
                
            # Mamografia
            if any(term in exame for term in ["MAMO", "MAMA"]):
                return "MAMOGRAFIA"
                
            # Densitometria
            if any(term in exame for term in ["DENSI", "OSTEO"]):
                return "DENSITOMETRIA"
                
            # Eletrocardiograma
            if any(term in exame for term in ["ECG", "ELETRO", "CARDIO"]):
                return "ELETROCARDIOGRAMA"
                
            return "OUTROS"
        
        d["GRUPO_EXAME"] = d["EXAME_NORM"].apply(classificar_grupo_avancado).astype("category")
        
        # Dose estimada corrigida baseada em referências médicas
        # Referência: ICRP 103, 2007 e NCRP 160, 2009
        dose_referencias = {
            # Raio-X (mSv)
            "RX TORAX": 0.1,
            "RX ABDOME": 0.7,
            "RX COLUNA": 1.5,
            "RX PELVE": 0.6,
            "RX EXTREMIDADES": 0.01,
            "RX CRANEO": 0.1,
            "RX COLUNA CERVICAL": 0.2,
            "RX COLUNA LOMBAR": 1.5,
            
            # Tomografia Computadorizada (mSv)
            "TC CRANIO": 2.0,
            "TC TORAX": 7.0,
            "TC ABDOME": 8.0,
            "TC PELVE": 6.0,
            "TC COLUNA": 6.0,
            "TC CARDIAC": 16.0,
            
            # Mamografia (mSv)
            "MAMOGRAFIA": 0.4,
            
            # Sem radiação ionizante
            "RESSONANCIA": 0.0,
            "ULTRASSOM": 0.0,
            "ELETROCARDIOGRAMA": 0.0,
            "DENSITOMETRIA": 0.01,
        }
        
        def estimar_dose_corrigida(exame):
            exame = str(exame).upper().strip()
            
            # Busca por palavras-chave mais específicas
            for ref_exame, dose in dose_referencias.items():
                palavras_ref = ref_exame.split()
                if all(palavra in exame for palavra in palavras_ref if len(palavra) > 2):
                    return dose
            
            # Busca por categoria geral
            if "TC" in exame or "TOMOGRAFIA" in exame:
                return 5.0  # Média geral para TC
            elif "RX" in exame or "RAIO" in exame:
                return 0.5  # Média geral para RX
            elif "MAMO" in exame:
                return 0.4
            elif any(termo in exame for termo in ["RM", "RESSONANCIA", "US", "ULTRA", "ECG"]):
                return 0.0
            
            return 0.0
        
        d["DOSE_ESTIMADA"] = d["EXAME_NORM"].apply(estimar_dose_corrigida)
        
        # Features temporais
        d["ANO"] = d["DATA_REALIZACAO"].dt.year
        d["MES"] = d["DATA_REALIZACAO"].dt.month
        d["DIA_SEMANA"] = d["DATA_REALIZACAO"].dt.dayofweek  # 0=Segunda
        d["HORA"] = d["DATA_REALIZACAO"].dt.hour
        d["SEMANA_ANO"] = d["DATA_REALIZACAO"].dt.isocalendar().week
        
        # Período do dia
        def classificar_periodo(hora):
            if pd.isna(hora):
                return "NÃO_INFORMADO"
            if 6 <= hora < 12:
                return "MANHÃ"
            elif 12 <= hora < 18:
                return "TARDE"
            elif 18 <= hora < 24:
                return "NOITE"
            else:
                return "MADRUGADA"
        
        d["PERIODO_DIA"] = d["HORA"].apply(classificar_periodo).astype("category")
        
        # Tempo estimado já fornecido na planilha
        if col_mappings["TEMPO_ESTIMADO"]:
            d["TEMPO_ESTIMADO_HORAS"] = pd.to_numeric(
                d[col_mappings["TEMPO_ESTIMADO"]], errors="coerce"
            )
        else:
            d["TEMPO_ESTIMADO_HORAS"] = None

        return d

    # Processa os dados
    with st.spinner('⚙️ Processando dados avançados...'):
        df = advanced_preprocess(df_raw)
    
    st.success("✅ **Pré-processamento concluído!**")

    # ---------------------------
    # Sidebar: Filtros Avançados
    # ---------------------------
    st.sidebar.markdown("### 🎛️ **Painel de Controle**")
    
    # Tema
    tema_escuro = st.sidebar.checkbox("🌓 **Tema escuro**", value=False)
    template = "plotly_dark" if tema_escuro else "plotly_white"
    
    # Período de análise
    st.sidebar.markdown("#### 📅 **Período de Análise**")
    min_date = df["DATA_REALIZACAO"].dt.date.min()
    max_date = df["DATA_REALIZACAO"].dt.date.max()
    
    periodo_opcoes = {
        "Último mês": 30,
        "Últimos 3 meses": 90,
        "Últimos 6 meses": 180,
        "Último ano": 365,
        "Todo período": None,
        "Personalizado": "custom"
    }
    
    periodo_selecionado = st.sidebar.selectbox("**Período padrão**", list(periodo_opcoes.keys()), index=2)
    
    if periodo_selecionado == "Personalizado":
        data_inicio, data_fim = st.sidebar.date_input(
            "**Intervalo personalizado**", 
            [min_date, max_date], 
            min_value=min_date, 
            max_value=max_date
        )
    else:
        if periodo_opcoes[periodo_selecionado] is None:
            data_inicio, data_fim = min_date, max_date
        else:
            data_fim = max_date
            data_inicio = data_fim - timedelta(days=periodo_opcoes[periodo_selecionado])
    
    # Filtros de conteúdo
    st.sidebar.markdown("#### 🎯 **Filtros de Conteúdo**")
    
    # Grupos de exame
    grupos_disponiveis = sorted(df["GRUPO_EXAME"].unique())
    grupos_selecionados = st.sidebar.multiselect(
        "**Grupos de exame**", 
        grupos_disponiveis, 
        default=grupos_disponiveis
    )
    
    # Período do dia
    periodos_disponiveis = sorted(df["PERIODO_DIA"].unique())
    periodos_selecionados = st.sidebar.multiselect(
        "**Períodos do dia**", 
        periodos_disponiveis, 
        default=periodos_disponiveis
    )
    
    # Filtros adicionais condicionais
    if col_mappings["ENCAM"]:
        encam_disponiveis = sorted(df[col_mappings["ENCAM"]].dropna().unique())
        encam_selecionados = st.sidebar.multiselect(
            "**Encaminhamentos**", 
            encam_disponiveis, 
            default=encam_disponiveis
        )
    else:
        encam_selecionados = []
    
    # Botão reset
    if st.sidebar.button("🔄 **Resetar todos os filtros**"):
        st.rerun()

    # Aplicar filtros
    df_filtered = df[
        (df["DATA_REALIZACAO"].dt.date >= data_inicio) &
        (df["DATA_REALIZACAO"].dt.date <= data_fim) &
        (df["GRUPO_EXAME"].isin(grupos_selecionados)) &
        (df["PERIODO_DIA"].isin(periodos_selecionados))
    ].copy()
    
    if encam_selecionados and col_mappings["ENCAM"]:
        df_filtered = df_filtered[df_filtered[col_mappings["ENCAM"]].isin(encam_selecionados)]
    
    # ---------------------------
    # Dashboard Principal em Tabs
    # ---------------------------
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 **Visão Geral**", 
        "⏱️ **Análise Temporal**", 
        "👥 **Pacientes**", 
        "☢️ **Radioproteção**", 
        "📈 **Analytics**"
    ])
    
    with tab1:
        st.markdown("### 📊 **Visão Geral do Centro**")
        
        # Métricas principais
        col1, col2, col3, col4 = st.columns(4)
        
        total_exames = len(df_filtered)
        total_pacientes = df_filtered["PACIENTE_ID"].nunique()
        exames_por_paciente = total_exames / total_pacientes if total_pacientes > 0 else 0
        dias_periodo = (data_fim - data_inicio).days + 1
        media_diaria = total_exames / dias_periodo
        
        with col1:
            st.markdown(create_advanced_metrics_card(
                "Total de Exames", 
                f"{total_exames:,}",
                f"No período selecionado",
                color="#1f77b4"
            ), unsafe_allow_html=True)
        
        with col2:
            st.markdown(create_advanced_metrics_card(
                "Pacientes Únicos", 
                f"{total_pacientes:,}",
                f"Atendidos no período",
                color="#2ca02c"
            ), unsafe_allow_html=True)
        
        with col3:
            st.markdown(create_advanced_metrics_card(
                "Exames/Paciente", 
                f"{exames_por_paciente:.1f}",
                f"Média por paciente",
                color="#ff7f0e"
            ), unsafe_allow_html=True)
        
        with col4:
            st.markdown(create_advanced_metrics_card(
                "Média Diária", 
                f"{media_diaria:.1f}",
                f"Exames por dia",
                color="#d62728"
            ), unsafe_allow_html=True)
        
        # Insights automáticos
        insights = generate_insights(df_filtered, "volume")
        if insights:
            st.markdown(f"""
            <div class="insight-box">
                <h4>🔍 Insights Automáticos</h4>
                {"<br>".join(insights)}
            </div>
            """, unsafe_allow_html=True)
        
        # Gráficos principais
        col1, col2 = st.columns(2)
        
        with col1:
            # Distribuição por grupo
            grupo_dist = df_filtered["GRUPO_EXAME"].value_counts().reset_index()
            grupo_dist.columns = ["Grupo", "Quantidade"]
            
            fig_grupo = px.pie(
                grupo_dist, 
                values="Quantidade", 
                names="Grupo",
                title="📋 **Distribuição por Grupo de Exame**",
                template=template,
                hole=0.4
            )
            fig_grupo.update_traces(
                hovertemplate="<b>%{label}</b><br>Quantidade: %{value}<br>Percentual: %{percent}<extra></extra>"
            )
            st.plotly_chart(fig_grupo, use_container_width=True)
        
        with col2:
            # Top 10 exames
            top_exames = df_filtered["EXAME_NORM"].value_counts().head(10).reset_index()
            top_exames.columns = ["Exame", "Quantidade"]
            
            fig_top = px.bar(
                top_exames,
                x="Quantidade",
                y="Exame",
                orientation="h",
                title="🏆 **Top 10 Exames Mais Realizados**",
                template=template
            )
            fig_top.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_top, use_container_width=True)
        
        # Evolução temporal
        st.markdown("#### 📈 **Evolução Temporal**")
        
        evolucao_diaria = (df_filtered.groupby(df_filtered["DATA_REALIZACAO"].dt.date)
                          .agg({
                              "PACIENTE_ID": ["size", "nunique"]
                          }))
        evolucao_diaria.columns = ["Total_Exames", "Pacientes_Unicos"]
        evolucao_diaria = evolucao_diaria.reset_index()
        
        # Initialize the figure (make sure this is done before adding traces)
        fig_evolucao = go.Figure()

        # Now you can safely add traces
        fig_evolucao.add_trace(
            go.Scatter(
                x=evolucao_diaria["DATA_REALIZACAO"],
                y=evolucao_diaria["Total_Exames"],
                mode="lines+markers",
                name="Exames",
                line=dict(color="#1f77b4", width=2)
            )
        )

        fig_evolucao.add_trace(
            go.Scatter(
                x=evolucao_diaria["DATA_REALIZACAO"],
                y=evolucao_diaria["Pacientes_Unicos"],
                mode="lines+markers",
                name="Pacientes",
                line=dict(color="#2ca02c", width=2)
            )
        )

        fig_evolucao.update_layout(
            height=500,
            template=template,
            title="📅 **Evolução Diária do Centro**",
            showlegend=False
        )

        # Plot the chart
        st.plotly_chart(fig_evolucao, use_container_width=True)

    with tab2:
        st.markdown("### ⏱️ **Análise Temporal Detalhada**")
        
        if "TEMPO_ESTIMADO_HORAS" in df_filtered.columns and df_filtered["TEMPO_ESTIMADO_HORAS"].gt(0).any():
            df_tempo = df_filtered[df_filtered["TEMPO_ESTIMADO_HORAS"] > 0].copy()
            Q1 = df_tempo["TEMPO_ESTIMADO_HORAS"].quantile(0.25)
            Q3 = df_tempo["TEMPO_ESTIMADO_HORAS"].quantile(0.75)
            IQR = Q3 - Q1
            filtro_outliers = (
                (df_tempo["TEMPO_ESTIMADO_HORAS"] >= Q1 - 1.5 * IQR) &
                (df_tempo["TEMPO_ESTIMADO_HORAS"] <= Q3 + 1.5 * IQR)
            )
            df_tempo = df_tempo[filtro_outliers].copy()

            tempo_mediano = df_tempo["TEMPO_ESTIMADO_HORAS"].median()
            tempo_media = df_tempo["TEMPO_ESTIMADO_HORAS"].mean()
            tempo_p95 = df_tempo["TEMPO_ESTIMADO_HORAS"].quantile(0.95)
            tempo_max = df_tempo["TEMPO_ESTIMADO_HORAS"].max()

            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(create_advanced_metrics_card(
                    "Tempo Estimado Mediano", 
                    format_duration(tempo_mediano),
                    "50% dos exames",
                    color="#2ca02c"
                ), unsafe_allow_html=True)
            
            with col2:
                st.markdown(create_advanced_metrics_card(
                    "Tempo Estimado Médio", 
                    format_duration(tempo_media),
                    "Média geral",
                    color="#ff7f0e"
                ), unsafe_allow_html=True)
            
            with col3:
                st.markdown(create_advanced_metrics_card(
                    "Percentil 95", 
                    format_duration(tempo_p95),
                    "95% dos exames",
                    color="#d62728"
                ), unsafe_allow_html=True)
            
            with col4:
                st.markdown(create_advanced_metrics_card(
                    "Tempo Estimado Máximo", 
                    format_duration(tempo_max),
                    "Maior espera",
                    color="#9467bd"
                ), unsafe_allow_html=True)
            
            # Análise diária de tempos de espera
            st.markdown("#### 📊 **Análise Diária de Tempos de Espera**")
            
            # Tempo médio por dia
            tempo_diario = df_tempo.groupby(df_tempo["DATA_REALIZACAO"].dt.date).agg({
                "TEMPO_ESTIMADO_HORAS": ["median", "mean", "max", "count"]
            }).round(2)
            
            tempo_diario.columns = ["Mediana", "Media", "Maximo", "Quantidade"]
            tempo_diario = tempo_diario.reset_index()
            
            # Tempo mediano por grupo por dia
            tempo_grupo_dia = df_tempo.groupby([
                df_tempo["DATA_REALIZACAO"].dt.date, 
                "GRUPO_EXAME"
            ])["TEMPO_ESTIMADO_HORAS"].median().reset_index()
            
            # Gráficos de análise temporal
            col1, col2 = st.columns(2)
            
            with col1:
                # Evolução da mediana diária
                fig_tempo_dia = px.line(
                    tempo_diario,
                    x="DATA_REALIZACAO",
                    y="Mediana",
                    title="📈 **Mediana de Espera por Dia**",
                    template=template,
                    labels={"Mediana": "Tempo Mediano (horas)", "DATA_REALIZACAO": "Data"}
                )
                
                # Adicionar média geral como linha de referência
                fig_tempo_dia.add_hline(
                    y=tempo_mediano, 
                    line_dash="dash", 
                    line_color="red", 
                    annotation_text=f"Mediana Geral: {format_duration(tempo_mediano)}"
                )
                
                st.plotly_chart(fig_tempo_dia, use_container_width=True)
            
            with col2:
                # Tempo máximo por dia (paciente com maior espera)
                fig_max_dia = px.line(
                    tempo_diario,
                    x="DATA_REALIZACAO",
                    y="Maximo",
                    title="⏰ **Maior Tempo de Espera por Dia**",
                    template=template,
                    labels={"Maximo": "Tempo Máximo (horas)", "DATA_REALIZACAO": "Data"}
                )
                
                st.plotly_chart(fig_max_dia, use_container_width=True)
            
            # Mediana de espera por grupo
            mediana_grupo = df_tempo.groupby("GRUPO_EXAME")["TEMPO_ESTIMADO_HORAS"].agg([
                "median", "mean", "max", "count"
            ]).round(2)
            mediana_grupo.columns = ["Mediana_h", "Media_h", "Maximo_h", "Quantidade"]
            mediana_grupo = mediana_grupo.sort_values("Mediana_h", ascending=True).reset_index()
            
            fig_grupo_tempo = px.bar(
                mediana_grupo,
                x="Mediana_h",
                y="GRUPO_EXAME",
                orientation="h",
                title="📊 **Tempo Mediano de Espera por Grupo**",
                template=template,
                labels={"Mediana_h": "Tempo Mediano (horas)", "GRUPO_EXAME": "Grupo"}
            )
            fig_grupo_tempo.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_grupo_tempo, use_container_width=True)
            
            # Tabela detalhada com pacientes de maior espera por dia
            st.markdown("#### 📋 **Pacientes com Maior Tempo de Espera por Dia**")
            
            # Identificar o paciente com maior tempo de espera por dia
            pacientes_max_espera = df_tempo.loc[
                df_tempo.groupby(df_tempo["DATA_REALIZACAO"].dt.date)["TEMPO_ESTIMADO_HORAS"].idxmax()
            ][["DATA_REALIZACAO", "PACIENTE_ID", "EXAME_NORM", "TEMPO_ESTIMADO_HORAS"]].copy()

            pacientes_max_espera["DATA"] = pacientes_max_espera["DATA_REALIZACAO"].dt.date
            pacientes_max_espera["TEMPO_FORMATADO"] = pacientes_max_espera["TEMPO_ESTIMADO_HORAS"].apply(format_duration)

            tabela_max_espera = pacientes_max_espera[[
                "DATA", "PACIENTE_ID", "EXAME_NORM", "TEMPO_FORMATADO"
            ]].sort_values("DATA", ascending=False)
            tabela_max_espera.columns = ["Data", "Paciente", "Exame", "Tempo Estimado"]

            st.dataframe(tabela_max_espera.head(20), use_container_width=True)
            st.caption("Mostrando os 20 dias mais recentes")
            
            # Análise mensal de tempos
            st.markdown("#### 📅 **Análise Mensal de Tempos de Espera**")
            
            df_tempo["Ano_Mes"] = df_tempo["DATA_REALIZACAO"].dt.to_period("M")
            tempo_mensal = df_tempo.groupby("Ano_Mes")["TEMPO_ESTIMADO_HORAS"].agg([
                "median", "mean", "count"
            ]).round(2)
            tempo_mensal.columns = ["Mediana_h", "Media_h", "Quantidade"]
            tempo_mensal = tempo_mensal.reset_index()
            tempo_mensal["Ano_Mes_str"] = tempo_mensal["Ano_Mes"].astype(str)
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig_mensal = px.line(
                    tempo_mensal,
                    x="Ano_Mes_str",
                    y="Mediana_h",
                    title="📈 **Evolução Mensal - Tempo Mediano**",
                    template=template,
                    labels={"Mediana_h": "Tempo Mediano (horas)", "Ano_Mes_str": "Mês"}
                )
                st.plotly_chart(fig_mensal, use_container_width=True)
            
            with col2:
                # Tabela resumo mensal
                st.markdown("**📊 Resumo Mensal**")
                tempo_mensal_display = tempo_mensal.copy()
                tempo_mensal_display["Mediana_Formatada"] = tempo_mensal_display["Mediana_h"].apply(format_duration)
                tempo_mensal_display["Media_Formatada"] = tempo_mensal_display["Media_h"].apply(format_duration)
                
                resumo_mensal = tempo_mensal_display[[
                    "Ano_Mes_str", "Mediana_Formatada", "Media_Formatada", "Quantidade"
                ]]
                resumo_mensal.columns = ["Mês", "Mediana", "Média", "Exames"]
                st.dataframe(resumo_mensal, use_container_width=True)
            
            # Insights temporais
            insights_tempo = generate_insights(df_filtered, "temporal")
            if insights_tempo:
                st.markdown(f"""
                <div class="insight-box">
                    <h4>⏰ Insights Temporais</h4>
                    {"<br>".join(insights_tempo)}
                </div>
                """, unsafe_allow_html=True)
        
        else:
            st.warning("⚠️ **Análise temporal não disponível**: Não foram encontradas colunas de data de pedido para calcular tempos de espera.")
            
        # Análise de sazonalidade
        st.markdown("#### 📅 **Análise de Sazonalidade**")
        
        # Heatmap por hora e dia da semana
        df_heatmap = df_filtered.groupby(["DIA_SEMANA", "HORA"]).size().reset_index(name="Quantidade")
        
        # Criar matriz para heatmap
        heatmap_matrix = df_heatmap.pivot(index="DIA_SEMANA", columns="HORA", values="Quantidade").fillna(0)
        
        # Labels dos dias da semana
        dias_semana = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        heatmap_matrix.index = [dias_semana[i] for i in heatmap_matrix.index]
        
        fig_heatmap = px.imshow(
            heatmap_matrix,
            title="🔥 **Heatmap: Exames por Hora e Dia da Semana**",
            template=template,
            aspect="auto",
            color_continuous_scale="Blues"
        )
        fig_heatmap.update_layout(
            xaxis_title="Hora do Dia",
            yaxis_title="Dia da Semana"
        )
        
        st.plotly_chart(fig_heatmap, use_container_width=True)
        
        # Análise por período do dia
        col1, col2 = st.columns(2)
        
        with col1:
            periodo_dist = df_filtered["PERIODO_DIA"].value_counts().reset_index()
            periodo_dist.columns = ["Período", "Quantidade"]
            
            fig_periodo = px.bar(
                periodo_dist,
                x="Período",
                y="Quantidade",
                title="🌅 **Distribuição por Período do Dia**",
                template=template,
                color="Quantidade",
                color_continuous_scale="viridis"
            )
            st.plotly_chart(fig_periodo, use_container_width=True)
        
        with col2:
            # Análise mensal
            df_mensal = df_filtered.copy()
            df_mensal["Mes_Nome"] = df_mensal["DATA_REALIZACAO"].dt.strftime("%B")
            mensal_dist = df_mensal["Mes_Nome"].value_counts().reset_index()
            mensal_dist.columns = ["Mês", "Quantidade"]
            
            fig_mensal = px.bar(
                mensal_dist,
                x="Mês",
                y="Quantidade",
                title="📅 **Distribuição Mensal**",
                template=template,
                color="Quantidade",
                color_continuous_scale="plasma"
            )
            fig_mensal.update_xaxes(tickangle=45)
            st.plotly_chart(fig_mensal, use_container_width=True)
    
    with tab3:
        st.markdown("### 👥 **Análise de Pacientes**")
        
        # Análise de reincidência
        reincidencia = df_filtered.groupby("PACIENTE_ID").agg({
            "DATA_REALIZACAO": ["count", "nunique", lambda x: (x.max()-x.min()).days],
            "EXAME_NORM": lambda x: x.mode().iloc[0] if not x.empty else "N/A",
            "GRUPO_EXAME": "nunique"
        }).round(2)
        
        reincidencia.columns = ["Total_Exames", "Dias_Distintos", "Periodo_Dias", "Exame_Mais_Comum", "Grupos_Diferentes"]
        reincidencia = reincidencia.reset_index()
        
        # Métricas de pacientes
        col1, col2, col3, col4 = st.columns(4)
        
        pacientes_recorrentes = len(reincidencia[reincidencia["Total_Exames"] > 1])
        taxa_reincidencia = (pacientes_recorrentes / len(reincidencia)) * 100 if len(reincidencia) > 0 else 0
        media_exames_paciente = reincidencia["Total_Exames"].mean()
        max_exames_paciente = reincidencia["Total_Exames"].max()
        
        with col1:
            st.markdown(create_advanced_metrics_card(
                "Pacientes Recorrentes", 
                f"{pacientes_recorrentes:,}",
                f"Com mais de 1 exame",
                color="#9467bd"
            ), unsafe_allow_html=True)
        
        with col2:
            st.markdown(create_advanced_metrics_card(
                "Taxa de Reincidência", 
                f"{taxa_reincidencia:.1f}%",
                f"Pacientes que retornaram",
                color="#8c564b"
            ), unsafe_allow_html=True)
        
        with col3:
            st.markdown(create_advanced_metrics_card(
                "Média Exames/Paciente", 
                f"{media_exames_paciente:.1f}",
                f"Por paciente no período",
                color="#e377c2"
            ), unsafe_allow_html=True)
        
        with col4:
            st.markdown(create_advanced_metrics_card(
                "Máx Exames/Paciente", 
                f"{max_exames_paciente:,}",
                f"Paciente com mais exames",
                color="#17becf"
            ), unsafe_allow_html=True)
        
        # Gráficos de pacientes
        col1, col2 = st.columns(2)
        
        with col1:
            # Distribuição de exames por paciente
            dist_exames = reincidencia["Total_Exames"].value_counts().sort_index().reset_index()
            dist_exames.columns = ["Num_Exames", "Num_Pacientes"]
            
            fig_dist = px.bar(
                dist_exames.head(10),  # Primeiros 10 para legibilidade
                x="Num_Exames",
                y="Num_Pacientes",
                title="📊 **Distribuição: Número de Exames por Paciente**",
                template=template,
                labels={"Num_Exames": "Número de Exames", "Num_Pacientes": "Número de Pacientes"}
            )
            st.plotly_chart(fig_dist, use_container_width=True)
        
        with col2:
            # Top pacientes com mais exames
            top_pacientes = reincidencia.nlargest(15, "Total_Exames")[["PACIENTE_ID", "Total_Exames", "Exame_Mais_Comum"]]
            
            fig_top_pac = px.bar(
                top_pacientes,
                x="Total_Exames",
                y="PACIENTE_ID",
                orientation="h",
                title="🏆 **Top 15 Pacientes por Número de Exames**",
                template=template,
                hover_data=["Exame_Mais_Comum"]
            )
            fig_top_pac.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_top_pac, use_container_width=True)
        
        # Análise de jornada do paciente
        st.markdown("#### 🛤️ **Jornada dos Pacientes**")
        
        # Tabela detalhada de reincidência
        st.markdown("**📋 Tabela Detalhada de Pacientes**")
        
        # Filtros para a tabela
        col_filtro1, col_filtro2 = st.columns(2)
        with col_filtro1:
            min_exames = st.number_input("Mínimo de exames", min_value=1, value=1, max_value=int(max_exames_paciente))
        with col_filtro2:
            max_registros = st.number_input("Máximo de registros exibidos", min_value=10, value=100, max_value=1000)
        
        tabela_filtrada = reincidencia[reincidencia["Total_Exames"] >= min_exames].head(max_registros)
        st.dataframe(tabela_filtrada, use_container_width=True)
        
        # Export
        csv = tabela_filtrada.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 **Baixar Análise de Pacientes (CSV)**",
            csv,
            "analise_pacientes.csv",
            "text/csv"
        )
    
    with tab4:
        st.markdown("### ☢️ **Análise de Radioproteção**")
        
        # Métricas de dose
        dose_total = df_filtered["DOSE_ESTIMADA"].sum()
        dose_media_exame = df_filtered["DOSE_ESTIMADA"].mean()
        dose_media_paciente = df_filtered.groupby("PACIENTE_ID")["DOSE_ESTIMADA"].sum().mean()
        exames_com_dose = len(df_filtered[df_filtered["DOSE_ESTIMADA"] > 0])
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(create_advanced_metrics_card(
                "Dose Total Estimada", 
                f"{dose_total:.2f} mSv",
                f"Soma de todos os exames",
                color="#ff6b6b"
            ), unsafe_allow_html=True)
        
        with col2:
            st.markdown(create_advanced_metrics_card(
                "Dose Média/Exame", 
                f"{dose_media_exame:.3f} mSv",
                f"Por exame realizado",
                color="#ffa726"
            ), unsafe_allow_html=True)
        
        with col3:
            st.markdown(create_advanced_metrics_card(
                "Dose Média/Paciente", 
                f"{dose_media_paciente:.2f} mSv",
                f"Por paciente no período",
                color="#ffca28"
            ), unsafe_allow_html=True)
        
        with col4:
            st.markdown(create_advanced_metrics_card(
                "Exames com Radiação", 
                f"{exames_com_dose:,}",
                f"De {total_exames:,} total",
                color="#ef5350"
            ), unsafe_allow_html=True)
        
        # Referências de dose
        st.markdown("""
        <div class="dose-reference">
            <h4>📚 Referências para Estimativa de Dose</h4>
            <p><strong>Base de Cálculo:</strong> ICRP 103 (2007) e NCRP 160 (2009)</p>
            <p><strong>Doses Típicas:</strong></p>
            <ul>
                <li><strong>RX Tórax:</strong> 0.1 mSv</li>
                <li><strong>RX Abdome:</strong> 0.7 mSv</li>
                <li><strong>TC Tórax:</strong> 7.0 mSv</li>
                <li><strong>TC Abdome:</strong> 8.0 mSv</li>
                <li><strong>Mamografia:</strong> 0.4 mSv</li>
            </ul>
            <p><strong>Nota:</strong> Valores são estimativas baseadas em protocolos padrão. Doses reais podem variar conforme equipamento e protocolo utilizado.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Alertas de radioproteção
        dose_paciente = df_filtered.groupby("PACIENTE_ID")["DOSE_ESTIMADA"].sum()
        
        # Limites de referência (valores educativos)
        limite_anual_publico = 1.0  # mSv/ano para público geral
        limite_investigacao = 20.0  # mSv - nível de investigação
        
        pacientes_acima_limite = dose_paciente[dose_paciente > limite_anual_publico]
        pacientes_investigacao = dose_paciente[dose_paciente > limite_investigacao]
        
        if len(pacientes_acima_limite) > 0:
            st.markdown(f"""
            <div class="warning-box">
                <h4>⚠️ Atenção - Radioproteção</h4>
                <p><strong>{len(pacientes_acima_limite)} pacientes</strong> receberam dose estimada superior a {limite_anual_publico} mSv (limite anual para público).</p>
                {f"<p><strong>{len(pacientes_investigacao)} pacientes</strong> requerem investigação (> {limite_investigacao} mSv).</p>" if len(pacientes_investigacao) > 0 else ""}
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="success-box">
                <h4>✅ Radioproteção</h4>
                <p>Todos os pacientes estão dentro dos limites de referência (< {limite_anual_publico} mSv).</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Gráficos de dose
        col1, col2 = st.columns(2)
        
        with col1:
            # Dose por grupo de exame
            dose_grupo = df_filtered.groupby("GRUPO_EXAME")["DOSE_ESTIMADA"].sum().reset_index()
            dose_grupo = dose_grupo.sort_values("DOSE_ESTIMADA", ascending=False)
            
            fig_dose_grupo = px.bar(
                dose_grupo,
                x="DOSE_ESTIMADA",
                y="GRUPO_EXAME",
                orientation="h",
                title="☢️ **Dose Total por Grupo de Exame**",
                template=template,
                labels={"DOSE_ESTIMADA": "Dose Total (mSv)", "GRUPO_EXAME": "Grupo"}
            )
            fig_dose_grupo.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_dose_grupo, use_container_width=True)
        
        with col2:
            # Top exames por dose individual
            dose_exame = df_filtered.groupby("EXAME_NORM")["DOSE_ESTIMADA"].agg(["mean", "sum", "count"]).reset_index()
            dose_exame.columns = ["Exame", "Dose_Media", "Dose_Total", "Quantidade"]
            dose_exame = dose_exame[dose_exame["Dose_Media"] > 0].nlargest(10, "Dose_Media")
            
            fig_dose_exame = px.scatter(
                dose_exame,
                x="Quantidade",
                y="Dose_Media",
                size="Dose_Total",
                hover_name="Exame",
                title="🎯 **Dose Média vs Quantidade (bolha = dose total)**",
                template=template,
                labels={"Dose_Media": "Dose Média (mSv)", "Quantidade": "Número de Exames"}
            )
            st.plotly_chart(fig_dose_exame, use_container_width=True)
        
        # Evolução temporal da dose
        dose_diaria = df_filtered.groupby(df_filtered["DATA_REALIZACAO"].dt.date)["DOSE_ESTIMADA"].sum().reset_index()
        dose_diaria.columns = ["Data", "Dose_Diaria"]
        
        fig_dose_tempo = px.line(
            dose_diaria,
            x="Data",
            y="Dose_Diaria",
            title="📈 **Evolução Diária da Dose Total Estimada**",
            template=template,
            labels={"Dose_Diaria": "Dose Diária (mSv)", "Data": "Data"}
        )
        
        # Adicionar média móvel de 7 dias
        dose_diaria["Media_Movel_7d"] = dose_diaria["Dose_Diaria"].rolling(window=7, center=True).mean()
        fig_dose_tempo.add_trace(
            go.Scatter(
                x=dose_diaria["Data"],
                y=dose_diaria["Media_Movel_7d"],
                mode="lines",
                name="Média Móvel 7 dias",
                line=dict(dash="dash", color="red")
            )
        )
        
        st.plotly_chart(fig_dose_tempo, use_container_width=True)
        
        # Tabela de pacientes com maior dose
        if len(pacientes_acima_limite) > 0:
            st.markdown("#### 🚨 **Pacientes com Dose Elevada**")
            tabela_dose_alta = pacientes_acima_limite.reset_index()
            tabela_dose_alta.columns = ["Paciente", "Dose_Total_mSv"]
            tabela_dose_alta = tabela_dose_alta.sort_values("Dose_Total_mSv", ascending=False)
            
            st.dataframe(tabela_dose_alta, use_container_width=True)
            
            csv_dose = tabela_dose_alta.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 **Baixar Lista de Pacientes - Dose Elevada (CSV)**",
                csv_dose,
                "pacientes_dose_elevada.csv",
                "text/csv"
            )
    
    with tab5:
        st.markdown("### 📈 **Analytics Avançado**")
        
        # Análise de correlações
        st.markdown("#### 🔗 **Análise de Correlações**")
        
        # Preparar dados numéricos para correlação
        df_corr = df_filtered.select_dtypes(include=[np.number])
        
        if len(df_corr.columns) > 1:
            corr_matrix = df_corr.corr()
            
            fig_corr = px.imshow(
                corr_matrix,
                title="🔗 **Matriz de Correlação**",
                template=template,
                color_continuous_scale="RdBu",
                aspect="auto"
            )
            st.plotly_chart(fig_corr, use_container_width=True)
        
        # Análise de tendências
        st.markdown("#### 📊 **Análise de Tendências**")
        
        # Crescimento mensal
        df_mensal_analytics = df_filtered.copy()
        df_mensal_analytics["Ano_Mes"] = df_mensal_analytics["DATA_REALIZACAO"].dt.to_period("M")
        
        # Verifique se a coluna 'Ano_Mes' existe, caso contrário, crie-a
        df_filtered['Ano_Mes'] = df_filtered['DATA_REALIZACAO'].dt.to_period('M')

        # Agora, podemos agrupar os dados corretamente
        # -----------------------------------------
        tendencia_mensal = (
            df_filtered
            .groupby(df_filtered["DATA_REALIZACAO"].dt.to_period("M"))
            .agg(
                Total_Exames       = ("PACIENTE_ID", "size"),
                Pacientes_Unicos   = ("PACIENTE_ID", "nunique"),
                Dose_Total         = ("DOSE_ESTIMADA", "sum"),
            )
            .reset_index()
            .rename(columns={"DATA_REALIZACAO": "Ano_Mes"})
        )

        # Agora calcula as taxas de crescimento
        tendencia_mensal["Crescimento_Exames"]   = tendencia_mensal["Total_Exames"].pct_change() * 100
        tendencia_mensal["Crescimento_Pacientes"] = tendencia_mensal["Pacientes_Unicos"].pct_change() * 100


    # -----------------------------------------
    # 2) REFACTOR EM Tab2: MÉTRICAS DE ESPERA
    # -----------------------------------------

    with tab2:
        st.markdown("### ⏱️ Análise Temporal Detalhada")

        if "TEMPO_ESTIMADO_HORAS" in df_filtered.columns and df_filtered["TEMPO_ESTIMADO_HORAS"].gt(0).any():
            df_tempo = df_filtered[df_filtered["TEMPO_ESTIMADO_HORAS"] > 0].copy()

            # 2.1 Mediana de espera por dia (toda a frota)
            mediana_diaria = (
                df_tempo
                .groupby(df_tempo["DATA_REALIZACAO"].dt.date)["TEMPO_ESTIMADO_HORAS"]
                .median()
                .reset_index(name="Mediana_h")
            )
            mediana_diaria["Mediana_Formatada"] = mediana_diaria["Mediana_h"].apply(format_duration)

            fig_mediana = px.line(
                mediana_diaria,
                x="DATA_REALIZACAO",
                y="Mediana_h",
                title="📈 Mediana Diária de Tempo de Espera",
                labels={"Mediana_h": "Horas", "DATA_REALIZACAO": "Data"},
                template=template
            )
            fig_mediana.add_hline(
                y=mediana_diaria["Mediana_h"].mean(),
                line_dash="dash", line_color="red",
                annotation_text=f"Média Geral: {format_duration(mediana_diaria['Mediana_h'].mean())}"
            )
            st.plotly_chart(fig_mediana, use_container_width=True)

            # 2.2 Máximo de espera por dia e tabela de pacientes
            max_diaria = (
                df_tempo
                .groupby(df_tempo["DATA_REALIZACAO"].dt.date)["TEMPO_ESTIMADO_HORAS"]
                .max()
                .reset_index(name="Maximo_h")
            )
            max_diaria["Maximo_Formatado"] = max_diaria["Maximo_h"].apply(format_duration)

            fig_max = px.line(
                max_diaria,
                x="DATA_REALIZACAO",
                y="Maximo_h",
                title="⏰ Maior Tempo de Espera por Dia",
                labels={"Maximo_h": "Horas", "DATA_REALIZACAO": "Data"},
                template=template
            )
            st.plotly_chart(fig_max, use_container_width=True)

            # Tabela com data, paciente e exame que teve a maior espera
            pacientes_max = (
                df_tempo
                .loc[df_tempo.groupby(df_tempo["DATA_REALIZACAO"].dt.date)["TEMPO_ESTIMADO_HORAS"].idxmax()]
                [["DATA_REALIZACAO", "PACIENTE_ID", "EXAME_NORM", "TEMPO_ESTIMADO_HORAS"]]
            )
            pacientes_max["DATA"]          = pacientes_max["DATA_REALIZACAO"].dt.date
            pacientes_max["TEMPO_FORMATADO"] = pacientes_max["TEMPO_ESTIMADO_HORAS"].apply(format_duration)

            tabela_max = pacientes_max[["DATA", "PACIENTE_ID", "EXAME_NORM", "TEMPO_FORMATADO"]]
            tabela_max.columns = ["Data", "Paciente", "Exame", "Tempo de Espera"]
            st.markdown("#### 📋 Pacientes com Maior Tempo de Espera por Dia")
            st.dataframe(tabela_max.sort_values("Data", ascending=False), use_container_width=True)


            # 2.3 Métrica global e mensal de espera
            espera_global   = df_tempo["TEMPO_ESTIMADO_HORAS"].mean()
            st.markdown(f"**⏳ Tempo Médio Global de Espera:** {format_duration(espera_global)}")

            espera_mensal = (
                df_tempo
                .groupby(df_tempo["DATA_REALIZACAO"].dt.to_period("M"))["TEMPO_ESTIMADO_HORAS"]
                .mean()
                .reset_index(name="Media_h")
            )
            espera_mensal["Media_Formatada"] = espera_mensal["Media_h"].apply(format_duration)
            espera_mensal["Mes"] = espera_mensal["DATA_REALIZACAO"].astype(str)

            fig_espera_mes = px.bar(
                espera_mensal,
                x="Mes", y="Media_h",
                title="📅 Média Mensal de Espera",
                labels={"Media_h": "Horas", "Mes": "Mês"},
                template=template
            )
            st.plotly_chart(fig_espera_mes, use_container_width=True)

        else:
            st.warning("⚠️ **Análise temporal não disponível**: Não há valores válidos de tempo estimado para calcular a análise.")


        # -----------------------------------------
        # 3) RODAPÉ DE REFERÊNCIA EM Gráfico de Dose
        # -----------------------------------------

        # Depois de criar fig_dose_tempo:
        fig_dose_tempo.update_layout(
            annotations=[
                dict(
                    text=(
                         "Estimativas de dose: ICRP 103 (2007) & NCRP 160 (2009); "
                         "médias gerais: RX 0.5 mSv, TC 5 mSv"
                    ),
                    xref="paper", yref="paper",
                    x=0, y=-0.15,
                    showarrow=False,
                    font=dict(size=10, color="gray"),
                    align="left"
                )
           ]
        )
        st.plotly_chart(fig_dose_tempo, use_container_width=True)

        # Certifique-se de que o DataFrame tem 3 colunas antes de renomeá-las
        if tendencia_mensal.shape[1] == 3:
            tendencia_mensal.columns = ["Ano_Mes", "Total_Exames", "Pacientes_Unicos", "Dose_Total"]
        else:
            st.error("Erro: o DataFrame não possui o número correto de colunas.")
            st.stop()

        # Calcular a taxa de crescimento
        tendencia_mensal["Crescimento_Exames"] = tendencia_mensal["Total_Exames"].pct_change() * 100
        tendencia_mensal["Crescimento_Pacientes"] = tendencia_mensal["Pacientes_Unicos"].pct_change() * 100

        # Gráficos de tendência mensal
        fig_tendencia = make_subplots(
            rows=2, cols=2,
            subplot_titles=("Exames por Mês", "Pacientes Únicos por Mês", "Crescimento % Exames", "Dose Total por Mês"),
            specs=[[{"secondary_y": False}, {"secondary_y": False}],
                   [{"secondary_y": False}, {"secondary_y": False}]]
        )

        # Exames por mês
        fig_tendencia.add_trace(
            go.Scatter(x=tendencia_mensal["Ano_Mes"].astype(str), y=tendencia_mensal["Total_Exames"], 
                      mode="lines+markers", name="Exames"),
            row=1, col=1
        )

        # Pacientes por mês
        fig_tendencia.add_trace(
            go.Scatter(x=tendencia_mensal["Ano_Mes"].astype(str), y=tendencia_mensal["Pacientes_Unicos"], 
                      mode="lines+markers", name="Pacientes"),
            row=1, col=2
        )

        # Crescimento
        fig_tendencia.add_trace(
            go.Bar(x=tendencia_mensal["Ano_Mes"].astype(str), y=tendencia_mensal["Crescimento_Exames"], 
                  name="Crescimento %"),
            row=2, col=1
        )

        # Dose total
        fig_tendencia.add_trace(
            go.Scatter(x=tendencia_mensal["Ano_Mes"].astype(str), y=tendencia_mensal["Dose_Total"], 
                      mode="lines+markers", name="Dose"),
            row=2, col=2
        )

        fig_tendencia.update_layout(
            height=600,
            template="plotly_white",
            title="📈 **Dashboard de Tendências Mensais**",
            showlegend=False
        )

        st.plotly_chart(fig_tendencia, use_container_width=True)

        # Previsão simples usando média móvel
        st.markdown("#### 🔮 **Previsão Simples (Próximo Mês)**")
        
        if len(tendencia_mensal) >= 3:
            # Média móvel dos últimos 3 meses
            ultimos_3_meses = tendencia_mensal.tail(3)["Total_Exames"].mean()
            crescimento_medio = tendencia_mensal.tail(3)["Crescimento_Exames"].mean()
            
            previsao_proximo_mes = ultimos_3_meses * (1 + crescimento_medio/100)
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown(create_advanced_metrics_card(
                    "Previsão Próximo Mês", 
                    f"{previsao_proximo_mes:.0f}",
                    f"Exames estimados",
                    delta=crescimento_medio,
                    color="#9c27b0"
                ), unsafe_allow_html=True)
            
            with col2:
                st.markdown(create_advanced_metrics_card(
                    "Média Últimos 3 Meses", 
                    f"{ultimos_3_meses:.0f}",
                    f"Exames por mês",
                    color="#673ab7"
                ), unsafe_allow_html=True)
            
            with col3:
                st.markdown(create_advanced_metrics_card(
                    "Crescimento Médio", 
                    f"{crescimento_medio:+.1f}%",
                    f"Últimos 3 meses",
                    color="#3f51b5"
                ), unsafe_allow_html=True)
        
        # Análise de eficiência operacional
        st.markdown("#### ⚙️ **Eficiência Operacional**")
        
        insights_eficiencia = generate_insights(df_filtered, "efficiency")
        
        # Análise de capacidade
        capacidade_diaria = df_filtered.groupby(df_filtered["DATA_REALIZACAO"].dt.date).size()
        capacidade_maxima = capacidade_diaria.max()
        capacidade_media = capacidade_diaria.mean()
        utilizacao_media = (capacidade_media / capacidade_maxima) * 100
        
        dias_baixa_utilizacao = len(capacidade_diaria[capacidade_diaria < capacidade_media * 0.7])
        dias_alta_utilizacao = len(capacidade_diaria[capacidade_diaria > capacidade_media * 1.3])
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"""
            **📊 Métricas de Capacidade:**
            - **Capacidade máxima diária:** {capacidade_maxima} exames
            - **Média diária:** {capacidade_media:.1f} exames  
            - **Utilização média:** {utilizacao_media:.1f}%
            - **Dias de baixa utilização:** {dias_baixa_utilizacao} ({(dias_baixa_utilizacao/len(capacidade_diaria)*100):.1f}%)
            - **Dias de alta utilização:** {dias_alta_utilizacao} ({(dias_alta_utilizacao/len(capacidade_diaria)*100):.1f}%)
            """)
        
        with col2:
            if insights_eficiencia:
                st.markdown(f"""
                <div class="insight-box">
                    <h4>💡 Insights de Eficiência</h4>
                    {"<br>".join(insights_eficiencia)}
                </div>
                """, unsafe_allow_html=True)
        
        # Gráfico de utilização da capacidade
        utilizacao_diaria = (capacidade_diaria / capacidade_maxima * 100).reset_index()
        utilizacao_diaria.columns = ["Data", "Utilizacao_Percentual"]
        
        fig_utilizacao = px.line(
            utilizacao_diaria,
            x="Data",
            y="Utilizacao_Percentual",
            title="📊 **Utilização da Capacidade Diária (%)**",
            template=template
        )
        
        # Adicionar linhas de referência
        fig_utilizacao.add_hline(y=70, line_dash="dash", line_color="orange", annotation_text="Baixa utilização")
        fig_utilizacao.add_hline(y=100, line_dash="dash", line_color="green", annotation_text="Capacidade máxima")
        fig_utilizacao.add_hline(y=130, line_dash="dash", line_color="red", annotation_text="Sobrecarga")
        
        st.plotly_chart(fig_utilizacao, use_container_width=True)
    
    st.markdown("---")
    st.markdown("## 📁 Histórico de Arquivos e Comparativos")

    token = st.secrets.get("GITHUB_TOKEN")
    repo = st.secrets.get("GITHUB_REPO")

    if not token or not repo:
        st.warning("⚠️ GitHub não configurado corretamente em `st.secrets`.")
    else:
        historico = github_list_historico(token, repo)

        if not historico:
            st.info("Nenhum arquivo encontrado no histórico remoto ainda.")
        else:
            nomes = [f["nome"].replace(".xlsx", "") for f in historico]
            st.markdown(f"📂 Total de análises armazenadas: **{len(nomes)}**")
            selecao = st.multiselect("Selecione análises para comparar", nomes)

            if len(selecao) >= 2:
                dfs = []
                for nome in selecao:
                    caminho = f"historico_sadt/{nome}.xlsx"
                    conteudo = github_get_file(token, repo, caminho)
                    if conteudo:
                        df_tmp = pd.read_excel(BytesIO(conteudo))
                        df_tmp["Origem"] = nome
                        dfs.append(df_tmp)

                if dfs:
                    df_comp = pd.concat(dfs)
                    st.success(f"✅ {len(df_comp):,} registros combinados")

                    col1, col2 = st.columns(2)

                    # Total de exames por arquivo
                    total_exames = df_comp.groupby("Origem")["PACIENTE_ID"].count().reset_index()
                    fig_total = px.bar(
                        total_exames,
                        x="Origem", y="PACIENTE_ID",
                        title="📈 Total de Exames por Análise",
                        labels={"PACIENTE_ID": "Quantidade de Exames", "Origem": "Arquivo"},
                        text_auto=True, template="plotly_white"
                    )
                    with col1:
                        st.plotly_chart(fig_total, use_container_width=True)

                    # Pacientes únicos
                    pacientes = df_comp.groupby("Origem")["PACIENTE_ID"].nunique().reset_index()
                    fig_pac = px.bar(
                        pacientes,
                        x="Origem", y="PACIENTE_ID",
                        title="👥 Pacientes Únicos",
                        labels={"PACIENTE_ID": "Pacientes", "Origem": "Arquivo"},
                        text_auto=True, template="plotly_white"
                    )
                    with col2:
                        st.plotly_chart(fig_pac, use_container_width=True)

                    # Média de exames por paciente
                    metricas = total_exames.merge(pacientes, on="Origem", suffixes=("_Exames", "_Pacientes"))
                    metricas["Media"] = metricas["PACIENTE_ID_Exames"] / metricas["PACIENTE_ID_Pacientes"]
                    fig_media = px.bar(
                        metricas, x="Origem", y="Media", text_auto=True,
                        title="📊 Média de Exames por Paciente",
                        labels={"Media": "Média", "Origem": "Arquivo"}, template="plotly_white"
                    )
                    st.plotly_chart(fig_media, use_container_width=True)

                    # Variação percentual de exames
                    if len(metricas) > 1:
                        metricas["Var_Exames_%"] = metricas["PACIENTE_ID_Exames"].pct_change() * 100
                        fig_var = px.line(
                            metricas, x="Origem", y="Var_Exames_%", markers=True,
                            title="📉 Variação Percentual de Exames entre Períodos",
                            labels={"Var_Exames_%": "% Variação", "Origem": "Arquivo"},
                            template="plotly_white"
                        )
                        st.plotly_chart(fig_var, use_container_width=True)

    # ---------------------------
    # Seção de Export Melhorada
    # ---------------------------
    st.markdown("---")
    st.markdown("### 📄 **Exportação e Relatórios**")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # CSV do dataset filtrado
        csv_data = df_filtered.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 **Dados Filtrados (CSV)**",
            csv_data,
            "dados_radiologicos_filtrados.csv",
            "text/csv"
        )
    
    with col2:
        # Excel com múltiplas abas
        def create_excel_report():
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Aba principal com dados filtrados
                df_filtered.to_excel(writer, sheet_name='Dados_Filtrados', index=False)
                
                # Aba com resumo por grupo
                grupo_resumo = df_filtered.groupby('GRUPO_EXAME').agg({
                    'PACIENTE_ID': ['count', 'nunique'],
                    'DOSE_ESTIMADA': ['sum', 'mean'],
                    'DATA_REALIZACAO': ['min', 'max']
                }).round(2)
                grupo_resumo.columns = ['Total_Exames', 'Pacientes_Unicos', 'Dose_Total', 'Dose_Media', 'Data_Inicio', 'Data_Fim']
                grupo_resumo.to_excel(writer, sheet_name='Resumo_por_Grupo')
                
                # Aba com análise de pacientes se disponível
                if 'reincidencia' in locals():
                    reincidencia.to_excel(writer, sheet_name='Analise_Pacientes', index=False)
                
                # Aba com métricas temporais se disponível
                if 'TEMPO_ESTIMADO_HORAS' in df_filtered.columns:
                    tempo_resumo = df_filtered.groupby('GRUPO_EXAME')['TEMPO_ESTIMADO_HORAS'].agg(['mean', 'median', 'std']).round(2)
                    tempo_resumo.columns = ['Tempo_Medio_h', 'Tempo_Mediano_h', 'Desvio_Padrao_h']
                    tempo_resumo.to_excel(writer, sheet_name='Analise_Temporal')
                
                # Aba com dose por paciente
                dose_paciente_detalhada = df_filtered.groupby('PACIENTE_ID').agg({
                    'DOSE_ESTIMADA': 'sum',
                    'DATA_REALIZACAO': 'count',
                    'GRUPO_EXAME': lambda x: ', '.join(x.unique())
                }).round(2)
                dose_paciente_detalhada.columns = ['Dose_Total_mSv', 'Num_Exames', 'Grupos_Realizados']
                dose_paciente_detalhada.to_excel(writer, sheet_name='Dose_por_Paciente')
            
            output.seek(0)
            return output.getvalue()
        
        excel_data = create_excel_report()
        st.download_button(
            "📊 **Relatório Completo (Excel)**",
            excel_data,
            "relatorio_radiologico_completo.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    with col3:
        # Resumo executivo
        def create_executive_summary():
            summary = f"""
# RELATÓRIO EXECUTIVO - CENTRO RADIOLÓGICO

## 📊 RESUMO DO PERÍODO
**Período analisado:** {data_inicio} a {data_fim}
**Total de exames:** {total_exames:,}
**Pacientes únicos:** {total_pacientes:,}
**Média exames/paciente:** {exames_por_paciente:.1f}
**Média diária:** {media_diaria:.1f} exames

## 🏆 TOP 5 EXAMES MAIS REALIZADOS
"""
            top_5_exames = df_filtered['EXAME_NORM'].value_counts().head(5)
            for i, (exame, qtd) in enumerate(top_5_exames.items(), 1):
                pct = (qtd / total_exames) * 100
                summary += f"{i}. **{exame}**: {qtd:,} exames ({pct:.1f}%)\n"
            
            summary += f"""

## ☢️ RADIOPROTEÇÃO
**Dose total estimada:** {dose_total:.2f} mSv
**Dose média por exame:** {dose_media_exame:.3f} mSv
**Dose média por paciente:** {dose_media_paciente:.2f} mSv
**Exames com radiação:** {exames_com_dose:,} de {total_exames:,}
"""
            
            if 'pacientes_acima_limite' in locals() and len(pacientes_acima_limite) > 0:
                summary += f"**⚠️ Pacientes acima limite (1mSv):** {len(pacientes_acima_limite)}\n"
            
            if 'TEMPO_ESTIMADO_HORAS' in df_filtered.columns and not df_filtered['TEMPO_ESTIMADO_HORAS'].isna().all():
                tempo_medio_geral = df_filtered['TEMPO_ESTIMADO_HORAS'].mean()
                summary += f"""

## ⏱️ TEMPO DE RESPOSTA
**Tempo médio pedido→realização:** {tempo_medio_geral:.1f} horas
**Tempo mediano:** {df_filtered['TEMPO_ESTIMADO_HORAS'].median():.1f} horas
"""
            
            summary += f"""

## 📈 DISTRIBUIÇÃO POR GRUPO
"""
            dist_grupos = df_filtered['GRUPO_EXAME'].value_counts()
            for grupo, qtd in dist_grupos.items():
                pct = (qtd / total_exames) * 100
                summary += f"- **{grupo}**: {qtd:,} exames ({pct:.1f}%)\n"
            
            summary += f"""

## 🎯 INSIGHTS E RECOMENDAÇÕES
"""
            # Adiciona insights automáticos
            all_insights = []
            all_insights.extend(generate_insights(df_filtered, "volume"))
            all_insights.extend(generate_insights(df_filtered, "efficiency"))
            if 'TEMPO_ESTIMADO_HORAS' in df_filtered.columns:
                all_insights.extend(generate_insights(df_filtered, "temporal"))
            
            for insight in all_insights:
                summary += f"- {insight}\n"
            
            if not all_insights:
                summary += "- Operação dentro dos parâmetros normais\n"
                summary += "- Recomenda-se monitoramento contínuo\n"
            
            summary += f"""

## 📅 SAZONALIDADE
**Período de maior movimento:** {df_filtered.groupby(df_filtered['DATA_REALIZACAO'].dt.date).size().idxmax()}
**Dia da semana com mais exames:** {['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'][df_filtered['DIA_SEMANA'].mode().iloc[0]]}
**Período do dia preferencial:** {df_filtered['PERIODO_DIA'].mode().iloc[0]}

---
*Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y às %H:%M')}*
"""
            return summary
        
        summary_text = create_executive_summary()
        st.download_button(
            "📋 **Resumo Executivo (TXT)**",
            summary_text.encode('utf-8'),
            "resumo_executivo.txt",
            "text/plain"
        )

    # ---------------------------
    # Resumos Detalhados dos Gráficos
    # ---------------------------
    st.markdown("---")
    st.markdown("### 📋 **Resumos Detalhados dos Gráficos**")
    
    with st.expander("📊 **Interpretação dos Gráficos - Visão Geral**", expanded=False):
        st.markdown("""        
        **🔹 Distribuição por Grupo de Exame (Pizza):**
        - Mostra a proporção de cada tipo de exame realizado
        - Útil para identificar os principais serviços oferecidos
        - Cores diferentes facilitam a identificação visual
        - Hover mostra percentuais exatos
        
        **🔹 Top 10 Exames (Barras Horizontais):**
        - Lista os procedimentos mais frequentes em ordem decrescente
        - Permite identificar a demanda por tipo específico de exame
        - Barras horizontais facilitam a leitura de nomes longos
        - Essencial para planejamento de recursos e equipamentos
        
        **🔹 Evolução Diária (Linha Dupla):**
        - Gráfico superior: volume total de exames por dia
        - Gráfico inferior: número de pacientes únicos por dia
        - Identifica picos de demanda e sazonalidades
        - Útil para planejamento de escalas e recursos
        """)
    
    with st.expander("⏱️ **Interpretação dos Gráficos - Análise Temporal**", expanded=False):
        st.markdown("""        
        **🔹 Distribuição dos Tempos de Espera (Histograma):**
        - Mostra como os tempos de espera se distribuem
        - Linhas verticais indicam média (vermelha) e mediana (verde)
        - Concentração à esquerda indica tempos menores
        - Cauda longa à direita pode indicar casos problemáticos
        
        **🔹 Tempo por Grupo de Exame (Box Plot):**
        - Caixa central mostra 50% dos casos (quartis 1-3)
        - Linha central é a mediana
        - Pontos externos são outliers (casos extremos)
        - Permite comparar eficiência entre diferentes tipos de exame
        
        **🔹 Heatmap Hora vs Dia da Semana:**
        - Cores mais intensas = maior volume
        - Identifica horários de pico e baixa demanda
        - Essencial para otimização de recursos humanos
        - Azul mais escuro = maior concentração de exames
        """)
    
    with st.expander("👥 **Interpretação dos Gráficos - Análise de Pacientes**", expanded=False):
        st.markdown("""        
        **🔹 Distribuição Exames por Paciente (Barras):**
        - Mostra quantos pacientes fizeram 1, 2, 3... exames
        - Identifica padrões de reincidência
        - Maioria com 1 exame = baixa reincidência (normal)
        - Muitos com vários exames = alta reincidência ou casos complexos
        
        **🔹 Top 15 Pacientes (Barras Horizontais):**
        - Lista pacientes com mais exames no período
        - Cores indicam o exame mais comum para cada paciente
        - Útil para identificar casos que requerem atenção especial
        - Pode indicar tratamentos ou acompanhamentos específicos
        
        **🔹 Tabela Detalhada de Pacientes:**
        - **Total_Exames**: número total de exames do paciente
        - **Dias_Distintos**: em quantos dias diferentes fez exames
        - **Periodo_Dias**: intervalo entre primeiro e último exame
        - **Exame_Mais_Comum**: procedimento mais realizado
        - **Grupos_Diferentes**: diversidade de tipos de exame
        """)
    
    with st.expander("☢️ **Interpretação dos Gráficos - Radioproteção**", expanded=False):
        st.markdown("""        
        **🔹 Dose Total por Grupo (Barras Horizontais):**
        - Soma toda a radiação estimada por categoria
        - TC e Raio-X geralmente têm maiores valores
        - Ressonância e Ultrassom têm dose zero (sem radiação)
        - Importante para controle de exposição coletiva
        
        **🔹 Dose Média vs Quantidade (Dispersão/Bolhas):**
        - Eixo X: quantos exames deste tipo foram feitos
        - Eixo Y: dose média individual
        - Tamanho da bolha: dose total acumulada
        - Identifica exames de alta dose mas baixa frequência
        
        **🔹 Evolução Diária da Dose:**
        - Linha sólida: dose total diária
        - Linha tracejada: média móvel de 7 dias
        - Identifica tendências e picos de exposição
        - Útil para controle temporal da radioproteção
        
        **🔹 Alertas de Radioproteção:**
        - **Verde**: todos dentro dos limites
        - **Amarelo**: alguns pacientes acima de 1 mSv/ano
        - **Vermelho**: pacientes requerem investigação (>20 mSv)
        """)
    
    with st.expander("📈 **Interpretação dos Gráficos - Analytics Avançado**", expanded=False):
        st.markdown("""        
        **🔹 Matriz de Correlação:**
        - Cores azuis: correlação positiva (quando um sobe, outro sobe)
        - Cores vermelhas: correlação negativa (quando um sobe, outro desce)
        - Valores próximos a 1 ou -1: correlação forte
        - Valores próximos a 0: sem correlação
        
        **🔹 Dashboard de Tendências Mensais:**
        - **Superior esquerdo**: volume absoluto de exames por mês
        - **Superior direito**: número de pacientes únicos mensais
        - **Inferior esquerdo**: taxa de crescimento mensal (%)
        - **Inferior direito**: dose total mensal estimada
        
        **🔹 Utilização da Capacidade:**
        - 100% = dia de maior movimento (capacidade máxima)
        - Linha laranja (70%): limiar de baixa utilização
        - Linha vermelha (130%): possível sobrecarga
        - Identifica oportunidades e gargalos operacionais
        
        **🔹 Métricas de Previsão:**
        - Baseada em média móvel dos últimos 3 meses
        - Considera tendência de crescimento recente
        - Útil para planejamento de curto prazo
        - Seta verde/vermelha indica tendência positiva/negativa
        """) 

    # ---------------------------
    # Footer com informações técnicas
    # ---------------------------
    st.markdown("---")
    st.markdown(f"""
    <div style="text-align: center; padding: 2rem; background: #f8f9fa; border-radius: 10px; margin-top: 2rem;">
        <h4>🏥 Relatorio Analitico</h4>
        <p><strong>Desenvolvido para Centros de Diagnóstico por Imagem</strong></p>
        <p>
            📊 Análises avançadas | ☢️ Controle de radioproteção | ⏱️ Métricas temporais | 
            👥 Gestão de pacientes | 📈 Business Intelligence
        </p>
        <p style="font-size: 0.9em; color: #6c757d;">
            Dados processados: <strong>{len(df_filtered):,}</strong> registros | 
            Período: <strong>{data_inicio}</strong> a <strong>{data_fim}</strong> | 
            Última atualização: <strong>{datetime.now().strftime('%d/%m/%Y %H:%M')}</strong>
        </p>
    </div>
    """, unsafe_allow_html=True)

else:
    # ---------------------------
    # Página inicial quando não há arquivo
    # ---------------------------
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        <div style="text-align: center; padding: 3rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 15px; margin: 2rem 0;">
            <h2>🏥 Bem-vindo ao Dashboard Radiológico</h2>
            <p style="font-size: 1.2em;">Sistema Completo de Análise de Dados Radiológicos</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Instruções de uso
    st.markdown("### 🚀 **Como Começar**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        #### 📂 **1. Prepare seus dados**
        - Arquivo Excel (.xlsx ou .xls)
        - Dados de exames radiológicos
        - Colunas obrigatórias: DATA_REALIZACAO, EXAME
        - Colunas opcionais: PACIENTE, DATA_PEDIDO, etc.
        
        #### 🔧 **2. Configure os filtros**
        - Selecione período de análise
        - Escolha grupos de exame
        - Defina filtros específicos
        - Ajuste tema visual
        """)
    
    with col2:
        st.markdown("""
        #### 📊 **3. Explore as análises**
        - **Visão Geral**: métricas principais e distribuições
        - **Análise Temporal**: tempos de espera e sazonalidade
        - **Pacientes**: reincidência e jornadas
        - **Radioproteção**: doses e alertas de segurança
        - **Analytics**: correlações e previsões
        
        #### 📄 **4. Exporte resultados**
        - Dados filtrados (CSV)
        - Relatório completo (Excel multi-abas)
        - Resumo executivo (TXT)
        """)
    
    # Recursos destacados
    st.markdown("### ✨ **Recursos Principais**")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div class="metric-card">
            <h4>📊 Análises Inteligentes</h4>
            <ul>
                <li>Detecção automática de colunas</li>
                <li>Insights gerados automaticamente</li>
                <li>Correlações avançadas</li>
                <li>Previsões simples</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <div class="metric-card">
            <h4>☢️ Radioproteção</h4>
            <ul>
                <li>Cálculo de doses estimadas</li>
                <li>Alertas automáticos</li>
                <li>Controle por paciente</li>
                <li>Relatórios de segurança</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown("""
        <div class="metric-card">
            <h4>🎯 Interface Avançada</h4>
            <ul>
                <li>Design responsivo moderno</li>
                <li>Gráficos interativos</li>
                <li>Filtros dinâmicos</li>
                <li>Exportação completa</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    # Exemplo de estrutura de dados
    st.markdown("### 📋 **Estrutura de Dados Recomendada**")
    
    exemplo_df = pd.DataFrame({
        'ATEND': ['2024001', '2024002', '2024003'],
        'NOME_PACIENTE': ['João Silva', 'Maria Santos', 'Pedro Costa'],
        'DATA_PEDIDO': ['2024-01-15', '2024-01-16', '2024-01-17'],
        'DATA_REALIZACAO': ['2024-01-16', '2024-01-18', '2024-01-17'],
        'EXAME': ['RX TORAX PA', 'TC ABDOME', 'US ABDOME'],
        'ENCAMINHAMENTO': ['CLINICA GERAL', 'GASTRO', 'CLINICA GERAL'],
        'TECNICO': ['TEC001', 'TEC002', 'TEC001'],
        'MEDICO': ['DR. SILVA', 'DR. SANTOS', 'DR. SILVA'],
        'TEMPO_ESTIMADO': ['0.01:55:00', '1.00:45:02', '0.22:43:53']
    })
    
    st.dataframe(exemplo_df, use_container_width=True)
    st.caption("💡 Exemplo de estrutura de dados. O sistema detecta automaticamente variações nos nomes das colunas.")
    
    # Call to action
    st.markdown("""
    <div style="text-align: center; padding: 2rem; background: #e3f2fd; border-radius: 10px; margin: 2rem 0;">
        <h3>📤 Pronto para começar?</h3>
        <p style="font-size: 1.1em;">Faça upload do seu arquivo Excel usando o botão acima e descubra insights valiosos sobre seu centro radiológico!</p>
    </div>
    """, unsafe_allow_html=True)
