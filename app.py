import streamlit as st
import openai
import fitz  # PyMuPDF
import io, json, base64
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="AI Report Editor", layout="wide")

# --- KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")

# --- STAN APLIKACJI (Session State) ---
if 'extracted_data' not in st.session_state:
    st.session_state.extracted_data = None
if 'template_info' not in st.session_state:
    st.session_state.template_info = None

def get_pdf_page_as_image(pdf_stream):
    doc = fitz.open(stream=pdf_stream, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    return base64.b64encode(pix.tobytes("png")).decode('utf-8'), page.rect.width, page.rect.height

# --- INTERFEJS ---
st.title("📄 Inteligentny Edytor Raportów")

col_a, col_b = st.columns(2)
with col_a:
    uploaded_template = st.file_uploader("1. Wgraj WZÓR PDF", type="pdf")
with col_b:
    uploaded_data = st.file_uploader("2. Wgraj ZDJĘCIA/WIDEO", type=["jpg", "png", "mp4"], accept_multiple_files=True)

if st.button("🔍 KROK 1: Analizuj i przygotuj dane"):
    if uploaded_template and uploaded_data:
        with st.spinner("AI analizuje dokument i dowody..."):
            # Przygotowanie obrazów
            template_b64, p_w, p_h = get_pdf_page_as_image(uploaded_template.read())
            uploaded_template.seek(0) # reset streamu
            
            evidence_imgs = [base64.b64encode(f.read()).decode('utf-8') for f in uploaded_data if f.type.startswith("image")]
            
            prompt = f"""
            Jesteś asystentem biura nieruchomości. 
            Przeanalizuj wzór dokumentu i zdjęcia z wizyty.
            Zidentyfikuj pola do wypełnienia we wzorze i dopasuj do nich informacje ze zdjęć.
            
            Zwróć JSON w formacie:
            {{
              "fields": [
                {{"label": "Nazwa Pola (np. Licznik)", "value": "Wartość ze zdjęć", "x": x, "y": y}}
              ]
            }}
            Skala współrzędnych: 0-{int(p_w)} (X), 0-{int(p_h)} (Y).
            Zwróć TYLKO czysty JSON.
            """

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{template_b64}"}},
                        *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in evidence_imgs[:5]]
                    ]
                }],
                response_format={ "type": "json_object" }
            )
            
            st.session_state.extracted_data = json.loads(response.choices[0].message.content).get("fields", [])
            st.session_state.template_info = {"stream": uploaded_template.read(), "w": p_w, "h": p_h}
            st.rerun()

# --- KROK 2: WERYFIKACJA I EDYCJA ---
if st.session_state.extracted_data:
    st.divider()
    st.subheader("📝 KROK 2: Zweryfikuj i uzupełnij raport")
    st.write("AI przygotowało propozycję wpisów. Możesz je teraz dowolnie edytować przed zapisem do PDF.")
    
    updated_fields = []
    
    # Tworzymy dynamiczny formularz
    for i, field in enumerate(st.session_state.extracted_data):
        col_f1, col_f2 = st.columns([1, 2])
        with col_f1:
            label = st.text_input(f"Pole {i+1}", value=field['label'], key=f"label_{i}")
        with col_f2:
            val = st.text_area(f"Wartość {i+1}", value=field['value'], key=f"val_{i}", height=68)
        
        updated_fields.append({"label": label, "text": val, "x": field['x'], "y": field['y']})

    # Opcja dodania nowego pola ręcznie
    if st.button("+ Dodaj inne pole (ręcznie)"):
        updated_fields.append({"label": "Nowe pole", "text": "", "x": 100, "y": 100})
        st.session_state.extracted_data = updated_fields
        st.rerun()

    st.divider()
    
    # --- KROK 3: OPCJE PODPISU ---
    st.subheader("🖋️ KROK 3: Podpisy i Finalizacja")
    wants_signature = st.checkbox("Chcę dodać podpisy elektroniczne do tego raportu")
    
    sig_n = None
    sig_p = None

    if wants_signature:
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Podpis Najemcy")
            sig_n = st_canvas(stroke_width=2, stroke_color="#000", background_color="#f0f0f0", height=100, width=300, key="sn")
        with c2:
            st.caption("Podpis Pracownika")
            sig_p = st_canvas(stroke_width=2, stroke_color="#000", background_color="#f0f0f0", height=100, width=300, key="sp")

    if st.button("🖨️ GENERUJ FINALNY PDF"):
        with st.spinner("Składanie dokumentu..."):
            doc = fitz.open(stream=st.session_state.template_info["stream"], filetype="pdf")
            page = doc[0]
            
            # Naniesienie edytowanych danych
            for field in updated_fields:
                page.insert_text((field['x'], field['y']), field['text'], fontsize=10, color=(0, 0, 0.6))
            
            # Naniesienie podpisów (opcjonalnie)
            if wants_signature:
                def apply_sig(keyword, canvas):
                    if canvas and canvas.image_data is not None:
                        areas = page.search_for(keyword)
                        if areas:
                            r = areas[-1]
                            img = Image.fromarray(canvas.image_data.astype('uint8'), 'RGBA')
                            b = io.BytesIO(); img.save(b, format="PNG")
                            page.insert_image(fitz.Rect(r.x0, r.y0-50, r.x0+150, r.y0), stream=b.getvalue())

                apply_sig("Przejmujący", sig_n)
                apply_sig("Przekazujący", sig_p)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("PDF gotowy!")
            st.download_button("📥 Pobierz Raport", out.getvalue(), "raport_koncowy.pdf")
