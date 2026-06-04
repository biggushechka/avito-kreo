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
        self.text_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}"
        self.image_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-fast-generate-001:predict?key={self.api_key}"

    def _make_request_with_retry(self, url: str, payload: dict, timeout: int, max_retries: int = 4) -> requests.Response:
        import time
        delay = 2.0
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=self.headers, json=payload, timeout=timeout, proxies=self.proxies)
                if response.status_code == 429:
                    if attempt == max_retries - 1:
                        return response
                    print(f"[RATE LIMIT] Got 429 (Resource Exhausted). Retrying in {delay} seconds (Attempt {attempt+1}/{max_retries})...")
                    time.sleep(delay)
                    delay *= 1.5
                    continue
                elif response.status_code in (500, 502, 503, 504):
                    if attempt == max_retries - 1:
                        return response
                    print(f"[SERVER ERROR] Got {response.status_code}. Retrying in {delay} seconds (Attempt {attempt+1}/{max_retries})...")
                    time.sleep(delay)
                    delay *= 1.5
                    continue
                return response
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise e
                print(f"[CONNECTION ERROR] {e}. Retrying in {delay} seconds (Attempt {attempt+1}/{max_retries})...")
                time.sleep(delay)
                delay *= 1.5
        return requests.post(url, headers=self.headers, json=payload, timeout=timeout, proxies=self.proxies)

    def check_connection(self) -> bool:
        """Verify the API key by making a simple request to list models or generate a tiny text."""
        test_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 5}
        }
        try:
            response = requests.post(test_url, headers=self.headers, json=payload, timeout=10, proxies=self.proxies)
            return response.status_code == 200
        except Exception:
            return False

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
                "temperature": 0.2
            }
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
            
        response = self._make_request_with_retry(self.text_url, payload, timeout=30)
        if response.status_code != 200:
            raise Exception(f"Gemini API returned error {response.status_code}: {response.text}")
            
        try:
            result_json = response.json()
            return result_json["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            raise Exception(f"Failed to parse text response from Gemini: {e}")

    def generate_marketing_slots(self, global_context: str, visual_style: str, local_ad_input: str, references: List[str] = []) -> List[Dict[str, Any]]:
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
            "CRITICAL LANGUAGE RULE:\n"
            "The 'image_prompt' field for EVERY slot MUST BE WRITTEN ENTIRELY IN ENGLISH. Do not use Russian letters or words in the image_prompt. The text of the banner (banner_text) and titles must be in Russian, but the image_prompt itself must be in pure English.\n\n"
            "CRITICAL NICHE ADAPTABILITY & PARAMETER ENFORCEMENT:\n"
            "This system works across multiple business niches. You must identify all specific parameters in the ad description (e.g. size/dimensions, color/stain, price, material, or service specifics) and RIGIDLY incorporate them into the English image_prompt for every single slot. Do not generalize or omit these parameters. They must match the specific item or service being advertised.\n\n"
            "CRITICAL PRODUCT/SERVICE FOCUS & NO-HUMANS RULE:\n"
            "1. Identify whether the advertised item is a physical product (e.g., saunas, building materials, physical goods) or a service (e.g., Avito manager/avitoologist, marketing, consulting, repairs).\n"
            "2. For PHYSICAL PRODUCTS: All generated images MUST feature the physical product itself (or its details, materials, and components) as the central focus. Strictly NO humans, NO faces, NO workers, and NO characters must be visible in the image. Focus entirely on the object, its textures, and its environment.\n"
            "3. For SERVICES: All generated images MUST feature the workspace, tools, or direct visual representations of the service (e.g., a modern laptop screen showing business growth charts, graphs, or the Avito dashboard; a neat office desk with a notebook and coffee; a professional workstation). Avoid generic stock-photo style humans. If a human representation is absolutely necessary for the service context, describe them only in a professional, natural setting (e.g., 'a close-up over-the-shoulder view focusing on a computer screen showing analytics charts', which keeps the focus on the screen/work, avoiding direct faces).\n\n"
            "CRITICAL GEOMETRY & PROPORTIONS RULE (FOR SAUNA PRODUCTS):\n"
            "For sauna shapes and dimensions:\n"
            "- It must always be represented as a barrel-shaped sauna (rounded profile). If the description mentions 'Quadro' (Квадро) or 'Quadro-box' (квадробаня) or 'закругленный квадрат', it MUST be described as a rounded-rectangular profile with heavily rounded corners, curved side walls, and a slightly arched roof. It is NOT a square cabin, NOT a box house, and has NO sharp 90-degree corners. You must explicitly specify 'Quadro barrel sauna with a distinctive rounded-rectangular profile, heavily rounded corners, and slightly curved walls'. Do not use words like 'cube-shaped', 'cubical', or 'box-like'.\n"
            "- For '2x2' or '2 by 2': Describe as 'an extremely short, squat, single-room rounded-rectangular Quadro barrel sauna. The length of the sauna is exactly equal to its diameter (2 meters long by 2 meters wide). Underneath, it stands on exactly two wooden support skids (foundation logs). It has exactly two metal bands wrapping around it. It must look like a very short barrel sauna with heavily rounded corners, NOT a long barrel, and NOT a flat-roofed square cabin. Strictly no third metal band, strictly only two bands.'\n"
            "- For '2x3' or '2 by 3': Describe as 'a compact, slightly elongated rounded-rectangular Quadro barrel sauna (3 meters long). Underneath, it stands on exactly three wooden support skids. It has exactly three metal bands.'\n"
            "- For '2x4' or '2 by 4': Describe as 'an elongated rounded-rectangular Quadro barrel sauna (4 meters long). Underneath, it stands on exactly three or four wooden support skids. It has exactly three or four metal bands wrapping it, showing a moderately long structure.'\n"
            "- For '2x5' or '2x6' or similar: Describe as 'a very long, tunnel-like rounded-rectangular Quadro barrel sauna structure (5 to 6 meters long). Underneath, it stands on four or five wooden support skids, with four or five metal bands, clearly showing a very long multi-room structure.'\n"
            "Never mix up these proportions. Ensure the English image_prompt matches the input dimensions geometrically by specifying the correct profile, bands, and skids.\n\n"
            "CRITICAL NICHES & SLOTS INSTRUCTIONS:\n"
            "- For installation/delivery/startup slots: If it's a physical product like a sauna, describe it suspended by crane/manipulator straps being lowered onto foundation blocks, with no people. If it is a service, describe the start of work (e.g., a clean laptop opening up, or a neat notebook with a pen and a digital dashboard on a screen).\n"
            "- For color/materials/options slots: If it's a physical product, show close-up textures or material sample blocks neatly arranged. If it is a service, show representative professional tool setups, reports, or charts.\n"
            "- For interior/experience slots: If it's a physical product, show a clean, warm, empty interior (e.g., inside the sauna with benches and stove). If it is a service, show a detailed view of the final output (e.g., a screen showing an active Avito dashboard with high views, charts, and successful statistics).\n"
            "- For call-to-action/more info slots: Show a clean, professional, inviting representation of the complete product or workspace (e.g., a complete Quadro barrel sauna standing in a yard, or a modern office desk setup with business analytics visible on a screen).\n\n"
            "CRITICAL WINDOWS, DOORS & ANGLE RULE (FOR SAUNA PRODUCTS):\n"
            "To make the saunas look highly realistic, cozy, and functional, do not show solid blank back wooden walls. You must always explicitly describe windows and doors in the English image prompt for every slot showing the exterior:\n"
            "- Always specify an entrance: describe 'a wooden entrance door with a vertical glass window pane' or 'a premium tinted tempered glass door'.\n"
            "- Always specify windows: describe 'small square double-glazed windows with dark-stained wooden frames on the side or rear wall'.\n"
            "- Describe warm glowing interior sauna lights visible through the glass door and windows to create a cozy, inviting atmosphere.\n"
            "- Always ensure the camera angle captures these functional features (e.g., a three-quarter exterior perspective view showing both the front entrance door and the side wall with windows).\n\n"
            "CRITICAL IMAGE PROMPT STRUCTURE RULE:\n"
            "When writing the 'image_prompt' for each slot, structure it as follows:\n"
            "1. First, analyze the style, lighting, colors, and atmosphere of the uploaded reference images and describe it in English (e.g., matching the color grading, natural daytime daylight, smartphone photo look of the provided images).\n"
            "2. Second, describe the user-provided general visual style guide (atmosphere, light, camera angle).\n"
            "3. Finally, describe the specific action, subject, or focus of the slot (e.g. 'A close-up of a laptop screen' or 'An exterior shot of...'). Combine them into a cohesive English prompt."
        )

        user_prompt = (
            f"--- GLOBAL MARKETING CONTEXT & BRAND INFO ---\n"
            f"{global_context}\n\n"
            f"--- VISUAL STYLE PREFERENCES ---\n"
            f"{visual_style}\n\n"
            f"--- SPECIFIC AD DESCRIPTION (THIS ITEM) ---\n"
            f"Create the 9-slot marketing breakdown for this item:\n"
            f"\"{local_ad_input}\"\n\n"
            f"IMPORTANT: Respond ONLY with a valid JSON object matching the schema below. Do not wrap in markdown code blocks like ```json ... ```. Just return raw JSON.\n"
            f"Schema:\n"
            f"{{\n"
            f"  \"product_name\": \"Clean product name for Excel (e.g. Баня-бочка Квадро 2х2)\",\n"
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

        response = self._make_request_with_retry(self.text_url, payload, timeout=45)
        
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
            
            # Post-process slots if it's a sauna product to use bulletproof templates
            if self._is_sauna_product(local_ad_input, global_context):
                slots = self._apply_sauna_prompt_templates(local_ad_input, global_context, slots)
                
            return {
                "product_name": data.get("product_name", ""),
                "parameters": data.get("parameters", ""),
                "slots": slots[:9]
            }
        except Exception as e:
            print(f"Error parsing Gemini JSON response: {e}")
            print(f"Raw response text: {response.text}")
            raise Exception(f"Failed to parse marketing slots JSON from Gemini: {e}")

    def _is_sauna_product(self, ad_input: str, global_context: str) -> bool:
        text = (ad_input + " " + global_context).lower()
        keywords = ["баня", "бани", "сауна", "сауны", "квадробаня", "баня-бочка", "баню", "баней"]
        return any(kw in text for kw in keywords)

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
        Calls the Imagen 3 API to generate an image from the prompt.
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

        response = self._make_request_with_retry(self.image_url, payload, timeout=40)
        
        if response.status_code != 200:
            raise Exception(f"Imagen API returned error {response.status_code}: {response.text}")

        try:
            result_json = response.json()
            predictions = result_json.get("predictions", [])
            if not predictions:
                raise Exception("No predictions/images returned from Imagen API: " + json.dumps(result_json))
            
            image_b64 = predictions[0]["bytesBase64Encoded"]
            image_bytes = base64.b64decode(image_b64)
            return image_bytes
            
        except Exception as e:
            raise Exception(f"Failed to decode generated image: {e}")

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

        response = self._make_request_with_retry(self.text_url, payload, timeout=45)
        if response.status_code != 200:
            raise Exception(f"Gemini API returned error {response.status_code}: {response.text}")

        try:
            result_json = response.json()
            style_guide = result_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            return style_guide
        except Exception as e:
            raise Exception(f"Failed to parse style guide response: {e}")

