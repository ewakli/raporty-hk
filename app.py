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
                    # Resetujemy wskaźnik pliku i czytamy zawartość
                    f.seek(0)
                    content = f.read()
                    images_for_ai.append(base64.b64encode(content).decode('utf-8'))
                
                # 2. Analiza przez OpenAI GPT-4o
                prompt_text = """Jesteś inteligentnym asystentem biura nieruchomości. 
                Przeanalizuj zdjęcia i wypisz dane do protokołu w formacie JSON.
                Wymagane klucze w JSON: 
                - "data": "dzisiejsza data",
                - "wyposażenie": "lista mebli",
                - "stan_licznik_energia": "liczba z licznika",
                - "uwagi_techniczne": "krótki opis usterek lub brak",
                - "klucze": "ile i jakie klucze".
                Zwróć WYŁĄCZNIE czysty obiekt JSON."""

                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": prompt_text},
                        *[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}} for img in images_for_ai[:10]]
                    ]}],
                    response_format={ "type": "json_object" }
                )
                
                raw_content = response.choices[0].message.content
                data = json.loads(raw_content)

                # 3. Modyfikacja PDF
                # Plik wzor_home_keeper.pdf musi być w tym samym folderze na GitHub
                doc = fitz.open("wzor_home_keeper.pdf")
                page = doc[0]

                # Nanoszenie danych (Współrzędne dostosowane do Twojego wzoru)
                page.insert_text((120, 85), str(data.get('data', '')), fontsize=11, color=(0, 0, 0.5))
                page.insert_text((70, 280), str(data.get('wyposażenie', '')), fontsize=9, color=(0, 0, 0))
                page.insert_text((100, 525), str(data.get('stan_licznik_energia', '')), fontsize=11, color=(0, 0, 0))
                page.insert_text((70, 420), str(data.get('uwagi_techniczne', '')), fontsize=9, color=(0, 0, 0))
                page.insert_text((70, 630), str(data.get('klucze', '')), fontsize=9, color=(0, 0, 0))

                # 4. Wstawianie podpisów (zgodnie ze wzorem na dole strony)
                if sig_najemca.image_data is not None and sig_pracownik.image_data is not None:
                    # Podpis Najemcy (Lewo)
                    img_n = Image.fromarray(sig_najemca.image_data.astype('uint8'), 'RGBA')
                    buf_n = io.BytesIO()
                    img_n.save(buf_n, format="PNG")
                    page.insert_image(fitz.Rect(70, 780, 220, 830), stream=buf_n.getvalue())

                    # Podpis Pracownika (Prawo)
                    img_p = Image.fromarray(sig_pracownik.image_data.astype('uint8'), 'RGBA')
                    buf_p = io.BytesIO()
                    img_p.save(buf_p, format="PNG")
                    page.insert_image(fitz.Rect(370, 780, 520, 830), stream=buf_p.getvalue())

                # 5. Export pliku
                pdf_output = io.BytesIO()
                doc.save(pdf_output)
                doc.close()

                st.success("✅ Raport został wygenerowany pomyślnie!")
                st.download_button("📥 POBIERZ PROTOKÓŁ PDF", pdf_output.getvalue(), "protokol_home_keeper.pdf", "application/pdf")

            except Exception as e:
                st.error(f"Wystąpił błąd podczas generowania: {str(e)}")
