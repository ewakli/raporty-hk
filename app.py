import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Word AI - Ultra Fix", layout="wide")

# --- KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# --- INICJALIZACJA SESJI ---
if 'step' not in st.session_state: st.session_state.step = 1
if 'extracted_data' not in st.session_state: st.session_state.extracted_data = {}
if 'text_tags' not in st.session_state: st.session_state.text_tags = []
if 'sig_tags' not in st.session_state: st.session_state.sig_tags = []

# --- FUNKCJE POMOCNICZE ---
def get_all_tags(docx_file):
    doc = Document(docx_file)
    full_text = ""
    for para in doc.paragraphs: full_text += para.text + " "
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells: full_text += cell.text + " "
    
    found = re.findall(r"\{\{(.*?)\}\}", full_text)
    cleaned_tags = [t.strip() for t in found]
    text_t = [t for t in set(cleaned_tags) if 'podpis' not in t.lower()]
    sig_t = [t for t in set(cleaned_tags) if 'podpis' in t.lower()]
    return text_t, sig_t

def safe_replace(doc, tag_name, value, is_image=False, canvas_data=None):
    # Regex obsługujący spacje w klamrach: {{ tag }}
    pattern = re.compile(r"\{\{\s*" + re.escape(tag_name) + r"\s*\}\}")

    def process_paras(paragraphs):
        for para in paragraphs:
            if pattern.search(para.text):
                if is_image and canvas_data is not None:
                    if canvas_data.image_data is not None:
                        para.text = pattern.sub("", para.text)
                        img = Image.fromarray(canvas_data.image_data.astype('uint8'), 'RGBA')
                        b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                        para.add_run().add_picture(b, width=Inches(2.0))
                else:
                    para.text = pattern.sub(str(value), para.text)

    process_paras(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                process_paras(cell.paragraphs)

# --- KROK 1: WGRYWANIE ---
st.title("📑 Generator Home Keeper - Wersja Stabilna")

if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1: uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with c2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🔍 ANALIZUJ ZDJĘCIA"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje zdjęcia... Czekaj cierpliwie."):
                t_tags, s_tags = get_all_tags(uploaded_word)
                st.session_state.text_tags = t_tags
                st.session_state.sig_tags = s_tags
                
                b64_imgs = []
                for f in uploaded_imgs:
                    f.seek(0)
                    b64_imgs.append(base64.b64encode(f.read()).decode('utf-8'))
                
                prompt = f"Wypełnij te pola na podstawie zdjęć: {t_tags}. Zwróć WYŁĄCZNIE JSON: {{'tag': 'wartosc'}}"
                
                try:
                    res = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role":"user","content":[{"type":"text","text":prompt},
                        *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:8]]]}],
                        response_format={"type": "json_object"}
                    )
                    
                    raw_content = res.choices[0].message.content
                    
                    if raw_content:
                        # Oczyszczanie odpowiedzi z ewentualnych znaczników markdown
                        clean_json = raw_content.replace("```json", "").replace("```", "").strip()
                        st.session_state.extracted_data = json.loads(clean_json)
                        uploaded_word.seek(0)
                        st.session_state.template_bytes = uploaded_word.read()
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("AI zwróciło pustą odpowiedź. Spróbuj wgrać mniej zdjęć (max 5) lub zdjęcia o mniejszym rozmiarze.")
                except Exception as e:
                    st.error(f"Błąd analizy: {str(e)}")

# --- KROK 2: WERYFIKACJA I PODPISY ---
elif st.session_state.step == 2:
    st.subheader("📝 Sprawdź dane i podpisz dokument")
    
    updated_text = {}
    for tag in st.session_state.text_tags:
        val = st.session_state.extracted_data.get(tag, "")
        updated_text[tag] = st.text_area(f"Edytuj pole: {tag}", value=val, height=100)
    
    st.divider()
    canvases = {}
    if st.session_state.sig_tags:
        st.write("🖋️ Podpisy (każdy tag to osobne okienko):")
        cols = st.columns(len(st.session_state.sig_tags))
        for i, tag in enumerate(st.session_state.sig_tags):
            with cols[i]:
                st.write(f"Podpis dla: **{tag}**")
                canvases[tag] = st_canvas(height=150, width=400, key=f"c_{tag}", background_color="#f5f5f5", display_toolbar=False)
    
    if st.button("🖨️ GENERUJ FINALNY RAPORT"):
        with st.spinner("Zapisywanie danych do Worda..."):
            doc = Document(io.BytesIO(st.session_state.template_bytes))
            
            for tag, val in updated_text.items():
                safe_replace(doc, tag, val)
            
            for tag, canv in canvases.items():
                safe_replace(doc, tag, "", is_image=True, canvas_data=canv)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Gotowe!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_finalny.docx")

    if st.button("⬅️ Wróć (nowe pliki)"):
        st.session_state.step = 1
        st.rerun()
