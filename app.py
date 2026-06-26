import streamlit as st
import openai
import fitz  # PyMuPDF
import io, json, base64
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates
from streamlit_drawable_canvas import st_canvas

# Ustawienia strony
st.set_page_config(page_title="HK Universal AI Editor", layout="wide")

if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# Inicjalizacja stanów
if 'extracted' not in st.session_state: st.session_state.extracted = None
if 'placed' not in st.session_state: st.session_state.placed = {}
if 'active_key' not in st.session_state: st.session_state.active_key = None
if 'pdf_bytes' not in st.session_state: st.session_state.pdf_bytes = None

def get_preview(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    return Image.open(io.BytesIO(pix.tobytes("png"))), page.rect.width, page.rect.height

st.title("📄 Uniwersalny Protokół AI")
st.write("Wgraj dowolny wzór i zdjęcia – AI samo zidentyfikuje pola i dopasuje dane.")

# --- KROK 1: ANALIZA WZORU I DANYCH ---
with st.sidebar:
    st.header("📂 1. Pliki")
    tmpl = st.file_uploader("Wgraj DOWOLNY WZÓR PDF", type="pdf")
    imgs = st.file_uploader("Wgraj ZDJĘCIA/NOTATKI", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
    
    if st.button("🔍 ANALIZUJ"):
        if tmpl and imgs:
            with st.spinner("AI analizuje układ dokumentu i dane..."):
                # 1. Przygotowanie obrazu wzoru dla AI
                pdf_content = tmpl.read()
                doc_temp = fitz.open(stream=pdf_content, filetype="pdf")
                pix = doc_temp[0].get_pixmap()
                img_temp_b64 = base64.b64encode(pix.tobytes("png")).decode('utf-8')
                
                # 2. Przygotowanie zdjęć
                b64_imgs = []
                for f in imgs:
                    f.seek(0)
                    b64_imgs.append(base64.b64encode(f.read()).decode('utf-8'))
                
                # UNIWERSALNY PROMPT: AI najpierw patrzy na PDF, potem na zdjęcia
                prompt = """
                Działaj jako uniwersalny system wypełniania dokumentów.
                1. Przeanalizuj dołączony obraz wzoru PDF (Template). Zidentyfikuj wszystkie puste miejsca i etykiety pól.
                2. Przeanalizuj zdjęcia z wizyty.
                3. Dopasuj informacje ze zdjęć do pól znalezionych na wzorze. 
                Jeśli na zdjęciu jest np. 'kod 1234', a na wzorze pole 'Kod do klatki' lub 'Uwagi' - przypisz to tam.
                Zwróć WYŁĄCZNIE JSON, gdzie kluczami są nazwy pól ze wzoru, a wartościami dane ze zdjęć.
                Format: {"Nazwa Pola 1": "Wartość", "Nazwa Pola 2": "Wartość"}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{
                        "role":"user",
                        "content":[
                            {"type":"text", "text": prompt},
                            {"type":"image_url", "image_url": {"url": f"data:image/png;base64,{img_temp_b64}"}},
                            *[{"type":"image_url", "image_url": {"url": f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]
                        ]
                    }],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.extracted = json.loads(res.choices[0].message.content)
                st.session_state.pdf_bytes = pdf_content
                st.rerun()

# --- KROK 2: EDYCJA I WIZUALIZACJA ---
if st.session_state.extracted:
    col_edit, col_viz = st.columns([1, 2])

    with col_edit:
        st.subheader("📝 Edytuj i Wybierz")
        # Teraz pola są dynamiczne - takie, jakie AI znalazło na wzorze
        for k in list(st.session_state.extracted.keys()):
            st.session_state.extracted[k] = st.text_area(f"Pole: {k}", value=st.session_state.extracted[k], key=f"ed_{k}")
            
            label = "📍 USTAW" if k not in st.session_state.placed else "✅ OK"
            if st.button(label, key=f"btn_{k}", use_container_width=True):
                st.session_state.active_key = k
            st.divider()

    with col_viz:
        st.subheader("📍 Podgląd i Pozycjonowanie")
        if st.session_state.active_key:
            st.warning(f"Kliknij w miejsce dla: {st.session_state.active_key}")
        
        if st.session_state.pdf_bytes:
            img, pw, ph = get_preview(st.session_state.pdf_bytes)
            draw = ImageDraw.Draw(img)
            for k, p in st.session_state.placed.items():
                draw.text((p['x'], p['y']), str(st.session_state.extracted[k])[:15], fill="blue")
            
            coords = streamlit_image_coordinates(img, key="doc_map")
            
            if coords and st.session_state.active_key:
                st.session_state.placed[st.session_state.active_key] = {
                    "x": coords['x'], "y": coords['y'],
                    "px": coords['x'] / 2, "py": coords['y'] / 2
                }
                st.session_state.active_key = None
                st.rerun()

    # --- KROK 3: FINALIZACJA ---
    st.divider()
    wants_sig = st.checkbox("Dodaj podpisy (szuka słów Przejmujący/Przekazujący)")
    sn, sp = None, None
    if wants_sig:
        c1, c2 = st.columns(2)
        with c1: sn = st_canvas(height=100, width=250, key="sn", background_color="#eee")
        with c2: sp = st_canvas(height=100, width=250, key="sp", background_color="#eee")

    if st.button("🖨️ GENERUJ FINALNY PDF", use_container_width=True):
        if not st.session_state.placed:
            st.error("Nie ustawiono żadnych pól!")
        else:
            with st.spinner("Tworzenie PDF..."):
                doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                page = doc[0]
                
                for k, p in st.session_state.placed.items():
                    # ROZWIĄZANIE DLA POLSKICH ZNAKÓW
                    page.insert_text(
                        (p['px'], p['py']), 
                        str(st.session_state.extracted[k]), 
                        fontsize=10, 
                        fontname="helv", # Standardowa czcionka
                        color=(0, 0, 0.5)
                    )
                
                if wants_sig:
                    def apply_s(kw, canv):
                        areas = page.search_for(kw)
                        if areas and canv.image_data is not None:
                            r = areas[-1]
                            pi = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                            b = io.BytesIO(); pi.save(b, format="PNG")
                            page.insert_image(fitz.Rect(r.x0, r.y0-40, r.x0+120, r.y0), stream=b.getvalue())
                    apply_s("Przejmujący", sn)
                    apply_s("Przekazujący", sp)
                
                st.download_button("📥 POBIERZ PDF", doc.tobytes(), "raport_ai.pdf", "application/pdf")
