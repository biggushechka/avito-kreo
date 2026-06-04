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
SYSTEM_DEFAULTS_FILE = os.path.join(DATA_DIR, "system_defaults.json")

def load_system_defaults() -> dict:
    # Baseline fallback defaults with empty credentials in git
    defaults = {
        "gemini_api_key": "",
        "yandex_token": "",
        "yandex_client_id": "",
        "yandex_client_secret": "",
        "gemini_proxy": "",
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
    
    # Try to load custom defaults from system_defaults.json on the server/host
    if os.path.exists(SYSTEM_DEFAULTS_FILE):
        try:
            with open(SYSTEM_DEFAULTS_FILE, "r", encoding="utf-8") as f:
                saved_defaults = json.load(f)
                for k, v in saved_defaults.items():
                    if v: # Only override if the value is not empty
                        defaults[k] = v
        except Exception as e:
            logger.error(f"Error loading system_defaults.json: {e}")
            
    return defaults

DEFAULT_CONFIG = load_system_defaults()

def load_config() -> dict:
    defaults = load_system_defaults()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # Merge with default config to ensure all keys are present and not empty
                for k, v in defaults.items():
                    if k not in config or not config[k]:
                        config[k] = v
                return config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
    return defaults.copy()

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
    yandex_client_id: Optional[str] = ""
    yandex_client_secret: Optional[str] = ""
    gemini_proxy: Optional[str] = ""
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
    if masked_config.get("yandex_client_id"):
        masked_config["yandex_client_id"] = masked_config["yandex_client_id"][:4] + "..." + masked_config["yandex_client_id"][-4:]
    if masked_config.get("yandex_client_secret"):
        masked_config["yandex_client_secret"] = masked_config["yandex_client_secret"][:4] + "..." + masked_config["yandex_client_secret"][-4:]
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

    yandex_client_id = data.yandex_client_id.strip() if data.yandex_client_id else ""
    if yandex_client_id and "..." in yandex_client_id:
        yandex_client_id = current_config.get("yandex_client_id", "")

    yandex_client_secret = data.yandex_client_secret.strip() if data.yandex_client_secret else ""
    if yandex_client_secret and "..." in yandex_client_secret:
        yandex_client_secret = current_config.get("yandex_client_secret", "")
        
    google_service_account_json = data.google_service_account_json.strip() if data.google_service_account_json else ""
    if google_service_account_json and "*установлен*" in google_service_account_json:
        google_service_account_json = current_config.get("google_service_account_json", "")

    updated = {
        "gemini_api_key": gemini_api_key,
        "yandex_token": yandex_token,
        "yandex_client_id": yandex_client_id,
        "yandex_client_secret": yandex_client_secret,
        "gemini_proxy": data.gemini_proxy.strip() if data.gemini_proxy else "",
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
        gemini = GeminiHandler(config["gemini_api_key"], proxy=config.get("gemini_proxy"))
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
        handler = GeminiHandler(api_key, proxy=config.get("gemini_proxy"))
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
        handler = GeminiHandler(api_key, proxy=config.get("gemini_proxy"))
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
    prompt_fields: str
    prompt_instruction: Optional[str] = ""

# Global state for background scanning task
table_generator_status = {
    "active": False,
    "progress": 0.0,
    "current_folder": "",
    "logs": [],
    "error": "",
    "result_headers": [],
    "result_tsv": ""
}

def add_log(msg: str):
    logger.info(msg)
    table_generator_status["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    if len(table_generator_status["logs"]) > 200:
        table_generator_status["logs"] = table_generator_status["logs"][-200:]

def escape_tsv_cell(val: Any) -> str:
    s = str(val) if val is not None else ""
    if "\n" in s or "\t" in s or '"' in s:
        # Wrap in quotes and double internal quotes as per standard RFC 4180
        s = s.replace('"', '""')
        return f'"{s}"'
    return s

def run_table_generation_task(yandex_folder_path: str, prompt_fields: str, prompt_instruction: str):
    global table_generator_status
    table_generator_status["active"] = True
    table_generator_status["progress"] = 0.0
    table_generator_status["current_folder"] = ""
    table_generator_status["logs"] = []
    table_generator_status["error"] = ""
    table_generator_status["result_headers"] = []
    table_generator_status["result_tsv"] = ""
    
    try:
        add_log("Запуск процесса сборки таблицы для копирования...")
        config = load_config()
        gemini_key = config.get("gemini_api_key")
        yandex_token = config.get("yandex_token")
        
        if not gemini_key:
            raise Exception("Gemini API Key не настроен в конфигурации.")
        if not yandex_token:
            raise Exception("Яндекс.Диск OAuth токен не настроен в конфигурации.")
            
        # Parse prompt_fields
        field_names = [f.strip() for f in prompt_fields.split(",") if f.strip()]
        if not field_names:
            raise Exception("Не указаны поля для извлечения. Укажите хотя бы одно поле (например, Название, Цена).")
            
        add_log(f"Поля для извлечения ИИ: {field_names}")
        
        add_log(f"Сканирование директории Яндекс.Диска: {yandex_folder_path}...")
        yandex_handler = YandexDiskHandler(yandex_token)
        gemini_handler = GeminiHandler(gemini_key, proxy=config.get("gemini_proxy"))
        
        if not yandex_handler.check_directory_exists(yandex_folder_path):
            raise Exception(f"Папка {yandex_folder_path} не найдена на Яндекс.Диске.")
            
        subdirs = yandex_handler.list_subdirectories(yandex_folder_path)
        
        # Check if we have categories starting with '!'
        categories = [d for d in subdirs if d.startswith("!")]
        
        products_to_process = []
        image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        doc_extensions   = {".docx", ".doc", ".txt"}
        pricing_keywords = ["стоимост", "цен", "прайс", "price", "54 44"]
        
        def collect_files_and_images(path: str):
            """
            Рекурсивно собирает все файлы изображений и документов в указанной папке
            и её подпапках на Яндекс.Диске (глубина рекурсии 2).
            """
            images = []
            docs = []
            try:
                files = yandex_handler.list_files(path)
                for f in files:
                    ext = os.path.splitext(f["name"])[1].lower()
                    if ext in image_extensions:
                        images.append(f)
                    elif ext in doc_extensions:
                        docs.append(f)
                
                # Получаем подпапки 1-го уровня
                try:
                    subdirs = yandex_handler.list_subdirectories(path)
                    for sub in subdirs:
                        sub_path = f"{path.rstrip('/')}/{sub}"
                        try:
                            sub_files = yandex_handler.list_files(sub_path)
                            for sf in sub_files:
                                ext = os.path.splitext(sf["name"])[1].lower()
                                if ext in image_extensions:
                                    images.append(sf)
                                elif ext in doc_extensions:
                                    docs.append(sf)
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception as e:
                add_log(f"Предупреждение при сканировании {path}: {e}")
            return images, docs

        def read_docx(file_info: dict) -> str:
            """Скачивает docx/doc/txt файл с Яндекс.Диска и возвращает текст."""
            local_temp = os.path.join(TEMP_UPLOADS_DIR, f"temp_desc_{int(time.time() * 1000)}_{os.path.basename(file_info['name'])}")
            try:
                yandex_handler.download_file(file_info["path"], local_temp)
                text = docx_parser.extract_text_from_file(local_temp)
                return text or ""
            except Exception as e:
                add_log(f"Ошибка чтения {file_info['name']}: {e}")
                return ""
            finally:
                if os.path.exists(local_temp):
                    try:
                        os.remove(local_temp)
                    except Exception:
                        pass
        
        if categories:
            add_log(f"Обнаружены папки категорий (начинаются с '!'): {categories}")
            for cat_name in categories:
                cat_path = f"{yandex_folder_path.rstrip('/')}/{cat_name}"
                add_log(f"Сканирование категории {cat_name}...")
                
                # List files in category folder (for docx / pricing info)
                cat_files = yandex_handler.list_files(cat_path)
                cat_docs = [f for f in cat_files if os.path.splitext(f["name"])[1].lower() in doc_extensions]
                
                # Read all category-level docs
                cat_description_text = ""
                cat_pricing_text = ""
                for doc in cat_docs:
                    try:
                        add_log(f"Чтение файла описания категории {cat_name}: {doc['name']}...")
                        text = read_docx(doc)
                        if text:
                            if any(kw in doc["name"].lower() for kw in pricing_keywords):
                                cat_pricing_text += f"\n--- Файл {doc['name']} ---\n{text}\n"
                            else:
                                cat_description_text += f"\n--- Файл {doc['name']} ---\n{text}\n"
                    except Exception as doc_err:
                        add_log(f"Ошибка чтения файла {doc['name']}: {doc_err}")
                
                # List subdirectories (the actual products/models)
                model_dirs = yandex_handler.list_subdirectories(cat_path)
                
                if model_dirs:
                    add_log(f"В категории {cat_name} найдено моделей: {len(model_dirs)}")
                    for model_name in model_dirs:
                        model_path = f"{cat_path}/{model_name}"
                        
                        # Collect images and documents inside the model folder recursively
                        model_images, model_docs = collect_files_and_images(model_path)
                        
                        # Read model-level documents
                        model_desc_text = ""
                        model_pricing_text = ""
                        for doc in model_docs:
                            try:
                                add_log(f"Чтение файла модели {model_name}: {doc['name']}...")
                                text = read_docx(doc)
                                if text:
                                    if any(kw in doc["name"].lower() for kw in pricing_keywords):
                                        model_pricing_text += f"\n--- Файл {doc['name']} ---\n{text}\n"
                                    else:
                                        model_desc_text += f"\n--- Файл {doc['name']} ---\n{text}\n"
                            except Exception as doc_err:
                                add_log(f"Ошибка чтения файла модели {doc['name']}: {doc_err}")
                        
                        # Combine category and model contexts
                        combined_desc = (cat_description_text + "\n" + model_desc_text).strip()
                        combined_pricing = (cat_pricing_text + "\n" + model_pricing_text).strip()
                        
                        products_to_process.append({
                            "name": model_name,
                            "folder_path": model_path,
                            "description_text": combined_desc,
                            "pricing_text": combined_pricing,
                            "category": cat_name.lstrip("!").strip(),
                            "image_files": model_images
                        })
                else:
                    # Treat category itself as one product
                    add_log(f"В категории {cat_name} не найдено подпапок моделей. Обрабатываем её как один товар.")
                    cat_images, cat_docs = collect_files_and_images(cat_path)
                    
                    products_to_process.append({
                        "name": cat_name.lstrip("!").strip(),
                        "folder_path": cat_path,
                        "description_text": cat_description_text,
                        "pricing_text": cat_pricing_text,
                        "category": cat_name.lstrip("!").strip(),
                        "image_files": cat_images
                    })
        else:
            # Traditional behavior: each subdirectory is a product
            add_log(f"Папки категорий с '!' не найдены. Обрабатываем подпапки как товары.")
            for folder_name in subdirs:
                folder_path = f"{yandex_folder_path.rstrip('/')}/{folder_name}"
                add_log(f"Сканирование папки товара: {folder_name}...")
                
                images, docs = collect_files_and_images(folder_path)
                
                description_text = ""
                pricing_text = ""
                for doc in docs:
                    try:
                        add_log(f"Чтение файла товара {folder_name}: {doc['name']}...")
                        text = read_docx(doc)
                        if text:
                            if any(kw in doc["name"].lower() for kw in pricing_keywords):
                                pricing_text += f"\n--- {doc['name']} ---\n{text}\n"
                            else:
                                description_text += f"\n--- {doc['name']} ---\n{text}\n"
                    except Exception as doc_err:
                        add_log(f"Ошибка чтения файла товара {doc['name']}: {doc_err}")
                        
                products_to_process.append({
                    "name": folder_name,
                    "folder_path": folder_path,
                    "description_text": description_text,
                    "pricing_text": pricing_text,
                    "category": "",
                    "image_files": images
                })
                
        if not products_to_process:
            add_log("Обработка завершена: нет товаров для сканирования.")
            table_generator_status["progress"] = 100.0
            return
            
        total_products = len(products_to_process)
        add_log(f"Всего товаров для обработки ИИ: {total_products}")
        
        # Build headers: field_names + "Ссылка на фото" (all image links in a single column)
        headers = field_names + ["Ссылка на фото"]
        table_generator_status["result_headers"] = headers
        
        # Construct TSV header line
        tsv_lines = [ "\t".join(headers) ]
        table_generator_status["result_tsv"] = tsv_lines[0] + "\n"
        
        # Phase 2: Process each product
        for idx, item in enumerate(products_to_process):
            product_name = item["name"]
            category = item["category"]
            table_generator_status["current_folder"] = product_name
            current_progress = round((idx / total_products) * 100, 1)
            table_generator_status["progress"] = current_progress
            
            add_log(f"=== [{idx + 1}/{total_products}] Извлечение данных: {product_name} ===")
            
            description_text = item["description_text"]
            pricing_text     = item["pricing_text"]
            
            combined_context = ""
            if description_text.strip():
                combined_context += f"=== ОПИСАНИЕ / КОМПЛЕКТАЦИЯ ===\n{description_text}\n"
            if pricing_text.strip():
                combined_context += f"=== ПРАЙС-ЛИСТ (СТОИМОСТЬ МОДЕЛЕЙ) ===\n{pricing_text}\n"
            
            product_info = {field: "" for field in field_names}
            
            # Pre-populate category/вид строения field if present and we know it
            if category:
                for field in field_names:
                    if field.lower() in ["вид строения", "категория"]:
                        product_info[field] = category
            
            if combined_context.strip():
                add_log("Форматирование и извлечение данных через Gemini...")
                json_template = ", ".join([f'"{f}": "значение"' for f in field_names])
                
                category_part = f' из категории "{category}"' if category else ""
                
                gemini_prompt = f"""Ты помогаешь собрать таблицу товаров для маркетплейса Авито.

Категория{category_part}. Текущая папка/модель: "{product_name}"

Контекст (описание и прайс-лист стоимости):
{combined_context}

Задача: извлеки из предоставленного контекста значения для следующих полей КОНКРЕТНО для модели "{product_name}":
{', '.join(field_names)}

Правила заполнения:
1. "Название" — извлеки и приведи в читаемый вид реальное коммерческое название модели. Если название папки малоинформативно (например, 'Новая папка', 'Новая папка (2)', 'модель без названия', 'АВИТО БАНИ (1)' и т.д.), то обязательно найди и извлеки красивое и точное название модели из текста описания или характеристик (например, 'Беседка каркасная 3х5м', 'Баня-бочка Квадро 2x2м').
2. "Цена" — найди точную стоимость ИМЕННО этой модели в прайс-листе. Модель может упоминаться сокращенно или частично (например, "МБ 11" или "сауна 2.4х4.9" для папки "МБ 11 сауна(2.4х4.9)"). 
КРИТИЧЕСКИ ВАЖНО: 
- Если цена для конкретной модели "{product_name}" не найдена в предоставленном прайс-листе, верни пустую строку "". 
- Не придумывай цену и не бери вместо цены технические характеристики или размеры (такие как размеры фундамента, толщина доски '5-10 см', сечение блоков '200х200х400' и т.д.).
- Значение цены должно обязательно содержать денежные единицы (руб., ₽) и относиться именно к стоимости модели "{product_name}". Если указано несколько комплектаций (например, стеновой комплект и под ключ), перечисли их через запятую (например, "136 400 ₽ (комплект), 391 000 ₽ (под ключ)").
3. "Описание" — составь подробное маркетинговое описание конкретно для этой модели на основе контекста (2-4 предложения).
4. "Параметры" — укажи размеры, габариты и комплектацию модели (например, '3х5 м, сухая древесина'). Если размеров нет, оставь пустую строку "".
5. "Вид строения" — тип постройки: {category if category else 'определи из контекста'} (например, Баня, Беседка, Хозблок, Садовый дом).
6. Если какое-либо поле не удаётся заполнить на основе контекста, верни пустую строку "".

Пользовательские инструкции:
{prompt_instruction or 'Заполни поля максимально точно.'}

Ответ строго в формате JSON без каких-либо пояснений и разметки markdown (только валидный JSON-объект):
{{
   {json_template}
}}"""
                try:
                    gemini_res_str = gemini_handler.generate_text(gemini_prompt)
                    clean_json = gemini_res_str.strip()
                    for prefix in ["```json", "```"]:
                        if clean_json.startswith(prefix):
                            clean_json = clean_json[len(prefix):]
                    if clean_json.endswith("```"):
                        clean_json = clean_json[:-3]
                    clean_json = clean_json.strip()
                    
                    parsed = json.loads(clean_json)
                    for field in field_names:
                        # Only overwrite pre-populated category if Gemini returned something valid
                        val = str(parsed.get(field, "") or "").strip()
                        if val:
                            product_info[field] = val
                    add_log(f"Успешный разбор полей ИИ!")
                except Exception as gemini_err:
                    add_log(f"Предупреждение: Ошибка анализа Gemini ({gemini_err}). Используем fallback.")
                    # Keep pre-populated
                    if field_names and not product_info.get(field_names[0]):
                        product_info[field_names[0]] = product_name
            else:
                add_log("Описание отсутствует, используем имя папки.")
                if field_names and not product_info.get(field_names[0]):
                    product_info[field_names[0]] = product_name

            # Ensure Category field is populated
            if category:
                for field in field_names:
                    if field.lower() in ["вид строения", "категория"] and not product_info.get(field):
                        product_info[field] = category
            
            # Publish photos
            photo_urls = []
            image_files = item["image_files"]
            if image_files:
                add_log(f"Публикация {len(image_files)} фото для товара {product_name}...")
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
                
            # Compile row: fields + comma-separated photo links in one cell
            photo_cell = ", ".join(photo_urls)
            row_data = [product_info.get(field, "") for field in field_names] + [photo_cell]
                
            # Convert to TSV row with cell escaping
            tsv_row = "\t".join([escape_tsv_cell(cell) for cell in row_data])
            tsv_lines.append(tsv_row)
            
            # Update status in real-time
            table_generator_status["result_tsv"] = "\n".join(tsv_lines)
            add_log(f"Товар успешно обработан и добавлен в таблицу!")
            
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
        prompt_fields=request.prompt_fields,
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
