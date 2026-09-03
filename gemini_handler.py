import requests
import json
import base64
import os
from typing import List, Dict, Any, Optional

class GeminiHandler:
    def __init__(self, api_key: str, proxy: Optional[str] = None):
        self.api_key = api_key
        self.headers = {"Content-Type": "application/json"}
        # Read proxy from parameter or environment variable
        self.proxy = proxy or os.environ.get("GEMINI_PROXY")
        self.proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        
        # We use direct REST API endpoints for maximum compatibility on any Python version.
        self.text_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={self.api_key}"
        self.image_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-fast-generate-001:predict?key={self.api_key}"

    def _make_request_with_retry(self, url: str, payload: dict, timeout: int, max_retries: int = 2) -> requests.Response:
        import time
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=self.headers, json=payload, timeout=timeout, proxies=self.proxies)
                if response.status_code == 429:
                    resp_text = response.text.lower()
                    if "quota exceeded" in resp_text or "prepayment credits" in resp_text or "depleted" in resp_text:
                        return response
                    if attempt == max_retries - 1:
                        return response
                    print(f"[RATE LIMIT] Got 429. Quick wait 3s (Attempt {attempt+1}/{max_retries})...")
                    time.sleep(3.0)
                    continue
                elif response.status_code in (500, 502, 503, 504):
                    if attempt == max_retries - 1:
                        return response
                    print(f"[SERVER ERROR] Got {response.status_code}. Quick wait 1.5s (Attempt {attempt+1}/{max_retries})...")
                    time.sleep(1.5)
                    continue
                return response
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise e
                print(f"[CONNECTION ERROR] {e}. Retrying in 1.5s (Attempt {attempt+1}/{max_retries})...")
                time.sleep(1.5)
        return requests.post(url, headers=self.headers, json=payload, timeout=timeout, proxies=self.proxies)

    def _make_text_request_with_fallback(self, payload: dict, timeout: int) -> requests.Response:
        models = ["gemini-3.7-flash", "gemini-flash-latest", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
        last_response = None
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            try:
                response = self._make_request_with_retry(url, payload, timeout)
                if response.status_code == 200:
                    return response
                print(f"[FALLBACK] Model {model} returned status {response.status_code}. Trying next model...")
                last_response = response
            except Exception as e:
                print(f"[FALLBACK] Model {model} failed with exception: {e}. Trying next model...")
        if last_response is not None:
            return last_response
        raise Exception("All Gemini models in fallback chain failed.")



    def check_connection(self) -> bool:
        """Verify the API key by making a fast lightweight request."""
        payload = {
            "contents": [{"parts": [{"text": "Say: ok"}]}],
            "generationConfig": {"maxOutputTokens": 10}
        }
        for model in ["gemini-3.7-flash", "gemini-flash-latest"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            try:
                r = requests.post(url, headers=self.headers, json=payload, timeout=4, proxies=self.proxies)
                if r.status_code in (200, 429):
                    return True
            except Exception as e:
                err = str(e).lower()
                if "empty" in err or "output text" in err or "tool calls" in err or "output must contain" in err:
                    return True
        return False

    def analyze_photo_for_banner(self, image_bytes: bytes, global_context: str) -> str:
        """
        Analyzes a real photo using Gemini Vision and generates a short punchy
        banner text in Russian that matches what is visible in the image.
        Uses global_context to stay on-brand.
        Returns a short Russian marketing phrase (max 8 words).
        """
        import base64
        encoded = base64.b64encode(image_bytes).decode("utf-8")

        system_instruction = (
            "You are a Russian-language marketing copywriter specializing in short, punchy ad banner texts. "
            "Your task: look at the photo and the marketing context, then write ONE short Russian marketing phrase "
            "that matches what you SEE in the photo AND fits the brand/product. "
            "Rules: max 8 words, no punctuation at the end, direct and commercial tone. "
            "Output ONLY the banner text, nothing else. No quotes, no explanation."
        )

        user_prompt = (
            f"MARKETING CONTEXT:\n{global_context}\n\n"
            "Look at this photo. Based on what you see AND the marketing context above, "
            "generate ONE short punchy Russian banner text (max 8 words) for this specific image. "
            "Match the content: if you see an exterior — write about price/look; "
            "if interior — write about comfort/experience; if close-up — write about quality/material; "
            "if installation — write about speed/service. Output ONLY the text."
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": encoded
                            }
                        },
                        {"text": f"{system_instruction}\n\n{user_prompt}"}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 300
            }
        }

        response = self._make_text_request_with_fallback(payload, timeout=30)
        if response.status_code != 200:
            raise Exception(f"Vision API error {response.status_code}: {response.text}")

        try:
            result_json = response.json()
            candidates = result_json.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                text_parts = [p.get("text", "") for p in parts if "text" in p]
                if text_parts:
                    text = " ".join(text_parts).strip()
                    # Strip markdown bold/quotes
                    import re
                    text = re.sub(r'[*#_`]', '', text).strip()
                    text = text.strip('"\'«»')
                    return text
            raise Exception("No text parts returned from Gemini Vision")
        except Exception as e:
            raise Exception(f"Failed to parse vision response: {e}")

    def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """
        Generates a text response from Gemini for a given prompt.
        """
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048
            }
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
            
        response = self._make_text_request_with_fallback(payload, timeout=30)
        if response.status_code != 200:
            raise Exception(f"Gemini API returned error {response.status_code}: {response.text}")
            
        try:
            result_json = response.json()
            candidates = result_json.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                text_parts = [p.get("text", "") for p in parts if "text" in p]
                if text_parts:
                    return " ".join(text_parts).strip()
            raise Exception("No text parts in candidates")
        except Exception as e:
            raise Exception(f"Failed to parse text response from Gemini: {e}")

    def generate_marketing_slots(self, global_context: str, visual_style: str, local_ad_input: str, references: List[str] = [], variation_context: Optional[dict] = None) -> List[Dict[str, Any]]:
        """
        Takes global context, visual style preferences, specific ad details, and style reference image paths,
        and generates a 9-slot marketing campaign breakdown with text and image prompts.
        """
        import os
        import base64

        system_instruction = (
            "You are a professional conversion copywriter and marketing designer specializing in creating ad creatives. "
            "Your task is to take the general marketing context, a visual style prompt guide, any uploaded reference images, and a specific ad input, and break it down into exactly 9 distinct advertising slots (stories/slides/cards). "
            "Each slot represents one marketing trigger, pain point, USP, offer, or testimonial. "
            "For each of the 9 slots, you MUST output:\n"
            "1. slot_number (1 to 9)\n"
            "2. title (in Russian, e.g. 'Главный оффер', 'Боль: качество древесины')\n"
            "3. marketing_logic (in Russian, explaining why this trigger works for the target audience)\n"
            "4. banner_text (in Russian, the short, punchy marketing phrase to be written directly on the image/banner)\n"
            "5. image_prompt (in English, a highly detailed prompt for Imagen 4. Do not include text on the image in the prompt itself. Focus on composition, lighting, materials, colors, and camera angle. Align with the style of the references. No text/watermarks/banners on the image output).\n\n"
            "STEP 0 — MANDATORY NICHE & PRODUCT ANALYSIS (do this FIRST before generating any slots):\n"
            "Before generating any content, silently analyze both input sources to understand what you are working with:\n"
            "A) BUSINESS NICHE (from GLOBAL MARKETING CONTEXT): Read the global context to identify: what does this company sell? What materials do they use? What is their primary product category? (e.g. 'profiled timber structures: houses, bathhouses, gazebos' OR 'barrel sauna manufacturer' OR 'Avito marketing service' OR 'massage/spa center').\n"
            "B) SPECIFIC PRODUCT (from LOCAL AD INPUT): Read the specific ad input to identify the exact product or service being advertised (e.g. 'timber-frame bathhouse Oresnik-6', 'barrel sauna Quadro 2x3', '120 sqm wooden house', 'Avito account management service').\n"
            "C) COMBINE: Generate all image prompts so they visually represent the EXACT SPECIFIC PRODUCT (B) within the visual style of the BUSINESS NICHE (A). Every image must accurately show what the customer would actually receive.\n\n"
            "CRITICAL LANGUAGE RULE:\n"
            "The 'image_prompt' field for EVERY slot MUST BE WRITTEN ENTIRELY IN ENGLISH. Do not use Russian letters or words in the image_prompt. The text of the banner (banner_text) and titles must be in Russian, but the image_prompt itself must be in pure English.\n\n"
            "CRITICAL NICHE ADAPTABILITY & PARAMETER ENFORCEMENT:\n"
            "This system works across multiple business niches. You must identify all specific parameters in the ad description (e.g. size/dimensions, color/stain, price, material, or service specifics) and RIGIDLY incorporate them into the English image_prompt for every single slot. Do not generalize or omit these parameters. They must match the specific item or service being advertised.\n\n"
            "CRITICAL PRODUCT/SERVICE FOCUS & NO-HUMANS RULE:\n"
            "1. Identify whether the advertised item is a physical product (e.g., saunas, building materials, physical goods) or a service (e.g., Avito manager/avitoologist, marketing, consulting, repairs).\n"
            "2. For PHYSICAL PRODUCTS: All generated images MUST feature the physical product itself (or its details, materials, and components) as the central focus. Strictly NO humans, NO faces, NO workers, and NO characters must be visible in the image. Focus entirely on the object, its textures, and its environment.\n"
            "3. For SERVICES: All generated images MUST feature the workspace, tools, or direct visual representations of the service (e.g., a modern laptop screen showing business growth charts, graphs, or the Avito dashboard; a neat office desk with a notebook and coffee; a professional workstation). Avoid generic stock-photo style humans. If a human representation is absolutely necessary for the service context, describe them only in a professional, natural setting (e.g., 'a close-up over-the-shoulder view focusing on a computer screen showing analytics charts', which keeps the focus on the screen/work, avoiding direct faces).\n\n"
            "CRITICAL PRODUCT TYPE MATCHING & GEOMETRY RULES:\n"
            "You MUST generate image prompts that precisely match the EXACT TYPE and PHYSICAL PARAMETERS of the product from the local ad description. Do NOT substitute a different product type just because it appeared in the global context as a competitor comparison.\n\n"
            "--- IF THE PRODUCT IS A BARREL SAUNA (баня-бочка, квадробаня, сауна-бочка, Квадро) ---\n"
            "Determine the shape: if 'Quadro' / 'квадро' / 'квадробаня' → use 'rounded-rectangular profile (with heavily rounded corners, flat front face, and slightly bowed vertical side walls)'. If plain 'бочка' (no Quadro) → use 'classic circular cylinder-shaped profile (perfectly round cross-section, flat wooden end walls)'.\n"
            "Determine the dimensions from the ad (e.g. 2x2, 2x3, 2x4, 2x5, 2x6):\n"
            "  - 2x2: 'extremely short, squat, single-room sauna. Length equals diameter (2m x 2m). Exactly two wooden support skids underneath. Exactly two wide stainless steel tensioning bands.'\n"
            "  - 2x3: 'compact, slightly elongated (3m long). Exactly three wooden support skids. Exactly three tensioning bands.'\n"
            "  - 2x4: 'moderately elongated (4m long). Three or four wooden support skids. Three or four tensioning bands.'\n"
            "  - 2x5 or 2x6: 'very long, tunnel-like structure (5-6m long). Four or five wooden support skids. Four or five tensioning bands.'\n"
            "Determine the wood stain color from the ad: 'орех' → medium walnut brown; 'коньяк' → rich cognac-chestnut; 'каштан' → warm chestnut; 'тик' → golden teak; 'палисандр' → dark rosewood; 'сосна/ель/натуральный' → light natural pine. Default: rich cognac-chestnut.\n"
            "Determine the roof color: 'бордо/красн' → burgundy-red; 'зелен' → forest-green; 'серый/черн' → charcoal-gray; 'коричн' → chocolate-brown. Default: burgundy-red.\n"
            "For ALL barrel sauna exterior shots: always show a wooden entrance door with a vertical glass window pane and a small square side window, with warm glowing yellow interior light visible through the glass. Always use a three-quarter perspective angle showing front entrance and side wall. Sauna stands on gray concrete foundation blocks on a gravel pad over green grass. Natural overcast daylight. No people.\n\n"
            "--- IF THE PRODUCT IS A TIMBER-FRAME HOUSE (дом из бруса, дом из профилированного бруса) ---\n"
            "Show a rectangular wooden house with pitched or flat roof. Show the exact footprint from dimensions if given. Use horizontal profiled lumber planks with a rich cognac-stained or natural wood finish matching the ad description. Show large windows, entrance door, porch if mentioned. Use the visual style from the reference images and style guide. No barrel or rounded shape. No people.\n\n"
            "--- IF THE PRODUCT IS A TIMBER-FRAME BATHHOUSE (баня из бруса, баня блочная — NOT баня-бочка) ---\n"
            "Show a square or rectangular wooden bathhouse with a gabled or flat roof. Horizontal profiled timber planks. Show windows and wooden entrance door. Do NOT draw any barrel, rounded, or cylindrical shape. Show cozy warm interior light through windows. No people.\n\n"
            "--- IF THE PRODUCT IS A GAZEBO (беседка) ---\n"
            "Show an open or semi-open garden pavilion/pergola made of profiled timber. Show the footprint size from dimensions. No walls unless described. Decorative wooden columns. Green garden background.\n\n"
            "--- IF THE PRODUCT IS A SHED/UTILITY (сарай, хозблок, МБ, мини-блок) ---\n"
            "Show a compact rectangular utility outbuilding. Simple gabled or flat roof. Sliding or double-leaf door. Horizontal timber plank walls.\n\n"
            "--- IF THE PRODUCT IS A SERVICE ---\n"
            "Focus entirely on workspace, tools, and results: Avito dashboard on a laptop, business charts, professional desk setup, etc. No product structures.\n\n"
            "DISAMBIGUATION: 'Альтернатива бани-бочки' in global context = company sells timber structures INSTEAD of barrel saunas. Do NOT generate barrel saunas unless LOCAL AD INPUT explicitly names one.\n\n"
            "MANDATORY FIXED SLOT STRUCTURE — ALL 9 SLOTS MUST ALWAYS FOLLOW THIS EXACT SEQUENCE. Adapt the content to match the actual business niche identified in Step 0, but NEVER change the slot roles or their order:\n"
            "Slot 1 — MAIN OFFER WITH PRICE: Banner MUST contain the exact price and the primary USP in one short phrase. "
            "For products: product name + price + key condition (e.g. 'Баня 2х2 — от 185 000 ₽ под ключ'). "
            "For services: service name + price or starting price (e.g. 'Ведение Авито — от 5 000 ₽/мес'). "
            "Image: most attractive hero shot of the product or service workspace.\n"
            "Slot 2 — PAIN POINT: Name the buyer's biggest fear, frustration or problem and imply you solve it. "
            "Banner is a direct question or a bold statement about the pain (e.g. 'Боитесь брака и обмана?', 'Объявления уходят в бан?', 'Боль в зубах мешает жить?'). "
            "Image: close-up of the problem area, material detail, or a tense 'before' situation.\n"
            "Slot 3 — QUALITY / PROOF OF COMPETENCE: Demonstrate the core quality, material, or professional expertise. "
            "For physical products: close macro shot of material texture, precision joinery, or construction detail. Banner: material or craftsmanship claim. "
            "For services: visual proof of result — dashboard, charts, portfolio screenshot. Banner: credential or method.\n"
            "Slot 4 — SPEED / CONVENIENCE / TERMS: Highlight how fast or easy it is to get the result. "
            "Banner: specific number or timeline (e.g. 'Монтаж за 1 день', 'Запуск за 48 часов', 'Приём без очереди'). "
            "Image: product in motion or dynamic composition, or service workflow visual.\n"
            "Slot 5 — RESULT / BENEFIT INSIDE: Show the end result or the experience the buyer receives. "
            "For physical enclosed products (sauna, house, room): interior shot showing the inside space. "
            "For open products (gazebo, fence): beautiful in-use shot of the product. "
            "For services: 'after' result — graph trending up, filled calendar, happy outcome. "
            "Banner: the concrete benefit the buyer feels or gains.\n"
            "Slot 6 — SOCIAL PROOF / TRUST: Make it look real and established. "
            "Image: authentic-looking photo as if taken by a real satisfied customer — natural framing, real environment. "
            "Banner: a credibility statement with a number (e.g. 'Уже 200+ установлено', '50 клиентов в топе', '1 200 пациентов'). "
            "No staged stock-photo look — it must feel real.\n"
            "Slot 7 — UNIQUE DIFFERENTIATOR: One specific thing this seller offers that competitors typically don't. "
            "Banner: the differentiating feature (e.g. '9 цветов пропитки на выбор', 'Работаем без предоплаты', 'Гарантия приживаемости 25 лет'). "
            "Image: detail shot or wide shot that visually highlights this unique aspect.\n"
            "Slot 8 — FINANCIAL EASE / GUARANTEE: Remove the last financial objection. "
            "If the ad mentions installment, lease, or 0% financing — use that as the banner. "
            "If no financing is mentioned — use a guarantee, warranty, or risk-reversal promise. "
            "Banner: (e.g. 'Рассрочка 0% — платите после установки', 'Гарантия 3 года', 'Возврат денег, если не выйдем в топ'). "
            "Image: clean confident product or service shot.\n"
            "Slot 9 — CALL TO ACTION: Create urgency and invite immediate contact. "
            "Banner: a direct, action-oriented CTA phrase (e.g. 'Оставьте заявку — перезвоним за 10 минут', 'Напишите сейчас — разберём ваш аккаунт бесплатно'). "
            "Image: the most inviting, widest, most attractive shot — final impression.\n"
            "CRITICAL: Slot 1 MUST ALWAYS have a price in the banner_text. Do not move the price to any other slot or leave it out.\n\n"
            "CRITICAL WINDOWS, DOORS & REALISM RULE:\n"
            "For any enclosed wooden structure: Always include realistic windows and entrance doors in exterior shots. Show warm interior light through glass. Use a three-quarter camera angle to show both front and side. No blank wooden walls.\n\n"
            "CRITICAL IMAGE PROMPT STRUCTURE RULE:\n"
            "When writing the 'image_prompt' for each slot, structure it as follows:\n"
            "1. Start with the photographic style matching the uploaded reference images (e.g. 'Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, natural overcast daylight, commercial real-estate photography style.').\n"
            "2. Apply the visual style guide (atmosphere, light, colors, camera angle from the VISUAL STYLE PREFERENCES section).\n"
            "3. Describe the exact subject: product type + all physical parameters (dimensions, color, material, shape) + slot-specific scene (exterior/interior/close-up/delivery/etc.).\n"
            "4. End with: 'No text, no watermarks, no people.'"
        )


        # Build variation block if this is a multi-pack generation
        variation_block = ""
        if variation_context:
            variation_block = (
                f"\n--- PACK VARIATION SEED (PACK #{variation_context.get('id', '?')}) ---\n"
                f"This is pack #{variation_context.get('id', '?')} of a multi-pack generation. "
                f"The 9-slot STRUCTURE IS IDENTICAL to all other packs (same slot roles, same sequence). "
                f"Your ONLY job is to vary the following while keeping the structure:\n"
                f"1. BANNER TEXT WORDING — use different phrasing, synonyms, different sentence structure. "
                f"NEVER repeat a banner_text from another pack.\n"
                f"2. CAMERA ANGLE & COMPOSITION — rotate the perspective: "
                f"Pack 1: three-quarter front-left. Pack 2: three-quarter front-right. "
                f"Pack 3: low angle looking up slightly. Pack 4: high angle bird's-eye looking down slightly. "
                f"Pack 5: straight-on frontal. Pack 6: side profile. "
                f"Pack 7: close-up on door and window. Pack 8: wide-angle with more yard context. "
                f"Pack 9: slightly raised angle from distance. Pack 10: straight three-quarter front-left again but tighter crop.\n"
                f"3. LIGHTING MOOD — vary slightly: overcast flat, soft morning haze, golden warm afternoon, bright midday, cool blue-grey cloudy.\n"
                f"DO NOT change: slot roles/structure, price info, key USPs, product parameters. "
                f"DO NOT add family/gift/persona themes. Stay product-focused and commercial.\n"
            )

        user_prompt = (
            f"--- GLOBAL MARKETING CONTEXT & BRAND INFO ---\n"
            f"{global_context}\n\n"
            f"--- VISUAL STYLE PREFERENCES ---\n"
            f"{visual_style}\n\n"
            f"--- SPECIFIC AD DESCRIPTION (THIS ITEM) ---\n"
            f"Create the 9-slot marketing breakdown for this item:\n"
            f"\"{local_ad_input}\"\n"
            f"{variation_block}\n"
            f"IMPORTANT: Respond ONLY with a valid JSON object matching the schema below. Do not wrap in markdown code blocks like ```json ... ```. Just return raw JSON.\n"
            f"Schema:\n"
            f"{{\n"
            f"  \"product_name\": \"Clean product name for Excel (e.g. Дом из бруса 6х8, Беседка 3х4, Баня-бочка 2х3)\",\n"
            f"  \"parameters\": \"Key physical parameters of the product for Excel (e.g. Размер 2х2м, пропитка орех, кровля бордо, цена 185к)\",\n"
            f"  \"slots\": [\n"
            f"    {{\n"
            f"      \"slot_number\": 1,\n"
            f"      \"title\": \"Title here\",\n"
            f"      \"marketing_logic\": \"Logic description\",\n"
            f"      \"banner_text\": \"Short text on banner\",\n"
            f"      \"image_prompt\": \"Detailed English prompt for image generation\"\n"
            f"    }}\n"
            f"    // ... exactly 9 slots\n"
            f"  ]\n"
            f"}}"
        )

        # Build parts array
        parts = []
        
        # Load and base64-encode visual style references if provided
        if references:
            for ref_path in references:
                if ref_path and os.path.exists(ref_path):
                    try:
                        ext = os.path.splitext(ref_path)[1].lower()
                        mime_type = "image/jpeg"
                        if ext == ".png":
                            mime_type = "image/png"
                        elif ext == ".webp":
                            mime_type = "image/webp"
                            
                        with open(ref_path, "rb") as image_file:
                            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
                            
                        parts.append({
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": encoded_string
                            }
                        })
                    except Exception as ref_err:
                        print(f"Error encoding reference image {ref_path}: {ref_err}")
                        
        # Append text prompt part
        parts.append({"text": user_prompt})

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.3
            }
        }

        response = self._make_text_request_with_fallback(payload, timeout=45)
        
        if response.status_code != 200:
            raise Exception(f"Gemini API returned error {response.status_code}: {response.text}")

        try:
            response_json = response.json()
            text = response_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines).strip()

            data = json.loads(text)
            slots = data.get("slots", [])

            # Apply hardcoded templates for saunas, or run QA verification for other niches
            if self._is_sauna_product(local_ad_input, global_context):
                print("[Sauna Template] Applying optimized templates for barrel sauna.")
                slots = self._apply_sauna_prompt_templates(local_ad_input, global_context, slots)
            else:
                print("[QA Pass] Running prompt verification and alignment pass.")
                slots = self.verify_and_align_prompts(slots, global_context, local_ad_input)

            return {
                "product_name": data.get("product_name", ""),
                "parameters": data.get("parameters", ""),
                "slots": slots[:9]
            }
        except Exception as e:
            print(f"Error parsing Gemini JSON response: {e}")
            print(f"Raw response text: {response.text}")
            raise Exception(f"Failed to parse marketing slots JSON from Gemini: {e}")

    def verify_and_align_prompts(self, slots: list, global_context: str, local_ad_input: str) -> list:
        """
        Runs a secondary validation pass using Gemini to ensure every image prompt
        strictly adheres to the product details in global context and specific ad input.
        """
        if not slots:
            return slots

        slots_json = []
        for s in slots:
            slots_json.append({
                "slot_number": s.get("slot_number"),
                "title": s.get("title"),
                "image_prompt": s.get("image_prompt")
            })

        system_instruction = (
            "You are a Quality Assurance assistant for an image generation pipeline. "
            "Your task is to review a list of image prompts and correct any prompt that does not align with the product details. "
            "You must ensure that:\n"
            "1. The product shape, type, and name matches EXACTLY what is specified in the Specific Ad Description (e.g. if the ad is for a frame house, the prompt must NOT describe a barrel sauna, and vice versa).\n"
            "2. All key parameters (e.g., dimensions like 6x8, colors, specific materials, etc.) from the Specific Ad Description are strictly included in the prompts.\n"
            "3. Visual style matches the target marketing hook, but NEVER at the expense of correct product specs. "
            "4. The prompts are strictly in English, with NO text overlays, NO people (unless service), NO watermarks.\n\n"
            "Respond ONLY with a JSON array of corrected slots containing 'slot_number' and the corrected 'image_prompt'."
        )

        prompt = (
            f"--- GLOBAL MARKETING CONTEXT ---\n{global_context}\n\n"
            f"--- SPECIFIC AD DESCRIPTION (THE ACTUAL PRODUCT) ---\n{local_ad_input}\n\n"
            f"--- GENERATED SLOTS TO VERIFY ---\n{json.dumps(slots_json, ensure_ascii=False, indent=2)}\n\n"
            f"Review the prompts. For any prompt that deviates from the product type or misses critical parameters, correct it. "
            f"Return ONLY a JSON array like: [{{'slot_number': 1, 'image_prompt': 'corrected prompt'}}, ...]"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1
            }
        }

        try:
            response = self._make_text_request_with_fallback(payload, timeout=30)
            if response.status_code == 200:
                result_json = response.json()
                text = result_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                
                if text.startswith("```"):
                    lines = text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines[-1].strip() == "```":
                        lines = lines[:-1]
                    text = "\n".join(lines).strip()
                
                verified_data = json.loads(text)
                corrections = {item["slot_number"]: item["image_prompt"] for item in verified_data if "slot_number" in item and "image_prompt" in item}
                
                for s in slots:
                    num = s.get("slot_number")
                    if num in corrections:
                        orig = s.get("image_prompt", "")
                        corr = corrections[num]
                        if orig.strip() != corr.strip():
                            print(f"[QA VERIFICATION] Aligned prompt for Slot {num}.")
                            s["image_prompt"] = corr
            else:
                print(f"[QA VERIFICATION] Verification failed with status {response.status_code}. Using original prompts.")
        except Exception as e:
            print(f"[QA VERIFICATION] Error during verification pass: {e}. Using original prompts.")

        return slots

    def _is_sauna_product(self, ad_input: str, global_context: str) -> bool:
        """
        Determines if barrel sauna hardcoded templates should be applied.
        Uses BOTH local ad_input (highest priority) and global_context (business niche),
        but intelligently excludes comparison/competitive phrases from global context.
        """
        import re
        
        # PRIORITY 1: Local ad_input — explicit product keywords (definitive)
        local_text = ad_input.lower()
        local_barrel_kw = ["баня-бочка", "сауна-бочка", "квадробаня", "квадро-баня", "бочка", "сауна", "квадро"]
        if any(kw in local_text for kw in local_barrel_kw):
            return True
        
        # PRIORITY 2: Global context — detect if this COMPANY sells barrel saunas as main product
        # BUT exclude comparison/competitive phrases where competitor's products are mentioned:
        # "Альтернатива бани-бочки", "вместо бочки", "лучше чем бочка", etc.
        gc_text = global_context.lower()
        # Strip phrases where barrel sauna is mentioned as a COMPETITOR / ALTERNATIVE product
        gc_stripped = re.sub(r'альтернатив[аеуы]\s+[\w\-]+(?:\s+[\w\-]+)?', '', gc_text)
        gc_stripped = re.sub(r'вместо\s+[\w\-]+', '', gc_stripped)
        gc_stripped = re.sub(r'в\s+отличие\s+от\s+[\w\-]+', '', gc_stripped)
        gc_stripped = re.sub(r'замен[яит]+\s+[\w\-]+', '', gc_stripped)
        gc_stripped = re.sub(r'лучше\s+(?:чем\s+)?[\w\-]+', '', gc_stripped)
        gc_stripped = re.sub(r'не\s+(?:нужна|нужен|нужно)?\s*[\w\-]*баня', '', gc_stripped)
        
        # Check if the company's OWN products include barrel saunas
        gc_barrel_kw = ["баня-бочка", "сауна-бочка", "квадробаня", "квадро-баня"]
        if any(kw in gc_stripped for kw in gc_barrel_kw):
            return True
        
        return False


    def _apply_sauna_prompt_templates(self, ad_input: str, global_context: str, slots: list) -> list:
        import re
        text = (ad_input + " " + global_context).lower()
        
        # 1. Detect shape type
        shape_type = "Quadro barrel sauna"
        shape_desc = "rounded-rectangular profile (with heavily rounded corners, flat front face, and slightly bowed vertical side walls)"
        if "бочк" in text and "квадр" not in text:
            shape_type = "classic round barrel sauna"
            shape_desc = "circular cylinder-shaped profile (perfectly round shape with flat wooden end walls)"
            
        # 2. Detect dimensions
        width = "2 meters"
        length = "2-meter"
        bands_desc = "exactly two wide vertical stainless steel tensioning bands wrapping around it"
        
        # Search for pattern like 2x2, 2х3, 3*4
        size_match = re.search(r"(\d)[xх\*](\d)", text)
        if size_match:
            w_val = size_match.group(1)
            l_val = size_match.group(2)
            width = f"{w_val} meters"
            length = f"{l_val}-meter"
            
            try:
                l_num = int(l_val)
                if l_num <= 2:
                    bands_desc = "exactly two wide vertical stainless steel tensioning bands wrapping around it"
                elif l_num == 3:
                    bands_desc = "exactly three wide vertical stainless steel tensioning bands wrapping around it"
                elif l_num == 4:
                    bands_desc = "exactly three or four wide vertical stainless steel tensioning bands wrapping around it"
                else:
                    bands_desc = f"exactly {l_num-1} or {l_num} wide vertical stainless steel tensioning bands wrapping around it"
            except:
                pass
                
        # 3. Detect wood color
        wood_color = "rich warm cognac-chestnut brown"
        if "орех" in text:
            wood_color = "medium-brown walnut"
        elif "коньяк" in text:
            wood_color = "rich warm cognac-chestnut brown"
        elif "каштан" in text:
            wood_color = "warm chestnut brown"
        elif "тик" in text:
            wood_color = "golden-brown teak"
        elif "палисандр" in text:
            wood_color = "dark rosewood brown"
        elif "сосн" in text or "ель" in text or "хвоя" in text:
            wood_color = "light natural pine"
            
        # 4. Detect roof color
        roof_color = "burgundy-red and black variegated"
        if "зелен" in text:
            roof_color = "forest-green and black variegated"
        elif "серы" in text or "черн" in text:
            roof_color = "charcoal-gray and black variegated"
        elif "коричн" in text:
            roof_color = "chocolate-brown and black variegated"
        elif "бордо" in text or "красн" in text:
            roof_color = "burgundy-red and black variegated"
            
        templates = {
            1: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. An exterior three-quarter perspective view of a brand-new, complete {shape_type} ({length} long by {width} wide) with a {shape_desc}. The sauna is made of fresh vertical wood planks stained in a {wood_color} shade with detailed natural wood grain. It has a {roof_color} soft hexagonal shingle roof, a silver metal chimney, and is wrapped by {bands_desc} with low-profile horizontal metal tension bolts. The front face features a wooden entrance door with a vertical glass window pane, and a small square window is on the side wall. Warm glowing yellow light is visible inside through the glass. The sauna stands on gray concrete foundation blocks on a gravel pad over a green grass lawn in a neat backyard under natural overcast daylight. No people.",
            2: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. A detailed close-up shot of the wood corner construction of a brand-new {shape_type}. The focus is on the tight joints of the profiled timber planks, showing the detailed natural grain and a rich {wood_color} stain. The planks are clean, smooth, and precisely fitted. A section of a stainless steel tensioning band is visible, pressing firmly against the wood. Natural overcast daylight highlights the high-quality craftsmanship of the wood planks. No people, no tools, no construction debris.",
            3: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. A wide shot showing a complete brand-new {shape_type} ({length} long by {width} wide) with a {shape_desc} being carefully lowered onto foundation blocks on a green grass lawn. The sauna is suspended by heavy-duty black lifting straps connected to a crane hook visible at the very top. The sauna is made of {wood_color} wood planks with a {roof_color} soft shingle roof. It has {bands_desc}. The environment is a neat yard under natural overcast daylight. Strictly no workers, no people, only the sauna suspended in the air being installed.",
            4: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. A close-up shot showing a neat arrangement of small, rectangular wooden sample blocks on a patch of green grass in front of a {wood_color} stained wooden sauna wall. There are nine wood samples, each stained in a different distinct natural wood shade (ranging from golden teak, cognac, walnut, to dark palisander), showing rich wood grain. The background shows the lower section of the sauna wall. Natural overcast daylight. No people.",
            5: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. An inviting, cozy, and clean interior view of an empty {shape_type}. The walls, ceiling, and benches are made of smooth, light-colored linden wood. Two tiers of benches run along the side. A compact black metal sauna stove with stones is visible in the corner, surrounded by a safety wooden railing. Warm, soft light glows from a shaded corner lamp, casting a cozy golden light. No people, no steam, no towels, perfectly clean and ready to use.",
            6: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. A macro close-up detail shot of the tensioning mechanism of a wide stainless steel band wrapping around a {wood_color} stained wooden sauna. The image shows the metal band running horizontally across the wood planks, joined by a heavy-duty horizontal bolt clamp with nuts. The metal is clean, slightly reflecting natural overcast daylight. The focus is sharp on the horizontal clamp, demonstrating strength and reliability. No people.",
            7: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. A clean, eye-level exterior three-quarter view of a brand-new {shape_type} ({length} long by {width} wide) with a {shape_desc}. The sauna has {wood_color} wood planks, a {roof_color} soft shingle roof, a silver chimney, and {bands_desc}. The entrance features a wooden door with a vertical window pane, with warm light glowing from within. The sauna is installed on concrete blocks on a neat grass lawn in a garden under natural overcast daylight. A highly professional, commercial presentation of the product. No people.",
            8: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. An inviting, warm, and bright exterior shot of a brand-new {shape_type} ({length} long by {width} wide) in a neat backyard during late afternoon golden hour. The {wood_color} stained wood glows warmly in the soft light. The {roof_color} soft shingles on the arched roof and the silver chimney are visible. Warm light shines through the windows and the glass door pane. The sauna stands on a flat gravel pad next to green bushes. A highly appealing and cozy image encouraging relaxation. No people.",
            9: "Realistic amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography style. A realistic smartphone photo of a brand-new {shape_type} ({length} long by {width} wide) with a {shape_desc} installed on a customer's country plot. The sauna is made of {wood_color} wood planks with a {roof_color} soft shingle roof and {bands_desc}. The camera captures it standing next to a neat wooden fence and garden plants. Natural overcast daylight, giving it the feel of a real photo taken by a customer to show how it looks in reality. No people."
        }
        
        for slot in slots:
            num = slot.get("slot_number")
            if num in templates:
                slot["image_prompt"] = templates[num].format(
                    length=length,
                    width=width,
                    shape_type=shape_type,
                    shape_desc=shape_desc,
                    wood_color=wood_color,
                    roof_color=roof_color,
                    bands_desc=bands_desc
                )
                
        return slots

    def generate_image(self, prompt: str, aspect_ratio: str = "1:1") -> bytes:
        """
        Calls the Imagen 4.0 API to generate an image from the prompt with fallback.
        Returns the raw image bytes.
        """
        # Supported aspect ratios: "1:1", "3:4", "4:3", "9:16", "16:9"
        if aspect_ratio not in ("1:1", "3:4", "4:3", "9:16", "16:9"):
            aspect_ratio = "1:1"

        payload = {
            "instances": [
                {
                    "prompt": prompt
                }
            ],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": aspect_ratio
            }
        }

        models_predict = ["imagen-4.0-fast-generate-001", "imagen-4.0-generate-001", "imagen-3.0-generate-002"]
        last_response = None
        
        # 1. Try Imagen predict models
        for model in models_predict:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={self.api_key}"
            try:
                print(f"[Image Gen] Requesting image using model: {model}...")
                response = self._make_request_with_retry(url, payload, timeout=40)
                if response.status_code == 200:
                    result_json = response.json()
                    predictions = result_json.get("predictions", [])
                    if predictions and "bytesBase64Encoded" in predictions[0]:
                        image_b64 = predictions[0]["bytesBase64Encoded"]
                        return base64.b64decode(image_b64)
                print(f"[Image Gen Fallback] Model {model} returned status {response.status_code}. Trying next model...")
                last_response = response
            except Exception as e:
                print(f"[Image Gen Fallback] Model {model} failed with exception: {e}. Trying next model...")

        # 2. Try Gemini generateContent image models (Nano Banana)
        models_gen = ["gemini-2.5-flash-image", "gemini-3.1-flash-image", "gemini-3-pro-image", "nano-banana-pro-preview"]
        gen_payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        for model in models_gen:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            try:
                print(f"[Image Gen] Requesting image using generateContent model: {model}...")
                response = self._make_request_with_retry(url, gen_payload, timeout=40)
                if response.status_code == 200:
                    result_json = response.json()
                    candidates = result_json.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            if "inlineData" in part and "data" in part["inlineData"]:
                                image_b64 = part["inlineData"]["data"]
                                return base64.b64decode(image_b64)
                print(f"[Image Gen Fallback] Model {model} returned status {response.status_code}. Trying next model...")
                last_response = response
            except Exception as e:
                print(f"[Image Gen Fallback] Model {model} failed with exception: {e}. Trying next model...")
        
        err_msg = last_response.text if last_response is not None else "No response received"
        err_code = last_response.status_code if last_response is not None else "Unknown"
        raise Exception(f"Image API returned error {err_code}: {err_msg}")

    def generate_style_guide_from_references(self, references: List[str]) -> str:
        """
        Analyzes style reference images and generates a descriptive English style guide.
        """
        import os
        import base64

        system_instruction = (
            "You are an expert AI prompt engineer and professional photographer. "
            "Your task is to analyze the provided reference images and generate a single, cohesive, high-quality visual style guide in English. "
            "Describe the visual style in detail, focusing on: "
            "1. Photographic style (e.g. amateur smartphone photo, shot on iPhone 15 Pro, 4k, realistic 'for sale' commercial photography, natural overcast daylight, neat yard background). "
            "2. Subject details, wood textures, materials, and color palette (e.g. cognac wood planks, black soft shingles). "
            "3. Lighting, angle, and atmosphere (e.g. dramatic warm lighting, cinematic composition). "
            "Keep the output as a single paragraph of 3-5 sentences in English. Do not write any introductory text, prefix, or markdown. Output only the pure text style guide."
        )
        
        parts = []
        for ref_path in references:
            if ref_path and os.path.exists(ref_path):
                try:
                    ext = os.path.splitext(ref_path)[1].lower()
                    mime_type = "image/jpeg"
                    if ext == ".png":
                        mime_type = "image/png"
                    elif ext == ".webp":
                        mime_type = "image/webp"
                        
                    with open(ref_path, "rb") as image_file:
                        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
                        
                    parts.append({
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": encoded_string
                        }
                    })
                except Exception as ref_err:
                    print(f"Error encoding reference image {ref_path}: {ref_err}")

        parts.append({"text": "Generate a detailed English style guide from these references."})

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "temperature": 0.4
            }
        }

        response = self._make_text_request_with_fallback(payload, timeout=45)
        if response.status_code != 200:
            raise Exception(f"Gemini API returned error {response.status_code}: {response.text}")

        try:
            result_json = response.json()
            style_guide = result_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            return style_guide
        except Exception as e:
            raise Exception(f"Failed to parse style guide response: {e}")

