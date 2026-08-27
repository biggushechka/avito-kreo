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
    defaults = {
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        "yandex_token": os.environ.get("YANDEX_TOKEN", ""),
        "yandex_client_id": os.environ.get("YANDEX_CLIENT_ID", "bb9d4b22f0884401a1aa1695def54e2d"),
        "yandex_client_secret": os.environ.get("YANDEX_CLIENT_SECRET", "89d8a53154444685a37738431393cf40"),
        "gemini_proxy": os.environ.get("GEMINI_PROXY", ""),
        "google_service_account_json": "",
        "default_local_dir": os.path.join(DATA_DIR, "local_output"),
        "default_yandex_dir": "/Markoos/Penkof",
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

def natural_sort_key(s: Any) -> list:
    """Sort strings containing numbers in natural human order: image_1 before image_2 before image_10."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

def clean_price_value(val: str) -> str:
    """Cleans up price values, converts 199,000 to 199 000 ₽ or clean format."""
    if not val:
        return ""
    val = str(val).replace('\xa0', ' ').replace('\u20bd', '₽').strip()
    val = re.sub(r'\s+', ' ', val)
    val = re.sub(r'(\d+),(\d{3})', r'\1 \2', val)
    digits_m = re.search(r'(\d[\d\s.,]*)', val)
    if digits_m:
        raw_num = digits_m.group(1).replace(' ', '').replace(',', '').replace('.', '')
        try:
            num = int(raw_num)
            if num > 1000:
                return f"{num:,}".replace(',', ' ') + " ₽"
        except Exception:
            pass
    return val

def parse_structured_product_text(text: str, target_fields: Optional[List[str]] = None) -> dict:
    """
    Универсальный динамический парсер для любых клиентов, категорий и произвольных списков полей.
    Автоматически извлекает свойства (Ключ: Значение), секции (--- СЕКЦИЯ ---), 
    цены, названия, ссылки на видео, габариты и сопоставляет с запрошенными полями.
    """
    res = {}
    if not text:
        return res
        
    normalized_text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 1. Сбор всех пар Ключ -> Значение из текста
    kv_store = {}
    for line in normalized_text.split('\n'):
        line_s = line.strip()
        if not line_s or line_s.startswith('---'):
            continue
        m = re.match(r'^(?:[-*•]\s*)?([A-Za-zА-Яа-я0-9\s()/_.,"-]{2,40})\s*[:=]\s*(.+)$', line_s)
        if m:
            k = m.group(1).strip().lower()
            v = m.group(2).strip()
            if v and len(k) < 40 and not any(skip in k for skip in ["http", "https", "//"]):
                kv_store[k] = v
                
    # 2. Сбор секций (--- НАЗВАНИЕ СЕКЦИИ ---)
    sections = {}
    sec_matches = list(re.finditer(r'(?:^|\n)\s*---\s*([A-Za-zА-Яа-я0-9\s()/_.,"-]+?)\s*---\s*\n([\s\S]+?)(?=(?:\n\s*---\s*[A-Za-zА-Яа-я0-9\s()/_.,"-]+?\s*---)|\Z)', normalized_text))
    for sm in sec_matches:
        sec_name = sm.group(1).strip().lower()
        sec_content = sm.group(2).strip()
        sections[sec_name] = sec_content

    # 3. Базовые сущности
    # 3.1. Цена
    clean_price = ""
    price_match = re.search(r'(?:^|\n)\s*(?:Цена[^\n:\-—]*|Стоимость[^\n:\-—]*|Прайс[^\n:\-—]*|Cost|Price)\s*[:\-—=]\s*([^\n\r]+)', normalized_text, re.IGNORECASE)
    if price_match:
        p_val = price_match.group(1).strip().strip('"\'«»')
        clean_price = clean_price_value(p_val)
            
    if not clean_price or clean_price == '000 ₽':
        price_fb = re.search(r'(?:Цена|Стоимость|Итого)[^\d\n]*(\d[\d\s]{3,}\d)', normalized_text, re.IGNORECASE)
        if price_fb:
            clean_price = clean_price_value(price_fb.group(1))

    # 3.2. Название / Модель
    clean_title = ""
    name_match = re.search(r'(?:^|\n)\s*(?:Название[^\n:\-—=]*|Модель[^\n:\-—=]*|Товар[^\n:\-—=]*|Наименование[^\n:\-—=]*|Product|Title|Model)\s*[:\-—=]\s*([^\n\r]+)', normalized_text, re.IGNORECASE)
    if name_match:
        clean_title = name_match.group(1).strip().strip('"\'«»')
    else:
        for line in normalized_text.split('\n'):
            line_str = line.strip().strip('"\'«»')
            if line_str and not line_str.startswith('---') and not any(kw in line_str.lower() for kw in ["цена", "стоимость", "id vk", "ссылка", "http"]):
                if len(line_str) < 120 and not line_str.startswith('-') and not line_str.startswith('*'):
                    clean_title = line_str
                    break

    # 3.3. Ссылки на видео
    video_links = []
    for line in normalized_text.split('\n'):
        line_clean = line.strip()
        if re.search(r'(?:https?://|//)?(?:[a-zA-Z0-9-]+\.)*(?:vkvideo\.ru|vk\.ru/video|vk\.com/video|okcdn\.ru|ok\.ru/video|youtube\.com|youtu\.be|rutube\.ru|vimeo\.com)[^\s]*', line_clean, re.IGNORECASE):
            m = re.search(r'((?:https?://|//)[^\s]+)', line_clean)
            if m:
                u = m.group(1)
                if u.startswith('//'):
                    u = 'https:' + u
                video_links.append(u)
            elif 'vkvideo.ru' in line_clean:
                video_links.append('https://vkvideo.ru')
    clean_video = "\n".join(video_links) if video_links else ""

    # 3.4. Описание и Параметры / Спецификация
    clean_desc = ""
    clean_params = ""
    for sec_k, sec_v in sections.items():
        if any(k in sec_k for k in ["габарит", "размер", "параметр", "характеристик", "спецификац", "комплектац"]):
            clean_params += f"{sec_v}\n"
        elif any(k in sec_k for k in ["описан", "информац", "о товаре", "полное"]):
            clean_desc += f"{sec_v}\n"

    if not clean_params:
        spec_match = re.search(r'(?:^|\n)\s*(?:Спецификация|Характеристики|Комплектация|Параметры)\s*[:\-—]?\s*\n?([\s\S]+?)(?=\n\s*(?:Цена|Стоимость|---|\Z))', normalized_text, re.IGNORECASE)
        if spec_match:
            clean_params = spec_match.group(1).strip()
            
    if not clean_desc:
        desc_match = re.search(r'(?:^|\n)\s*(?:Описание|О товаре|Подробно)\s*[:\-—]?\s*\n?([\s\S]+?)(?=\n\s*(?:Спецификация|Характеристики|Комплектация|Параметры|Цена|---|\Z))', normalized_text, re.IGNORECASE)
        if desc_match:
            clean_desc = desc_match.group(1).strip()

    clean_params = re.sub(r'Show\s*more|Отдельно просчитывается.*|Крыльцо для бани.*|ID VK:.*|Ссылка:.*', '', clean_params, flags=re.IGNORECASE).strip()
    clean_desc = re.sub(r'Show\s*more|Отдельно просчитывается.*|Крыльцо для бани.*|ID VK:.*|Ссылка:.*', '', clean_desc, flags=re.IGNORECASE).strip()

    # Стандартные ассоциации
    res["Цена"] = clean_price
    res["Название"] = clean_title
    res["Ссылка на видео"] = clean_video
    res["Видео"] = clean_video
    res["Параметры"] = clean_params
    res["Спецификация"] = clean_params
    res["Характеристики"] = clean_params
    res["Описание"] = clean_desc if clean_desc else (f"{clean_title}\n\nХарактеристики и комплектация:\n{clean_params}" if clean_params else "")

    # Динамический маппинг пользовательских полей
    if target_fields:
        for field in target_fields:
            f_norm = field.strip()
            f_low = f_norm.lower()
            if f_norm in res and res[f_norm]:
                continue
            # Поиск в kv_store
            for k, v in kv_store.items():
                if k == f_low or k.startswith(f_low) or f_low.startswith(k):
                    res[f_norm] = v
                    break
            # Поиск в sections
            if not res.get(f_norm):
                for sec_k, sec_v in sections.items():
                    if sec_k == f_low or sec_k.startswith(f_low) or f_low in sec_k:
                        res[f_norm] = sec_v
                        break

    return res

def save_config(config: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        with open(SYSTEM_DEFAULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving config: {e}")

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
    s = s.replace('\r\n', '\n').replace('\r', '\n')
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
        subdirs.sort(key=natural_sort_key)
        
        # Check if we have categories starting with '!'
        categories = [d for d in subdirs if d.startswith("!")]
        categories.sort(key=natural_sort_key)
        
        products_to_process = []
        image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        doc_extensions   = {".docx", ".doc", ".txt"}
        pricing_keywords = ["стоимост", "цен", "прайс", "price", "54 44"]
        
        def collect_files_and_images(path: str):
            """
            Рекурсивно собирает все файлы изображений и документов в указанной папке
            и её подпапках на Яндекс.Диске с натуральной сортировкой.
            """
            images = []
            docs = []
            try:
                files = yandex_handler.list_files(path)
                files.sort(key=lambda f: natural_sort_key(f["name"]))
                for f in files:
                    ext = os.path.splitext(f["name"])[1].lower()
                    if ext in image_extensions:
                        images.append(f)
                    elif ext in doc_extensions:
                        docs.append(f)
                
                # Получаем подпапки 1-го уровня
                try:
                    subs = yandex_handler.list_subdirectories(path)
                    subs.sort(key=natural_sort_key)
                    for sub in subs:
                        sub_path = f"{path.rstrip('/')}/{sub}"
                        try:
                            sub_files = yandex_handler.list_files(sub_path)
                            sub_files.sort(key=lambda f: natural_sort_key(f["name"]))
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
            
            # Гарантируем натуральную сортировку изображений (image_1.jpg перед image_2.jpg перед image_10.jpg)
            images.sort(key=lambda f: natural_sort_key(f["name"]))
            docs.sort(key=lambda f: natural_sort_key(f["name"]))
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
        
        # List files in the root folder (general docs)
        root_files = yandex_handler.list_files(yandex_folder_path)
        root_docs = [f for f in root_files if os.path.splitext(f["name"])[1].lower() in doc_extensions]
        root_docs.sort(key=lambda f: natural_sort_key(f["name"]))
        
        root_description_text = ""
        root_pricing_text = ""
        for doc in root_docs:
            try:
                add_log(f"Чтение общего файла в корне папки: {doc['name']}...")
                text = read_docx(doc)
                if text:
                    if any(kw in doc["name"].lower() for kw in pricing_keywords):
                        root_pricing_text += f"\n--- Файл {doc['name']} ---\n{text}\n"
                    else:
                        root_description_text += f"\n--- Файл {doc['name']} ---\n{text}\n"
            except Exception as doc_err:
                add_log(f"Ошибка чтения общего файла {doc['name']}: {doc_err}")
        
        if categories:
            add_log(f"Обнаружены папки категорий (начинаются с '!'): {categories}")
            for cat_name in categories:
                cat_path = f"{yandex_folder_path.rstrip('/')}/{cat_name}"
                add_log(f"Сканирование категории {cat_name}...")
                
                # List files in category folder (for docx / pricing info)
                cat_files = yandex_handler.list_files(cat_path)
                cat_docs = [f for f in cat_files if os.path.splitext(f["name"])[1].lower() in doc_extensions]
                cat_docs.sort(key=lambda f: natural_sort_key(f["name"]))
                
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
                model_dirs.sort(key=natural_sort_key)
                
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
                        
                        # Combine category, model and root contexts
                        combined_desc = (root_description_text + "\n" + cat_description_text + "\n" + model_desc_text).strip()
                        combined_pricing = (root_pricing_text + "\n" + cat_pricing_text + "\n" + model_pricing_text).strip()
                        
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
                    
                    combined_desc = (root_description_text + "\n" + cat_description_text).strip()
                    combined_pricing = (root_pricing_text + "\n" + cat_pricing_text).strip()
                    
                    products_to_process.append({
                        "name": cat_name.lstrip("!").strip(),
                        "folder_path": cat_path,
                        "description_text": combined_desc,
                        "pricing_text": combined_pricing,
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
                
                description_text = root_description_text
                pricing_text = root_pricing_text
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
                    "description_text": description_text.strip(),
                    "pricing_text": pricing_text.strip(),
                    "category": "",
                    "image_files": images
                })
                
        if not products_to_process:
            add_log("Обработка завершена: нет товаров для сканирования.")
            table_generator_status["progress"] = 100.0
            return
            
        total_products = len(products_to_process)
        add_log(f"Всего товаров для обработки ИИ: {total_products}")
        
        # Detect if user already included a dedicated photo/image link field in prompt_fields
        photo_field_name = None
        for fn in field_names:
            fn_low = fn.lower()
            if any(kw in fn_low for kw in ["фото", "photo", "image", "изображен", "картинк"]) or (("ссылк" in fn_low or "url" in fn_low or "link" in fn_low) and not any(v_kw in fn_low for v_kw in ["видео", "video", "youtube", "rutube", "vk"])):
                photo_field_name = fn
                break
        
        # Detect if user included a folder/id field
        folder_field_name = None
        for fn in field_names:
            fn_low = fn.lower()
            if "папк" in fn_low or fn_low in ["id", "идентификатор", "маркер"]:
                folder_field_name = fn
                break

        add_log(f"[DEBUG] photo_field_name='{photo_field_name}' | folder_field_name='{folder_field_name}' | field_names={field_names}")
        
        # Determine actual table headers
        if photo_field_name:
            headers = field_names
        else:
            headers = field_names + ["Ссылка на фото"]

        # Fields that Gemini should fill (exclude photo and auto-populated folder field)
        gemini_field_names = [
            f for f in field_names 
            if f != photo_field_name and f != folder_field_name
        ]
        
        table_generator_status["result_headers"] = headers
        
        # Construct TSV header line
        tsv_lines = [ "\t".join(headers) ]
        table_generator_status["result_tsv"] = tsv_lines[0] + "\n"
        
        # Phase 2: Process each product
        for idx, item in enumerate(products_to_process):
            if not table_generator_status["active"]:
                add_log("Генерация таблицы принудительно прервана пользователем.")
                break
            product_name = item["name"]
            category = item["category"]
            table_generator_status["current_folder"] = product_name
            current_progress = round((idx / total_products) * 100, 1)
            table_generator_status["progress"] = current_progress
            
            add_log(f"=== [{idx + 1}/{total_products}] Извлечение данных: {product_name} ===")
            
            description_text = item["description_text"]
            pricing_text     = item["pricing_text"]
            
            # Step 2a: Direct structured parsing from description/pricing text
            direct_parsed = parse_structured_product_text(description_text + "\n" + pricing_text, target_fields=field_names)
            
            combined_context = ""
            if description_text.strip():
                combined_context += f"=== ОПИСАНИЕ / КОМПЛЕКТАЦИЯ ===\n{description_text}\n"
            if pricing_text.strip():
                combined_context += f"=== ПРАЙС-ЛИСТ (СТОИМОСТЬ МОДЕЛЕЙ) ===\n{pricing_text}\n"
            
            product_info = {field: "" for field in field_names}
            
            # Pre-populate folder name if designated column exists
            if folder_field_name:
                product_info[folder_field_name] = product_name

            # Pre-populate category/вид строения field if present and we know it
            if category:
                for field in field_names:
                    if field.lower() in ["вид строения", "категория"]:
                        product_info[field] = category
            
            # Pre-populate direct matches
            for field in gemini_field_names:
                if field in direct_parsed and direct_parsed[field]:
                    product_info[field] = direct_parsed[field]
                else:
                    for direct_k, direct_v in direct_parsed.items():
                        if direct_k.lower() == field.lower() and direct_v:
                            product_info[field] = direct_v
            
            if combined_context.strip():
                add_log("Форматирование и извлечение данных через Gemini 3.6 Flash...")
                json_template = ", ".join([f'"{f}": "значение"' for f in gemini_field_names])
                
                category_part = f' из категории "{category}"' if category else ""
                
                gemini_prompt = f"""Ты помогаешь собрать таблицу товаров для маркетплейса Авито.

Категория{category_part}. Текущая папка/модель: "{product_name}"

Контекст (описание и прайс-лист стоимости):
{combined_context}

Задача: извлеки из предоставленного контекста точные значения для следующих полей КОНКРЕТНО для модели "{product_name}":
{', '.join(gemini_field_names)}

Правила заполнения:
1. "Название" — извлеки и приведи в красивый читаемый коммерческий вид реальное название модели (например, 'Баня-бочка Квадро 2x2 м', 'Беседка каркасная 3х5м'). Если название папки числовое или служебное (например, '1', '10', 'Новая папка'), обязательно возьми реальное название из текста.
2. "Цена" — найди точную стоимость ИМЕННО этой модели в контексте или прайс-листе.
КРИТИЧЕСКИ ВАЖНО:
- Если в тексте есть строка "Цена: ...", возьми точную цену оттуда.
- Значение цены должно быть числовым значением в рублях (например, "199 000 ₽" или "199 000").
- Не придумывай цену и не путай цену с толщиной бруса (45 мм), камнями (100 кг) или объемом (14 м3).
- Если цена не найдена, верни пустую строку "".
3. "Описание" — составь чистое маркетинговое описание товара для Авито на основе комплектации и характеристик (без лишних служебных символов).
4. "Параметры" — укажи размеры, габариты и комплектацию модели (например, '2x2 м, ель, профилированный брус 45 мм, печь Везувий').
5. "Вид строения" — тип постройки: {category if category else 'определи из контекста'} (например, Баня, Беседка, Хозблок, Садовый дом).
6. Если какое-либо поле не удаётся заполнить на основе контекста, верни пустую строку "".

Пользовательские инструкции:
{prompt_instruction or 'Заполни поля максимально точно и аккуратно.'}

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
                    for field in gemini_field_names:
                        val = str(parsed.get(field, "") or "").strip()
                        if val:
                            # If price, clean it
                            if any(p_kw in field.lower() for p_kw in ["цен", "стоимост", "price"]):
                                product_info[field] = clean_price_value(val)
                            else:
                                product_info[field] = val
                    add_log(f"Успешный разбор полей ИИ!")
                except Exception as gemini_err:
                    add_log(f"Предупреждение: Ошибка анализа Gemini ({gemini_err}). Используем структурированный парсер.")
                    for field in gemini_field_names:
                        for direct_k, direct_v in direct_parsed.items():
                            if direct_k.lower() == field.lower() and direct_v:
                                product_info[field] = direct_v
            else:
                add_log("Описание отсутствует, используем структурированные данные.")
                for field in gemini_field_names:
                    for direct_k, direct_v in direct_parsed.items():
                        if direct_k.lower() == field.lower() and direct_v:
                            product_info[field] = direct_v

            # Guarantee Name is populated accurately
            for field in field_names:
                if any(n_kw in field.lower() for n_kw in ["назван", "модел", "товар", "name"]) and field != folder_field_name:
                    curr_val = str(product_info.get(field, "")).strip()
                    if not curr_val or curr_val.isdigit() or curr_val.lower().startswith("новая папка"):
                        if direct_parsed.get("Название"):
                            product_info[field] = direct_parsed["Название"]
                        elif direct_parsed.get("Описание"):
                            first_line = direct_parsed["Описание"].split("\n")[0].strip()
                            if first_line and len(first_line) < 100 and not first_line.lower().startswith("спецификация"):
                                product_info[field] = first_line

            # Guarantee Price is populated accurately
            for field in field_names:
                if any(p_kw in field.lower() for p_kw in ["цен", "стоимост", "price"]):
                    curr_val = str(product_info.get(field, "")).strip()
                    if not curr_val or curr_val == '""' or curr_val == '000 ₽':
                        if direct_parsed.get("Цена"):
                            product_info[field] = direct_parsed["Цена"]

            # Guarantee Description is populated accurately
            for field in field_names:
                if any(d_kw in field.lower() for d_kw in ["описан", "desc"]):
                    curr_val = str(product_info.get(field, "")).strip()
                    if not curr_val and direct_parsed.get("Описание"):
                        product_info[field] = direct_parsed["Описание"]

            # Guarantee Parameters are populated accurately
            for field in field_names:
                if any(sp_kw in field.lower() for sp_kw in ["параметр", "характеристик", "спецификац", "комплектац", "габарит"]):
                    curr_val = str(product_info.get(field, "")).strip()
                    if not curr_val and direct_parsed.get("Параметры"):
                        product_info[field] = direct_parsed["Параметры"]

            # Guarantee Video Link is populated accurately
            for field in field_names:
                if any(v_kw in field.lower() for v_kw in ["видео", "video", "rutube", "vk"]):
                    curr_val = str(product_info.get(field, "")).strip()
                    if not curr_val and direct_parsed.get("Ссылка на видео"):
                        product_info[field] = direct_parsed["Ссылка на видео"]

            # Ensure Category field is populated
            if category:
                for field in field_names:
                    if field.lower() in ["вид строения", "категория"] and not product_info.get(field):
                        product_info[field] = category
            
            # Publish photos (guaranteeing natural numeric sort so image_1 is always first)
            photo_urls = []
            image_files = item.get("image_files", [])
            image_files.sort(key=lambda f: natural_sort_key(f.get("name", "")))
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
                
            # Compile row: put photo URLs into the correct column
            photo_cell = "\n".join(photo_urls)
            if photo_field_name:
                # Put URLs directly into the user's designated link column
                product_info[photo_field_name] = photo_cell
                row_data = [product_info.get(field, "") for field in field_names]
            else:
                # Append as extra column
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

# ─────────────────────────────────────────────────────────────────────────────
# MULTI-PACK GENERATION
# ─────────────────────────────────────────────────────────────────────────────

PACK_PRESETS = [
    {"id": 1,  "name": "Вариант 1"},
    {"id": 2,  "name": "Вариант 2"},
    {"id": 3,  "name": "Вариант 3"},
    {"id": 4,  "name": "Вариант 4"},
    {"id": 5,  "name": "Вариант 5"},
    {"id": 6,  "name": "Вариант 6"},
    {"id": 7,  "name": "Вариант 7"},
    {"id": 8,  "name": "Вариант 8"},
    {"id": 9,  "name": "Вариант 9"},
    {"id": 10, "name": "Вариант 10"},
]

# Global state for pack generation
packs_generation_status = {
    "active": False,
    "current_pack": 0,
    "total_packs": 0,
    "current_slot": 0,
    "message": "",
    "error": "",
    "completed_packs": []
}

class GeneratePacksRequest(BaseModel):
    ad_input: str
    count: int  # 5 or 10

def split_text_into_two_lines(text: str):
    text = text.strip()
    if '.' in text:
        parts = text.split('.', 1)
        if parts[0].strip() and parts[1].strip():
            return [parts[0].strip(), parts[1].strip()]
    
    lower_text = text.lower()
    for keyword in [' — ', ' – ', ' - ', ' за ', ' всего ', ' от ']:
        if keyword in lower_text:
            idx = lower_text.index(keyword)
            return [text[:idx].strip(), text[idx:].strip()]
            
    words = text.split(' ')
    if len(words) > 2:
        mid = (len(words) + 1) // 2
        return [' '.join(words[:mid]), ' '.join(words[mid:])]
        
    return [text, '']

def get_text_size(text, font):
    bbox = font.getbbox(text)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return width, height

def wrap_text(text: str, max_chars: int = 28) -> list:
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    for word in words:
        if current_length + len(word) + (1 if current_line else 0) <= max_chars:
            current_line.append(word)
            current_length += len(word) + (1 if len(current_line) > 1 else 0)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            current_length = len(word)
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def parse_banner_text(text: str) -> tuple:
    text = text.strip()
    sep_idx = -1
    for char in ['.', '!', ';']:
        idx = text.find(char)
        if idx != -1:
            if sep_idx == -1 or idx < sep_idx:
                sep_idx = idx
    
    if sep_idx != -1:
        title = text[:sep_idx].strip()
        desc = text[sep_idx+1:].strip()
    else:
        words = text.split()
        if len(words) > 3:
            title = " ".join(words[:3])
            desc = " ".join(words[3:])
        else:
            title = text
            desc = ""
            
    desc = desc.lstrip(".,! ")
    desc_lines = wrap_text(desc, max_chars=32) if desc else []
    return title.upper(), desc_lines

def draw_text_overlay_python(image_bytes: bytes, banner_text: str, font_path: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    import io
    import math
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    width, height = img.size
    
    title_text, desc_lines = parse_banner_text(banner_text)
    
    # Plaque height based on image scale
    plaque_height = int(height * 0.14)
    
    # Fonts
    title_size = int(plaque_height * 0.24)
    title_font = ImageFont.truetype(font_path, title_size)
    desc_size = int(plaque_height * 0.16)
    desc_font = ImageFont.truetype(font_path, desc_size)
    
    def get_size(txt, fnt):
        bbox = fnt.getbbox(txt)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Calculate text layout
    w_title, h_title = get_size(title_text, title_font)
    w_desc_max = 0
    h_desc_total = 0
    desc_gap = int(plaque_height * 0.05)
    
    for line in desc_lines:
        w_l, h_l = get_size(line, desc_font)
        if w_l > w_desc_max:
            w_desc_max = w_l
        h_desc_total += h_l + desc_gap
    
    if desc_lines:
        h_desc_total -= desc_gap
        
    text_width_needed = max(w_title, w_desc_max)
    
    # Plaque layout geometry (no icon)
    padding_x = int(plaque_height * 0.3)
    padding_y = int(plaque_height * 0.2)
    
    max_allowed_width = int(width * 0.82)
    max_text_width = max_allowed_width - padding_x * 2
    
    # Scale down fonts if text exceeds max allowed width
    while text_width_needed > max_text_width and title_size > 10 and desc_size > 8:
        title_size -= 1
        desc_size -= 1
        title_font = ImageFont.truetype(font_path, title_size)
        desc_font = ImageFont.truetype(font_path, desc_size)
        
        # Recalculate sizes
        w_title, h_title = get_size(title_text, title_font)
        w_desc_max = 0
        h_desc_total = 0
        for line in desc_lines:
            w_l, h_l = get_size(line, desc_font)
            if w_l > w_desc_max:
                w_desc_max = w_l
            h_desc_total += h_l + desc_gap
        if desc_lines:
            h_desc_total -= desc_gap
        text_width_needed = max(w_title, w_desc_max)
        
    plaque_width = padding_x * 2 + text_width_needed
    
    # Place in bottom-right corner with margins
    margin_x = int(width * 0.04)
    margin_y = int(height * 0.04)
    x_pos = width - plaque_width - margin_x
    y_pos = height - plaque_height - margin_y
    radius = int(plaque_height * 0.18)
    
    GOLD_COLOR = (229, 193, 88)  # Golden Premium
    BG_COLOR = (10, 14, 23, 245)  # Slate-950 deep dark blue-black with high opacity
    
    # Draw plaque background
    plaque_img = Image.new("RGBA", (plaque_width, plaque_height), BG_COLOR)
    mask = Image.new("L", (plaque_width, plaque_height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, plaque_width, plaque_height], radius=radius, fill=255)
    img.paste(plaque_img, (x_pos, y_pos), mask)
    
    draw = ImageDraw.Draw(img)
    
    # Elegant 1px golden border
    draw.rounded_rectangle(
        [x_pos, y_pos, x_pos + plaque_width, y_pos + plaque_height],
        radius=radius,
        outline=GOLD_COLOR,
        width=1
    )
    
    # Draw text block
    text_x = x_pos + padding_x
    
    total_text_height = h_title
    if desc_lines:
        total_text_height += int(plaque_height * 0.08) + h_desc_total
        
    cy = y_pos + int(plaque_height / 2)
    start_y = cy - total_text_height // 2
    
    # Title (Gold CAPS)
    draw.text((text_x, start_y), title_text, fill=GOLD_COLOR, font=title_font)
    
    # Description lines (White)
    if desc_lines:
        curr_y = start_y + h_title + int(plaque_height * 0.08)
        for line in desc_lines:
            draw.text((text_x, curr_y), line, fill=(255, 255, 255), font=desc_font)
            _, h_l = get_size(line, desc_font)
            curr_y += h_l + desc_gap
            
    final_img = img.convert("RGB")
    out_buf = io.BytesIO()
    final_img.save(out_buf, format="JPEG", quality=95)
    return out_buf.getvalue()



def run_pack_generation(count: int, ad_input: str):
    """Background task: sequentially generates N packs of 9 slots each."""
    global packs_generation_status
    import datetime

    packs_generation_status["active"] = True
    packs_generation_status["current_pack"] = 0
    packs_generation_status["total_packs"] = count
    packs_generation_status["current_slot"] = 0
    packs_generation_status["message"] = "Запуск генерации пачек..."
    packs_generation_status["error"] = ""
    packs_generation_status["completed_packs"] = []

    try:
        config = load_config()
        api_key = config.get("gemini_api_key")
        yandex_token = config.get("yandex_token")
        global_context = config.get("global_context", "")
        visual_style = config.get("visual_style", "")
        base_yandex_dir = config.get("default_yandex_dir", "/Generator_Kreo").rstrip("/")

        if not api_key:
            raise Exception("Gemini API Key не настроен.")
        if not yandex_token:
            raise Exception("Яндекс.Диск токен не настроен.")

        gemini = GeminiHandler(api_key, proxy=config.get("gemini_proxy"))
        yandex = YandexDiskHandler(yandex_token)

        # Timestamp suffix for unique folder names
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        presets_to_use = PACK_PRESETS[:count]

        for pack_idx, preset in enumerate(presets_to_use):
            pack_num = pack_idx + 1
            pack_name = preset["name"]
            packs_generation_status["current_pack"] = pack_num
            packs_generation_status["current_slot"] = 0
            packs_generation_status["message"] = f"Пачка {pack_num}/{count} «{pack_name}»: генерация слотов..."
            logger.info(f"[Packs] Starting pack {pack_num}/{count}: {pack_name}")

            # Step 1: Generate 9 marketing slots via Gemini
            try:
                result = gemini.generate_marketing_slots(
                    global_context=global_context,
                    visual_style=visual_style,
                    local_ad_input=ad_input,
                    references=[],
                    variation_context=preset
                )
                slots_data = result.get("slots", [])
            except Exception as e:
                logger.error(f"[Packs] Gemini failed for pack {pack_num}: {e}")
                packs_generation_status["message"] = f"Пачка {pack_num}: ошибка Gemini — {e}"
                continue

            # Safe folder name (remove special chars)
            import re as _re
            safe_name = _re.sub(r"[^\w\-]", "_", pack_name)
            pack_folder = f"{base_yandex_dir}/Pack_{pack_num:02d}_{safe_name}_{ts}"

            # Step 2: For each slot, generate image and upload to Yandex Disk
            completed_slots = []
            for slot in slots_data:
                slot_num = slot.get("slot_number", len(completed_slots) + 1)
                packs_generation_status["current_slot"] = slot_num
                packs_generation_status["message"] = f"Пачка {pack_num}/{count} «{pack_name}»: картинка {slot_num}/9..."
                logger.info(f"[Packs] Pack {pack_num}, slot {slot_num}: generating image...")

                image_prompt = slot.get("image_prompt", "")
                yandex_url = None

                # Retry up to 3 times on image error
                for attempt in range(1, 4):
                    try:
                        image_bytes = gemini.generate_image(prompt=image_prompt, aspect_ratio="1:1")
                        
                        # Apply programmatic text overlay if banner_text is present
                        banner_text = slot.get("banner_text", "")
                        if banner_text:
                            try:
                                font_path = os.path.join(BASE_DIR, "static", "Montserrat-Bold.ttf")
                                if os.path.exists(font_path):
                                    image_bytes = draw_text_overlay_python(image_bytes, banner_text, font_path)
                                else:
                                    logger.warning(f"[Packs] Montserrat-Bold.ttf not found at {font_path}, skipping text overlay.")
                            except Exception as overlay_err:
                                logger.error(f"[Packs] Failed to draw text overlay: {overlay_err}")
                                
                        disk_path = f"{pack_folder}/{slot_num:02d}.jpg"
                        url = yandex.upload_bytes(image_bytes, disk_path, overwrite=True)
                        if url:
                            yandex_url = url
                            logger.info(f"[Packs] Pack {pack_num}, slot {slot_num}: uploaded → {url}")
                            break
                        else:
                            logger.warning(f"[Packs] Pack {pack_num}, slot {slot_num}: upload returned no URL (attempt {attempt})")
                    except Exception as img_err:
                        logger.warning(f"[Packs] Pack {pack_num}, slot {slot_num}: attempt {attempt} failed: {img_err}")
                        if attempt < 3:
                            time.sleep(3)

                completed_slots.append({
                    "slot_number": slot_num,
                    "title": slot.get("title", ""),
                    "banner_text": slot.get("banner_text", ""),
                    "marketing_logic": slot.get("marketing_logic", ""),
                    "image_prompt": image_prompt,
                    "yandex_url": yandex_url or ""
                })

                # Small delay between slots to avoid rate limits
                time.sleep(config.get("generation_delay_sec", 3))

            packs_generation_status["completed_packs"].append({
                "pack_number": pack_num,
                "pack_name": pack_name,
                "slots": completed_slots
            })
            packs_generation_status["message"] = f"Пачка {pack_num}/{count} «{pack_name}» готова!"
            logger.info(f"[Packs] Pack {pack_num} completed with {len(completed_slots)} slots.")
            
            # Cooldown delay between packs to avoid API rate limit (429) errors
            if pack_idx < len(presets_to_use) - 1:
                logger.info(f"[Packs] Cool down between packs: sleeping 10 seconds...")
                time.sleep(10)

        packs_generation_status["message"] = f"Готово! Все {count} пачек сгенерированы."
        logger.info("[Packs] All packs completed.")

    except Exception as e:
        logger.exception("[Packs] Fatal error in run_pack_generation")
        packs_generation_status["error"] = str(e)
        packs_generation_status["message"] = f"Критическая ошибка: {e}"
    finally:
        packs_generation_status["active"] = False


@app.post("/api/generate-packs")
def start_generate_packs(request: GeneratePacksRequest, background_tasks: BackgroundTasks):
    """Start multi-pack generation in background."""
    if packs_generation_status["active"]:
        raise HTTPException(status_code=400, detail="Генерация пачек уже запущена.")
    if request.count not in (5, 10):
        raise HTTPException(status_code=400, detail="count должен быть 5 или 10.")
    if not request.ad_input.strip():
        raise HTTPException(status_code=400, detail="ad_input не может быть пустым.")

    # Reset state synchronously
    packs_generation_status["active"] = True
    packs_generation_status["current_pack"] = 0
    packs_generation_status["total_packs"] = request.count
    packs_generation_status["current_slot"] = 0
    packs_generation_status["message"] = "Запуск..."
    packs_generation_status["error"] = ""
    packs_generation_status["completed_packs"] = []

    background_tasks.add_task(run_pack_generation, count=request.count, ad_input=request.ad_input)
    return {"status": "success", "message": f"Запущена генерация {request.count} пачек."}


@app.get("/api/generate-packs/status")
def get_packs_status():
    """Returns current pack generation status and completed packs."""
    return packs_generation_status


@app.post("/api/table-generator/scan")
def start_table_generation(request: TableGeneratorRequest, background_tasks: BackgroundTasks):
    if table_generator_status["active"]:
        raise HTTPException(status_code=400, detail="Задача генерации таблицы уже запущена.")
    
    # Set active=True synchronously to prevent race condition with concurrent requests
    table_generator_status["active"] = True
    table_generator_status["progress"] = 0.0
    table_generator_status["current_folder"] = ""
    table_generator_status["logs"] = []
    table_generator_status["error"] = ""
    table_generator_status["result_headers"] = []
    table_generator_status["result_tsv"] = ""
    
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

@app.post("/api/table-generator/stop")
def stop_table_generation():
    if not table_generator_status["active"]:
        return {"status": "success", "message": "Генерация таблицы не запущена."}
    table_generator_status["active"] = False
    add_log("Получен запрос на принудительную остановку от пользователя.")
    return {"status": "success", "message": "Процесс генерации таблицы останавливается..."}

def open_browser():
    """Wait for server to start, then open standard web browser."""
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")


# ─────────────────────────────────────────────────────────────────────────────
# UNIQUALIZATION MODULE
# ─────────────────────────────────────────────────────────────────────────────

uniqualize_status = {
    "active": False,
    "total_photos": 0,
    "current_photo": 0,
    "total_variants": 0,
    "done_variants": 0,
    "message": "",
    "error": "",
    "result_links": [],       # list of {"filename": ..., "url": ...}
    "output_folder": ""
}

class UniqualizRequest(BaseModel):
    yandex_folder: str     # e.g. /Markoos/Penkof/raw_photos
    variants_count: int    # 5, 10, or 15


def apply_uniqualization(image_bytes: bytes, seed: int) -> bytes:
    """
    Apply a deterministic-but-varied set of transformations to uniqualize an image for Avito.
    Removes EXIF metadata, applies micro-rotation with smart crop, color/lighting tweaks,
    simulated sensor noise, and varied compression.
    """
    import io, random
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    rng = random.Random(seed)
    
    # Open and strip EXIF completely by creating a clean copy
    raw_img = Image.open(io.BytesIO(image_bytes))
    # Correct orientation from EXIF before stripping
    raw_img = ImageOps.exif_transpose(raw_img)
    img = Image.new("RGB", raw_img.size)
    img.paste(raw_img)
    w, h = img.size

    # 1. Slight rotation (±0.4° to ±1.6°)
    angle = rng.uniform(-1.6, 1.6)
    if abs(angle) > 0.2:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)

    # 2. Smart crop (4.5–6.5% from edges to eliminate any rotation borders and vary composition)
    crop_top    = int(h * rng.uniform(0.045, 0.065))
    crop_bottom = int(h * rng.uniform(0.045, 0.065))
    crop_left   = int(w * rng.uniform(0.045, 0.065))
    crop_right  = int(w * rng.uniform(0.045, 0.065))
    img = img.crop((crop_left, crop_top, w - crop_right, h - crop_bottom))

    # 3. Horizontal flip (only ~20% of variants, controlled by seed)
    if rng.random() < 0.20:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)

    # 4. Brightness adjustment (±3–8%)
    brightness_factor = rng.uniform(0.93, 1.07)
    img = ImageEnhance.Brightness(img).enhance(brightness_factor)

    # 5. Contrast adjustment (±3–7%)
    contrast_factor = rng.uniform(0.94, 1.06)
    img = ImageEnhance.Contrast(img).enhance(contrast_factor)

    # 6. Color saturation (±3–9%)
    saturation_factor = rng.uniform(0.92, 1.08)
    img = ImageEnhance.Color(img).enhance(saturation_factor)

    # 7. Sharpness micro-adjustment
    sharpness_factor = rng.uniform(0.90, 1.10)
    img = ImageEnhance.Sharpness(img).enhance(sharpness_factor)

    # 8. Micro-noise (simulates authentic smartphone sensor noise)
    noise_level = rng.uniform(0.5, 4.5)
    if noise_level > 1.0:
        import numpy as np
        arr = np.array(img, dtype=np.int16)
        noise = np.random.RandomState(seed).randint(-int(noise_level), int(noise_level)+1, arr.shape, dtype=np.int16)
        arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)

    # Output clean JPEG with randomized quality (89-95)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=rng.randint(89, 95), optimize=True)
    return out.getvalue()


def run_uniqualization(yandex_folder: str, variants_count: int):
    """Background task: download photos from Yandex.Disk, uniqualize, overlay banner, re-upload."""
    global uniqualize_status
    import datetime, re as _re, io, tempfile

    uniqualize_status["active"] = True
    uniqualize_status["result_links"] = []
    uniqualize_status["error"] = ""
    uniqualize_status["output_folder"] = ""

    try:
        config = load_config()
        api_key    = config.get("gemini_api_key")
        yandex_token = config.get("yandex_token")
        global_context = config.get("global_context", "")

        if not api_key:
            raise Exception("Gemini API Key не настроен.")
        if not yandex_token:
            raise Exception("Яндекс.Диск токен не настроен.")

        gemini = GeminiHandler(api_key, proxy=config.get("gemini_proxy"))
        yandex = YandexDiskHandler(yandex_token)

        # 1. List photos in the source folder with natural sort
        uniqualize_status["message"] = "Читаю папку на Яндекс.Диске..."
        all_files = yandex.list_files(yandex_folder)
        photo_files = [
            f for f in all_files
            if f["name"].lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ]
        photo_files.sort(key=lambda f: natural_sort_key(f["name"]))
        if not photo_files:
            raise Exception(f"В папке '{yandex_folder}' не найдено фото (JPG/PNG/WEBP).")

        uniqualize_status["total_photos"] = len(photo_files)
        uniqualize_status["total_variants"] = len(photo_files) * variants_count
        uniqualize_status["done_variants"] = 0
        uniqualize_status["message"] = f"Найдено {len(photo_files)} фото. Начинаю обработку..."
        logger.info(f"[Unique] Found {len(photo_files)} photos in '{yandex_folder}'.")

        # 2. Create output folder
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # Put output folder next to source folder (sibling)
        parent = "/".join(yandex_folder.rstrip("/").split("/")[:-1]) or "/"
        src_name = yandex_folder.rstrip("/").split("/")[-1]
        out_folder = f"{parent}/{src_name}_unique_{ts}"
        yandex.create_folder(out_folder)
        uniqualize_status["output_folder"] = out_folder
        logger.info(f"[Unique] Output folder: {out_folder}")

        # 3. Font path for plaque overlay
        font_path = os.path.join(BASE_DIR, "static", "Montserrat-Bold.ttf")

        result_links = []

        for photo_idx, photo in enumerate(photo_files):
            uniqualize_status["current_photo"] = photo_idx + 1
            base_name = os.path.splitext(photo["name"])[0]
            disk_path = photo["path"]

            uniqualize_status["message"] = (
                f"Фото {photo_idx+1}/{len(photo_files)} «{photo['name']}»: скачиваю..."
            )

            # 3a. Download photo from Yandex.Disk to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp_path = tmp.name
            try:
                ok = yandex.download_file(disk_path, tmp_path)
                if not ok or not os.path.exists(tmp_path):
                    raise Exception(f"Не удалось скачать {photo['name']}")
                with open(tmp_path, "rb") as f:
                    original_bytes = f.read()
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

            # 3b. Analyze photo with Gemini Vision to get banner text
            uniqualize_status["message"] = (
                f"Фото {photo_idx+1}/{len(photo_files)} «{photo['name']}»: генерирую текст плашки..."
            )
            try:
                banner_text = gemini.analyze_photo_for_banner(original_bytes, global_context)
                logger.info(f"[Unique] Photo {photo_idx+1} banner: «{banner_text}»")
            except Exception as vision_err:
                banner_text = ""
                logger.warning(f"[Unique] Vision failed for {photo['name']}: {vision_err}. No overlay.")

            # 3c. Generate N uniqualized variants
            for v_idx in range(variants_count):
                seed = photo_idx * 1000 + v_idx
                uniqualize_status["message"] = (
                    f"Фото {photo_idx+1}/{len(photo_files)}: вариант {v_idx+1}/{variants_count}..."
                )

                try:
                    # Apply uniqualization transforms
                    variant_bytes = apply_uniqualization(original_bytes, seed)

                    # Overlay Slate Neon plaque if we have banner text
                    if banner_text and os.path.exists(font_path):
                        try:
                            variant_bytes = draw_text_overlay_python(variant_bytes, banner_text, font_path)
                        except Exception as overlay_err:
                            logger.warning(f"[Unique] Overlay failed: {overlay_err}")

                    # Upload to Yandex.Disk
                    variant_name = f"{base_name}_v{v_idx+1:02d}.jpg"
                    disk_out_path = f"{out_folder}/{variant_name}"
                    url = yandex.upload_bytes(variant_bytes, disk_out_path, overwrite=True)

                    if url:
                        result_links.append({"filename": variant_name, "url": url})
                        logger.info(f"[Unique] Uploaded {variant_name} → {url}")
                    else:
                        logger.warning(f"[Unique] Upload returned no URL for {variant_name}")

                except Exception as variant_err:
                    logger.error(f"[Unique] Variant {v_idx+1} of {photo['name']} failed: {variant_err}")

                uniqualize_status["done_variants"] += 1
                uniqualize_status["result_links"] = result_links

        uniqualize_status["result_links"] = result_links
        uniqualize_status["message"] = (
            f"Готово! {len(result_links)} файлов загружено в «{out_folder}»."
        )
        logger.info(f"[Unique] Completed. {len(result_links)} files uploaded.")

    except Exception as e:
        logger.exception("[Unique] Fatal error")
        uniqualize_status["error"] = str(e)
        uniqualize_status["message"] = f"Ошибка: {e}"
    finally:
        uniqualize_status["active"] = False


@app.post("/api/uniqualize")
def start_uniqualize(request: UniqualizRequest, background_tasks: BackgroundTasks):
    """Start uniqualization in background."""
    if uniqualize_status["active"]:
        raise HTTPException(status_code=400, detail="Уникализация уже запущена.")
    if not (1 <= request.variants_count <= 200):
        raise HTTPException(status_code=400, detail="variants_count должен быть числом от 1 до 200.")
    if not request.yandex_folder.strip():
        raise HTTPException(status_code=400, detail="yandex_folder не может быть пустым.")

    uniqualize_status["active"] = True
    uniqualize_status["total_photos"] = 0
    uniqualize_status["current_photo"] = 0
    uniqualize_status["total_variants"] = 0
    uniqualize_status["done_variants"] = 0
    uniqualize_status["message"] = "Запуск..."
    uniqualize_status["error"] = ""
    uniqualize_status["result_links"] = []
    uniqualize_status["output_folder"] = ""

    background_tasks.add_task(
        run_uniqualization,
        yandex_folder=request.yandex_folder.strip(),
        variants_count=request.variants_count
    )
    return {"status": "success", "message": f"Уникализация запущена: {request.variants_count} вариантов на фото."}


@app.get("/api/uniqualize/status")
def get_uniqualize_status():
    """Returns current uniqualization status and result links."""
    return uniqualize_status


if __name__ == "__main__":
    # Start browser thread
    threading.Thread(target=open_browser, daemon=True).start()
    # Run server
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
