import streamlit as st
import openai
import fitz  # PyMuPDF
import io, json, base64
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="Home Keeper AI", layout="wide")

# --- LOGIN & SECRETS ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API!")
    st.stop()

# Inicjalizacja pamięci przesunięć (offsetów)
if 'offsets' not in st.session_state:
    st.session_state.offsets = {}

# --- FUNKCJE ---
def find_label_pos(page, keyword):
    """Szuka słowa w PDF i zwraca punkt zaraz za nim"""
    areas = page.search_for(keyword)
    if areas:
        return {"x": areas[0].x1 + 10, "y": areas[0].y1 + 2}
    return {"x": 100, "y": 100}

# --- INTERFEJS ---
st.title("📄 Szybki Generator Raportów")

col1, col2 = st.columns(2)
with col1:
    uploaded_template = st.file_uploader("1. WZÓR (PDF)", type="pdf")
with col2:
    uploaded_data = st.file_uploader("2. ZDJĘCIA Z WIZYTY", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if st.button("🔍 KROK 1: ANALIZUJ I DOPASUJ"):
    if uploaded_template and uploaded_data:
        with st.spinner("AI czyta dane, system szuka linii we wzorze..."):
            temp_content = uploaded_template.read()
            doc = fitz.open(stream=temp_content, filetype="pdf")
            page = doc[0]
            
            # Mapowanie "magnesem" - szukamy etykiet w Twoim PDF
            labels = {
                "Data": "W dniu",
                "Energa": "ENERGA:",
                "Meble": "wyposażony jest w przedmioty i meble:",
                "Klucze": "kluczy (opis kluczy):",
                "Kod": "NR kodu do klatki"
            }
            
            positions = {}
            for key, lab in labels.items():
                pos = find_label_pos(page, lab)
                # Poprawka dla mebli (pod napis)
                if key == "Meble": pos['y'] += 25; pos['x'] = 70
                positions[key] = pos

            # AI czyta zdjęcia
            evidence = [base64.b64encode(f.read()).decode('utf-8') for f in uploaded_data]
            prompt = """Wyciągnij dane: Data, Meble, Energa, Klucze, Kod. JSON: {"Data":"","Meble":"","Energa":"","Klucze":"","Kod":""}"""
            
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role":"user","content":[{"type":"text","text":prompt},
                *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{img}"}} for img in evidence[:10]]]}],
                response_format={"type":"json_object"}
            )
            
            ai_data = json.loads(resp.choices[0].message.content)
            
            # Zapisujemy do sesji
            res = []
            for k in labels.keys():
                res.append({"id": k, "label": k, "text": ai_data.get(k, ""), "x": positions[k]['x'], "y": positions[k]['y']})
            
            st.session_state.extracted = res
            st.session_state.template_pdf = temp_content
            st.rerun()

# --- KROK 2: WIZUALNE DOPASOWANIE ---
if 'extracted' in st.session_state:
    st.divider()
    st.subheader("📝 KROK 2: Sprawdź i popraw pozycję")
    st.info("Jeśli tekst nie leży na linii, kliknij strzałki pod polem.")

    final_fields = []
    for i, field in enumerate(st.session_state.extracted):
        with st.expander(f"Edytuj: {field['label']}", expanded=True):
            c_text, c_move = st.columns([3, 1])
            
            with c_text:
                txt = st.text_area("Treść", field['text'], key=f"t_{i}")
            
            with c_move:
                st.write("Przesuń tekst:")
                # Proste przyciski zamiast wpisywania liczb
                m_up, m_down = st.columns(2)
                if m_up.button("⬆️", key=f"up_{i}"): field['y'] -= 5; st.rerun()
                if m_down.button("⬇️", key=f"dn_{i}"): field['y'] += 5; st.rerun()
                
                m_left, m_right = st.columns(2)
                if m_left.button("⬅️", key=f"lt_{i}"): field['x'] -= 10; st.rerun()
                if m_right.button("➡️", key=f"rt_{i}"): field['x'] += 10; st.rerun()
            
            final_fields.append({"text": txt, "x": field['x'], "y": field['y']})

    st.divider()
    wants_sig = st.checkbox("Chcę dodać podpisy")
    sn, sp = None, None
    if wants_sig:
        ca, cb = st.columns(2)
        with ca: sn = st_canvas(height=100, width=280, key="sn", background_color="#f0f0f0")
        with cb: sp = st_canvas(height=100, width=280, key="sp", background_color="#f0f0f0")

    if st.button("🖨️ GENERUJ PDF"):
        doc = fitz.open(stream=st.session_state.template_pdf, filetype="pdf")
        page = doc[0]
        for f in final_fields:
            page.insert_text((f['x'], f['y']), str(f['text']), fontsize=10, color=(0, 0, 0.5))
        
        if wants_sig:
            def apply_sig(kw, canvas):
                areas = page.search_for(kw)
                if areas and canvas.image_data is not None:
                    r = areas[-1]; img = Image.fromarray(canvas.image_data.astype('uint8'), 'RGBA')
                    buf = io.BytesIO(); img.save(buf, format="PNG")
                    page.insert_image(fitz.Rect(r.x0, r.y0-45, r.x0+120, r.y0), stream=buf.getvalue())
            apply_sig("Przejmujący", sn); apply_sig("Przekazujący", sp)

        pdf_bytes = doc.save()
        st.success("Gotowe!")
        st.download_button("📥 POBIERZ RAPORT", pdf_bytes, "raport.pdf")
