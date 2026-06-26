import streamlit as st
import openai
from docx import Document
from docx.shared import Inches
import io, json, base64, re
from streamlit_drawable_canvas import st_canvas
from PIL import Image

st.set_page_config(page_title="HK Universal AI Word", layout="wide")

# --- KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")
    st.stop()

# --- FUNKCJE ANALIZY DOKUMENTU ---
def get_docx_structure(docx_file):
    """Odczytuje dokument i znajduje tagi wraz z kontekstem (tekstem obok)"""
    doc = Document(docx_file)
    found_tags = []
    
    def extract_from_text(text):
        return re.findall(r"\{\{(.*?)\}\}", text)

    # Przeszukujemy paragrafy
    for i, para in enumerate(doc.paragraphs):
        tags = extract_from_text(para.text)
        for t in tags:
            # Przekazujemy AI tekst paragrafu jako kontekst
            found_tags.append({"tag": t, "context": para.text, "type": "text"})
            
    # Przeszukujemy tabele
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                tags = extract_from_text(cell.text)
                for t in tags:
                    found_tags.append({"tag": t, "context": cell.text, "type": "text"})
    
    # Rozpoznajemy podpisy po nazwie tagu (jeśli zawiera 'podpis' lub 'sig')
    for item in found_tags:
        if any(x in item['tag'].lower() for x in ['podpis', 'sig']):
            item['type'] = 'signature'
            
    return found_tags

# --- INTERFEJS ---
st.title("📑 Uniwersalny Generator Word AI")
st.write("Wstaw we wzorze `{{}}` w dowolnym miejscu. AI samo zrozumie kontekst.")

if 'step' not in st.session_state: st.session_state.step = 1

if st.session_state.step == 1:
    c1, c2 = st.columns(2)
    with c1: uploaded_word = st.file_uploader("1. Wgraj wzór WORD", type="docx")
    with c2: uploaded_imgs = st.file_uploader("2. Wgraj zdjęcia (liczniki, klucze, notatki)", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

    if st.button("🔍 ANALIZUJ DOKUMENT I ZDJĘCIA"):
        if uploaded_word and uploaded_imgs:
            with st.spinner("AI analizuje strukturę dokumentu i czyta zdjęcia..."):
                # 1. Analiza tagów
                structure = get_docx_structure(uploaded_word)
                st.session_state.structure = structure
                
                # 2. Zdjęcia
                b64_imgs = [base64.b64encode(f.read()).decode('utf-8') for f in uploaded_imgs]
                
                # 3. Prompt do AI - Bardzo szczegółowy dla kluczy i kodów
                prompt = f"""
                Jesteś ekspertem biura nieruchomości. 
                Oto lista tagów znalezionych w dokumencie Word wraz z ich kontekstem (tekstem otaczającym):
                {structure}
                
                Twoje zadanie:
                1. Przeanalizuj zdjęcia. Skup się na KAŻDYM detalu.
                2. Jeśli widnieją informacje o kluczach, wypisz: liczbę kompletów, opis każdego klucza (np. piwnica, skrzynka) oraz wszystkie KODY (do klatki, szlabanu). Nie pomijaj niczego.
                3. Dopasuj te informacje do tagów na podstawie ich kontekstu.
                
                Zwróć WYŁĄCZNIE JSON, gdzie kluczem jest nazwa tagu, a wartością treść do wpisania.
                Pomiń tagi typu 'signature'.
                JSON format: {{"nazwa_tagu": "wyczerpująca treść"}}
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

elif st.session_state.step == 2:
    st.subheader("📝 Weryfikacja danych")
    
    # Wyświetlamy tylko pola tekstowe do edycji
    final_data = {}
    text_items = [i for i in st.session_state.structure if i['type'] == 'text']
    
    for item in text_items:
        tag = item['tag']
        val = st.session_state.ai_results.get(tag, "")
        final_data[tag] = st.text_area(f"Kontekst: {item['context']}", value=val, key=f"ed_{tag}")

    st.divider()
    
    # Podpisy
    sig_items = [i for i in st.session_state.structure if i['type'] == 'signature']
    canvases = {}
    if sig_items:
        st.subheader("🖋️ Podpisy")
        cols = st.columns(len(sig_items))
        for idx, sig in enumerate(sig_items):
            with cols[idx]:
                st.write(f"Podpis: {sig['tag']}")
                canvases[sig['tag']] = st_canvas(height=150, width=250, key=f"can_{sig['tag']}", background_color="#f0f0f0", display_toolbar=False)

    if st.button("🖨️ GENERUJ FINALNY WORD"):
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
            if canvas.image_data is not None:
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

    if st.button("⬅️ Wróć"):
        st.session_state.step = 1
        st.rerun()
