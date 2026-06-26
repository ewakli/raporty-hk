import streamlit as st
import openai
import fitz  # PyMuPDF
import io, json, base64
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="Home Keeper AI - Precyzyjny Edytor", layout="wide")

if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API!")
    st.stop()

if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = None
if 'template_info' not in st.session_state:
    st.session_state.template_info = None

def get_pdf_page_as_image(pdf_content):
    doc = fitz.open(stream=pdf_content, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    return base64.b64encode(pix.tobytes("png")).decode('utf-8'), page.rect.width, page.rect.height

def find_keyword_pos(doc, keyword):
    """Szuka słowa w PDF i zwraca jego współrzędne"""
    page = doc[0]
    areas = page.search_for(keyword)
    if areas:
        # Zwracamy koniec słowa (x1) i linię bazową (y1)
        return {"x": areas[0].x1 + 5, "y": areas[0].y1 + 2}
    return {"x": 100, "y": 100}

st.title("🏗️ Home Keeper - Precyzyjny Generator")

col_a, col_b = st.columns(2)
with col_a:
    uploaded_template = st.file_uploader("1. Wgraj WZÓR PDF", type="pdf")
with col_b:
    uploaded_data = st.file_uploader("2. Wgraj ZDJĘCIA", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if st.button("🔍 KROK 1: Analizuj i pozycjonuj"):
    if uploaded_template and uploaded_data:
        with st.spinner("AI czyta zdjęcia, a system szuka linii w PDF..."):
            template_content = uploaded_template.read()
            doc = fitz.open(stream=template_content, filetype="pdf")
            
            # Mapowanie pozycji na podstawie słów kluczowych we wzorze
            positions = {
                "Data": find_keyword_pos(doc, "W dniu"),
                "Meble": find_keyword_pos(doc, "meble:"),
                "Energa": find_keyword_pos(doc, "ENERGA:"),
                "Klucze": find_keyword_pos(doc, "kluczy (opis kluczy):"),
                "Kod": find_keyword_pos(doc, "NR kodu do klatki")
            }
            
            # Przygotowanie zdjęć dla AI
            evidence_imgs = []
            for f in uploaded_data:
                evidence_imgs.append(base64.b64encode(f.read()).decode('utf-8'))
            
            prompt = """Wyciągnij dane z obrazów i przypisz je do kluczy: Data, Meble, Energa, Klucze, Kod. 
            Zwróć JSON: {"Data": "...", "Meble": "...", "Energa": "...", "Klucze": "...", "Kod": "..."}"""

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in evidence_imgs[:10]]
                ]}],
                response_format={ "type": "json_object" }
            )
            
            ai_vals = json.loads(response.choices[0].message.content)
            
            # Łączymy treść z AI z pozycjami z PDF
            final_extracted = []
            for key, pos in positions.items():
                val = ai_vals.get(key, "")
                # Specjalna poprawka dla mebli (żeby zaczynały się pod napisem)
                if key == "Meble": pos['y'] += 20; pos['x'] = 70
                final_extracted.append({"label": key, "value": val, "x": pos['x'], "y": pos['y']})

            st.session_state.extracted_data = final_extracted
            st.session_state.template_info = {"content": template_content}
            st.rerun()

if st.session_state.extracted_data:
    st.divider()
    st.subheader("📝 KROK 2: Precyzyjna korekta")
    st.info("Jeśli tekst nie leży idealnie na linii, użyj suwaków X i Y obok pola.")
    
    updated_fields = []
    for i, field in enumerate(st.session_state.extracted_data):
        with st.expander(f"Pole: {field['label']}", expanded=True):
            col1, col2, col3, col4 = st.columns([2, 4, 1, 1])
            with col1:
                lbl = st.text_input("Etykieta", field['label'], key=f"l_{i}")
            with col2:
                txt = st.text_area("Treść", field['value'], key=f"v_{i}")
            with col3:
                new_x = st.number_input("Pozycja X", value=float(field['x']), key=f"x_{i}")
            with col4:
                new_y = st.number_input("Pozycja Y", value=float(field['y']), key=f"y_{i}")
            updated_fields.append({"text": txt, "x": new_x, "y": new_y})

    st.divider()
    wants_signature = st.checkbox("Dodaj podpisy")
    sig_n, sig_p = None, None
    if wants_signature:
        c1, c2 = st.columns(2); sig_n = st_canvas(height=120, width=300, key="n", background_color="#eee"); sig_p = st_canvas(height=120, width=300, key="p", background_color="#eee")

    if st.button("🖨️ GENERUJ PDF"):
        doc = fitz.open(stream=st.session_state.template_info["content"], filetype="pdf")
        page = doc[0]
        for f in updated_fields:
            page.insert_text((f['x'], f['y']), str(f['text']), fontsize=10, color=(0, 0, 0.5))
        
        if wants_signature:
            def place_sig(kw, canvas):
                areas = page.search_for(kw)
                if areas and canvas.image_data is not None:
                    r = areas[-1]; img = Image.fromarray(canvas.image_data.astype('uint8'), 'RGBA')
                    buf = io.BytesIO(); img.save(buf, format="PNG")
                    page.insert_image(fitz.Rect(r.x0, r.y0-50, r.x0+150, r.y0), stream=buf.getvalue())
            place_sig("Przejmujący", sig_n); place_sig("Przekazujący", sig_p)

        out = io.BytesIO(); doc.save(out)
        st.success("✅ Gotowe!")
        st.download_button("Pobierz PDF", out.getvalue(), "raport_idealny.pdf")
