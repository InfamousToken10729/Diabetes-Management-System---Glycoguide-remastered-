import json
import re
import requests
from typing import Dict, Any, Optional

SYSTEM_PROMPT = (
    "You are a clinical diabetes nutrition estimator supporting a person with Type 1 diabetes. "
    "Estimate macronutrients in grams (carbohydrates, protein, fat, and sugars as a subset of carbs). "
    "CRITICAL CLINICAL RULE: Sugar is already included within total carbohydrates; NEVER add sugar on top of carbs. "
    "Each item and the totals must satisfy: 0 <= sugar <= carbs. "
    "When the user specifies weights or quantities, trust them over visual estimates. "
    "Use standard cooked food composition data. "
    "Be conservative and never hallucinate foods that are not described or visible. "
    "Totals must equal the exact sum of individual items. "
    "Return strictly valid JSON with this exact schema:\n"
    "{\n"
    '  "items": [\n'
    '    {"name": "string", "estimatedGrams": 0, "carbs": 0, "protein": 0, "fat": 0, "sugar": 0}\n'
    "  ],\n"
    '  "totals": {"carbs": 0, "protein": 0, "fat": 0, "sugar": 0},\n'
    '  "confidence": "low" | "medium" | "high",\n'
    '  "notes": "short clinical assumption sentence"\n'
    "}"
)

def analyze_meal_nutrition(
    description: str,
    image_base64: Optional[str],
    api_key: str,
    model: str = "gemini-2.5-flash",
    base_url: str = "https://generativelanguage.googleapis.com"
) -> Dict[str, Any]:
    """
    Analyzes a meal photo and/or text description and returns structured nutritional estimation.
    Supports both Google Gemini native endpoints and OpenAI-compatible completions.
    """
    if not api_key:
        raise ValueError("AI API Key is not configured. Please set it in Settings.")

    cleaned_desc = description.strip() if description else ""
    if not cleaned_desc and not image_base64:
        raise ValueError("Please provide either a meal description or a photo.")

    # 1. Native Google Gemini API
    if "generativelanguage.googleapis.com" in base_url or "gemini" in model.lower() and not "openai" in base_url:
        parts = []
        if cleaned_desc:
            parts.append({"text": f"Meal description: {cleaned_desc}"})
        else:
            parts.append({"text": "No description provided. Estimate from the meal photo."})

        if image_base64:
            # Extract mime and clean base64 data
            mime = "image/jpeg"
            data = image_base64
            if "," in image_base64:
                header, data = image_base64.split(",", 1)
                match = re.search(r"data:([^;]+);base64", header)
                if match:
                    mime = match.group(1)
            parts.append({
                "inline_data": {
                    "mime_type": mime,
                    "data": data
                }
            })

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1
            }
        }

        resp = requests.post(endpoint, json=payload, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API returned status {resp.status_code}: {resp.text}")

        res_json = resp.json()
        try:
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
            # Clean markdown formatting if present
            clean_raw = re.sub(r"^```json\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE)
            return json.loads(clean_raw)
        except Exception as e:
            raise RuntimeError(f"Failed to parse Gemini response: {e}")

    # 2. OpenAI-Compatible Fallback (Groq, OpenRouter, OpenAI, Local LLMs)
    else:
        messages_content = []
        messages_content.append({
            "type": "text",
            "text": cleaned_desc if cleaned_desc else "No description provided. Estimate from the meal photo."
        })
        if image_base64:
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": image_base64}
            })

        clean_base = base_url.rstrip("/")
        endpoint = f"{clean_base}/chat/completions"
        payload = {
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": messages_content}
            ]
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        resp = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"AI Provider returned status {resp.status_code}: {resp.text}")

        res_json = resp.json()
        try:
            raw_text = res_json["choices"][0]["message"]["content"]
            clean_raw = re.sub(r"^```json\s*|\s*```$", "", raw_text.strip(), flags=re.MULTILINE)
            return json.loads(clean_raw)
        except Exception as e:
            raise RuntimeError(f"Failed to parse AI response: {e}")
