import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Pro v6 - Totalna Precyzja", layout="wide")

# --- 1. KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

if 'step' not in st.session_state: st.session_state.step = 1
if 'extracted_data' not in st.session_state: st.session_state.extracted_data = {}

# --- 2. PANCERNE FUNKCJE WORD ---
def clean_tag_name(tag):
    """Czyści nazwę tagu ze spacji i znaków specjalnych dla stabilności"""
    return tag.strip()

def get_tags_from_docx(docx_bytes):
    doc = Document(io.BytesIO(docx_bytes))
    full_text = ""
    for p in doc.paragraphs: full_text += p.text + " "
    for t in doc.tables:
        for r in t.rows:
            for c in r.cells: full_text += c.text + " "
    
    found = re.findall(r"\{\{(.*?)\}\}", full_text)
    # Zapisujemy tagi dokładnie tak jak są, ale bez spacji na brzegach
    cleaned = [t.strip() for t in found if t.strip()]
    text_tags = [t for t in set(cleaned) if 'podpis' not in t.lower()]
    sig_tags = [t for t in set(cleaned) if 'podpis' in t.lower()]
    return text_tags, sig_tags

def apply_data_to_doc(doc, text_map, sig_map):
    """Najbardziej odporna metoda zamiany tagów na dane"""
    all_paras = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_paras.extend(cell.paragraphs)

    for p in all_paras:
        # Próbujemy scalić rozbite tagi wewnątrz paragrafu (Word XML fix)
        full_p_text = p.text
        
        # 1. Podmiana Tekstu
        for tag, val in text_map.items():
            # Regex szukający {{ tag }} z dowolną ilością białych znaków (spacje, twarde spacje, itp.)
            pattern = re.compile(r"\{\{\s*" + re.escape(tag) + r"\s*\}\}", re.IGNORECASE)
            if pattern.search(full_p_text):
                full_p_text = pattern.sub(str(val), full_p_text)
                p.text = full_p_text # Aktualizujemy tekst paragrafu

        # 2. Podmiana Podpisów
        for tag, canv in sig_map.items():
            pattern = re.compile(r"\{\{\s*" + re.escape(tag) + r"\s*\}\}", re.IGNORECASE)
            if pattern.search(p.text):
                if canv.image_data is not None and canv.image_data.any():
                    # Usuwamy tekst tagu i wstawiamy obraz
                    p.text = pattern.sub("", p.text)
                    img = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                    b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                    run = p.add_run()
                    run.add_picture(b, width=Inches(1.8))

def compress_img(file):
    img = Image.open(file)
    if img.mode != "RGB": img = img.convert("RGB")
    img.thumbnail((1200, 1200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- 3. KROK 1: ANALIZA ---
st.title("🏗️ Home Keeper Pro v6")

if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1: uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with c2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia wizyty", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🚀 ANALIZUJ I WYCIĄGNIJ DETALE"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje zdjęcia... Pamiętaj: ZAKAZ STRESZCZANIA!"):
                word_data = uploaded_word.read()
                t_tags, s_tags = get_tags_from_docx(word_data)
                st.session_state.t_tags = t_tags
                st.session_state.s_tags = s_tags
                st.session_state.template = word_data
                
                b64_imgs = [compress_img(f) for f in uploaded_imgs]
                
                # Super-Prompt wymuszający brak skrótów
                prompt = f"""
                Jesteś ekspertem ds. inwentaryzacji. Przeanalizuj zdjęcia i wypełnij te pola: {t_tags}.
                
                BARDZO WAŻNE REGUŁY:
                1. NIE STRESZCZAJ. Jeśli widzisz 5 kluczy, opisz każdy z nich (np. 1x piwniczny metalowy, 1x do skrzynki na listy, 2x wejściowy Gerda, 1x pilot szary).
                2. Jeśli pole dotyczy wyposażenia, wymień KAŻDY mebel i sprzęt osobno.
                3. Jeśli na zdjęciu jest kod (np. 1953), przypisz go do odpowiedniego pola kody.
                4. Twoja odpowiedź musi być bardzo szczegółowa. Dłuższy opis jest lepszy niż krótki.
                
                Zwróć WYŁĄCZNIE JSON: {{"tag": "szczegółowa_wartość"}}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.extracted_data = json.loads(res.choices[0].message.content)
                st.session_state.step = 2
                st.rerun()

# --- 4. KROK 2: WERYFIKACJA I PODPISY ---
elif st.session_state.step == 2:
    st.subheader("📝 Sprawdź sczytane dane")
    st.info("Poniżej widzisz co AI odczytało. Możesz to dowolnie dopisać lub zmienić przed generowaniem.")
    
    final_text_map = {}
    for tag in st.session_state.t_tags:
        val = st.session_state.extracted_data.get(tag, "")
        final_text_map[tag] = st.text_area(f"Edytuj pole: {tag}", value=val, height=120)
    
    st.divider()
    final_sig_map = {}
    if st.session_state.s_tags:
        st.subheader("🖋️ Podpisy")
        st.warning("Złóż podpis w KAŻDYM polu poniżej.")
        for tag in st.session_state.s_tags:
            st.write(f"Złóż podpis dla: **{tag}**")
            final_sig_map[tag] = st_canvas(
                height=150, width=450, key=f"sig_{tag}", 
                background_color="#f9f9f9", display_toolbar=False
            )

    if st.button("🖨️ GENERUJ FINALNY PLIK WORD"):
        with st.spinner("Zastępowanie danych w dokumencie..."):
            doc = Document(io.BytesIO(st.session_state.template))
            apply_data_to_doc(doc, final_text_map, final_sig_map)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Dokument gotowy!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_finalny.docx")

    if st.button("⬅️ Zacznij od nowa"):
        st.session_state.step = 1; st.rerun()
