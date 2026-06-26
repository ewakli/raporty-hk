import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Word AI - Final Fix", layout="wide")

# --- KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# --- FUNKCJE POMOCNICZE ---
def get_all_tags(docx_file):
    doc = Document(docx_file)
    text_content = []
    for para in doc.paragraphs: text_content.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells: text_content.append(cell.text)
    
    full_text = " ".join(text_content)
    # Znajduje wszystko między {{ }} i usuwa zbędne spacje z nazw tagów
    found = re.findall(r"\{\{(.*?)\}\}", full_text)
    cleaned_tags = [t.strip() for t in found]
    
    text_t = [t for t in set(cleaned_tags) if 'podpis' not in t.lower()]
    sig_t = [t for t in set(cleaned_tags) if 'podpis' in t.lower()]
    return text_t, sig_t

def safe_replace(doc, tag_name, value, is_image=False, canvas_data=None):
    """Bezpiecznie zastępuje tag, obsługując rozbite 'runs' w Wordzie i spacje"""
    # Szukamy tagu z dowolną liczbą spacji wewnątrz: {{ podpis }} lub {{podpis}}
    pattern = re.compile(r"\{\{\s*" + re.escape(tag_name) + r"\s*\}\}")

    def process_paragraphs(paragraphs):
        for para in paragraphs:
            if pattern.search(para.text):
                if is_image and canvas_data is not None:
                    if canvas_data.image_data is not None:
                        # Zastępowanie obrazkiem
                        para.text = pattern.sub("", para.text) # Usuń tekst tagu
                        img = Image.fromarray(canvas_data.image_data.astype('uint8'), 'RGBA')
                        b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                        run = para.add_run()
                        run.add_picture(b, width=Inches(2.0))
                else:
                    # Zastępowanie tekstem
                    para.text = pattern.sub(str(value), para.text)

    process_paragraphs(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                process_paragraphs(cell.paragraphs)

# --- KROK 1: WGRYWANIE ---
st.title("📑 Generator Home Keeper - Poprawka Podpisów")

if 'step' not in st.session_state: st.session_state.step = 1

if st.session_state.step == 1:
    col1, col2 = st.columns(2)
    with col1: uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with col2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🔍 ANALIZUJ"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje zdjęcia..."):
                t_tags, s_tags = get_all_tags(uploaded_word)
                st.session_state.text_tags = t_tags
                st.session_state.sig_tags = s_tags
                
                b64_imgs = [base64.b64encode(f.read()).decode('utf-8') for f in uploaded_imgs]
                prompt = f"Wypełnij te pola na podstawie zdjęć: {t_tags}. Zwróć JSON: {{'tag': 'wartosc'}}"
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.ai_results = json.loads(res.choices[0].message.content)
                uploaded_word.seek(0); st.session_state.template_bytes = uploaded_word.read()
                st.session_state.step = 2
                st.rerun()

# --- KROK 2: WERYFIKACJA I PODPISY ---
elif st.session_state.step == 2:
    st.subheader("📝 Edytuj dane i złóż podpisy")
    
    updated_text = {}
    for tag in st.session_state.text_tags:
        val = st.session_state.ai_results.get(tag, "")
        updated_text[tag] = st.text_area(f"Pole: {tag}", value=val, height=100)
    
    st.divider()
    canvases = {}
    if st.session_state.sig_tags:
        st.subheader("🖋️ Podpisy (każdy tag to osobne okienko)")
        for tag in st.session_state.sig_tags:
            st.write(f"Złóż podpis dla: **{tag}**")
            canvases[tag] = st_canvas(height=150, width=400, key=f"c_{tag}", background_color="#f0f0f0", display_toolbar=False)
    
    if st.button("🖨️ GENERUJ RAPORT WORD"):
        with st.spinner("Wstawianie danych..."):
            doc = Document(io.BytesIO(st.session_state.template_bytes))
            
            # Podmiana tekstów
            for tag, val in updated_text.items():
                safe_replace(doc, tag, val)
            
            # Podmiana podpisów
            for tag, canv in canvases.items():
                safe_replace(doc, tag, "", is_image=True, canvas_data=canv)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Gotowe!")
            st.download_button("📥 POBIERZ PLIK", out.getvalue(), "raport.docx")

    if st.button("⬅️ Wróć"):
        st.session_state.step = 1; st.rerun()
