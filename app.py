import io
import os
import re
import time
import sqlite3
from datetime import datetime
from pathlib import Path
from google import genai
from google.genai import types
from PIL import Image
import pandas as pd
import streamlit as st
import anthropic
import fitz  # PyMuPDF para manipular PDFs
from dotenv import load_dotenv

# Força o carregamento do .env na mesma pasta do app.py
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path)
load_dotenv()

# --- CONFIGURAÇÃO INICIAL DA PÁGINA ---
st.set_page_config(
    page_title="DRX Terminal",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- CSS CUSTOMIZADO PARA ESTÉTICA INDUSTRIAL MODERNA & TECNOLÓGICA ---
st.markdown("""
    <style>
    .stApp {
        background-color: var(--background-color);
    }
    h1, h2, h3, h4 {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .stButton>button[kind="primary"] {
        border-radius: 8px;
        font-weight: 600;
        letter-spacing: 0.5px;
    }
    div[data-testid="stVerticalBlock"] > div[style*="border"] {
        border-radius: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- ÍCONES SVG TECNOLÓGICOS (SEM EMOJIS) ---
SVG_ICONS = {
    "terminal": '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>',
    "porao": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>',
    "armazem": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="7.5 4.21 12 6.81 16.5 4.21"></polyline><polyline points="7.5 19.79 7.5 14.6 3 12"></polyline><polyline points="21 12 16.5 14.6 16.5 19.79"></polyline><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line></svg>',
    "check": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>',
    "alert": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
}

# --- CONFIGURAÇÃO DO BANCO DE DADOS SQLITE ---
DB_NAME = "historico_conferencias.db"

def inicializar_banco():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conferencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT,
            navio TEXT,
            operador TEXT,
            status TEXT,
            coil_no TEXT,
            item TEXT,
            cliente TEXT,
            bl TEXT,
            produto TEXT,
            peso_liq_t TEXT,
            peso_brut_t TEXT,
            destino TEXT
        )
    ''')
    conn.commit()
    conn.close()

inicializar_banco()

# --- SISTEMA DE SENHA DE ACESSO ---
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False

if not st.session_state["autenticado"]:
    st.markdown("""
        <div style='text-align: center; padding: 3rem 1rem;'>
            <h2 style='color: #38bdf8; font-family: monospace;'>DRX TERMINAL</h2>
            <p style='color: #94a3b8;'>Controle de Acesso Restrito</p>
        </div>
    """, unsafe_allow_html=True)
    
    col_auth1, col_auth2, col_auth3 = st.columns([1, 2, 1])
    with col_auth2:
        senha_digitada = st.text_input("Senha do Sistema:", type="password", key="input_senha_restrita")
        if st.button("Autenticar Acesso", type="primary", width='stretch'):
            if senha_digitada == "porto2026":
                st.session_state["autenticado"] = True
                st.rerun()
            else:
                st.error("Senha incorreta.")
    st.stop()

PASTA_NAVIOS = "navios"
os.makedirs(PASTA_NAVIOS, exist_ok=True)

def ler_etiqueta_com_ia(imagem_pil):
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    max_largura = 1000
    if imagem_pil.width > max_largura:
        proporcao = max_largura / float(imagem_pil.width)
        nova_altura = int(float(imagem_pil.height) * proporcao)
        imagem_pil = imagem_pil.resize(
            (max_largura, nova_altura), Image.Resampling.LANCZOS
        )

    buffered = io.BytesIO()
    imagem_pil.save(buffered, format="JPEG", quality=80)
    img_bytes = buffered.getvalue()

    prompt = (
        "Analise esta etiqueta de aço de navio/siderurgia. "
        "Localize o código de identificação principal da bobina (frequentemente "
        "identificado como COIL NO, PROD NO, ID, ou um código alfanumérico longo). "
        "Retorne APENAS o código completo da bobina, sem nenhum texto adicional, "
        "explicações ou pontuação."
    )

    if gemini_key:
        client_gemini = genai.Client(api_key=gemini_key)
        modelos_gemini = ["gemini-2.5-flash", "gemini-2.0-flash-lite"]

        for modelo in modelos_gemini:
            for tentativa in range(2):
                try:
                    response = client_gemini.models.generate_content(
                        model=modelo,
                        contents=[
                            types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                            prompt,
                        ],
                    )
                    if response and response.text:
                        codigo_extraido = response.text.strip().upper()
                        if codigo_extraido:
                            return (
                                codigo_extraido.replace(" ", "")
                                .replace("\n", "")
                                .replace('"', "")
                            )
                except Exception:
                    time.sleep(1)
                    continue

    if anthropic_key:
        try:
            import base64
            client_claude = anthropic.Anthropic(api_key=anthropic_key)
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")

            message = client_claude.messages.create(
                model="claude-haiku-4-5",
                max_tokens=100,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": img_base64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )

            if message.content and message.content[0].text:
                codigo_extraido = message.content[0].text.strip().upper()
                if codigo_extraido:
                    return (
                        codigo_extraido.replace(" ", "")
                        .replace("\n", "")
                        .replace('"', "")
                    )
        except Exception:
            pass

    return None

def salvar_historico(dados_conferencia):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO conferencias (
            data_hora, navio, operador, status, coil_no, item, cliente, bl, produto, peso_liq_t, peso_brut_t, destino
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        dados_conferencia.get("DATA_HORA"),
        dados_conferencia.get("NAVIO"),
        dados_conferencia.get("OPERADOR"),
        dados_conferencia.get("STATUS"),
        dados_conferencia.get("COIL_NO"),
        dados_conferencia.get("ITEM"),
        dados_conferencia.get("CLIENTE"),
        dados_conferencia.get("BL"),
        dados_conferencia.get("PRODUTO"),
        dados_conferencia.get("PESO_LIQ_T"),
        dados_conferencia.get("PESO_BRUT_T"),
        dados_conferencia.get("DESTINO")
    ))
    conn.commit()
    conn.close()

# --- FUNÇÃO AUXILIAR SEGURA PARA BUSCAR COLUNAS POR PALAVRAS-CHAVE ---
def get_val(df_row, keywords):
    for col in df_row.index:
        col_str = str(col).upper()
        if any(k in col_str for k in keywords):
            val = df_row[col]
            if pd.notna(val):
                return str(val)
    return 'N/A'

# --- CONTROLE DE ESTADO DAS TELAS ---
if "modo" not in st.session_state:
    st.session_state.modo = "Home"

if "bobinas_conferidas_sessao" not in st.session_state:
    st.session_state["bobinas_conferidas_sessao"] = []

# ==========================================
# 1. TELA DE ESCOLHA (HOME)
# ==========================================
if st.session_state.modo == "Home":
    st.markdown(f"""
        <div style='text-align: center; padding: 2.5rem 0 1rem 0;'>
            <div style='display: flex; justify-content: center; align-items: center; gap: 8px;'>
                {SVG_ICONS["terminal"]}
                <h1 style='color: #38bdf8; font-family: monospace; letter-spacing: 2px; margin-bottom: 0; font-size: 1.6rem;'>DRX TERMINAL</h1>
            </div>
            <p style='color: #94a3b8; font-size: 0.85rem; margin-top: 6px;'>Sistema de Conferência e Identificação Portuária</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    st.markdown("### Selecione o Módulo Operacional")
    
    col_h1, col_h2 = st.columns(2)
    
    with col_h1:
        with st.container(border=True):
            st.markdown(f"<div style='display: flex; align-items: center; gap: 6px;'>{SVG_ICONS['porao']}<h4>Porão</h4></div>", unsafe_allow_html=True)
            st.write("Consulta rápida por foto única direto com o manifesto ativo.")
            st.write("")
            if st.button("Acessar Porão", type="primary", width='stretch', key="nav_porao"):
                st.session_state.modo = "Porao"
                st.rerun()
                
    with col_h2:
        with st.container(border=True):
            st.markdown(f"<div style='display: flex; align-items: center; gap: 6px;'>{SVG_ICONS['armazem']}<h4>Armazém</h4></div>", unsafe_allow_html=True)
            st.write("Recebimento em lote, múltiplos arquivos e relatórios.")
            st.write("")
            if st.button("Acessar Armazém", type="primary", width='stretch', key="nav_armazem"):
                st.session_state.modo = "Armazem"
                st.rerun()

    st.markdown("---")
    st.caption("DRX SOLUTIONS")

# ==========================================
# 2. MODO PORÃO (CONSULTA RÁPIDA)
# ==========================================
elif st.session_state.modo == "Porao":
    col_voltar, col_titulo = st.columns([1, 4])
    with col_voltar:
        if st.button("Menu", width='stretch'):
            st.session_state.modo = "Home"
            st.rerun()
    with col_titulo:
        st.markdown("<h3 style='margin: 0; color: #38bdf8; font-size: 1.1rem; padding-top: 6px;'>MÓDULO PORÃO</h3>", unsafe_allow_html=True)

    st.markdown("---")

    arquivos_excel = [f.replace(".xlsx", "") for f in os.listdir(PASTA_NAVIOS) if f.endswith(".xlsx")]

    if not arquivos_excel:
        st.warning("Nenhum manifesto Excel encontrado na pasta 'navios'.")
    else:
        with st.container(border=True):
            navio_selecionado = st.selectbox("Manifesto Ativo:", arquivos_excel)
            caminho_excel = os.path.join(PASTA_NAVIOS, f"{navio_selecionado}.xlsx")
            operador = st.text_input("Operador Responsável / Porão:", value="Porão 1")

        st.markdown("#### Captura de Etiqueta")
        with st.container(border=True):
            foto_upload = st.file_uploader("Carregar foto da etiqueta", type=["jpg", "jpeg", "png"], label_visibility="collapsed", key="up_porao")

            if foto_upload:
                img_porao = Image.open(foto_upload)
                st.image(img_porao, caption="Etiqueta Capturada", width='stretch')

                if st.button("Processar Leitura Inteligente", type="primary", width='stretch'):
                    with st.spinner("Analisando imagem com IA..."):
                        codigo_lido = ler_etiqueta_com_ia(img_porao)
                        st.session_state["codigo_porao_sugerido"] = codigo_lido if codigo_lido else ""

        codigo_inicial = st.session_state.get("codigo_porao_sugerido", "")
        
        with st.container(border=True):
            codigo_digitado = st.text_input("Código da Bobina (Confirmar ou Ajustar):", value=codigo_inicial, placeholder="Ex: 97CE6739A")

        if codigo_digitado.strip():
            df = pd.read_excel(caminho_excel)
            if "ITEM" in df.iloc[0].values.astype(str) or any("COIL" in str(val).upper() for val in df.iloc[0].values):
                df.columns = df.iloc[0]
                df = df[1:].reset_index(drop=True)

            colunas_possiveis = [c for c in df.columns if c and ("COIL" in str(c).upper() or "BOBINA" in str(c).upper() or "PROD" in str(c).upper())]
            
            if colunas_possiveis:
                col_coil = colunas_possiveis[0]
                
                def norm(t):
                    return re.sub(r"[^A-Z0-9]", "", str(t).upper())

                df["NORM"] = df[col_coil].apply(norm)
                alvo = norm(codigo_digitado)

                match = df[df["NORM"] == alvo]

                if not match.empty:
                    linha = match.iloc[0]
                    
                    item_val = get_val(linha, ['ITEM'])
                    cliente_val = get_val(linha, ['CLIENTE'])
                    bl_val = get_val(linha, ['BL'])
                    produto_val = get_val(linha, ['PRODUTO', 'DESC', 'MATERIAL'])
                    peso_liq = get_val(linha, ['LIQ', 'LÍQ'])
                    peso_brut = get_val(linha, ['BRUT', 'BRUTO'])
                    destino_val = get_val(linha, ['DESTINO', 'PORTO'])

                    st.markdown(f"""
                        <div style="display: flex; align-items: center; gap: 8px; background: rgba(34, 197, 94, 0.1); padding: 10px; border-radius: 6px; border: 1px solid #22c55e; margin-bottom: 10px;">
                            {SVG_ICONS['check']} <span style="color: #22c55e; font-weight: 600;">Bobina encontrada no Manifesto!</span>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    with st.container(border=True):
                        st.markdown(f"**Item:** {item_val}")
                        st.markdown(f"**Cliente:** {cliente_val}")
                        st.markdown(f"**BL:** {bl_val}")
                        st.markdown(f"**Produto:** {produto_val}")
                        st.markdown(f"**Peso Líq:** {peso_liq} t")
                        st.markdown(f"**Peso Brut:** {peso_brut} t")
                        st.markdown(f"**Destino:** {destino_val}")

                    salvar_historico({
                        "DATA_HORA": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "NAVIO": navio_selecionado,
                        "OPERADOR": operador,
                        "STATUS": "OK",
                        "COIL_NO": str(linha.get(col_coil, codigo_digitado)),
                        "ITEM": item_val,
                        "CLIENTE": cliente_val,
                        "BL": bl_val,
                        "PRODUTO": produto_val,
                        "PESO_LIQ_T": peso_liq,
                        "PESO_BRUT_T": peso_brut,
                        "DESTINO": destino_val
                    })
                else:
                    st.markdown(f"""
                        <div style="display: flex; align-items: center; gap: 8px; background: rgba(239, 68, 68, 0.1); padding: 10px; border-radius: 6px; border: 1px solid #ef4444; margin-bottom: 10px;">
                            {SVG_ICONS['alert']} <span style="color: #ef4444; font-weight: 600;">Divergência: Código não localizado no manifesto!</span>
                        </div>
                    """, unsafe_allow_html=True)

# ==========================================
# 3. MODO ARMAZÉM (MÚLTIPLOS LOTES)
# ==========================================
elif st.session_state.modo == "Armazem":
    col_voltar, col_titulo = st.columns([1, 4])
    with col_voltar:
        if st.button("Menu", width='stretch'):
            st.session_state.modo = "Home"
            st.rerun()
    with col_titulo:
        st.markdown("<h3 style='margin: 0; color: #38bdf8; font-size: 1.1rem; padding-top: 6px;'>MÓDULO ARMAZÉM</h3>", unsafe_allow_html=True)

    st.markdown("---")

    arquivos_navios_disp = [f.replace(".xlsx", "").replace(".pdf", "") for f in os.listdir(PASTA_NAVIOS) if f.endswith((".xlsx", ".pdf"))]
    arquivos_navios_disp = sorted(list(set(arquivos_navios_disp)))

    if not arquivos_navios_disp:
        st.warning("Nenhum manifesto encontrado na pasta 'navios'.")
    else:
        with st.container(border=True):
            navio_sel = st.selectbox("Manifesto do Armazém:", arquivos_navios_disp)
            op_armazem = st.text_input("Operador Responsável:", value="Armazém 1")

        st.markdown("#### Envio de Lotes de Fotos")
        with st.container(border=True):
            fotos_lote = st.file_uploader(
                "Selecionar fotos das etiquetas",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=True,
                key="fotos_lote_armazem"
            )

            if fotos_lote and st.button("Processar e Adicionar Lote de Fotos", type="primary", width='stretch'):
                caminho_planilha = os.path.join(PASTA_NAVIOS, f"{navio_sel}.xlsx")
                
                if os.path.exists(caminho_planilha):
                    df_manifesto = pd.read_excel(caminho_planilha)
                    if "ITEM" in df_manifesto.iloc[0].values.astype(str) or any("COIL" in str(val).upper() for val in df_manifesto.iloc[0].values):
                        df_manifesto.columns = df_manifesto.iloc[0]
                        df_manifesto = df_manifesto[1:].reset_index(drop=True)

                    col_c = [c for c in df_manifesto.columns if c and ("COIL" in str(c).upper() or "BOBINA" in str(c).upper() or "PROD" in str(c).upper())]
                    col_coil_manifesto = col_c[0] if col_c else df_manifesto.columns[0]

                    def normalizar_str(t):
                        return re.sub(r"[^A-Z0-9]", "", str(t).upper())

                    df_manifesto["NORM"] = df_manifesto[col_coil_manifesto].apply(normalizar_str)

                    with st.spinner(f"Processando {len(fotos_lote)} etiquetas..."):
                        for f_item in fotos_lote:
                            img_lote = Image.open(f_item)
                            codigo_extraido = ler_etiqueta_com_ia(img_lote)

                            if codigo_extraido:
                                norm_ext = normalizar_str(codigo_extraido)
                                match_lote = df_manifesto[df_manifesto["NORM"] == norm_ext]

                                if not match_lote.empty:
                                    row = match_lote.iloc[0]
                                    item_val = get_val(row, ['ITEM'])
                                    cliente_val = get_val(row, ['CLIENTE'])
                                    bl_val = get_val(row, ['BL'])
                                    produto_val = get_val(row, ['PRODUTO', 'DESC', 'MATERIAL'])
                                    peso_liq_lote = get_val(row, ['LIQ', 'LÍQ'])
                                    peso_brut_lote = get_val(row, ['BRUT', 'BRUTO'])
                                    destino_val = get_val(row, ['DESTINO', 'PORTO'])
                                    
                                    item_dados = {
                                        "COIL_NO": str(row.get(col_coil_manifesto, codigo_extraido)),
                                        "ITEM": item_val,
                                        "CLIENTE": cliente_val,
                                        "BL": bl_val,
                                        "PRODUTO": produto_val,
                                        "PESO_LIQ_T": peso_liq_lote,
                                        "PESO_BRUT_T": peso_brut_lote,
                                        "DESTINO": destino_val,
                                        "STATUS": "OK"
                                    }
                                else:
                                    item_dados = {
                                        "COIL_NO": codigo_extraido,
                                        "ITEM": "N/A",
                                        "CLIENTE": "Não Encontrado",
                                        "BL": "N/A",
                                        "PRODUTO": "N/A",
                                        "PESO_LIQ_T": "N/A",
                                        "PESO_BRUT_T": "N/A",
                                        "DESTINO": "N/A",
                                        "STATUS": "DIVERGENTE"
                                    }
                                
                                st.session_state["bobinas_conferidas_sessao"].append(item_dados)
                                
                                salvar_historico({
                                    "DATA_HORA": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "NAVIO": navio_sel,
                                    "OPERADOR": op_armazem,
                                    "STATUS": item_dados["STATUS"],
                                    "COIL_NO": item_dados["COIL_NO"],
                                    "ITEM": item_dados["ITEM"],
                                    "CLIENTE": item_dados["CLIENTE"],
                                    "BL": item_dados["BL"],
                                    "PRODUTO": item_dados["PRODUTO"],
                                    "PESO_LIQ_T": item_dados["PESO_LIQ_T"],
                                    "PESO_BRUT_T": item_dados["PESO_BRUT_T"],
                                    "DESTINO": item_dados["DESTINO"]
                                })
                else:
                    st.error("Planilha Excel do manifesto não encontrada para este navio.")

        if st.session_state["bobinas_conferidas_sessao"]:
            st.markdown(f"#### Total Acumulado: {len(st.session_state['bobinas_conferidas_sessao'])} Bobinas")
            
            df_sessao = pd.DataFrame(st.session_state["bobinas_conferidas_sessao"])
            st.dataframe(df_sessao, width='stretch')

            col_limp, col_gerar = st.columns(2)
            with col_limp:
                if st.button("Limpar Lista", width='stretch'):
                    st.session_state["bobinas_conferidas_sessao"] = []
                    st.rerun()
            with col_gerar:
                if st.button("Gerar Relatório Final", type="primary", width='stretch'):
                    st.session_state["gerar_relatorio_final"] = True

            if st.session_state.get("gerar_relatorio_final", False):
                st.markdown("---")
                st.markdown("### RELATÓRIO FINAL DA OPERAÇÃO")
                
                with st.container(border=True):
                    st.markdown(f"**Navio/Lote:** {navio_sel}")
                    st.markdown(f"**Operador:** {op_armazem}")
                    st.markdown(f"**Total Conferido:** {len(df_sessao)}")

                    if "CLIENTE" in df_sessao.columns and "BL" in df_sessao.columns:
                        resumo = df_sessao.groupby(["CLIENTE", "BL"]).size().reset_index(name="QUANTIDADE")
                        st.markdown("#### Resumo por Cliente e BL:")
                        st.dataframe(resumo, width='stretch')

                caminho_pdf_original = os.path.join(PASTA_NAVIOS, f"{navio_sel}.pdf")
                if os.path.exists(caminho_pdf_original):
                    doc = fitz.open(caminho_pdf_original)
                    lista_norm_conferidas = [re.sub(r"[^A-Z0-9]", "", str(c).upper()) for c in df_sessao["COIL_NO"]]

                    for page in doc:
                        for termo in lista_norm_conferidas:
                            if len(termo) > 3:
                                areas = page.search_for(termo)
                                for rect in areas:
                                    annot = page.add_highlight_annot(rect)
                                    annot.set_colors(stroke=[0, 1, 0])
                                    annot.update()

                    pdf_bytes_out = doc.tobytes()
                    doc.close()

                    st.download_button(
                        label="Baixar PDF Marcado (Conferido)",
                        data=pdf_bytes_out,
                        file_name=f"manifesto_marcado_{navio_sel}.pdf",
                        mime="application/pdf",
                        type="primary",
                        width='stretch'
                    )

            st.markdown("---")
            if st.button("Iniciar Nova Operação (Zerar Tudo)", width='stretch'):
                st.session_state["bobinas_conferidas_sessao"] = []
                st.session_state["gerar_relatorio_final"] = False
                st.rerun()