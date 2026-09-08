import streamlit as st
import pandas as pd
import os
from datetime import datetime
from PIL import Image
import io
import time
import pdfplumber
from google import genai
from google.genai import types

# Configuração da Página para Mobile e PWA
st.set_page_config(
    page_title="Conferência de Bobinas - Porto", 
    page_icon="📦", 
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Injeção de Meta Tags para transformar em PWA (Instalável no Celular)
st.markdown("""
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="Conferência Bobinas">
    <link rel="manifest" href="data:application/manifest+json;charset=utf-8,{
      'short_name': 'Bobinas',
      'name': 'Conferência de Bobinas Porto',
      'start_url': '/',
      'display': 'standalone',
      'background_color': '#ffffff',
      'theme_color': '#0f172a'
    }">
""", unsafe_allow_html=True)

# Puxa a chave configurada no ambiente
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

PASTA_NAVIOS = "navios"
os.makedirs(PASTA_NAVIOS, exist_ok=True)

def ler_etiqueta_com_ia(imagem_pil):
    if not GEMINI_API_KEY:
        st.error("⚠️ Chave GEMINI_API_KEY não configurada.")
        return None

    client = genai.Client(api_key=GEMINI_API_KEY)
    
    buffered = io.BytesIO()
    imagem_pil.save(buffered, format="JPEG")
    img_bytes = buffered.getvalue()

    prompt = (
        "Analise esta etiqueta de aço padronizada. "
        "Localize o código da bobina (geralmente impresso perto de 'PROD. NO.' ou 'COIL NO.'). "
        "Retorne APENAS o código exato da bobina (exemplo: 97CE6739A), sem nenhum texto adicional, comentários ou pontuação."
    )

    max_tentativas = 3
    for tentativa in range(max_tentativas):
        try:
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=[
                    types.Part.from_bytes(
                        data=img_bytes,
                        mime_type='image/jpeg',
                    ),
                    prompt
                ]
            )
            codigo_extraido = response.text.strip().upper()
            return codigo_extraido.replace(" ", "").replace("\n", "")
        except Exception as e:
            if "503" in str(e) and tentativa < max_tentativas - 1:
                time.sleep(2)
                continue
            else:
                st.warning(f"⚠️ Servidor da IA ocupado. Digite o código manualmente abaixo.")
                return None

def salvar_historico(dados_conferencia, caminho_historico="historico_conferencias.xlsx"):
    if os.path.exists(caminho_historico):
        df_hist = pd.read_excel(caminho_historico)
        df_hist = pd.concat([df_hist, pd.DataFrame([dados_conferencia])], ignore_index=True)
    else:
        df_hist = pd.DataFrame([dados_conferencia])
    df_hist.to_excel(caminho_historico, index=False)

# --- INTERFACE MOBILE-FRIENDLY ---
st.title("📦 Conferência de Bobinas")
st.caption("Modo Operacional Portuário")

# Listar navios disponíveis na pasta 'navios'
arquivos_navios = [f.replace(".xlsx", "") for f in os.listdir(PASTA_NAVIOS) if f.endswith(".xlsx")]

if not arquivos_navios:
    st.warning("⚠️ Nenhum manifesto de navio encontrado na pasta `navios/`.")
else:
    navio_selecionado = st.selectbox("⚓ Navio em Operação:", arquivos_navios)
    caminho_excel_ativo = os.path.join(PASTA_NAVIOS, f"{navio_selecionado}.xlsx")

    st.markdown("---")

    operador = st.text_input("Conferente:", value="Operador Pátio")
    
    # Suporte nativo a câmera frontal/traseira do celular
    foto_upload = st.file_uploader("Tire a foto da etiqueta:", type=['jpg', 'jpeg', 'png'])

    if foto_upload is not None:
        image = Image.open(foto_upload)
        st.image(image, caption="Etiqueta Capturada", width='stretch')

        if st.button("🔍 Ler Etiqueta com IA", type="primary", use_container_width=True):
            with st.spinner("Analisando etiqueta..."):
                codigo_lido_ia = ler_etiqueta_com_ia(image)
                st.session_state['codigo_sugerido'] = codigo_lido_ia if codigo_lido_ia else ""

        codigo_sugerido_inicial = st.session_state.get('codigo_sugerido', '')
        
        st.markdown("### ✍️ Código da Bobina:")
        codigo_final_digitado = st.text_input(
            "Confirme ou ajuste o código:", 
            value=codigo_sugerido_inicial,
            placeholder="Ex: 97CE6739A"
        )

        if codigo_final_digitado.strip():
            df = pd.read_excel(caminho_excel_ativo)
            if 'ITEM' in df.iloc[0].values or any('COIL' in str(val).upper() for val in df.iloc[0].values):
                df.columns = df.iloc[0]
                df = df[1:].reset_index(drop=True)

            colunas_possiveis = [col for col in df.columns if col and ('COIL' in str(col).upper() or 'BOBINA' in str(col).upper() or 'PROD' in str(col).upper())]
            if colunas_possiveis:
                coluna_coil = colunas_possiveis[0]
                
                def normalizar(t):
                    import re
                    return re.sub(r'[^A-Z0-9]', '', str(t).upper())

                df['COIL_NORMALIZADO'] = df[coluna_coil].apply(normalizar)
                codigo_alvo_norm = normalizar(codigo_final_digitado)

                bobina_encontrada = None
                codigo_confirmado = ""

                for index, linha in df.iterrows():
                    codigo_real = linha['COIL_NORMALIZADO']
                    if codigo_real and (codigo_real == codigo_alvo_norm or codigo_alvo_norm in codigo_real or codigo_real in codigo_alvo_norm):
                        bobina_encontrada = linha
                        codigo_confirmado = linha[coluna_coil]
                        break

                if bobina_encontrada is not None:
                    data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    item = str(bobina_encontrada.get('ITEM', 'N/A'))
                    cliente = str(bobina_encontrada.get('CLIENTE', 'N/A'))
                    bl = str(bobina_encontrada.get('BL', 'N/A'))
                    
                    col_prod = next((c for c in df.columns if c and ('GRADE' in str(c).upper() or 'PROD' in str(c).upper() or 'COATING' in str(c).upper())), 'N/A')
                    produto = str(bobina_encontrada.get(col_prod, 'N/A'))
                    
                    col_peso_liq = next((c for c in df.columns if c and ('LIQ' in str(c).upper())), 'N/A')
                    peso_liq = str(bobina_encontrada.get(col_peso_liq, 'N/A'))
                    
                    col_peso_brut = next((c for c in df.columns if c and ('BRUT' in str(c).upper())), 'N/A')
                    peso_brut = str(bobina_encontrada.get(col_peso_brut, 'N/A'))
                    
                    col_destino = next((c for c in df.columns if c and ('DESTINO' in str(c).upper() or 'DEST' in str(c).upper())), 'N/A')
                    destino = str(bobina_encontrada.get(col_destino, 'N/A'))

                    st.success("✅ BOBINA VALIDADA COM SUCESSO!")

                    st.markdown("### ✍️ MARCAR NA BOBINA COM CANETÃO:")
                    st.code(f"""
================ RESULTADO DA CONFERÊNCIA ================
 NAVIO: {navio_selecionado}
 Código: {codigo_confirmado}
 Item: {item} | Cliente: {cliente}
 BL: {bl} | Destino: {destino}
 Peso Liq: {peso_liq}t | Peso Brut: {peso_brut}t
==========================================================
""", language="text")

                    chave_cache_hist = f"{navio_selecionado}_{codigo_final_digitado.strip()}"
                    if 'ultimo_salvo' not in st.session_state or st.session_state['ultimo_salvo'] != chave_cache_hist:
                        registro = {
                            'DATA_HORA': data_hora,
                            'NAVIO': navio_selecionado,
                            'OPERADOR': operador,
                            'STATUS': 'CONFERIDO',
                            'COIL_NO': codigo_confirmado,
                            'ITEM': item,
                            'CLIENTE': cliente,
                            'BL': bl,
                            'PRODUTO': produto,
                            'PESO_LIQ_T': peso_liq,
                            'PESO_BRUT_T': peso_brut,
                            'DESTINO': destino
                        }
                        salvar_historico(registro)
                        st.session_state['ultimo_salvo'] = chave_cache_hist
                else:
                    st.warning(f"⏳ Procurando código '{codigo_final_digitado}'...")