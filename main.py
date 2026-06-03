import os
import sys
import json
import uvicorn
import webbrowser
import threading
import time
import shutil
from typing import List, Dict, Any, Optional
import re
from fastapi import FastAPI, HTTPException, Request, Response, Depends, Cookie, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Google API modules
from google.oauth2 import service_account
from googleapiclient.discovery import build

import docx_parser
from gemini_handler import GeminiHandler
from yandex_disk_handler import YandexDiskHandler

# Initialize FastAPI app
app = FastAPI(title="Generator Kreo API")

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session tracking for single-user authentication
active_sessions = set()

# HTTP Middleware to verify session tokens for all api routes (except login/logout)
@app.middleware("http")
async def check_session_middleware(request: Request, call_next):
    path = request.url.path
    # Allow static files, login/logout, and root page
    if (
        path.startswith("/static") or 
        path.startswith("/temp_uploads") or 
        path == "/api/login" or 
        path == "/api/logout" or 
        path == "/"
    ):
        return await call_next(request)
        
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in active_sessions:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        
    return await call_next(request)

# Constants
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TEMP_UPLOADS_DIR = os.path.join(DATA_DIR, "temp_uploads")

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TEMP_UPLOADS_DIR, exist_ok=True)

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(DATA_DIR, "app.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger("generator_kreo")

# Default configuration structure
DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "yandex_token": "",
    "google_service_account_json": "",
    "default_local_dir": os.path.join(DATA_DIR, "local_output"),
    "default_yandex_dir": "/Generator_Kreo",
    "global_context": (
        "Продукт: Современные бани-бочки формы «Квадро» (закругленный квадрат) двух размеров: 2х2 метра и 2х4 метра под ключ.\n"
        "УТП:\n"
        "- Доступная цена: 2х2 от 185 000 ₽, 2х4 от 299 000 ₽ под ключ.\n"
        "- 9 цветов пропитки дерева на выбор.\n"
        "- Надежные стяжные обручи с регулировкой натяжения.\n"
        "Материалы:\n"
        "- Качественный профилированный брус с пропиткой теплого коньячно-каштанового оттенка (орех/тик).\n"
        "- Кровля — мягкая черепица «соты» бордово-черного цвета.\n"
        "Установка:\n"
        "- Быстрая доставка манипулятором и установка на 4 бетонных блока с подсыпкой из щебня на дачном участке за 1 день.\n"
        "Площадка:\n"
        "- Реклама для Авито. Картинки должны быть реалистичными любительскими фотографиями готовых бань на дачных участках (снятыми на смартфон), чтобы вызывать максимальное доверие покупателей."
    ),
    "visual_style": (
        "Cozy modern wooden bathhouse, warm and inviting atmosphere. "
        "High-end photorealistic design, warm dramatic golden hour lighting, "
        "detailed wood textures, steam rising gently, cinematic composition, 8k resolution, no text."
    ),
    "generation_delay_sec": 5
}

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # Merge with default config to ensure all keys are present
                for k, v in DEFAULT_CONFIG.items():
                    if k not in config:
                        config[k] = v
                return config
        except Exception as e:
            print(f"Error loading config: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(config: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")

# Models
class ConfigModel(BaseModel):
    gemini_api_key: str
    yandex_token: str
    google_service_account_json: Optional[str] = ""
    default_local_dir: str
    default_yandex_dir: str
    global_context: str
    visual_style: str
    generation_delay_sec: int = 5

class AnalyzeRequest(BaseModel):
    local_ad_input: str
    references: Optional[List[str]] = []

class GenerateRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "1:1"

class UploadRequest(BaseModel):
    local_file_path: str
    disk_file_path: str

class SaveLocalRequest(BaseModel):
    image_base64: str
    folder_path: str
    filename: str

class StyleGuideRequest(BaseModel):
    references: List[str]

# API Routes
@app.get("/api/config")
def get_config():
    config = load_config()
    # Return masked credentials for security
    masked_config = config.copy()
    if masked_config.get("gemini_api_key"):
        masked_config["gemini_api_key"] = masked_config["gemini_api_key"][:4] + "..." + masked_config["gemini_api_key"][-4:]
    if masked_config.get("yandex_token"):
        masked_config["yandex_token"] = masked_config["yandex_token"][:4] + "..." + masked_config["yandex_token"][-4:]
    if masked_config.get("google_service_account_json"):
        # Display short helper text in UI to confirm it is configured
        masked_config["google_service_account_json"] = "{\n  \"type\": \"service_account\",\n  \"private_key\": \"*установлен (скрыт)*\"\n}"
    return masked_config

@app.post("/api/config")
def update_config(data: ConfigModel):
    current_config = load_config()
    
    # Only update API key/Token if they are not the masked ones
    gemini_api_key = data.gemini_api_key.strip()
    if "..." in gemini_api_key:
        gemini_api_key = current_config.get("gemini_api_key", "")
        
    yandex_token = data.yandex_token.strip()
    if "..." in yandex_token:
        yandex_token = current_config.get("yandex_token", "")
        
    google_service_account_json = data.google_service_account_json.strip() if data.google_service_account_json else ""
    if google_service_account_json and "*установлен*" in google_service_account_json:
        google_service_account_json = current_config.get("google_service_account_json", "")

    updated = {
        "gemini_api_key": gemini_api_key,
        "yandex_token": yandex_token,
        "google_service_account_json": google_service_account_json,
        "default_local_dir": data.default_local_dir.strip(),
        "default_yandex_dir": data.default_yandex_dir.strip(),
        "global_context": data.global_context,
        "visual_style": data.visual_style,
        "generation_delay_sec": data.generation_delay_sec
    }
    
    save_config(updated)
    return {"status": "success", "message": "Configuration saved successfully."}

@app.post("/api/check-apis")
def check_apis():
    config = load_config()
    gemini_ok = False
    yandex_ok = False
    
    if config.get("gemini_api_key"):
        gemini = GeminiHandler(config["gemini_api_key"])
        gemini_ok = gemini.check_connection()
        
    if config.get("yandex_token"):
        yandex = YandexDiskHandler(config["yandex_token"])
        yandex_ok = yandex.check_connection()
        
    return {
        "gemini_connected": gemini_ok,
        "yandex_connected": yandex_ok
    }

@app.post("/api/analyze")
def analyze_ad(request: AnalyzeRequest):
    config = load_config()
    api_key = config.get("gemini_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key is not set in configuration.")
    
    try:
        handler = GeminiHandler(api_key)
        result = handler.generate_marketing_slots(
            global_context=config.get("global_context", ""),
            visual_style=config.get("visual_style", ""),
            local_ad_input=request.local_ad_input,
            references=request.references or []
        )
        return result
    except Exception as e:
        logger.exception("Error in /api/analyze")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate-image")
def generate_image(request: GenerateRequest):
    config = load_config()
    api_key = config.get("gemini_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key is not set in configuration.")
    
    try:
        logger.info(f"Generating image with prompt: {request.prompt[:100]}...")
        handler = GeminiHandler(api_key)
        image_bytes = handler.generate_image(prompt=request.prompt, aspect_ratio=request.aspect_ratio)
        
        # Save image temporarily
        temp_filename = f"temp_gen_{int(time.time() * 1000)}.jpg"
        temp_path = os.path.join(TEMP_UPLOADS_DIR, temp_filename)
        with open(temp_path, "wb") as f:
            f.write(image_bytes)
            
        logger.info(f"Image generated and saved temporarily to {temp_path}")
        return {
            "temp_file_path": temp_path,
            "filename": temp_filename
        }
    except Exception as e:
        logger.exception("Error in /api/generate-image")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload-yandex")
def upload_yandex(request: UploadRequest):
    config = load_config()
    token = config.get("yandex_token")
    if not token:
        raise HTTPException(status_code=400, detail="Yandex.Disk OAuth Token is not set in configuration.")
    
    try:
        handler = YandexDiskHandler(token)
        public_url = handler.upload_file(
            local_file_path=request.local_file_path,
            disk_file_path=request.disk_file_path
        )
        if not public_url:
            raise HTTPException(status_code=500, detail="Failed to upload file or retrieve public URL from Yandex.Disk.")
            
        return {"public_url": public_url}
    except Exception as e:
        logger.exception("Error in /api/upload-yandex")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save-local")
def save_local_file(request: UploadRequest):
    """Saves a temporary generated file to the user's specified local folder."""
    try:
        src = request.local_file_path
        dest = request.disk_file_path  # We reuse the field name for destination path
        
        if not os.path.exists(src):
            raise HTTPException(status_code=400, detail="Source file not found")
            
        dest_dir = os.path.dirname(dest)
        os.makedirs(dest_dir, exist_ok=True)
        
        shutil.copy2(src, dest)
        return {"saved_path": dest}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class SaveBase64Request(BaseModel):
    image_base64: str
    temp_file_path: str

@app.post("/api/save-base64")
def save_base64_image(request: SaveBase64Request):
    """Saves a client-rendered base64 image (containing text overlay) back to the server, overwriting the temp file."""
    import base64
    try:
        data = request.image_base64
        if "," in data:
            data = data.split(",")[1]
        
        image_bytes = base64.b64decode(data)
        
        # Verify the path is within TEMP_UPLOADS_DIR or restrict it
        file_path = request.temp_file_path
        # Normalize and ensure it is in the temp uploads folder
        filename = os.path.basename(file_path)
        secure_path = os.path.join(TEMP_UPLOADS_DIR, filename)
            
        with open(secure_path, "wb") as f:
            f.write(image_bytes)
            
        logger.info(f"Overwrote temp file with base64 image: {secure_path}")
        return {"status": "success", "temp_file_path": secure_path}
    except Exception as e:
        logger.exception("Error in /api/save-base64")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload-references")
async def upload_references(files: List[UploadFile] = File(...)):
    """Upload visual style reference files to temp storage."""
    saved_files = []
    try:
        for file in files:
            # Secure file name and path
            filename = f"ref_{int(time.time() * 1000)}_{file.filename}"
            dest_path = os.path.join(TEMP_UPLOADS_DIR, filename)
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            saved_files.append(dest_path)
        return {"saved_files": saved_files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate-style-guide")
def generate_style_guide(request: StyleGuideRequest):
    """Analyze references and write style guide text using Gemini."""
    config = load_config()
    api_key = config.get("gemini_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Gemini API Key is not set in configuration.")
    if not request.references:
        raise HTTPException(status_code=400, detail="No reference images provided.")
    try:
        handler = GeminiHandler(api_key)
        style_guide = handler.generate_style_guide_from_references(request.references)
        return {"style_guide": style_guide}
    except Exception as e:
        logger.exception("Error in /api/generate-style-guide")
        raise HTTPException(status_code=500, detail=str(e))

# Setup Static files routing
static_dir = os.path.join(BASE_DIR, "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

# Mount static folder
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.mount("/temp_uploads", StaticFiles(directory=TEMP_UPLOADS_DIR), name="temp_uploads")

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/login")
def login(data: LoginRequest, response: Response):
    # Username: 89284483992, Password: QL3EFfyLaW
    if data.username.strip() == "89284483992" and data.password == "QL3EFfyLaW":
        import uuid
        token = str(uuid.uuid4())
        active_sessions.add(token)
        # Set httponly secure session cookie
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=7 * 24 * 3600
        )
        return {"status": "success", "message": "Logged in successfully."}
    raise HTTPException(status_code=400, detail="Неверный логин или пароль")

@app.post("/api/logout")
def logout(response: Response, session_token: Optional[str] = Cookie(None)):
    if session_token in active_sessions:
        active_sessions.remove(session_token)
    response.delete_cookie("session_token")
    return {"status": "success", "message": "Logged out successfully."}

@app.get("/")
def read_root(request: Request):
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in active_sessions:
        login_file = os.path.join(static_dir, "login.html")
        if os.path.exists(login_file):
            with open(login_file, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>Generator Kreo</h1><p>Login page not found.</p>")
        
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Generator Kreo</h1><p>index.html not found.</p>")

class TableGeneratorRequest(BaseModel):
    yandex_folder_path: str
    google_sheet_url: str
    tab_name: str = "Лист1"
    prompt_instruction: Optional[str] = ""

# Global state for background scanning task
table_generator_status = {
    "active": False,
    "progress": 0.0,
    "current_folder": "",
    "logs": [],
    "error": ""
}

def add_log(msg: str):
    logger.info(msg)
    table_generator_status["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    if len(table_generator_status["logs"]) > 200:
        table_generator_status["logs"] = table_generator_status["logs"][-200:]

def run_table_generation_task(yandex_folder_path: str, google_sheet_url: str, tab_name: str, prompt_instruction: str):
    global table_generator_status
    table_generator_status["active"] = True
    table_generator_status["progress"] = 0.0
    table_generator_status["current_folder"] = ""
    table_generator_status["logs"] = []
    table_generator_status["error"] = ""
    
    try:
        add_log("Запуск процесса генерации таблицы...")
        config = load_config()
        gemini_key = config.get("gemini_api_key")
        yandex_token = config.get("yandex_token")
        sa_json = config.get("google_service_account_json")
        
        if not gemini_key:
            raise Exception("Gemini API Key не настроен в конфигурации.")
        if not yandex_token:
            raise Exception("Яндекс.Диск OAuth токен не настроен в конфигурации.")
        if not sa_json:
            raise Exception("Ключ сервисного аккаунта Google Sheets не настроен в конфигурации.")
            
        sheet_id_match = re.search(r"/d/([a-zA-Z0-9-_]+)", google_sheet_url)
        sheet_id = sheet_id_match.group(1) if sheet_id_match else google_sheet_url.strip()
        add_log(f"Определен ID Google Таблицы: {sheet_id}")
        
        add_log("Подключение к Google Sheets API...")
        try:
            info = json.loads(sa_json)
            creds = service_account.Credentials.from_service_account_info(
                info,
                scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
            sheets_service = build('sheets', 'v4', credentials=creds)
            res = sheets_service.spreadsheets().values().get(
                spreadsheetId=sheet_id,
                range=f"{tab_name}!A1:Z1"
            ).execute()
            headers = res.get('values', [[]])[0]
            add_log(f"Подключение успешно! Колонок найдено: {len(headers)}")
        except Exception as sheet_err:
            raise Exception(f"Ошибка подключения к Google Sheets: {sheet_err}")
            
        mapping = {}
        for idx, h in enumerate(headers):
            h_lower = h.lower().strip()
            if any(x in h_lower for x in ["название", "заголовок", "title", "модель"]):
                mapping["title"] = idx
            elif any(x in h_lower for x in ["описание", "description", "текст"]):
                mapping["description"] = idx
            elif any(x in h_lower for x in ["цена", "price"]):
                mapping["price"] = idx
            elif any(x in h_lower for x in ["параметр", "характеристик", "parameter", "специфик"]):
                mapping["parameters"] = idx
            elif any(x in h_lower for x in ["фото", "картинк", "image", "url", "ссылка"]):
                if "photos" not in mapping:
                    mapping["photos"] = []
                mapping["photos"].append(idx)
                
        add_log(f"Карта колонок: {mapping}")
        
        add_log(f"Сканирование директории Яндекс.Диска: {yandex_folder_path}...")
        yandex_handler = YandexDiskHandler(yandex_token)
        if not yandex_handler.check_directory_exists(yandex_folder_path):
            raise Exception(f"Папка {yandex_folder_path} не найдена на Яндекс.Диске.")
            
        subdirs = yandex_handler.list_subdirectories(yandex_folder_path)
        add_log(f"Найдено подпапок товаров: {len(subdirs)}")
        
        if not subdirs:
            add_log("Обработка завершена: нет подпапок для сканирования.")
            table_generator_status["progress"] = 100.0
            return
            
        total_folders = len(subdirs)
        
        for folder_idx, folder_name in enumerate(subdirs):
            table_generator_status["current_folder"] = folder_name
            current_progress = round((folder_idx / total_folders) * 100, 1)
            table_generator_status["progress"] = current_progress
            
            add_log(f"=== [{folder_idx + 1}/{total_folders}] Обработка товара: {folder_name} ===")
            folder_full_path = f"{yandex_folder_path.rstrip('/')}/{folder_name}"
            
            files = yandex_handler.list_files(folder_full_path)
            
            image_extensions = [".jpg", ".jpeg", ".png", ".webp", ".bmp"]
            image_files = []
            text_files = []
            
            for file_info in files:
                name = file_info["name"]
                ext = os.path.splitext(name)[1].lower()
                if ext in image_extensions:
                    image_files.append(file_info)
                elif ext in [".txt", ".docx", ".doc"]:
                    text_files.append(file_info)
                    
            add_log(f"Найдено фото: {len(image_files)}, текстов: {len(text_files)}")
            
            raw_text = ""
            if text_files:
                txt_file = text_files[0]
                add_log(f"Чтение файла описания: {txt_file['name']}...")
                local_temp_path = os.path.join(TEMP_UPLOADS_DIR, f"temp_desc_{int(time.time())}{os.path.splitext(txt_file['name'])[1]}")
                yandex_handler.download_file(txt_file["path"], local_temp_path)
                raw_text = docx_parser.extract_text_from_file(local_temp_path)
                if os.path.exists(local_temp_path):
                    os.remove(local_temp_path)
                add_log(f"Размер текста: {len(raw_text)} символов.")
            else:
                add_log(f"Файл описания не найден. Будем использовать имя папки '{folder_name}'.")
                raw_text = f"Имя товара: {folder_name}"
                
            add_log("Форматирование и извлечение данных через Gemini...")
            gemini_handler = GeminiHandler(gemini_key)
            
            product_info = {
                "title": folder_name,
                "price": "",
                "parameters": "",
                "description": raw_text
            }
            
            try:
                gemini_prompt = f"""
                Тебе дан текст описания товара. Вытащи из него ключевую информацию и составь продающее структурированное объявление для Авито.
                
                Верни ответ СТРОГО в формате JSON с четырьмя ключами (все значения должны быть строками):
                {{
                  "title": "Короткое название товара для заголовка объявления Авито",
                  "price": "Стоимость товара цифрами (например, '185000'), если цена не найдена - оставь пустым",
                  "parameters": "Ключевые параметры/спецификации через запятую (например: '2х2 метра, форма квадро, печь в подарок')",
                  "description": "Продающий структурированный текст объявления для Авито. Используй абзацы, списки, привлекательные выгоды и смайлики."
                }}
                
                Пользовательские требования к тексту:
                {prompt_instruction or 'Сделай текст привлекательным для покупателей на Авито.'}
                
                Текст описания товара:
                {raw_text}
                """
                
                gemini_res_str = gemini_handler.generate_text(gemini_prompt)
                
                clean_json = gemini_res_str.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                clean_json = clean_json.strip()
                
                parsed_json = json.loads(clean_json)
                product_info["title"] = parsed_json.get("title", folder_name) or folder_name
                product_info["price"] = parsed_json.get("price", "") or ""
                product_info["parameters"] = parsed_json.get("parameters", "") or ""
                product_info["description"] = parsed_json.get("description", raw_text) or raw_text
                add_log(f"Успешный разбор! Заголовок: {product_info['title']}, Цена: {product_info['price']}")
            except Exception as gemini_err:
                add_log(f"Предупреждение: Ошибка анализа Gemini ({gemini_err}). Используем fallback.")
                
            photo_urls = []
            if image_files:
                add_log(f"Публикация {len(image_files)} фото на Яндекс.Диске...")
                for img_info in image_files:
                    try:
                        pub_url = yandex_handler.publish_and_get_link(img_info["path"])
                        if pub_url:
                            photo_urls.append(pub_url)
                    except Exception as img_err:
                        add_log(f"Ошибка публикации {img_info['name']}: {img_err}")
                add_log(f"Опубликовано ссылок: {len(photo_urls)}")
            else:
                add_log("Фото не найдены.")
                
            if headers:
                row_data = [""] * len(headers)
                if "title" in mapping:
                    row_data[mapping["title"]] = product_info["title"]
                if "price" in mapping:
                    row_data[mapping["price"]] = product_info["price"]
                if "description" in mapping:
                    row_data[mapping["description"]] = product_info["description"]
                if "parameters" in mapping:
                    row_data[mapping["parameters"]] = product_info["parameters"]
                    
                if "photos" in mapping and photo_urls:
                    for photo_col_idx, pub_url in enumerate(photo_urls):
                        if photo_col_idx < len(mapping["photos"]):
                            target_col = mapping["photos"][photo_col_idx]
                            row_data[target_col] = pub_url
                        else:
                            break
            else:
                row_data = [
                    product_info["title"],
                    product_info["price"],
                    product_info["description"],
                    product_info["parameters"],
                    *photo_urls
                ]
                
            add_log("Добавление строки в Google Таблицу...")
            sheets_service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f"{tab_name}!A:Z",
                valueInputOption='USER_ENTERED',
                insertDataOption='INSERT_ROWS',
                body={"values": [row_data]}
            ).execute()
            add_log(f"Строка успешно записана!")
            
            # Wait to avoid Rate Limit errors
            time.sleep(config.get("generation_delay_sec", 5))
            
        add_log("=== РАБОТА ПОЛНОСТЬЮ ЗАВЕРШЕНА! ===")
        table_generator_status["progress"] = 100.0
        
    except Exception as e:
        logger.exception("Error in run_table_generation_task")
        table_generator_status["error"] = str(e)
        add_log(f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
    finally:
        table_generator_status["active"] = False

@app.post("/api/table-generator/scan")
def start_table_generation(request: TableGeneratorRequest, background_tasks: BackgroundTasks):
    if table_generator_status["active"]:
        raise HTTPException(status_code=400, detail="Задача генерации таблицы уже запущена.")
        
    background_tasks.add_task(
        run_table_generation_task,
        yandex_folder_path=request.yandex_folder_path,
        google_sheet_url=request.google_sheet_url,
        tab_name=request.tab_name,
        prompt_instruction=request.prompt_instruction
    )
    return {"status": "success", "message": "Фоновый процесс генерации таблицы запущен."}

@app.get("/api/table-generator/status")
def get_table_generator_status():
    return table_generator_status

def open_browser():
    """Wait for server to start, then open standard web browser."""
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == "__main__":
    # Start browser thread
    threading.Thread(target=open_browser, daemon=True).start()
    # Run server
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
