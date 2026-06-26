import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Universal Reporter Pro", layout="wide")

# --- KONFIGURACJA API ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Skonfiguruj OPENAI_API_KEY w Secrets!")
    st.stop()

# --- INICJALIZACJA SESJI ---
if 'step' not in st.session_state: st.session_state.step = 1
if 'extracted' not in st.session_state: st.session_state.extracted = {}
if 't_tags' not in st.session_state: st.session_state.t_tags = []
if 's_tags' not in st.session_state: st.session_state.s_tags = []

# --- FUNKCJE ---
def resize_img(file):
    img = Image.open(file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((1200, 1200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def find_all_tags(docx_bytes):
    doc = Document(io.BytesIO(docx_bytes))
    full_text = ""
    for p in doc.paragraphs: full_text += p.text + " "
    for t in doc.tables:
        for r in t.rows:
            for c in r.cells: full_text += c.text + " "
    
    found = re.findall(r"\{\{(.*?)\}\}", full_text)
    tags = [t.strip() for t in found if t.strip()]
    
    # Podział na tekstowe i podpisy (uniwersalny)
    text_tags = [t for t in set(tags) if 'podpis' not in t.lower() and 'sig' not in t.lower()]
    sig_tags = [t for t in set(tags) if 'podpis' in t.lower() or 'sig' in t.lower()]
    return text_tags, sig_tags

def inject_data(doc, text_map, sig_map):
    """Wstawia dane i obrazy w miejsca tagów {{tag}}"""
    def process_paragraphs(paragraphs):
        for p in paragraphs:
            # 1. Tekst - obsługa uniwersalna
            for tag, val in text_map.items():
                target = "{{" + tag + "}}"
                if target in p.text:
                    p.text = p.text.replace(target, str(val))
            
            # 2. Podpisy - obsługa uniwersalna dla każdego tagu
            for tag, canv in sig_map.items():
                target = "{{" + tag + "}}"
                if target in p.text and canv.image_data is not None:
                    # Sprawdzamy czy użytkownik faktycznie coś narysował
                    if canv.image_data.any():
                        p.text = p.text.replace(target, "")
                        img = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                        b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                        run = p.add_run()
                        run.add_picture(b, width=Inches(1.8))

    process_paragraphs(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                process_paragraphs(cell.paragraphs)

# --- KROK 1: ANALIZA ---
st.title("📄 Uniwersalny Generator Raportów Word")

if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1: uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with c2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia wizyty", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🚀 ANALIZUJ I PRZYGOTUJ FORMULARZ"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje szczegóły zdjęć..."):
                word_bytes = uploaded_word.read()
                t_tags, s_tags = find_all_tags(word_bytes)
                st.session_state.t_tags = t_tags
                st.session_state.s_tags = s_tags
                st.session_state.template = word_bytes
                
                b64_imgs = [resize_img(f) for f in uploaded_imgs]
                
                # UNIWERSALNY PROMPT - nie dotyczy tylko kluczy, ale każdego pola
                prompt = f"""
                Jesteś ekspertem analizy dokumentacji. Przeanalizuj zdjęcia.
                Twoim zadaniem jest dostarczenie danych dla następujących pól: {t_tags}.
                
                Zasady:
                1. Opisuj KAŻDY szczegół, który widzisz. 
                2. Jeśli pole dotyczy listy przedmiotów, wymień KAŻDY z nich osobno (np. nie pisz 'meble', napisz '1x szafa, 2x krzesło dębowe').
                3. Absolutny ZAKAZ STRESZCZANIA lub uogólniania informacji. 
                4. Jeśli widzisz numery, kody lub liczby, podaj je precyzyjnie.
                
                Zwróć TYLKO czysty JSON: {{"nazwa_tagu": "szczegółowa_wartość"}}
                """
                
                res = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                    response_format={"type": "json_object"}
                )
                
                st.session_state.extracted = json.loads(res.choices[0].message.content)
                st.session_state.step = 2
                st.rerun()

# --- KROK 2: EDYCJA I PODPISY ---
elif st.session_state.step == 2:
    st.subheader("📝 Zweryfikuj sczytane dane i podpisz")
    
    # Formularz edycji
    updated_text = {}
    for tag in st.session_state.t_tags:
        val = st.session_state.extracted.get(tag, "")
        updated_text[tag] = st.text_area(f"Pole we wzorze: {tag}", value=val, height=120)
    
    st.divider()
    
    # Dynamiczne okienka podpisów
    updated_sigs = {}
    if st.session_state.s_tags:
        st.subheader("🖋️ Podpisy (złóż podpis w każdym polu)")
        for tag in st.session_state.s_tags:
            st.write(f"Podpis dla miejsca: **{tag}**")
            updated_sigs[tag] = st_canvas(
                height=150, width=400, key=f"c_{tag}", 
                background_color="#f9f9f9", display_toolbar=False
            )

    if st.button("🖨️ GENERUJ DOKUMENT WORD"):
        with st.spinner("Składanie dokumentu..."):
            doc = Document(io.BytesIO(st.session_state.template))
            inject_data(doc, updated_text, updated_sigs)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Gotowe!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_hk.docx")

    if st.button("⬅️ Wróć i zmień pliki"):
        st.session_state.step = 1; st.rerun()
