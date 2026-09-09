import io
import os
import sqlite3
import time
from datetime import datetime
from google import genai
from google.genai import types
from PIL import Image
import pandas as pd
import pdfplumber
import streamlit as st
import anthropic

# --- CONFIGURAÇÃO INICIAL DA PÁGINA (APENAS UMA VEZ) ---
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
    st.stop()  # Para a execução do app aqui se não estiver logado

# Puxa a chave configurada no ambiente
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

PASTA_NAVIOS = "navios"
os.makedirs(PASTA_NAVIOS, exist_ok=True)

# --- CONFIGURAÇÃO DO BANCO DE DADOS SQLite (CONCORRÊNCIA SEGURA) ---
DB_PATH = "historico_conferencias.db"


def inicializar_banco():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historico (
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
    """)
    conn.commit()
    conn.close()


inicializar_banco()


def ler_etiqueta_com_ia(imagem_pil):
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    # Reduz a imagem proporcionalmente mantendo a nitidez
    max_largura = 1200
    if imagem_pil.width > max_largura:
        proporcao = max_largura / float(imagem_pil.width)
        nova_altura = int(float(imagem_pil.height) * proporcao)
        imagem_pil = imagem_pil.resize(
            (max_largura, nova_altura), Image.Resampling.LANCZOS
        )

    buffered = io.BytesIO()
    imagem_pil.save(buffered, format="JPEG", quality=85)
    img_bytes = buffered.getvalue()

    prompt = (
        "Analise esta etiqueta de aço de navio/siderurgia. "
        "Localize o código de identificação principal da bobina (frequentemente "
        "identificado como COIL NO, PROD NO, ID, ou um código alfanumérico longo). "
        "Retorne APENAS o código completo da bobina, sem nenhum texto adicional, "
        "explicações ou pontuação."
    )

    # --- TENTATIVA 1: REDE DE MODELOS GEMINI ---
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

    # --- TENTATIVA 2: PLANO B - ANTHROPIC CLAUDE (SE CONFIGURADO) ---
    if anthropic_key:
        try:
            import base64
            client_claude = anthropic.Anthropic(api_key=anthropic_key)
            img_base64 = base64.b64encode(img_bytes).decode("utf-8")

            message = client_claude.messages.create(
                model="claude-3-5-haiku-20241022",
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

    st.warning(
        "Servidores de IA instáveis no momento. O sistema tentará novamente ou você"
        " pode digitar o código abaixo."
    )
    return None


def salvar_historico(dados_conferencia):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO historico (data_hora, navio, operador, status, coil_no, item, cliente, bl, produto, peso_liq_t, peso_brut_t, destino)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
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
                dados_conferencia.get("DESTINO"),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Erro ao salvar histórico: {e}")


# --- INTERFACE MOBILE-FRIENDLY & TECNOLÓGICA ---
st.markdown(
    "<h2 style='font-family: monospace; letter-spacing: 2px; color: #38bdf8;"
    " text-transform: uppercase;'>IDENTIFICAÇÃO DE BOBINAS - DRX</h2>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='color: #94a3b8; font-size: 13px;'>SISTEMA DE LEITURA E CONFERÊNCIA</p>",
    unsafe_allow_html=True,
)

# Listar navios disponíveis na pasta 'navios'
arquivos_navios = [
    f.replace(".xlsx", "") for f in os.listdir(PASTA_NAVIOS) if f.endswith(".xlsx")
]

if not arquivos_navios:
    st.warning(
        "Nenhum manifesto de navio encontrado na pasta navios. Adicione arquivos"
        " na pasta do GitHub."
    )
else:
    navio_selecionado = st.selectbox("Manifesto Ativo:", arquivos_navios)
    caminho_excel_ativo = os.path.join(PASTA_NAVIOS, f"{navio_selecionado}.xlsx")

    st.markdown("---")

    operador = st.text_input("Porão:", value="Porão 1")

    st.markdown("### Leitura de Etiqueta")
    
    foto_upload = st.camera_input("Tirar foto da etiqueta", label_visibility="collapsed")

    if not foto_upload:
        foto_upload = st.file_uploader(
            "Ou carregar imagem da etiqueta",
            type=["jpg", "jpeg", "png"],
        )

    if foto_upload is not None:
        image = Image.open(foto_upload)
        st.image(image, caption="Etiqueta Capturada", use_container_width=True)

        if st.button("Executar Leitura Inteligente", type="primary"):
            with st.spinner("Processando imagem..."):
                codigo_lido_ia = ler_etiqueta_com_ia(image)
                st.session_state["codigo_sugerido"] = (
                    codigo_lido_ia if codigo_lido_ia else ""
                )

    codigo_sugerido_inicial = st.session_state.get("codigo_sugerido", "")

    st.markdown("### Código da Bobina:")
    codigo_final_digitado = st.text_input(
        "Confirme ou ajuste o código:",
        value=codigo_sugerido_inicial,
        placeholder="Ex: 97CE6739A",
        label_visibility="collapsed",
    )

    if codigo_final_digitado.strip():
        df = pd.read_excel(caminho_excel_ativo)
        if "ITEM" in df.iloc[0].values or any(
            "COIL" in str(val).upper() for val in df.iloc[0].values
        ):
            df.columns = df.iloc[0]
            df = df[1:].reset_index(drop=True)

        colunas_possiveis = [
            col
            for col in df.columns
            if col
            and (
                "COIL" in str(col).upper()
                or "BOBINA" in str(col).upper()
                or "PROD" in str(col).upper()
            )
        ]
        if colunas_possiveis:
            coluna_coil = colunas_possiveis[0]

            def normalizar(t):
                import re
                return re.sub(r"[^A-Z0-9]", "", str(t).upper())

            df["COIL_NORMALIZADO"] = df[coluna_coil].apply(normalizar)
            codigo_alvo_norm = normalizar(codigo_final_digitado)

            bobina_encontrada = None
            codigo_confirmado = ""

            for index, linha in df.iterrows():
                codigo_real = linha["COIL_NORMALIZADO"]
                if codigo_real and (
                    codigo_real == codigo_alvo_norm
                    or codigo_alvo_norm in codigo_real
                    or codigo_real in codigo_alvo_norm
                ):
                    bobina_encontrada = linha
                    codigo_confirmado = linha[coluna_coil]
                    break

            if bobina_encontrada is not None:
                data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                item = str(bobina_encontrada.get("ITEM", "N/A"))
                cliente = str(bobina_encontrada.get("CLIENTE", "N/A"))
                bl = str(bobina_encontrada.get("BL", "N/A"))

                col_prod = next(
                    (
                        c
                        for c in df.columns
                        if c
                        and (
                            "GRADE" in str(c).upper()
                            or "PROD" in str(c).upper()
                            or "COATING" in str(c).upper()
                        )
                    ),
                    "N/A",
                )
                produto = str(bobina_encontrada.get(col_prod, "N/A"))

                col_peso_liq = next(
                    (c for c in df.columns if c and ("LIQ" in str(c).upper())), "N/A"
                )
                peso_liq = str(bobina_encontrada.get(col_peso_liq, "N/A"))

                col_peso_brut = next(
                    (c for c in df.columns if c and ("BRUT" in str(c).upper())), "N/A"
                )
                peso_brut = str(bobina_encontrada.get(col_peso_brut, "N/A"))

                col_destino = next(
                    (
                        c
                        for c in df.columns
                        if c and ("DESTINO" in str(c).upper() or "DEST" in str(c).upper())
                    ),
                    "N/A",
                )
                destino = str(bobina_encontrada.get(col_destino, "N/A"))

                st.success("STATUS: VALIDADO")
                st.code(codigo_confirmado, language="text")

                st.markdown(f"**Manifesto:** {navio_selecionado}")
                st.markdown(f"**Item:** {item} | **BL:** {bl}")
                st.markdown(f"**Cliente:** {cliente}")
                st.markdown(f"**Destino:** {destino}")
                st.markdown(f"**Peso Líq:** {peso_liq}t | **Peso Brut:** {peso_brut}t")

                chave_cache_hist = f"{navio_selecionado}_{codigo_final_digitado.strip()}"
                if (
                    "ultimo_salvo" not in st.session_state
                    or st.session_state["ultimo_salvo"] != chave_cache_hist
                ):
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