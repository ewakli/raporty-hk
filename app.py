import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Universal AI Word", layout="wide")

# --- INICJALIZACJA SESJI (Zapobieganie AttributeError) ---
if 'step' not in st.session_state: st.session_state.step = 1
if 'structure' not in st.session_state: st.session_state.structure = []
if 'ai_results' not in st.session_state: st.session_state.ai_results = {}
if 'word_template' not in st.session_state: st.session_state.word_template = None
if 'text_tags' not in st.session_state: st.session_state.text_tags = []

# --- KONFIGURACJA API ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# --- FUNKCJE ANALIZY ---
def get_docx_structure(docx_file):
    """Odczytuje dokument i znajduje tagi wraz z kontekstem"""
    doc = Document(docx_file)
    found_tags = []
    
    def extract_tags(text):
        return re.findall(r"\{\{(.*?)\}\}", text)

    # Szukanie w paragrafach
    for para in doc.paragraphs:
        tags = extract_tags(para.text)
        for t in tags:
            tag_type = 'signature' if any(x in t.lower() for x in ['podpis', 'sig']) else 'text'
            found_tags.append({"tag": t, "context": para.text.strip(), "type": tag_type})
            
    # Szukanie w tabelach
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                tags = extract_tags(cell.text)
                for t in tags:
                    tag_type = 'signature' if any(x in t.lower() for x in ['podpis', 'sig']) else 'text'
                    found_tags.append({"tag": t, "context": cell.text.strip(), "type": tag_type})
    
    return found_tags

# --- INTERFEJS ---
st.title("📑 Inteligentny Generator Word HK")

# KROK 1: Ładowanie i Analiza
if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1:
        uploaded_word = st.file_uploader("1. Wgraj wzór WORD", type="docx")
    with c2:
        uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia (liczniki, klucze, kody)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🔍 ANALIZUJ DOKUMENT I ZDJĘCIA"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje strukturę i zdjęcia..."):
                try:
                    # 1. Analiza struktury
                    st.session_state.structure = get_docx_structure(uploaded_word)
                    
                    # 2. Zdjęcia
                    b64_imgs = [base64.b64encode(f.read()).decode('utf-8') for f in uploaded_imgs]
                    
                    # 3. Prompt do AI
                    prompt = f"""
                    Jesteś ekspertem biura nieruchomości. 
                    Oto lista miejsc do wypełnienia w Wordzie (tagi {{...}}) wraz z tekstem obok:
                    {st.session_state.structure}
                    
                    Przeanalizuj zdjęcia. Skup się na:
                    - KLUCZE: ile kompletów, opis (piwnica, listy, śmietnik).
                    - KODY: do klatki (domofon), do szlabanu, do skrytki.
                    - LICZNIKI: energia, woda, gaz.
                    
                    Zwróć WYŁĄCZNIE JSON, gdzie kluczem jest nazwa tagu, a wartością treść.
                    Format: {{"nazwa_tagu": "dokładna treść"}}
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
                except Exception as e:
                    st.error(f"Wystąpił błąd podczas analizy: {e}")

# KROK 2: Weryfikacja i Podpisy
elif st.session_state.step == 2:
    if not st.session_state.structure:
        st.warning("Brak danych do wyświetlenia. Wróć do Kroku 1.")
        if st.button("⬅️ Wróć do początku"):
            st.session_state.step = 1
            st.rerun()
        st.stop()

    st.subheader("📝 Zweryfikuj dane sczytane przez AI")
    
    final_data = {}
    text_items = [i for i in st.session_state.structure if i['type'] == 'text']
    
    # Wyświetlanie pól do edycji
    for item in text_items:
        tag = item['tag']
        val = st.session_state.ai_results.get(tag, "")
        final_data[tag] = st.text_area(f"Pole: {tag} (Kontekst: {item['context']})", value=val, key=f"input_{tag}")

    st.divider()
    
    # Sekcja podpisów
    sig_items = [i for i in st.session_state.structure if i['type'] == 'signature']
    canvases = {}
    if sig_items:
        st.subheader("🖋️ Podpisy")
        cols = st.columns(len(sig_items))
        for idx, sig in enumerate(sig_items):
            with cols[idx]:
                st.write(f"Złóż podpis: {sig['tag']}")
                canvases[sig['tag']] = st_canvas(
                    height=150, width=280, key=f"canvas_{sig['tag']}", 
                    background_color="#f0f0f0", display_toolbar=False
                )

    # Generowanie pliku
    if st.button("🖨️ GENERUJ FINALNY WORD"):
        with st.spinner("Składanie dokumentu..."):
            doc = Document(io.BytesIO(st.session_state.word_template))
            
            # Podmiana tekstów
            for tag, value in final_data.items():
                placeholder = "{{" + tag + "}}"
                for para in doc.paragraphs:
                    if placeholder in para.text: para.text = para.text.replace(placeholder, str(value))
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            if placeholder in cell.text: cell.text = cell.text.replace(placeholder, str(value))

            # Podmiana podpisów
            for tag, canvas in canvases.items():
                if canvas is not None and canvas.image_data is not None:
                    img = Image.fromarray(canvas.image_data.astype('uint8'), 'RGBA')
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    buf.seek(0)
                    
                    placeholder = "{{" + tag + "}}"
                    for para in doc.paragraphs:
                        if placeholder in para.text:
                            para.text = para.text.replace(placeholder, "")
                            para.add_run().add_picture(buf, width=Inches(1.5))

            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Gotowe!")
            st.download_button("📥 POBIERZ RAPORT", out.getvalue(), "raport_hk.docx")

    if st.button("🗑️ Zacznij od nowa"):
        st.session_state.step = 1
        st.session_state.structure = []
        st.rerun()
