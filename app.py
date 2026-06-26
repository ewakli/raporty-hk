import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Pro v7 - Fixed Signatures", layout="wide")

# --- 1. KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Skonfiguruj klucz API!")
    st.stop()

if 'step' not in st.session_state: st.session_state.step = 1
if 'data' not in st.session_state: st.session_state.data = {}

# --- 2. FUNKCJE TECHNICZNE ---
def resize_image(image_file):
    img = Image.open(image_file)
    if img.mode != "RGB": img = img.convert("RGB")
    img.thumbnail((1200, 1200))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def get_tags(docx_bytes):
    doc = Document(io.BytesIO(docx_bytes))
    full_text = ""
    # Czytamy wszystko (akapity i tabele)
    for p in doc.paragraphs: full_text += p.text + " "
    for t in doc.tables:
        for r in t.rows:
            for c in r.cells: full_text += c.text + " "
    
    found = re.findall(r"\{\{(.*?)\}\}", full_text)
    cleaned = [t.strip() for t in found if t.strip()]
    
    # Rozdzielamy: wszystko co ma "podpis" idzie do sekcji podpisów
    text_tags = [t for t in set(cleaned) if 'podpis' not in t.lower()]
    sig_tags = [t for t in set(cleaned) if 'podpis' in t.lower()]
    return text_tags, sig_tags

def apply_final_changes(doc, text_map, sig_map):
    """Pancerna metoda podmiany: tekst po tekście, obraz po obrazie"""
    
    # 1. Zbieramy wszystkie akapity (z dokumentu głównego i tabel)
    all_paras = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_paras.extend(cell.paragraphs)

    for p in all_paras:
        p_text_orig = p.text
        if "{{" not in p_text_orig:
            continue

        # PODMIANA PODPISÓW (Priorytet)
        for sig_tag, canv in sig_map.items():
            pattern = r"\{\{\s*" + re.escape(sig_tag) + r"\s*\}\}"
            if re.search(pattern, p_text_orig):
                if canv.image_data is not None and canv.image_data.any():
                    # USUWAMY CAŁY TEKST AKAPITU, żeby tag nie został
                    for run in p.runs:
                        run.text = ""
                    p.text = "" 
                    # WSTAWIAMY OBRAZ
                    img = Image.fromarray(canv.image_data.astype('uint8'), 'RGBA')
                    b = io.BytesIO(); img.save(b, format='PNG'); b.seek(0)
                    p.add_run().add_picture(b, width=Inches(1.5))
                
        # PODMIANA TEKSTU
        for txt_tag, val in text_map.items():
            pattern = r"\{\{\s*" + re.escape(txt_tag) + r"\s*\}\}"
            if re.search(pattern, p.text):
                # Zamiana tekstu wewnątrz akapitu
                new_text = re.sub(pattern, str(val), p.text)
                p.text = new_text

# --- 3. INTERFEJS - KROK 1 ---
st.title("📄 Home Keeper Pro v7")

if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1: uploaded_word = st.file_uploader("1. Wgraj wzór Word (.docx)", type="docx")
    with c2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia wizyty", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🚀 ANALIZUJ I WYCIĄGNIJ SZCZEGÓŁY"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje zdjęcia... ZAKAZ STRESZCZANIA!"):
                w_bytes = uploaded_word.read()
                t_tags, s_tags = get_tags(w_bytes)
                st.session_state.t_tags = t_tags
                st.session_state.s_tags = s_tags
                st.session_state.template = w_bytes
                
                b64_imgs = [resize_image(f) for f in uploaded_imgs]
                
                prompt = f"""
                Jesteś rzeczoznawcą. Przeanalizuj zdjęcia i wypełnij te pola: {t_tags}.
                ZASADA: WYPISZ KAŻDY ELEMENT OSOBNO. Nie używaj ogólników typu '3 klucze'. 
                Napisz np. '1x piwnica, 1x Gerda, 1x pilot szlaban'. 
                ZAKAZ STRESZCZANIA. Jeśli czegoś nie ma, zostaw puste.
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

# --- 4. INTERFEJS - KROK 2 ---
elif st.session_state.step == 2:
    st.subheader("📝 Edycja danych i Podpisy")
    
    # Edycja danych tekstowych
    col_edit, col_sig = st.columns([1, 1])
    
    with col_edit:
        st.write("🔍 **Sprawdź treść:**")
        updated_text = {}
        for tag in st.session_state.t_tags:
            val = st.session_state.data.get(tag, "")
            updated_text[tag] = st.text_area(f"Pole: {tag}", value=val, height=100)
    
    with col_sig:
        st.write("🖋️ **Złóż podpisy:**")
        final_sigs = {}
        for tag in st.session_state.s_tags:
            st.write(f"Podpis dla: **{tag}**")
            final_sigs[tag] = st_canvas(
                height=150, width=400, key=f"sig_{tag}", 
                background_color="#f5f5f5", display_toolbar=False
            )

    if st.button("🖨️ GENERUJ RAPORT FINALNY"):
        with st.spinner("Budowanie dokumentu..."):
            doc = Document(io.BytesIO(st.session_state.template))
            apply_final_changes(doc, updated_text, final_sigs)
            
            out = io.BytesIO()
            doc.save(out)
            st.success("✅ Gotowe!")
            st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_hk.docx")

    if st.button("⬅️ Zacznij od nowa"):
        st.session_state.step = 1; st.rerun()
