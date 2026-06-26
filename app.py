import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Word AI v4", layout="wide")

# --- KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

if 'step' not in st.session_state: st.session_state.step = 1
if 'data' not in st.session_state: st.session_state.data = {}

# --- FUNKCJE POMOCNICZE ---
def resize_image(image_file):
    img = Image.open(image_file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1024, 1024))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def get_tags(docx_file):
    doc = Document(docx_file)
    full_text = ""
    for p in doc.paragraphs: full_text += p.text + " "
    for t in doc.tables:
        for r in t.rows:
            for c in r.cells: full_text += c.text + " "
    
    found = re.findall(r"\{\{(.*?)\}\}", full_text)
    # Czyścimy tagi ze spacji na początku i końcu
    cleaned = [t.strip() for t in found if t.strip() != ""]
    text_tags = [t for t in set(cleaned) if 'podpis' not in t.lower()]
    sig_tags = [t for t in set(cleaned) if 'podpis' in t.lower()]
    return text_tags, sig_tags

def replace_text_in_paragraph(paragraph, key, value, is_signature=False, canvas_data=None):
    """Zaawansowana funkcja podmieniająca tagi na tekst lub obraz"""
    # Szukamy tagu ignorując spacje wewnątrz klamer: {{ tag }}
    search_pattern = r"\{\{\s*" + re.escape(key) + r"\s*\}\}"
    
    if re.search(search_pattern, paragraph.text):
        if is_signature and canvas_data is not None:
            if canvas_data.image_data is not None:
                # Usuwamy tekst tagu
                paragraph.text = re.sub(search_pattern, "", paragraph.text)
                # Wstawiamy obraz
                img = Image.fromarray(canvas_data.image_data.astype('uint8'), 'RGBA')
                b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                run = paragraph.add_run()
                run.add_picture(b, width=Inches(2.0))
        else:
            # Zwykła podmiana tekstu
            paragraph.text = re.sub(search_pattern, str(value), paragraph.text)

def process_word_document(doc_bytes, text_map, sig_map):
    doc = Document(io.BytesIO(doc_bytes))
    
    # 1. Przetwarzamy paragrafy
    for p in doc.paragraphs:
        for tag, val in text_map.items():
            replace_text_in_paragraph(p, tag, val)
        for tag, canv in sig_map.items():
            replace_text_in_paragraph(p, tag, "", is_signature=True, canvas_data=canv)
            
    # 2. Przetwarzamy tabele
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for tag, val in text_map.items():
                        replace_text_in_paragraph(p, tag, val)
                    for tag, canv in sig_map.items():
                        replace_text_in_paragraph(p, tag, "", is_signature=True, canvas_data=canv)
    return doc

# --- INTERFEJS ---
st.title("📑 Generator Home Keeper v4")

if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1: uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with c2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia wizyty", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🚀 ANALIZUJ I PRZYGOTUJ"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje dokument..."):
                t_tags, s_tags = get_tags(uploaded_word)
                st.session_state.t_tags = t_tags
                st.session_state.s_tags = s_tags
                
                b64_imgs = [resize_image(f) for f in uploaded_imgs]
                
                prompt = f"""
                Jesteś ekspertem ds. nieruchomości. Przeanalizuj zdjęcia.
                Wypełnij te pola z dokumentu: {t_tags}.
                Zwróć WYŁĄCZNIE czysty JSON: {{"tag": "wartość"}}. 
                Nie dodawaj żadnego innego tekstu.
                """
                
                try:
                    res = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[{"role":"user","content":[{"type":"text","text":prompt},
                        *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                        response_format={"type": "json_object"}
                    )
                    
                    st.session_state.data = json.loads(res.choices[0].message.content)
                    uploaded_word.seek(0); st.session_state.template_bytes = uploaded_word.read()
                    st.session_state.step = 2
                    st.rerun()
                except Exception as e:
                    st.error(f"Błąd: {e}")

elif st.session_state.step == 2:
    st.subheader("📝 Sprawdź i podpisz")
    
    final_text_map = {}
    for tag in st.session_state.t_tags:
        val = st.session_state.data.get(tag, "")
        final_text_map[tag] = st.text_area(f"Pole: {tag}", value=val, height=100)
    
    st.divider()
    final_sig_map = {}
    if st.session_state.s_tags:
        st.write("🖋️ Podpisy:")
        cols = st.columns(len(st.session_state.s_tags))
        for i, tag in enumerate(st.session_state.s_tags):
            with cols[i]:
                st.write(f"Złóż podpis dla: **{tag}**")
                final_sig_map[tag] = st_canvas(height=150, width=350, key=f"c_{tag}", background_color="#f5f5f5", display_toolbar=False)

    if st.button("🖨️ GENERUJ PLIK WORD"):
        with st.spinner("Zastępowanie tagów i wstawianie podpisów..."):
            final_doc = process_word_document(st.session_state.template_bytes, final_text_map, final_sig_map)
            
            out = io.BytesIO()
            final_doc.save(out)
            st.success("✅ Gotowe!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_finalny.docx")

    if st.button("⬅️ Zacznij od nowa"):
        st.session_state.step = 1; st.rerun()
