import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Word AI - Precision Sign", layout="wide")

# --- INICJALIZACJA ---
if 'step' not in st.session_state: st.session_state.step = 1
if 'extracted_data' not in st.session_state: st.session_state.extracted_data = {}
if 'template_bytes' not in st.session_state: st.session_state.template_bytes = None
if 'text_tags' not in st.session_state: st.session_state.text_tags = []
if 'sig_tags' not in st.session_state: st.session_state.sig_tags = []

if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Skonfiguruj klucz API w Secrets!")
    st.stop()

# --- FUNKCJE ---
def get_all_tags(docx_file):
    doc = Document(docx_file)
    all_tags = []
    # Szukaj w paragrafach i tabelach
    for para in doc.paragraphs:
        all_tags.extend(re.findall(r"\{\{(.*?)\}\}", para.text))
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_tags.extend(re.findall(r"\{\{(.*?)\}\}", cell.text))
    
    unique_tags = list(set(all_tags))
    # Rozdziel na tekstowe i podpisy
    text_t = [t for t in unique_tags if 'podpis' not in t.lower() and 'sig' not in t.lower()]
    sig_t = [t for t in unique_tags if 'podpis' in t.lower() or 'sig' in t.lower()]
    return text_t, sig_t

def replace_with_image(doc, tag, canvas_data):
    """Zastępuje tag obrazkiem w tym samym miejscu"""
    if canvas_data is not None and canvas_data.image_data is not None:
        img = Image.fromarray(canvas_data.image_data.astype('uint8'), 'RGBA')
        b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
        
        target = "{{" + tag + "}}"
        # Szukaj w paragrafach
        for para in doc.paragraphs:
            if target in para.text:
                para.text = para.text.replace(target, "")
                run = para.add_run()
                run.add_picture(b, width=Inches(1.6))
        # Szukaj w tabelach
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        if target in para.text:
                            para.text = para.text.replace(target, "")
                            run = para.add_run()
                            run.add_picture(b, width=Inches(1.4))

# --- KROK 1: WGRYWANIE ---
st.title("📑 Generator Protokółów Home Keeper")

if st.session_state.step == 1:
    col1, col2 = st.columns(2)
    with col1:
        uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with col2:
        uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia (liczniki, klucze, notatki)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🔍 ANALIZUJ ZDJĘCIA"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje zdjęcia pod kątem wzoru..."):
                t_tags, s_tags = get_all_tags(uploaded_word)
                st.session_state.text_tags = t_tags
                st.session_state.sig_tags = s_tags
                
                b64_imgs = []
                for f in uploaded_imgs:
                    f.seek(0); b64_imgs.append(base64.b64encode(f.read()).decode('utf-8'))
                
                prompt = f"""
                Jesteś ekspertem nieruchomości. Przeanalizuj zdjęcia.
                Wypełnij te pola z dokumentu: {t_tags}.
                BARDZO WAŻNE:
                - Klucze: wypisz ilość kompletów i dokładnie opisz każdy klucz (np. piwnica, pilot, skrzynka).
                - Kody: wyciągnij kody do klatek/domofonów.
                - Liczniki: podaj odczyty.
                Zwróć WYŁĄCZNIE JSON: {{"tag": "wartosc"}}.
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.extracted_data = json.loads(res.choices[0].message.content)
                uploaded_word.seek(0); st.session_state.template_bytes = uploaded_word.read()
                st.session_state.step = 2
                st.rerun()

# --- KROK 2: WERYFIKACJA I PODPISY ---
elif st.session_state.step == 2:
    st.subheader("📝 Edytuj dane i złóż podpisy")
    
    # 1. Edycja tekstów
    updated_text = {}
    for tag in st.session_state.text_tags:
        val = st.session_state.extracted_data.get(tag, "")
        updated_text[tag] = st.text_area(f"Pole: {tag}", value=val, height=100)
    
    # 2. Podpisy (dynamiczne na podstawie tagów)
    st.divider()
    canvases = {}
    if st.session_state.sig_tags:
        st.subheader("🖋️ Podpisy (kliknij pole i podpisz się)")
        cols = st.columns(len(st.session_state.sig_tags))
        for i, tag in enumerate(st.session_state.sig_tags):
            with cols[i]:
                st.write(f"Miejsce na: {tag}")
                canvases[tag] = st_canvas(height=150, width=300, key=f"canvas_{tag}", background_color="#f0f0f0", display_toolbar=False)
    
    # 3. Generowanie
    if st.button("🖨️ GENERUJ FINALNY DOKUMENT WORD"):
        with st.spinner("Wstawianie danych i podpisów do Worda..."):
            doc = Document(io.BytesIO(st.session_state.template_bytes))
            
            # Podmiana tekstów
            for tag, val in updated_text.items():
                placeholder = "{{" + tag + "}}"
                for para in doc.paragraphs:
                    if placeholder in para.text: para.text = para.text.replace(placeholder, str(val))
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            if placeholder in cell.text: cell.text = cell.text.replace(placeholder, str(val))
            
            # Podmiana podpisów (w miejscu tagów)
            for tag, canv in canvases.items():
                replace_with_image(doc, tag, canv)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Gotowe!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_hk.docx")

    if st.button("⬅️ Wróć"):
        st.session_state.step = 1; st.rerun()
