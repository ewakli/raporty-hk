import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Word AI v5 - Pancerna", layout="wide")

# --- 1. KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

if 'step' not in st.session_state: st.session_state.step = 1
if 'data' not in st.session_state: st.session_state.data = {}
if 't_tags' not in st.session_state: st.session_state.t_tags = []
if 's_tags' not in st.session_state: st.session_state.s_tags = []

# --- 2. FUNKCJE TECHNICZNE ---
def resize_image(image_file):
    img = Image.open(image_file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1200, 1200)) # Optymalna wielkość dla AI
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def get_tags_universal(docx_bytes):
    """Wyciąga tagi ze wszystkich zakamarków Worda"""
    doc = Document(io.BytesIO(docx_bytes))
    full_text = ""
    for p in doc.paragraphs: full_text += p.text + " "
    for t in doc.tables:
        for r in t.rows:
            for c in r.cells: full_text += c.text + " "
    
    found = re.findall(r"\{\{(.*?)\}\}", full_text)
    cleaned = [t.strip() for t in found if t.strip() != ""]
    text_tags = [t for t in set(cleaned) if 'podpis' not in t.lower()]
    sig_tags = [t for t in set(cleaned) if 'podpis' in t.lower()]
    return text_tags, sig_tags

def apply_to_doc(doc, text_map, sig_map):
    """Pancerna funkcja podmieniająca tagi (ignoruje spacje i rozbite runy)"""
    # Łączymy wszystkie paragrafy z dokumentu i tabel
    all_paras = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_paras.extend(cell.paragraphs)

    for p in all_paras:
        # 1. Podmiana Tekstowa
        for tag, val in text_map.items():
            # Regex szuka {{ tag }} ignorując dowolną ilość spacji
            pattern = re.compile(r"\{\{\s*" + re.escape(tag) + r"\s*\}\}")
            if pattern.search(p.text):
                p.text = pattern.sub(str(val), p.text)
        
        # 2. Podmiana Podpisów
        for tag, canv in sig_map.items():
            pattern = re.compile(r"\{\{\s*" + re.escape(tag) + r"\s*\}\}")
            if pattern.search(p.text) and canv.image_data is not None:
                # Sprawdź czy użytkownik faktycznie coś narysował
                if canv.image_data.any():
                    p.text = pattern.sub("", p.text) # Usuwamy tekst tagu
                    img = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                    b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                    run = p.add_run()
                    run.add_picture(b, width=Inches(1.8))

# --- 3. KROK 1: ANALIZA ---
st.title("🏗️ Home Keeper Pro v5")

if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1: uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with c2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia wizyty", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🚀 ANALIZUJ I WYCIĄGNIJ SZCZEGÓŁY"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje KAŻDY DETAL na zdjęciach..."):
                w_bytes = uploaded_word.read()
                t_tags, s_tags = get_tags_universal(w_bytes)
                st.session_state.t_tags = t_tags
                st.session_state.s_tags = s_tags
                st.session_state.template_bytes = w_bytes
                
                b64_imgs = [resize_image(f) for f in uploaded_imgs]
                
                # Ulepszony Prompt - AI nie może streszczać
                prompt = f"""
                Jesteś profesjonalnym rzeczoznawcą. Przeanalizuj zdjęcia.
                Wypełnij te pola z dokumentu: {t_tags}.
                
                INSTRUKCJA SZCZEGÓŁOWOŚCI:
                - WYPISZ KAŻDY ELEMENT OSOBNO. 
                - Jeśli widzisz klucze, wypisz: np. '1x piwnica, 1x skrzynka, 1x szlaban'. 
                - Nie pisz '3 klucze' ani 'komplet'. Wypisz wszystkie funkcje kluczy i kodów.
                - Podobnie z wyposażeniem: '2x szafka, 1x lampa' itd.
                - ZAKAZ STRESZCZANIA.
                
                Zwróć TYLKO czysty JSON: {{"tag": "wartość"}}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.data = json.loads(res.choices[0].message.content)
                st.session_state.step = 2
                st.rerun()

# --- 4. KROK 2: WERYFIKACJA I PODPISY ---
elif st.session_state.step == 2:
    st.subheader("📝 Sprawdź sczytane dane i podpisz")
    
    updated_text = {}
    for tag in st.session_state.t_tags:
        val = st.session_state.data.get(tag, "")
        updated_text[tag] = st.text_area(f"Pole: {tag}", value=val, height=100)
    
    st.divider()
    final_sigs = {}
    if st.session_state.s_tags:
        st.write("🖋️ Podpisy (każdy tag to osobne pole):")
        # Wyświetlamy podpisy jeden pod drugim dla wygody mobilnej
        for tag in st.session_state.s_tags:
            st.write(f"Złóż podpis dla miejsca: **{tag}**")
            final_sigs[tag] = st_canvas(
                height=160, width=400, key=f"c_{tag}", 
                background_color="#f9f9f9", display_toolbar=False
            )

    if st.button("🖨️ GENERUJ FINALNY RAPORT WORD"):
        with st.spinner("Składanie dokumentu..."):
            doc = Document(io.BytesIO(st.session_state.template_bytes))
            apply_to_doc(doc, updated_text, final_sigs)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Dokument wygenerowany pomyślnie!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_finalny.docx")

    if st.button("⬅️ Zacznij od nowa"):
        st.session_state.step = 1; st.rerun()
