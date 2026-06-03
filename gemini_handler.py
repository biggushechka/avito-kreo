import requests
import json
import base64
from typing import List, Dict, Any, Optional

class GeminiHandler:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"Content-Type": "application/json"}
        # We use direct REST API endpoints for maximum compatibility on any Python version.
        self.text_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}"
        self.image_url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={self.api_key}"

    def _make_request_with_retry(self, url: str, payload: dict, timeout: int, max_retries: int = 4) -> requests.Response:
        import time
        delay = 10.0
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=self.headers, json=payload, timeout=timeout)
                if response.status_code == 429:
                    print(f"[RATE LIMIT] Got 429 (Resource Exhausted). Retrying in {delay} seconds (Attempt {attempt+1}/{max_retries})...")
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
        return requests.post(url, headers=self.headers, json=payload, timeout=timeout)

    def check_connection(self) -> bool:
        """Verify the API key by making a simple request to list models or generate a tiny text."""
        test_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": "ping"}]}],
            "generationConfig": {"maxOutputTokens": 5}
        }
        try:
            response = requests.post(test_url, headers=self.headers, json=payload, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

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
            "This system works across multiple business niches. You must identify all specific product parameters in the ad description (e.g. size/dimensions like 2x2 or 2x4, colors like cognac or tick, roof shape/material, price, etc.) and RIGIDLY incorporate them into the English image_prompt for every single slot. Do not generalize or omit these parameters. They must match the physical parameters of the specific item.\n\n"
            "CRITICAL GEOMETRY & PROPORTIONS RULE:\n"
            "For sauna dimensions (e.g. 2x2, 2x4, etc.):\n"
            "- For '2x2' or '2 by 2': Describe as 'an extremely short, squat, single-room cubical-shaped sauna. The length of the sauna is exactly equal to its diameter (2 meters long by 2 meters wide). Underneath, it stands on exactly two wooden support skids (foundation logs). It has exactly two metal bands wrapping around it. It must look like a compact wooden cube or short wooden ring, NOT a long barrel or tunnel. Strictly no third metal band, strictly only two bands.'\n"
            "- For '2x3' or '2 by 3': Describe as 'a compact, slightly elongated barrel sauna (3 meters long). Underneath, it stands on exactly three wooden support skids. It has exactly three metal bands.'\n"
            "- For '2x4' or '2 by 4': Describe as 'an elongated rectangular barrel sauna (4 meters long). Underneath, it stands on exactly three or four wooden support skids. It has exactly three or four metal bands wrapping it, showing a moderately long structure.'\n"
            "- For '2x5' or '2x6' or similar: Describe as 'a very long, tunnel-like rectangular barrel sauna structure (5 to 6 meters long). Underneath, it stands on four or five wooden support skids, with four or five metal bands, clearly showing a very long multi-room structure.'\n"
            "Never mix up these proportions. Ensure the English image_prompt matches the input dimensions geometrically by specifying the correct number of bands and skids.\n\n"
            "CRITICAL WINDOWS, DOORS & ANGLE RULE:\n"
            "To make the saunas look highly realistic, cozy, and functional, do not show solid blank back wooden walls. You must always explicitly describe windows and doors in the English image prompt for every slot showing the exterior:\n"
            "- Always specify an entrance: describe 'a wooden entrance door with a vertical glass window pane' or 'a premium tinted tempered glass door'.\n"
            "- Always specify windows: describe 'small square double-glazed windows with dark-stained wooden frames on the side or rear wall'.\n"
            "- Describe warm glowing interior sauna lights visible through the glass door and windows to create a cozy, inviting atmosphere.\n"
            "- Always ensure the camera angle captures these functional features (e.g., a three-quarter exterior perspective view showing both the front entrance door and the side wall with windows).\n\n"
            "CRITICAL IMAGE PROMPT STRUCTURE RULE:\n"
            "When writing the 'image_prompt' for each slot, structure it as follows:\n"
            "1. First, analyze the style, lighting, colors, and atmosphere of the uploaded reference images and describe it in English (e.g., matching the color grading, natural daytime daylight, smartphone photo look of the provided images).\n"
            "2. Second, describe the user-provided general visual style guide (atmosphere, light, camera angle).\n"
            "3. Finally, describe the specific action, subject, or focus of the slot (e.g. 'A close-up of a rustic wooden door with black hinges' or 'An exterior shot of...'). Combine them into a cohesive English prompt."
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
            return {
                "product_name": data.get("product_name", ""),
                "parameters": data.get("parameters", ""),
                "slots": slots[:9]
            }
        except Exception as e:
            print(f"Error parsing Gemini JSON response: {e}")
            print(f"Raw response text: {response.text}")
            raise Exception(f"Failed to parse marketing slots JSON from Gemini: {e}")

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

        response = self._make_request_with_retry(self.image_url, payload, timeout=90)
        
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

