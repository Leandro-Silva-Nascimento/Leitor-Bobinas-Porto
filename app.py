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
from dotenv import load_dotenv

# Força o carregamento do .env na mesma pasta do app.py
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path)
load_dotenv()

# --- CONFIGURAÇÃO INICIAL DA PÁGINA ---
st.set_page_config(
    page_title="DRX Bobinas",
    page_icon="📦",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- INJEÇÃO DE HTML PARA O PWA E IDENTIDADE VISUAL ---
st.markdown(
    """
    <link rel="manifest" href="/app/static/manifest.json">
    <meta name="theme-color" content="#4a148c">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="DRX Bobinas">
    """,
    unsafe_allow_html=True,
)

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
    st.markdown("<h2>🔒 Acesso Restrito - Conferência</h2>", unsafe_allow_html=True)
    senha_digitada = st.text_input("Digite a senha do sistema:", type="password")
    if st.button("Entrar"):
        if senha_digitada == "porto2026":
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta!")
    st.stop()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
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

# --- CONTROLE DE ESTADO DAS TELAS ---
if "modo" not in st.session_state:
    st.session_state.modo = "Home"

if "bobinas_conferidas_sessao" not in st.session_state:
    st.session_state["bobinas_conferidas_sessao"] = []

# ==========================================
# 1. TELA DE ESCOLHA (HOME)
# ==========================================
if st.session_state.modo == "Home":
    st.title("DRX - SISTEMA DE IDENTIFICAÇÃO DE BOBINAS")
    st.markdown("---")
    st.markdown("### Selecione o modo de operação para começar:")

    col1, col2 = st.columns(2)

    with col1:
        st.info(
            "**🔍 Consulta Rápida (Porão)**\n\n• Leitura de foto única\n• Consulta com o manifesto do navio"
        )
        if st.button("Entrar no Modo Porão", type="primary", use_container_width=True):
            st.session_state.modo = "Porao"
            st.rerun()

    with col2:
        st.success(
            "**📦 Conferência de Armazém**\n\n• Envio de fotos em bloco\n• Relatório final por Cliente e BL"
        )
        if st.button("Entrar no Modo Armazém", type="primary", use_container_width=True):
            st.session_state.modo = "Armazem"
            st.rerun()

# ==========================================
# 2. MODO PORÃO
# ==========================================
elif st.session_state.modo == "Porao":
    if st.button("⬅️ Voltar ao Menu Principal"):
        st.session_state.modo = "Home"
        st.rerun()

    st.markdown("---")
    st.markdown(
        "<h2 style='font-family: monospace; letter-spacing: 2px; color: #38bdf8; text-transform: uppercase;'>IDENTIFICAÇÃO DE BOBINAS - DRX (PORÃO)</h2>",
        unsafe_allow_html=True,
    )

    arquivos_navios = [
        f.replace(".xlsx", "") for f in os.listdir(PASTA_NAVIOS) if f.endswith(".xlsx")
    ]

    if not arquivos_navios:
        st.warning("Nenhum manifesto de navio encontrado na pasta navios.")
    else:
        navio_selecionado = st.selectbox("Manifesto Ativo:", arquivos_navios)
        caminho_excel_ativo = os.path.join(PASTA_NAVIOS, f"{navio_selecionado}.xlsx")

        st.markdown("---")
        operador = st.text_input("Porão:", value="Porão 1", key="operador_porao")

        st.markdown("### Leitura de Etiqueta")
        foto_upload = st.file_uploader(
            "Carregar imagem da etiqueta",
            type=["jpg", "jpeg", "png"],
            label_visibility="collapsed",
            key="foto_porao"
        )

        if foto_upload is not None:
            image = Image.open(foto_upload)
            st.image(image, caption="Etiqueta Capturada", use_container_width=True)

            if st.button("Executar Leitura Inteligente", type="primary"):
                with st.spinner("Processando imagem..."):
                    codigo_lido_ia = ler_etiqueta_com_ia(image)
                    st.session_state["codigo_sugerido"] = codigo_lido_ia if codigo_lido_ia else ""

        codigo_sugerido_inicial = st.session_state.get("codigo_sugerido", "")

        st.markdown("### Código da Bobina:")
        codigo_final_digitado = st.text_input(
            "Confirme ou ajuste o código:",
            value=codigo_sugerido_inicial,
            placeholder="Ex: 97CE6739A",
            label_visibility="collapsed",
            key="input_codigo_porao"
        )

        if codigo_final_digitado.strip():
            df = pd.read_excel(caminho_excel_ativo)
            if "ITEM" in df.iloc[0].values or any("COIL" in str(val).upper() for val in df.iloc[0].values):
                df.columns = df.iloc[0]
                df = df[1:].reset_index(drop=True)

            colunas_possiveis = [
                col for col in df.columns if col and ("COIL" in str(col).upper() or "BOBINA" in str(col).upper() or "PROD" in str(col).upper())
            ]
            if colunas_possiveis:
                coluna_coil = colunas_possiveis[0]

                def normalizar(t):
                    return re.sub(r"[^A-Z0-9]", "", str(t).upper())

                df["COIL_NORMALIZADO"] = df[coluna_coil].apply(normalizar)
                codigo_alvo_norm = normalizar(codigo_final_digitado)

                bobina_encontrada = None
                codigo_confirmado = ""

                for index, linha in df.iterrows():
                    codigo_real = linha["COIL_NORMALIZADO"]
                    if codigo_real and (codigo_real == codigo_alvo_norm or codigo_alvo_norm in codigo_real or codigo_real in codigo_alvo_norm):
                        bobina_encontrada = linha
                        codigo_confirmado = linha[coluna_coil]
                        break

                if bobina_encontrada is not None:
                    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    item = str(bobina_encontrada.get("ITEM", "N/A"))
                    cliente = str(bobina_encontrada.get("CLIENTE", "N/A"))
                    bl = str(bobina_encontrada.get("BL", "N/A"))

                    col_prod = next((c for c in df.columns if c and ("GRADE" in str(c).upper() or "PROD" in str(c).upper() or "COATING" in str(c).upper())), "N/A")
                    produto = str(bobina_encontrada.get(col_prod, "N/A"))

                    col_peso_liq = next((c for c in df.columns if c and ("LIQ" in str(c).upper())), "N/A")
                    peso_liq = str(bobina_encontrada.get(col_peso_liq, "N/A"))

                    col_peso_brut = next((c for c in df.columns if c and ("BRUT" in str(c).upper())), "N/A")
                    peso_brut = str(bobina_encontrada.get(col_peso_brut, "N/A"))

                    col_destino = next((c for c in df.columns if c and ("DESTINO" in str(c).upper() or "DEST" in str(c).upper())), "N/A")
                    destino = str(bobina_encontrada.get(col_destino, "N/A"))

                    st.success("STATUS: VALIDADO")
                    st.code(codigo_confirmado, language="text")

                    st.markdown(f"**Manifesto:** {navio_selecionado}")
                    st.markdown(f"**Item:** {item} | **BL:** {bl}")
                    st.markdown(f"**Cliente:** {cliente}")
                    st.markdown(f"**Destino:** {destino}")
                    st.markdown(f"**Peso Líq:** {peso_liq}t | **Peso Brut:** {peso_brut}t")

                    chave_cache_hist = f"{navio_selecionado}_{codigo_final_digitado.strip()}"
                    if "ultimo_salvo" not in st.session_state or st.session_state["ultimo_salvo"] != chave_cache_hist:
                        registro = {
                            "DATA_HORA": data_hora,
                            "NAVIO": navio_selecionado,
                            "OPERADOR": operador,
                            "STATUS": "CONFERIDO",
                            "COIL_NO": codigo_confirmado,
                            "ITEM": item,
                            "CLIENTE": cliente,
                            "BL": bl,
                            "PRODUTO": produto,
                            "PESO_LIQ_T": peso_liq,
                            "PESO_BRUT_T": peso_brut,
                            "DESTINO": destino,
                        }
                        salvar_historico(registro)
                        st.session_state["ultimo_salvo"] = chave_cache_hist
                else:
                    st.error("STATUS: DIVERGÊNCIA")
                    st.markdown("O código informado não foi localizado no manifesto ativo.")

# ==========================================
# 3. MODO ARMAZÉM
# ==========================================
elif st.session_state.modo == "Armazem":
    if st.button("⬅️ Voltar ao Menu Principal"):
        st.session_state.modo = "Home"
        st.rerun()

    st.markdown("---")
    st.title("📦 Modo: Conferência de Armazém (Múltiplos Lotes)")

    if "bobinas_conferidas_sessao" not in st.session_state:
        st.session_state["bobinas_conferidas_sessao"] = []
    if "gerar_relatorio_final" not in st.session_state:
        st.session_state["gerar_relatorio_final"] = False

    arquivos_navios = [
        f.replace(".xlsx", "").replace(".pdf", "") for f in os.listdir(PASTA_NAVIOS) if f.endswith((".xlsx", ".pdf"))
    ]
    arquivos_navios = sorted(list(set(arquivos_navios)))

    if not arquivos_navios:
        st.warning("Nenhum manifesto (.xlsx ou .pdf) encontrado na pasta 'navios'. Adicione o manifesto na pasta do sistema.")
    else:
        navio_selecionado = st.selectbox("Selecione o Manifesto / Navio do Armazém:", arquivos_navios, key="sel_navio_armazem")
        
        caminho_excel = os.path.join(PASTA_NAVIOS, f"{navio_selecionado}.xlsx")
        caminho_pdf = os.path.join(PASTA_NAVIOS, f"{navio_selecionado}.pdf")

        df_manifesto = None
        if os.path.exists(caminho_excel):
            df_manifesto = pd.read_excel(caminho_excel)
            if "ITEM" in df_manifesto.iloc[0].values or any("COIL" in str(val).upper() for val in df_manifesto.iloc[0].values):
                df_manifesto.columns = df_manifesto.iloc[0]
                df_manifesto = df_manifesto[1:].reset_index(drop=True)
        elif os.path.exists(caminho_pdf):
            import pdfplumber
            with pdfplumber.open(caminho_pdf) as pdf:
                dados_tabela = []
                for pagina in pdf.pages:
                    t = pagina.extract_table()
                    if t:
                        dados_tabela.extend(t)
                if dados_tabela:
                    df_manifesto = pd.DataFrame(dados_tabela[1:], columns=dados_tabela[0])

        operador_armazem = st.text_input("Operador Responsável:", value="Armazém 1", key="op_armazem_lote")

        st.markdown("---")
        st.subheader("📸 Envio de Lotes de Fotos")
        st.info("💡 Você pode enviar fotos em vários blocos/lotes seguidos. O sistema irá somar todas as bobinas na lista da operação atual.")
        
        fotos_lote = st.file_uploader(
            "Selecione as fotos das etiquetas para este lote:",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="fotos_lote_armazem"
        )

        if fotos_lote:
            if st.button("🚀 Processar e Adicionar Lote de Fotos", type="primary", width="stretch"):
                with st.spinner("Lendo etiquetas e cruzando com o manifesto..."):
                    
                    def normalizar(t):
                        return re.sub(r"[^A-Z0-9]", "", str(t).upper())

                    coluna_coil = None
                    if df_manifesto is not None:
                        colunas_possiveis = [
                            col for col in df_manifesto.columns if col and ("COIL" in str(col).upper() or "BOBINA" in str(col).upper() or "PROD" in str(col).upper())
                        ]
                        if colunas_possiveis:
                            coluna_coil = colunas_possiveis[0]
                            df_manifesto["COIL_NORMALIZADO"] = df_manifesto[coluna_coil].apply(normalizar)

                    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    for foto in fotos_lote:
                        img = Image.open(foto)
                        codigo_lido = ler_etiqueta_com_ia(img)
                        
                        if not codigo_lido:
                            continue

                        dados_bobina = {
                            "DATA_HORA": data_hora,
                            "NAVIO": navio_selecionado,
                            "OPERADOR": operador_armazem,
                            "STATUS": "CONFERIDO",
                            "COIL_NO": codigo_lido,
                            "ITEM": "N/A",
                            "CLIENTE": "N/A",
                            "BL": "N/A",
                            "PRODUTO": "N/A",
                            "PESO_LIQ_T": "N/A",
                            "PESO_BRUT_T": "N/A",
                            "DESTINO": "N/A"
                        }

                        if df_manifesto is not None and coluna_coil:
                            codigo_alvo_norm = normalizar(codigo_lido)
                            encontrado = None
                            for _, linha in df_manifesto.iterrows():
                                val_norm = linha["COIL_NORMALIZADO"]
                                if val_norm and (val_norm == codigo_alvo_norm or codigo_alvo_norm in val_norm or val_norm in codigo_alvo_norm):
                                    encontrado = linha
                                    break
                            
                            if encontrado is not None:
                                dados_bobina["COIL_NO"] = encontrado.get(coluna_coil, codigo_lido)
                                dados_bobina["ITEM"] = str(encontrado.get("ITEM", "N/A"))
                                dados_bobina["CLIENTE"] = str(encontrado.get("CLIENTE", "N/A"))
                                dados_bobina["BL"] = str(encontrado.get("BL", "N/A"))
                                col_prod = next((c for c in df_manifesto.columns if c and ("GRADE" in str(c).upper() or "PROD" in str(c).upper())), "N/A")
                                dados_bobina["PRODUTO"] = str(encontrado.get(col_prod, "N/A"))
                                col_liq = next((c for c in df_manifesto.columns if c and ("LIQ" in str(c).upper())), "N/A")
                                dados_bobina["PESO_LIQ_T"] = str(encontrado.get(col_liq, "N/A"))
                                col_brut = next((c for c in df_manifesto.columns if c and ("BRUT" in str(c).upper())), "N/A")
                                dados_bobina["PESO_BRUT_T"] = str(encontrado.get(col_brut, "N/A"))
                                col_dest = next((c for c in df_manifesto.columns if c and ("DESTINO" in str(c).upper())), "N/A")
                                dados_bobina["DESTINO"] = str(encontrado.get(col_dest, "N/A"))

                        if not any(b["COIL_NO"] == dados_bobina["COIL_NO"] for b in st.session_state["bobinas_conferidas_sessao"]):
                            st.session_state["bobinas_conferidas_sessao"].append(dados_bobina)
                            salvar_historico(dados_bobina)

                    st.success("Lote processado! As bobinas foram acumuladas na operação atual.")
                    st.rerun()

        if st.session_state["bobinas_conferidas_sessao"]:
            st.markdown("---")
            st.subheader(f"📋 Total Acumulado na Operação: {len(st.session_state['bobinas_conferidas_sessao'])} Bobinas")
            
            df_sessao = pd.DataFrame(st.session_state["bobinas_conferidas_sessao"])
            st.dataframe(df_sessao[["COIL_NO", "CLIENTE", "BL", "DESTINO", "PESO_LIQ_T"]], width="stretch")

            st.markdown("---")
            col_bt1, col_bt2 = st.columns(2)
            
            with col_bt1:
                if st.button("🗑️ Limpar Lista da Operação", width="stretch"):
                    st.session_state["bobinas_conferidas_sessao"] = []
                    st.session_state["gerar_relatorio_final"] = False
                    st.rerun()

            with col_bt2:
                if st.button("📊 Gerar Relatório e Marcar PDF em Verde", type="primary", width="stretch"):
                    st.session_state["gerar_relatorio_final"] = True

        if st.session_state.get("gerar_relatorio_final", False):
            st.markdown("---")
            st.markdown("## 📑 RELATÓRIO FINAL DA OPERAÇÃO")
            
            df_op = pd.DataFrame(st.session_state["bobinas_conferidas_sessao"])
            
            st.markdown(f"**Navio / Lote:** {navio_selecionado}")
            st.markdown(f"**Operador:** {operador_armazem}")
            st.markdown(f"**Total de Bobinas Conferidas:** {len(df_op)}")
            
            st.markdown("### 📊 Resumo Separado por Cliente e BL:")
            if not df_op.empty and "CLIENTE" in df_op.columns and "BL" in df_op.columns:
                resumo = df_op.groupby(["CLIENTE", "BL"]).size().reset_index(name="QUANTIDADE_BOBINAS")
                st.dataframe(resumo, width="stretch")

            if os.path.exists(caminho_pdf):
                import fitz  # PyMuPDF
                
                doc = fitz.open(caminho_pdf)
                bobinas_encontradas = df_op["COIL_NO"].tolist()
                
                for pagina in doc:
                    texto_pagina = pagina.get_text()
                    for coil in bobinas_encontradas:
                        if str(coil) in texto_pagina:
                            areas = pagina.search_for(str(coil))
                            for rect in areas:
                                highlight = pagina.add_highlight_annot(rect)
                                highlight.set_colors(stroke=(0, 1, 0))
                                highlight.update()

                pdf_marcado_path = os.path.join(PASTA_NAVIOS, f"RELATORIO_MARCADO_{navio_selecionado}.pdf")
                doc.save(pdf_marcado_path)
                doc.close()

                with open(pdf_marcado_path, "rb") as f_pdf:
                    st.download_button(
                        label="📥 Baixar PDF do Manifesto com Bobinas Marcadas em Verde",
                        data=f_pdf,
                        file_name=f"Manifesto_Marcado_{navio_selecionado}.pdf",
                        mime="application/pdf",
                        type="primary",
                        width="stretch"
                    )
            else:
                st.info("O manifesto original deste navio era em Excel (.xlsx). O relatório em PDF com marcação está disponível para manifestos baseados em PDF.")

            st.markdown("---")
            if st.button("🔄 Iniciar Nova Operação (Zerar Tudo)", width="stretch"):
                st.session_state["bobinas_conferidas_sessao"] = []
                st.session_state["gerar_relatorio_final"] = False
                st.rerun()