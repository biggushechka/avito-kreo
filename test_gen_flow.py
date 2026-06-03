import requests
import json
import os
import glob

def run_test():
    base_url = "http://127.0.0.1:8000"
    
    # 1. Look for reference files in temp_uploads
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_uploads")
    ref_files = glob.glob(os.path.join(temp_dir, "ref_*"))
    
    selected_refs = []
    if ref_files:
        selected_refs = [ref_files[0]]
        print(f"Using style reference file: {selected_refs[0]}")
    else:
        print("No style reference files found in temp_uploads.")
        
    ad_input = "Баня-бочка Квадро 2x2 под ключ за 185000 рублей"
    print(f"\n1. Sending analyze request for: '{ad_input}'...")
    
    analyze_payload = {
        "local_ad_input": ad_input,
        "references": selected_refs
    }
    
    try:
        # Step A: Analyze ad into 9 slots
        response = requests.post(f"{base_url}/api/analyze", json=analyze_payload, timeout=50)
        print(f"Response status code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Analysis failed: {response.text}")
            return False
            
        data = response.json()
        slots = data.get("slots", [])
        print(f"Received {len(slots)} slots.")
        
        if not slots:
            print("No slots generated.")
            return False
            
        # Inspect Slot 1
        slot1 = slots[0]
        print("\n--- Slot 1 Details ---")
        print(f"Title: {slot1.get('title')}".replace('₽', 'руб'))
        print(f"Logic: {slot1.get('marketing_logic')}".replace('₽', 'руб'))
        print(f"Banner Text: {slot1.get('banner_text')}".replace('₽', 'руб'))
        print(f"Image Prompt: {slot1.get('image_prompt')}")
        print("----------------------")
        
        # Verify language of prompt
        prompt = slot1.get("image_prompt", "")
        # Basic Cyrillic check to ensure it's in English
        has_cyrillic = any(u'\u0400' <= char <= u'\u04FF' for char in prompt)
        if has_cyrillic:
            print("ERROR: Image prompt contains Russian characters! Prompt must be purely in English.")
            return False
        else:
            print("Success: Image prompt is in English (no Cyrillic characters found).")
            
        # Step B: Generate Image for Slot 1
        print(f"\n2. Calling image generation for Slot 1 prompt...")
        gen_payload = {
            "prompt": prompt,
            "aspect_ratio": "1:1"
        }
        
        gen_response = requests.post(f"{base_url}/api/generate-image", json=gen_payload, timeout=120)
        print(f"Generation response status code: {gen_response.status_code}")
        
        if gen_response.status_code != 200:
            print(f"Generation failed: {gen_response.text}")
            return False
            
        gen_data = gen_response.json()
        temp_file = gen_data.get("temp_file_path")
        filename = gen_data.get("filename")
        print(f"Generated successfully!")
        print(f"Saved locally to: {temp_file}")
        print(f"Filename: {filename}")
        
        if temp_file and os.path.exists(temp_file):
            size = os.path.getsize(temp_file)
            print(f"File size: {size} bytes")
            if size > 10000:
                print("Flow test completed successfully with NO errors!")
                return True
            else:
                print("Error: Generated file size is suspiciously small.")
                return False
        else:
            print("Error: Generated image file does not exist on disk.")
            return False
            
    except Exception as e:
        print(f"Exception encountered during flow test: {e}")
        return False

if __name__ == "__main__":
    run_test()
