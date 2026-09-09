import io
import os
import time
from datetime import datetime
from google import genai
from google.genai import types
from PIL import Image
import pandas as pd
import pdfplumber
import streamlit as st

# Configuração da Página para Mobile e PWA
st.set_page_config(
    page_title="Identificação de Bobinas",
    page_icon="📦",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Injeção de Meta Tags para transformar em PWA (Instalável no Celular)
st.markdown(
    """
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Conferência Bobinas">
    <link rel="manifest" href="data:application/manifest+json;charset=utf-8,{
      'short_name': 'Bobinas',
      'name': 'Identificação de Bobinas',
      'start_url': '/',
      'display': 'standalone',
      'background_color': '#0b0f19',
      'theme_color': '#0f172a'
    }">
""",
    unsafe_allow_html=True,
)

# Puxa a chave configurada no ambiente
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

PASTA_NAVIOS = "navios"
os.makedirs(PASTA_NAVIOS, exist_ok=True)


def ler_etiqueta_com_ia(imagem_pil):
  if not GEMINI_API_KEY:
    st.error("Chave GEMINI_API_KEY não configurada.")
    return None

  client = genai.Client(api_key=GEMINI_API_KEY)

  buffered = io.BytesIO()
  imagem_pil.save(buffered, format="JPEG")
  img_bytes = buffered.getvalue()

  prompt = (
      "Analise esta etiqueta de aço padronizada. "
      "Localize o código da bobina (geralmente impresso perto de 'PROD. NO.' ou"
      " 'COIL NO.'). Retorne APENAS o código exato da bobina (exemplo:"
      " 97CE6739A), sem nenhum texto adicional, comentários ou pontuação."
  )

  # Atualizado para os modelos mais recentes e eficientes da linha Flash
  modelos_para_tentar = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]

  for modelo in modelos_para_tentar:
    # Aumentamos para 3 tentativas por modelo com espera progressiva
    for tentativa in range(3):
      try:
        response = client.models.generate_content(
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
        # Pausa curta antes de tentar de novo para contornar oscilações rápidas de rede/servidor
        time.sleep(1.5)
        continue

  st.warning(
      "Servidor da IA instável no momento. O sistema tentará novamente ou você"
      " pode digitar o código abaixo."
  )
  return None


def salvar_historico(
    dados_conferencia, caminho_historico="historico_conferencias.xlsx"
):
  if os.path.exists(caminho_historico):
    df_hist = pd.read_excel(caminho_historico)
    df_hist = pd.concat(
        [df_hist, pd.DataFrame([dados_conferencia])], ignore_index=True
    )
  else:
    df_hist = pd.DataFrame([dados_conferencia])
  df_hist.to_excel(caminho_historico, index=False)


# --- INTERFACE MOBILE-FRIENDLY & TECNOLÓGICA ---
st.markdown(
    "<h2 style='font-family: monospace; letter-spacing: 2px; color: #38bdf8;"
    " text-transform: uppercase;'>IDENTIFICAÇÃO DE BOBINAS</h2>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='color: #94a3b8; font-size: 13px;'>SISTEMA DE LEITURA E"
    " CONFERÊNCIA</p>",
    unsafe_allow_html=True,
)

# Listar navios disponíveis na pasta 'navios'
arquivos_navios = [
    f.replace(".xlsx", "")
    for f in os.listdir(PASTA_NAVIOS)
    if f.endswith(".xlsx")
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
  foto_upload = st.file_uploader(
      "Carregar imagem da etiqueta",
      type=["jpg", "jpeg", "png"],
      label_visibility="collapsed",
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

          # EXIBIÇÃO USANDO COMPONENTES NATIVOS (SEM RISCO DE VAZAR HTML)
          st.success("STATUS: VALIDADO")
          st.code(codigo_confirmado, language="text")

          st.markdown(f"**Manifesto:** {navio_selecionado}")
          st.markdown(f"**Item:** {item} | **BL:** {bl}")
          st.markdown(f"**Cliente:** {cliente}")
          st.markdown(f"**Destino:** {destino}")
          st.markdown(
              f"**Peso Líq:** {peso_liq}t | **Peso Brut:** {peso_brut}t"
          )

          chave_cache_hist = (
              f"{navio_selecionado}_{codigo_final_digitado.strip()}"
          )
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
          st.markdown(
              "O código informado não foi localizado no manifesto ativo."
          )