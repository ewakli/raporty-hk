import streamlit as st
import openai
import fitz  # PyMuPDF
import io, json, base64
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates
from streamlit_drawable_canvas import st_canvas

# Ustawienia strony
st.set_page_config(page_title="HK Smart Report", layout="wide")

if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# Inicjalizacja pamięci podręcznej aplikacji
if 'extracted' not in st.session_state: st.session_state.extracted = None
if 'placed' not in st.session_state: st.session_state.placed = {}
if 'active_key' not in st.session_state: st.session_state.active_key = None
if 'pdf_bytes' not in st.session_state: st.session_state.pdf_bytes = None

def get_preview(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    return Image.open(io.BytesIO(pix.tobytes("png"))), page.rect.width, page.rect.height

st.title("🏗️ Home Keeper - Edytor Wizualny")

# --- KROK 1: WGRYWANIE I ANALIZA ---
with st.sidebar:
    st.header("📂 1. Wgraj pliki")
    tmpl = st.file_uploader("WZÓR PDF", type="pdf")
    imgs = st.file_uploader("ZDJĘCIA", type=["jpg", "png", "jpeg"], accept_multiple_files=True)
    
    if st.button("🔍 ANALIZUJ ZDJĘCIA"):
        if tmpl and imgs:
            with st.spinner("AI analizuje zdjęcia..."):
                b64_imgs = []
                for f in imgs:
                    f.seek(0)
                    b64_imgs.append(base64.b64encode(f.read()).decode('utf-8'))
                
                prompt = 'Wyciągnij dane: Data, Wyposażenie, Energa, Klucze, Uwagi. Zwróć WYŁĄCZNIE JSON: {"Data":"","Wyposażenie":"","Energa":"","Klucze":"","Uwagi":""}'
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.extracted = json.loads(res.choices[0].message.content)
                st.session_state.pdf_bytes = tmpl.read()
                st.success("Analiza zakończona!")

# --- KROK 2: EDYCJA I ROZMIESZCZANIE ---
if st.session_state.extracted:
    col_edit, col_viz = st.columns([1, 2])

    with col_edit:
        st.subheader("📝 2. Sprawdź i Edytuj")
        st.write("Popraw tekst, jeśli AI się pomyliło:")
        
        for k in st.session_state.extracted.keys():
            # Pole do edycji treści
            st.session_state.extracted[k] = st.text_area(f"Treść: {k}", value=st.session_state.extracted[k], key=f"edit_{k}")
            
            # Przycisk do aktywacji pozycjonowania
            label = "📍 USTAW TO POLE" if k not in st.session_state.placed else "✅ POZYCJA USTAWIONA"
            if st.button(label, key=f"btn_{k}", use_container_width=True):
                st.session_state.active_key = k
            st.divider()

    with col_viz:
        st.subheader("📍 3. Wskaż miejsce na dokumencie")
        if st.session_state.active_key:
            st.warning(f"👉 Kliknij teraz na dokumencie, gdzie ma się pojawić: {st.session_state.active_key}")
        else:
            st.info("Wybierz pole z lewej strony, a następnie kliknij w dokument.")

        if st.session_state.pdf_bytes:
            img, pw, ph = get_preview(st.session_state.pdf_bytes)
            draw = ImageDraw.Draw(img)
            
            # Rysowanie podglądu postawionych już elementów
            for k, p in st.session_state.placed.items():
                draw.text((p['x'], p['y']), str(st.session_state.extracted[k])[:15]+"...", fill="blue")
            
            # Komponent do klikania
            coords = streamlit_image_coordinates(img, key="document_map")
            
            if coords and st.session_state.active_key:
                # Zapisujemy pozycję (skalowanie do PDF)
                st.session_state.placed[st.session_state.active_key] = {
                    "x": coords['x'], "y": coords['y'],
                    "px": coords['x'] / 2, "py": coords['y'] / 2
                }
                st.session_state.active_key = None
                st.rerun()

    # --- KROK 3: PODPISY I FINALIZACJA ---
    st.divider()
    wants_sig = st.checkbox("Chcę dodać podpisy")
    sn, sp = None, None
    if wants_sig:
        c1, c2 = st.columns(2)
        with c1: 
            st.caption("Podpis Najemcy")
            sn = st_canvas(height=120, width=280, key="sn", background_color="#f0f0f0", display_toolbar=False)
        with c2: 
            st.caption("Podpis Pracownika")
            sp = st_canvas(height=120, width=280, key="sp", background_color="#f0f0f0", display_toolbar=False)

    # --- GENEROWANIE I NAPRAWA BŁĘDU ---
    if st.button("🖨️ GENERUJ FINALNY PDF", use_container_width=True):
        if not st.session_state.placed:
            st.error("Nie ustawiono żadnego pola na dokumencie!")
        else:
            with st.spinner("Składanie pliku..."):
                doc = fitz.open(stream=st.session_state.pdf_bytes, filetype="pdf")
                page = doc[0]
                
                for k, p in st.session_state.placed.items():
                    page.insert_text((p['px'], p['py']), str(st.session_state.extracted[k]), fontsize=10, color=(0,0,0.5))
                
                if wants_sig:
                    def apply_s(kw, canv):
                        areas = page.search_for(kw)
                        if areas and canv.image_data is not None:
                            r = areas[-1]
                            pi = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                            b = io.BytesIO()
                            pi.save(b, format="PNG")
                            page.insert_image(fitz.Rect(r.x0, r.y0-45, r.x0+120, r.y0), stream=b.getvalue())
                    apply_s("Przejmujący", sn)
                    apply_s("Przekazujący", sp)
                
                # POPRAWKA BŁĘDU: Konwersja do tobytes() dla download_button
                final_pdf_bytes = doc.tobytes()
                doc.close()
                
                st.success("✅ Raport gotowy!")
                st.download_button(
                    label="📥 POBIERZ RAPORT PDF",
                    data=final_pdf_bytes,
                    file_name="protokol_hk.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
