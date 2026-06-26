import streamlit as st
import openai
import fitz  # PyMuPDF
import io
import json
import base64
import cv2
import numpy as np
from streamlit_drawable_canvas import st_canvas
from PIL import Image

# --- KONFIGURACJA POCZĄTKOWA ---
st.set_page_config(page_title="Home Keeper Mobile Report", layout="centered")

# Pobieranie klucza API z bezpiecznych ustawień Streamlit Secrets
if "OPENAI_API_KEY" in st.secrets:
    client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
else:
    st.error("Błąd: Brak klucza API w Secrets!")

# --- SYSTEM LOGOWANIA ---
if 'auth' not in st.session_state:
    st.session_state.auth = False

def login():
    st.title("🏠 Home Keeper System")
    user = st.text_input("Użytkownik")
    pw = st.text_input("Hasło", type="password")
    if st.button("Zaloguj się"):
        if user == "admin" and pw == "HK2024": # Tutaj zmień swoje hasło
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("Nieprawidłowe dane logowania.")

if not st.session_state.auth:
    login()
    st.stop()

# --- FUNKCJE POMOCNICZE ---
def process_video(video_bytes):
    """Wyciąga klatki z filmu dla AI"""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
        tmp.write(video_bytes)
        video_path = tmp.name
    
    cap = cv2.VideoCapture(video_path)
    frames = []
    while len(frames) < 10: # Pobierz 10 klatek z filmu
        ret, frame = cap.read()
        if not ret: break
        if int(cap.get(cv2.CAP_PROP_POS_FRAMES)) % 30 == 0:
            _, buffer = cv2.imencode('.jpg', frame)
            frames.append(base64.b64encode(buffer).decode('utf-8'))
    cap.release()
    return frames

# --- INTERFEJS UŻYTKOWNIKA ---
st.title("📝 Protokół Zdawczo-Odbiorczy")
st.write("Wypełnij raport używając aparatu i złóż podpisy.")

uploaded_files = st.file_uploader("Dodaj zdjęcia lub wideo (JPEG/MP4)", type=["jpg", "jpeg", "png", "mp4"], accept_multiple_files=True)

st.subheader("🖋️ Podpisy")
col1, col2 = st.columns(2)

with col1:
    st.caption("Najemca (Przejmujący)")
    sig_najemca = st_canvas(stroke_width=2, stroke_color="#000", background_color="#f0f0f0", height=150, width=280, key="sig_n")

with col2:
    st.caption("Pracownik (HK)")
    sig_pracownik = st_canvas(stroke_width=2, stroke_color="#000", background_color="#f0f0f0", height=150, width=280, key="sig_p")

# --- PROCES GENEROWANIA ---
if st.button("🚀 GENERUJ GOTOWY RAPORT PDF"):
    if not uploaded_files:
        st.warning("Najpierw wgraj zdjęcia lub wideo.")
    else:
        with st.spinner("AI analizuje dane i przygotowuje PDF..."):
            try:
                # 1. Przygotowanie obrazów dla AI
                images_for_ai = []
                for f in uploaded_files:
                    if f.type.startswith("image"):
                        images_for_ai.append(base64.b64encode(f.read()).decode('utf-8'))
                
                # 2. Analiza przez OpenAI GPT-4o
                prompt = """# 2. Analiza przez OpenAI GPT-4o
                prompt = """Jesteś inteligentnym asystentem biura nieruchomości. 
                Przeanalizuj zdjęcia i wypisz dane do protokołu w formacie JSON.
                Wymagane klucze w JSON: 
                - "data": "data wizyty",
                - "wyposażenie": "lista mebli i sprzętów",
                - "stan_licznik_energia": "sama liczba",
                - "uwagi_techniczne": "krótki opis usterek lub brak",
                - "klucze": "opis przekazanych kluczy".
                Ważne: Zwróć WYŁĄCZNIE czysty obiekt JSON, bez żadnych wstępów."""

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in images_for_ai[:10]]
                    ]}],
                    response_format={ "type": "json_object" } # <--- TO WYMUSZA POPRAWNY FORMAT
                )
                
                # Bezpieczne wczytywanie
                raw_content = response.choices[0].message.content
                data = json.loads(raw_content)."""

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in images_for_ai[:10]]
                    ]}]
                )
                
                data = json.loads(response.choices[0].message.content.replace("```json", "").replace("```", ""))

                # 3. Modyfikacja PDF
                # Upewnij się, że plik wzor_home_keeper.pdf jest w tym samym folderze na GitHub
                doc = fitz.open("wzor_home_keeper.pdf")
                page = doc[0]

                # Nanoszenie danych (Współrzędne przykładowe - dostosuj je)
                page.insert_text((100, 100), str(data.get('data', '')), fontsize=11, color=(0, 0, 0.6))
                page.insert_text((100, 250), str(data.get('wyposażenie', '')), fontsize=10)
                page.insert_text((100, 500), f"ENERGA: {data.get('stan_licznik_energia', '')}", fontsize=10)

                # 4. Wstawianie podpisów
                if sig_najemca.image_data is not None and sig_pracownik.image_data is not None:
                    # Najemca
                    img_n = Image.fromarray(sig_najemca.image_data.astype('uint8'), 'RGBA')
                    buf_n = io.BytesIO()
                    img_n.save(buf_n, format="PNG")
                    page.insert_image(fitz.Rect(70, 750, 220, 820), stream=buf_n.getvalue()) # Lewa linia

                    # Pracownik
                    img_p = Image.fromarray(sig_pracownik.image_data.astype('uint8'), 'RGBA')
                    buf_p = io.BytesIO()
                    img_p.save(buf_p, format="PNG")
                    page.insert_image(fitz.Rect(370, 750, 520, 820), stream=buf_p.getvalue()) # Prawa linia

                # 5. Export
                pdf_output = io.BytesIO()
                doc.save(pdf_output)
                doc.close()

                st.success("Raport gotowy!")
                st.download_button("📥 Pobierz Protokół PDF", pdf_output.getvalue(), "protokol_final.pdf", "application/pdf")

            except Exception as e:
                st.error(f"Błąd: {e}")
