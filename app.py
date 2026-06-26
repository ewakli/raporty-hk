import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Smart Word AI", layout="wide")

# --- 1. CONFIG & STATE ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

if 'step' not in st.session_state: st.session_state.step = 1
if 'data' not in st.session_state: st.session_state.data = {}
if 't_tags' not in st.session_state: st.session_state.t_tags = []
if 's_tags' not in st.session_state: st.session_state.s_tags = []

# --- 2. LOGIKA WORD ---
def get_tags(docx_file):
    doc = Document(docx_file)
    all_text = ""
    for p in doc.paragraphs: all_text += p.text + " "
    for t in doc.tables:
        for r in t.rows:
            for c in r.cells: all_text += c.text + " "
    
    found = re.findall(r"\{\{(.*?)\}\}", all_text)
    cleaned = [t.strip() for t in found]
    text_tags = [t for t in set(cleaned) if 'podpis' not in t.lower()]
    sig_tags = [t for t in set(cleaned) if 'podpis' in t.lower()]
    return text_tags, sig_tags

def process_word(doc, text_map, sig_map):
    """Zastępuje tagi tekstem lub obrazem we wszystkich sekcjach"""
    def replace_in_paras(paras):
        for p in paras:
            # Tekst
            for tag, val in text_map.items():
                target = "{{" + tag + "}}"
                if target in p.text:
                    p.text = p.text.replace(target, str(val))
            # Podpisy
            for tag, canv in sig_map.items():
                target = "{{" + tag + "}}"
                if target in p.text and canv.image_data is not None:
                    p.text = p.text.replace(target, "")
                    img = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                    b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                    p.add_run().add_picture(b, width=Inches(1.8))

    replace_in_paras(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                replace_in_paras(cell.paragraphs)

# --- 3. KROK 1: ANALIZA ---
st.title("🏗️ Home Keeper Pro - Generator Word")

if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1: uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with c2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia wizyty", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🔍 ANALIZUJ DOKUMENT I ZDJĘCIA"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje szczegóły (liczniki, klucze, kody)..."):
                t_tags, s_tags = get_tags(uploaded_word)
                st.session_state.t_tags = t_tags
                st.session_state.s_tags = s_tags
                
                b64_imgs = []
                for f in uploaded_imgs:
                    f.seek(0); b64_imgs.append(base64.b64encode(f.read()).decode('utf-8'))
                
                prompt = f"""
                Jesteś ekspertem ds. protokołów nieruchomości. Przeanalizuj zdjęcia.
                Wypełnij te pola: {t_tags}.
                BARDZO WAŻNE WYTYCZNE:
                - Liczniki: podaj dokładny stan cyfrowy.
                - Klucze: wypisz ilość kompletów i każdy klucz osobno (np. piwnica, skrzynka, pilot szlaban).
                - Kody: odczytaj kody do klatek i domofonów.
                - Wyposażenie: lista mebli i sprzętów AGD.
                Zwróć TYLKO czysty JSON: {{"tag": "wartosc"}}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                content = res.choices[0].message.content
                if content:
                    st.session_state.data = json.loads(content)
                    uploaded_word.seek(0); st.session_state.template_bytes = uploaded_word.read()
                    st.session_state.step = 2
                    st.rerun()
                else:
                    st.error("AI nie zwróciło danych. Spróbuj mniejszą ilość zdjęć.")

# --- 4. KROK 2: EDYCJA I PODPISY ---
elif st.session_state.step == 2:
    st.subheader("📝 Edytuj dane sczytane przez AI")
    
    final_text_map = {}
    for tag in st.session_state.text_tags:
        val = st.session_state.data.get(tag, "")
        final_text_map[tag] = st.text_area(f"Pole: {tag}", value=val, height=100)
    
    st.divider()
    final_sig_map = {}
    if st.session_state.s_tags:
        st.subheader("🖋️ Podpisy (każdy tag to osobne okienko)")
        cols = st.columns(len(st.session_state.s_tags))
        for i, tag in enumerate(st.session_state.s_tags):
            with cols[i]:
                st.write(f"Złóż podpis: **{tag}**")
                final_sig_map[tag] = st_canvas(height=150, width=350, key=f"c_{tag}", background_color="#f0f0f0", display_toolbar=False)

    if st.button("🖨️ GENERUJ FINALNY PLIK WORD"):
        with st.spinner("Zapisywanie danych do Worda..."):
            doc = Document(io.BytesIO(st.session_state.template_bytes))
            process_word(doc, final_text_map, final_sig_map)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Gotowe!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_homekeeper.docx")

    if st.button("⬅️ Wróć"):
        st.session_state.step = 1; st.rerun()
