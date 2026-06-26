import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="Home Keeper AI - Word Editor", layout="wide")

# --- 1. INICJALIZACJA SYSTEMU ---
if 'step' not in st.session_state: st.session_state.step = 1
if 'extracted_data' not in st.session_state: st.session_state.extracted_data = {}
if 'template_bytes' not in st.session_state: st.session_state.template_bytes = None
if 'found_tags' not in st.session_state: st.session_state.found_tags = []

if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Skonfiguruj klucz API w Secrets!")
    st.stop()

# --- 2. FUNKCJE POMOCNICZE ---
def get_tags_from_docx(docx_file):
    doc = Document(docx_file)
    text = ""
    for para in doc.paragraphs: text += para.text + " "
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells: text += cell.text + " "
    return list(set(re.findall(r"\{\{(.*?)\}\}", text)))

def replace_tags(doc, data):
    for tag, val in data.items():
        placeholder = "{{" + tag + "}}"
        for para in doc.paragraphs:
            if placeholder in para.text:
                para.text = para.text.replace(placeholder, str(val))
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if placeholder in cell.text:
                        cell.text = cell.text.replace(placeholder, str(val))

# --- 3. INTERFEJS - KROK 1: WGRYWANIE ---
st.title("📑 Generator Raportów Word")

if st.session_state.step == 1:
    col1, col2 = st.columns(2)
    with col1:
        uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with col2:
        uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia z wizyty", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🔍 ANALIZUJ ZDJĘCIA I WYPEŁNIJ WZÓR"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje zdjęcia... to może potrwać do minuty."):
                # Odczyt tagów
                tags = get_tags_from_docx(uploaded_word)
                st.session_state.found_tags = tags
                
                # Przygotowanie zdjęć
                b64_imgs = []
                for f in uploaded_imgs:
                    f.seek(0)
                    b64_imgs.append(base64.b64encode(f.read()).decode('utf-8'))
                
                # Zapytanie do AI
                prompt = f"""
                Jesteś profesjonalnym asystentem biura nieruchomości. 
                Przeanalizuj załączone zdjęcia (liczniki, notatki, klucze).
                Twoim zadaniem jest wypełnienie tych pól z dokumentu: {tags}.
                
                Szczególną uwagę zwróć na:
                - Liczniki (cyfry).
                - Klucze (ilość, opisy: piwnica, skrzynka, piloty).
                - Kody (do klatki, do szlabanu).
                - Wyposażenie (lista mebli).
                
                Zwróć WYŁĄCZNIE czysty JSON: {{"nazwa_tagu": "odczytana_wartosc"}}.
                """
                
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.extracted_data = json.loads(response.choices[0].message.content)
                uploaded_word.seek(0)
                st.session_state.template_bytes = uploaded_word.read()
                st.session_state.step = 2
                st.rerun()

# --- 4. INTERFEJS - KROK 2: WERYFIKACJA I PODPISY ---
elif st.session_state.step == 2:
    st.subheader("📝 Sprawdź i popraw dane")
    st.write("AI odczytało poniższe informacje. Możesz je teraz edytować:")
    
    updated_data = {}
    # Wyświetlamy pola w układzie, który był dobry
    for tag in st.session_state.found_tags:
        val = st.session_state.extracted_data.get(tag, "")
        updated_data[tag] = st.text_area(f"Pole: {tag}", value=val, height=100)
    
    st.divider()
    st.subheader("🖋️ Podpisy")
    st.info("Złóż podpisy poniżej (najlepiej na telefonie/tablecie).")
    
    c1, c2 = st.columns(2)
    with c1:
        st.write("Podpis Najemcy")
        sig_n = st_canvas(height=150, width=300, key="sig_n", background_color="#f0f0f0", display_toolbar=False)
    with c2:
        st.write("Podpis Pracownika")
        sig_p = st_canvas(height=150, width=300, key="sig_p", background_color="#f0f0f0", display_toolbar=False)

    if st.button("🖨️ GENERUJ I POBIERZ RAPORT WORD"):
        with st.spinner("Składanie dokumentu..."):
            doc = Document(io.BytesIO(st.session_state.template_bytes))
            
            # Podmiana tekstów
            replace_tags(doc, updated_data)
            
            # Dodawanie podpisów na końcu dokumentu
            def add_sig(canv, label):
                if canv.image_data is not None:
                    img = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                    b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                    p = doc.add_paragraph(label)
                    p.add_run().add_picture(b, width=Inches(1.5))

            add_sig(sig_n, "Podpis Najemcy:")
            add_sig(sig_p, "Podpis Pracownika:")
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Dokument gotowy!")
            st.download_button("📥 POBIERZ PLIK WORD (.docx)", out.getvalue(), "raport_finalny.docx")

    if st.button("⬅️ Wróć i wgraj inne pliki"):
        st.session_state.step = 1
        st.rerun()
