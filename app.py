import streamlit as st
import openai
import fitz  # PyMuPDF
import io, json, base64
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates
from streamlit_drawable_canvas import st_canvas

# Ustawienia pod telefon
st.set_page_config(page_title="HK Mobile", layout="wide", initial_sidebar_state="collapsed")

if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# Inicjalizacja pamięci
if 'placed' not in st.session_state: st.session_state.placed = {}
if 'active_key' not in st.session_state: st.session_state.active_key = None
if 'extracted' not in st.session_state: st.session_state.extracted = {}

def get_preview(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Zoom 2x dla lepszej widoczności
    return Image.open(io.BytesIO(pix.tobytes("png"))), page.rect.width, page.rect.height

st.title("📱 Protokół Home Keeper")

# 1. ŁADOWANIE
with st.expander("📂 KROK 1: Wgraj pliki", expanded=not st.session_state.extracted):
    tmpl = st.file_uploader("WZÓR PDF", type="pdf")
    imgs = st.file_uploader("ZDJĘCIA", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
    if st.button("🔍 ANALIZUJ ZDJĘCIA"):
        if tmpl and imgs:
            with st.spinner("AI pracuje..."):
                b64_imgs = [base64.b64encode(f.read()).decode('utf-8') for f in imgs]
                prompt = 'Wyciągnij: Data, Wyposażenie, Energa, Klucze, Uwagi. Tylko JSON: {"Data":"","Wyposażenie":"","Energa":"","Klucze":"","Uwagi":""}'
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type":"json_object"}
                )
                st.session_state.extracted = json.loads(res.choices[0].message.content)
                st.session_state.pdf_bytes = tmpl.read()
                st.rerun()

# 2. ROZMIESZCZANIE
if st.session_state.extracted:
    st.subheader("📍 KROK 2: Postaw tekst na dokumencie")
    st.info("Wybierz pole i kliknij w odpowiednie miejsce na podglądzie.")

    # Przyciski wyboru pola
    cols = st.columns(3)
    for i, k in enumerate(st.session_state.extracted.keys()):
        label = f"✅ {k}" if k in st.session_state.placed else f"📍 {k}"
        if cols[i%3].button(label, key=f"b_{k}", use_container_width=True):
            st.session_state.active_key = k

    if st.session_state.active_key:
        st.warning(f"👉 Kliknij na dokumencie, by postawić: {st.session_state.active_key}")

    # Podgląd i klikanie
    if 'pdf_bytes' in st.session_state:
        img, pw, ph = get_preview(st.session_state.pdf_bytes)
        draw = ImageDraw.Draw(img)
        for k, p in st.session_state.placed.items():
            draw.text((p['x'], p['y']), st.session_state.extracted[k][:30]+"...", fill="blue")
        
        # Interaktywna mapa
        coords = streamlit_image_coordinates(img, key="map")
        if coords and st.session_state.active_key:
            st.session_state.placed[st.session_state.active_key] = {
                "x": coords['x'], "y": coords['y'],
                "px": coords['x']/2, "py": coords['y']/2 # Skalowanie do PDF
            }
            st.session_state.active_key = None
            st.rerun()

    # 3. PODPISY I FINALIZACJA
    st.divider()
    wants_sig = st.checkbox("Chcę dodać podpisy")
    sn, sp = None, None
    if wants_sig:
        c1, c2 = st.columns(2)
        with c1: 
            st.caption("Najemca")
            sn = st_canvas(height=120, width=280, key="sn", background_color="#f0f0f0")
        with c2: 
            st.caption("Pracownik")
            sp = st_canvas(height=120, width=280, key="sp", background_color="#f0f0f0")

    if st.button("🖨️ GENERUJ I POBIERZ PDF", use_container_width=True):
        doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
        page = doc[0]
        for k, p in st.session_state.placed.items():
            page.insert_text((p['px'], p['py']), st.session_state.extracted[k], fontsize=10, color=(0,0,0.5))
        
        if wants_sig:
            def apply_s(kw, canv):
                areas = page.search_for(kw)
                if areas and canv.image_data is not None:
                    r = areas[-1]; pi = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                    b = io.BytesIO(); pi.save(b, format="PNG")
                    page.insert_image(fitz.Rect(r.x0, r.y0-45, r.x0+120, r.y0), stream=b.getvalue())
            apply_s("Przejmujący", sn); apply_s("Przekazujący", sp)
            
        st.download_button("📥 POBIERZ GOTOWY RAPORT", doc.save(), "raport.pdf", use_container_width=True)
