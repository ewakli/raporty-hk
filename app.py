import streamlit as st
import openai
from docx import Document
import io, json, base64

st.set_page_config(page_title="HK Word Reporter", layout="wide")

# --- KONFIGURACJA ---
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API!")
    st.stop()

def get_placeholders(docx_file):
    """Wyciąga wszystkie tagi {{...}} z dokumentu Word"""
    doc = Document(docx_file)
    placeholders = set()
    for para in doc.paragraphs:
        for word in para.text.split():
            if "{{" in word and "}}" in word:
                # Oczyszczanie tagu
                tag = word[word.find("{{"):word.find("}}")+2]
                placeholders.add(tag.replace("{{", "").replace("}}", ""))
    return list(placeholders)

st.title("📑 Generator Raportów Word (Precyzyjny)")

# --- ŁADOWANIE PLIKÓW ---
col1, col2 = st.columns(2)
with col1:
    uploaded_docx = st.file_uploader("1. Wgraj WZÓR WORD (.docx)", type="docx")
with col2:
    uploaded_imgs = st.file_uploader("2. Wgraj ZDJĘCIA", type=["jpg", "png", "jpeg"], accept_multiple_files=True)

if uploaded_docx and uploaded_imgs:
    if st.button("🔍 ANALIZUJ I DOPASUJ DO WZORU"):
        with st.spinner("AI analizuje zdjęcia pod kątem Twoich znaczników..."):
            
            # 1. Znajdź tagi w dokumencie
            tags = get_placeholders(uploaded_docx)
            st.session_state.tags = tags
            
            # 2. Przygotuj zdjęcia
            b64_imgs = [base64.b64encode(f.read()).decode('utf-8') for f in uploaded_imgs]
            
            # 3. Prompt AI - dynamicznie prosimy o wypełnienie tylko tych tagów, które są w Wordzie
            tags_list = ", ".join(tags)
            prompt = f"""
            Jesteś asystentem biura nieruchomości. 
            Przeanalizuj zdjęcia i wyciągnij dane dla następujących pól: {tags_list}.
            Zwróć WYŁĄCZNIE JSON, gdzie klucze to nazwy pól, a wartości to dane ze zdjęć.
            Format: {{"nazwa_pola": "wartość"}}
            Jeśli czegoś nie ma na zdjęciu, wpisz "brak danych".
            """
            
            res = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role":"user","content":[{"type":"text","text":prompt},
                *[{"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{i}"}} for i in b64_imgs[:10]]]}],
                response_format={"type": "json_object"}
            )
            
            st.session_state.extracted_vals = json.loads(res.choices[0].message.content)
            st.session_state.docx_template = uploaded_docx.getvalue()

# --- EDYCJA I GENEROWANIE ---
if 'extracted_vals' in st.session_state:
    st.divider()
    st.subheader("📝 Sprawdź i popraw dane przed zapisem")
    
    final_data = {}
    for tag in st.session_state.tags:
        val = st.session_state.extracted_vals.get(tag, "")
        final_data[tag] = st.text_area(f"Pole: {tag}", value=val, key=f"input_{tag}")

    if st.button("🖨️ GENERUJ GOTOWY DOKUMENT"):
        # Otwórz Worda ponownie
        doc = Document(io.BytesIO(st.session_state.docx_template))
        
        # Podmień tagi na wartości
        for tag, value in final_data.items():
            full_tag = "{{" + tag + "}}"
            for para in doc.paragraphs:
                if full_tag in para.text:
                    para.text = para.text.replace(full_tag, str(value))
            
            # Przeszukaj też tabele, jeśli są we wzorze
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if full_tag in cell.text:
                            cell.text = cell.text.replace(full_tag, str(value))
        
        # Zapisz wynik
        out = io.BytesIO()
        doc.save(out)
        
        st.success("✅ Dokument wygenerowany!")
        st.download_button("📥 POBIERZ RAPORT (.docx)", out.getvalue(), "raport_finalny.docx")
