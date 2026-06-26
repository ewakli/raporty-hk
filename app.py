import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Word AI", layout="wide")

# --- KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# --- FUNKCJE POMOCNICZE ---
def get_docx_tags(docx_file):
    """Wyciąga wszystkie tagi {{...}} z dokumentu Word"""
    doc = Document(docx_file)
    tags = []
    for para in doc.paragraphs:
        import re
        found = re.findall(r"\{\{(.*?)\}\}", para.text)
        tags.extend(found)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                found = re.findall(r"\{\{(.*?)\}\}", cell.text)
                tags.extend(found)
    return list(set(tags))

def replace_tags_in_docx(doc, data_dict):
    """Podmienia tagi na tekst w paragrafach i tabelach"""
    for tag, value in data_dict.items():
        placeholder = "{{" + tag + "}}"
        for para in doc.paragraphs:
            if placeholder in para.text:
                para.text = para.text.replace(placeholder, str(value))
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if placeholder in cell.text:
                        cell.text = cell.text.replace(placeholder, str(value))

def add_signature_to_word(doc, canvas_data, keyword):
    """Wstawia obraz podpisu pod paragrafem zawierającym konkretne słowo"""
    if canvas_data is not None and canvas_data.image_data is not None:
        # Konwersja canvas do obrazu
        img = Image.fromarray(canvas_data.image_data.astype('uint8'), 'RGBA')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        for para in doc.paragraphs:
            if keyword in para.text:
                run = para.add_run()
                run.add_break()
                run.add_picture(img_byte_arr, width=Inches(1.5))
                return

# --- INTERFEJS ---
st.title("📑 Generator Raportów Word z AI")

if 'step' not in st.session_state: st.session_state.step = 1

# KROK 1: WGRYWANIE
if st.session_state.step == 1:
    col1, col2 = st.columns(2)
    with col1:
        uploaded_word = st.file_uploader("1. Wgraj wzór WORD (.docx)", type="docx")
    with col2:
        uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia z wizyty", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🔍 ANALIZUJ DANE"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje dokument i zdjęcia..."):
                # 1. Pobierz tagi z Worda
                tags = get_docx_tags(uploaded_word)
                st.session_state.tags = tags
                
                # 2. Przygotuj zdjęcia
                b64_imgs = [base64.b64encode(f.read()).decode('utf-8') for f in uploaded_imgs]
                
                # 3. Zapytaj AI o wypełnienie tych konkretnych tagów
                prompt = f"""
                Jesteś asystentem nieruchomości. Mam dokument Word z tagami: {tags}.
                Przeanalizuj zdjęcia i dopasuj do każdego tagu odpowiednią informację.
                Zwróć WYŁĄCZNIE JSON, gdzie klucze to nazwy tagów (bez nawiasów), a wartości to tekst do wpisania.
                Przykład: {{"{tags[0] if tags else 'pole'}": "wartość"}}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.ai_results = json.loads(res.choices[0].message.content)
                uploaded_word.seek(0)
                st.session_state.word_template = uploaded_word.read()
                st.session_state.step = 2
                st.rerun()

# KROK 2: WERYFIKACJA I EDYCJA
elif st.session_state.step == 2:
    st.subheader("📝 Sprawdź i popraw dane")
    st.info("AI wypełniło pola na podstawie Twoich tagów w Wordzie. Możesz je teraz edytować.")
    
    edited_data = {}
    for tag in st.session_state.tags:
        val = st.session_state.ai_results.get(tag, "")
        edited_data[tag] = st.text_area(f"Pole: {tag}", value=val)
    
    st.session_state.final_data = edited_data
    
    st.divider()
    wants_sig = st.checkbox("Chcę dodać podpisy odręczne")
    
    sig_n, sig_p = None, None
    if wants_sig:
        c1, c2 = st.columns(2)
        with c1:
            st.write("Podpis Najemcy (Przejmujący)")
            sig_n = st_canvas(height=150, width=300, key="canvas_n", background_color="#f0f0f0", display_toolbar=False)
        with c2:
            st.write("Podpis Pracownika (Przekazujący)")
            sig_p = st_canvas(height=150, width=300, key="canvas_p", background_color="#f0f0f0", display_toolbar=False)

    if st.button("🖨️ GENERUJ PLIK WORD"):
        with st.spinner("Składanie dokumentu..."):
            doc = Document(io.BytesIO(st.session_state.word_template))
            
            # Podmiana tekstów
            replace_tags_in_docx(doc, st.session_state.final_data)
            
            # Dodawanie podpisów (szukamy słów Przejmujący / Przekazujący w tekście)
            if wants_sig:
                add_signature_to_word(doc, sig_n, "Przejmujący")
                add_signature_to_word(doc, sig_p, "Przekazujący")
            
            # Zapis
            out = io.BytesIO()
            doc.save(out)
            st.session_state.final_docx = out.getvalue()
            st.success("✅ Dokument gotowy!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", st.session_state.final_docx, "raport_hk.docx")

    if st.button("⬅️ Wróć (nowe pliki)"):
        st.session_state.step = 1
        st.rerun()
