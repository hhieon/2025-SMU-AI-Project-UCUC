# travel/llm_providers.py
from typing import Optional, List

# =========================
# 🔐 API KEY (하드코딩)
# =========================
OPENAI_API_KEY = "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"   # 예: sk-...
GEMINI_API_KEY = "AIzaSyD61lOc4-pQSj27lSlpFV7w8mEKwbWJdvI"  # 네가 준 키

# =========================
# 모델 카탈로그 (UI/서버 공용)
# =========================
OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4o",
    "gpt-5",            # 계정/시점에 따라 미지원일 수 있음
]
GEMINI_MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash-8b",
]
PROVIDERS = {"openai": OPENAI_MODELS, "gemini": GEMINI_MODELS}
DEFAULT_MODEL = {"openai": OPENAI_MODELS[0], "gemini": GEMINI_MODELS[0]}

def list_models(provider: str) -> List[str]:
    return PROVIDERS.get(provider, OPENAI_MODELS)

# =========================
# Provider 별 호출
# =========================
def _ask_openai(model: str, system: Optional[str], user: str,
                temperature: float = 0.7, max_tokens: int = 1200) -> str:
    # OpenAI SDK v1
    from openai import OpenAI
    if not OPENAI_API_KEY or OPENAI_API_KEY.startswith("여기에_"):
        raise RuntimeError("OPENAI_API_KEY 하드코딩 값이 비어 있습니다.")
    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system or ""},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()

def _ask_gemini(model: str, system: Optional[str], user: str,
                temperature: float = 0.7, max_output_tokens: int = 1500) -> str:
    import google.generativeai as genai
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 하드코딩 값이 비어 있습니다.")
    genai.configure(api_key=GEMINI_API_KEY)
    gmodel = genai.GenerativeModel(
        model_name=model,
        system_instruction=system or None
    )
    resp = gmodel.generate_content(
        user,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
    )
    if hasattr(resp, "text") and resp.text:
        return resp.text.strip()

    # fallback
    parts = []
    for c in getattr(resp, "candidates", []) or []:
        content = getattr(c, "content", None)
        for p in getattr(content, "parts", []) or []:
            t = getattr(p, "text", "")
            if t:
                parts.append(t)
    return "\n".join(parts).strip()

# =========================
# 공용 엔트리
# =========================
def ask_llm(provider: str, model: Optional[str], system: Optional[str], user: str,
            **kwargs) -> str:
    provider = (provider or "openai").lower()
    model = model or DEFAULT_MODEL.get(provider, OPENAI_MODELS[0])
    if provider == "gemini":
        return _ask_gemini(model, system, user, **kwargs)
    return _ask_openai(model, system, user, **kwargs)
