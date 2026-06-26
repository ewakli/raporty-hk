import streamlit as st
import openai
import fitz  # PyMuPDF
import io, json, base64
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="Home Keeper AI Editor", layout="wide")

# --- KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# --- STAN APLIKACJI ---
if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = None
if 'template_info' not in st.session_state:
    st.session_state.template_info = None

def get_pdf_page_as_image(pdf_content):
    doc = fitz.open(stream=pdf_content, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    return base64.b64encode(pix.tobytes("png")).decode('utf-8'), page.rect.width, page.rect.height

# --- INTERFEJS ---
st.title("📄 Inteligentny Edytor Raportów Home Keeper")

col_a, col_b = st.columns(2)
with col_a:
    uploaded_template = st.file_uploader("1. Wgraj WZÓR PDF", type="pdf")
with col_b:
    uploaded_data = st.file_uploader("2. Wgraj ZDJĘCIA/WIDEO", type=["jpg", "jpeg", "png", "mp4"], accept_multiple_files=True)

if st.button("🔍 KROK 1: Analizuj i przygotuj dane"):
    if uploaded_template and uploaded_data:
        with st.spinner("AI analizuje dokument i dowody..."):
            template_content = uploaded_template.read()
            template_b64, p_w, p_h = get_pdf_page_as_image(template_content)
            uploaded_template.seek(0)
            
            evidence_imgs = []
            for f in uploaded_data:
                if f.type.startswith("image"):
                    evidence_imgs.append(base64.b64encode(f.read()).decode('utf-8'))
            
            prompt = f"""
            Jesteś asystentem biura nieruchomości. 
            Przeanalizuj wzór dokumentu i zdjęcia z wizyty.
            Zidentyfikuj pola do wypełnienia we wzorze i dopasuj do nich informacje ze zdjęć.
            Zwróć JSON: {{ "fields": [ {{"label": "Nazwa", "value": "Treść", "x": x, "y": y}} ] }}
            Skala: 0-{int(p_w)} (X), 0-{int(p_h)} (Y).
            Zwróć TYLKO czysty JSON.
            """

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{template_b64}"}},
                        *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in evidence_imgs[:10]]
                    ]
                }],
                response_format={ "type": "json_object" }
            )
            
            st.session_state.extracted_data = json.loads(response.choices[0].message.content).get("fields", [])
            st.session_state.template_info = {"content": template_content, "w": p_w, "h": p_h}
            st.rerun()

# --- KROK 2: EDYCJA I FINALIZACJA ---
if st.session_state.extracted_data:
    st.divider()
    st.subheader("📝 KROK 2: Zweryfikuj i uzupełnij raport")
    
    updated_fields = []
    for i, field in enumerate(st.session_state.extracted_data):
        c1, c2 = st.columns([1, 3])
        with c1:
            new_label = st.text_input(f"Etykieta {i}", value=field.get('label', ''), key=f"lab_{i}")
        with c2:
            new_val = st.text_area(f"Treść {i}", value=field.get('value', ''), key=f"val_{i}", height=70)
        updated_fields.append({"label": new_label, "text": new_val, "x": field['x'], "y": field['y']})

    st.divider()
    st.subheader("🖋️ KROK 3: Podpisy i Finalizacja")
    wants_signature = st.checkbox("Dodaj pola podpisów elektronicznych")
    
    sig_n = None
    sig_p = None

    if wants_signature:
        col_sig1, col_sig2 = st.columns(2)
        with col_sig1:
            st.caption("Podpis Najemcy")
            sig_n = st_canvas(stroke_width=2, stroke_color="#000", background_color="#f0f0f0", height=150, width=300, key="canvas_n")
        with col_sig2:
            st.caption("Podpis Pracownika")
            sig_p = st_canvas(stroke_width=2, stroke_color="#000", background_color="#f0f0f0", height=150, width=300, key="canvas_p")

    if st.button("🖨️ GENERUJ FINALNY PDF"):
        with st.spinner("Generowanie dokumentu PDF..."):
            doc = fitz.open(stream=st.session_state.template_info["content"], filetype="pdf")
            page = doc[0]
            
            for field in updated_fields:
                page.insert_text((field['x'], field['y']), str(field['text']), fontsize=10, color=(0, 0, 0.5))
            
            if wants_signature:
                def place_signature(keyword, canvas_obj):
                    if canvas_obj is not None and canvas_obj.image_data is not None:
                        areas = page.search_for(keyword)
                        if areas:
                            rect = areas[-1]
                            img = Image.fromarray(canvas_obj.image_data.astype('uint8'), 'RGBA')
                            buf = io.BytesIO()
                            img.save(buf, format="PNG")
                            page.insert_image(fitz.Rect(rect.x0, rect.y0 - 60, rect.x0 + 140, rect.y0), stream=buf.getvalue())

                place_signature("Przejmujący", sig_n)
                place_signature("Przekazujący", sig_p)
            
            output_pdf = io.BytesIO()
            doc.save(output_pdf)
            doc.close()
            st.success("✅ PDF gotowy!")
            st.download_button("📥 Pobierz raport", output_pdf.getvalue(), "raport.pdf", "application/pdf")

    if st.button("🗑️ Zacznij od nowa"):
        st.session_state.extracted_data = None
        st.session_state.template_info = None
        st.rerun()
            st.success("PDF gotowy!")
            st.download_button("📥 Pobierz Raport", out.getvalue(), "raport_koncowy.pdf")
