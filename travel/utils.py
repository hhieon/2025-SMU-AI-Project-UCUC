import re, json, time, base64, random, imghdr, requests, pandas as pd
from datetime import datetime
from typing import Tuple, List, Dict, Any

# =========================================================
# 🔑 로컬 전용 OpenAI 키 (절대 공개 저장소 업로드 금지)
#  - 너가 전에 준 키를 그대로 하드코딩 (원하면 바꿔도 됨)
HARDCODE_OPENAI_KEY = "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"
# =========================================================

# ---------- OpenAI ----------
def get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=HARDCODE_OPENAI_KEY)

def run_llm(prompt: str, sys_prompt: str = "", temperature: float = 0.5, model: str = "gpt-4o-mini") -> str:
    client = get_openai_client()
    try:
        resp = client.responses.create(
            model=model,
            input=(f"[SYSTEM]\n{sys_prompt}\n\n[USER]\n{prompt}" if sys_prompt else prompt),
            temperature=temperature,
            timeout=20.0,  # 타임아웃
        )
        return getattr(resp, "output_text", None) or resp.output[0].content[0].text
    except Exception:
        # 폴백: chat.completions
        msgs = [{"role": "user", "content": prompt}]
        if sys_prompt:
            msgs = [{"role": "system", "content": sys_prompt}] + msgs
        comp = client.chat.completions.create(
            model=model, messages=msgs, temperature=temperature, timeout=20.0
        )
        return comp.choices[0].message.content

def _guess_mime(image_bytes: bytes) -> str:
    kind = imghdr.what(None, h=image_bytes)
    if kind in ("jpeg", "jpg"): return "image/jpeg"
    if kind == "png": return "image/png"
    if kind == "gif": return "image/gif"
    return "image/jpeg"

def run_llm_vision(image_bytes: bytes, prompt: str, sys_prompt: str = "", temperature: float = 0.2, model: str = "gpt-4o-mini") -> str:
    client = get_openai_client()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{_guess_mime(image_bytes)};base64,{b64}"
    try:
        # Responses API
        content = []
        if sys_prompt:
            content.append({"type": "input_text", "text": sys_prompt})
        content.append({"type": "input_text", "text": prompt})
        content.append({"type": "input_image", "image_url": {"url": data_url}})
        resp = client.responses.create(
            model=model,
            input=[{"role": "user", "content": content}],
            temperature=temperature,
            timeout=20.0,
        )
        return getattr(resp, "output_text", None) or resp.output[0].content[0].text
    except Exception:
        # 폴백: chat.completions (구버전 호환)
        msgs = []
        if sys_prompt:
            msgs.append({"role": "system", "content": sys_prompt})
        msgs.append({"role":"user","content":[
            {"type":"text","text":prompt},
            {"type":"image_url","image_url":{"url":data_url}}
        ]})
        comp = client.chat.completions.create(
            model=model, messages=msgs, temperature=temperature, timeout=20.0
        )
        return comp.choices[0].message.content

# ---------- 안전 JSON 파서 ----------
def safe_json_loads(raw: str):
    if isinstance(raw, (dict, list)): return raw
    txt = (raw or "").strip().replace("\ufeff", "")
    if txt.startswith("```"):
        lines = txt.splitlines()
        if lines and lines[0].startswith("```"): lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"): lines = lines[:-1]
        txt2 = "\n".join(lines).strip()
        try: return json.loads(txt2)
        except Exception: pass
    try: return json.loads(txt)
    except Exception: pass
    l = txt.find("{"); r = txt.rfind("}")
    if l != -1 and r != -1 and r > l:
        for j in range(r, l, -1):
            try: return json.loads(txt[l:j+1])
            except Exception: continue
    raise ValueError("JSON 추출 실패")

# ---------- Wikimedia / Commons (UA + 백오프) ----------
USER_AGENT = "TravelGuideDjango/1.0 (contact: you@example.com)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
WIKI_API = "https://{lang}.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

def _http_get(url, params, tries=4, base_sleep=0.7):
    last = None
    for i in range(tries):
        try:
            r = SESSION.get(url, params=params, timeout=20)
            if r.status_code in (429, 503):
                time.sleep(base_sleep*(i+1)+random.random()*0.3); last = r; continue
            r.raise_for_status(); return r
        except requests.HTTPError as e:
            last = e.response
            if last is not None and last.status_code in (429, 503):
                time.sleep(base_sleep*(i+1)+random.random()*0.3); continue
            raise
        except Exception as e:
            last = e
            time.sleep(base_sleep*(i+1)+random.random()*0.3)
    if isinstance(last, requests.Response): last.raise_for_status()
    else: raise requests.HTTPError("HTTP GET failed after retries")

def _looks_korean(text: str) -> bool:
    return bool(re.search(r"[\uac00-\ud7a3]", text or ""))

def wiki_search(query: str, lang: str = "auto", limit: int = 5):
    if lang == "auto":
        langs = ["ko","en"] if _looks_korean(query) else ["en","ko"]
    else:
        langs = [lang]
    for lg in langs:
        try:
            params = {"action":"query","list":"search","srsearch":query,"format":"json","srlimit":limit}
            r = _http_get(WIKI_API.format(lang=lg), params)
            results = r.json().get("query", {}).get("search", [])
            if results: return results, lg
        except Exception:
            continue
    return [], (langs[0] if langs else "en")

def wiki_page_thumb(pageid: int, lang: str = "en", size: int = 900):
    try:
        params = {"action":"query","prop":"pageimages","format":"json","pageids":pageid,"pithumbsize":size}
        r = _http_get(WIKI_API.format(lang=lang), params)
        pages = r.json().get("query", {}).get("pages", {})
        for _, p in pages.items():
            thumb = p.get("thumbnail", {})
            if thumb.get("source"): return thumb["source"]
    except Exception:
        pass
    return None

def commons_image_search(query: str, limit: int = 50):
    try:
        params = {"action":"query","format":"json","list":"search","srsearch":query,"srlimit":limit,"srnamespace":6}
        r = _http_get(COMMONS_API, params)
        return r.json().get("query", {}).get("search", [])
    except Exception:
        return []

def commons_first_image_url(file_title: str, thumb_width: int = 900):
    try:
        params = {"action":"query","format":"json","prop":"imageinfo","titles":file_title,"iiprop":"url","iiurlwidth":thumb_width}
        r = _http_get(COMMONS_API, params)
        pages = r.json().get("query", {}).get("pages", {})
        for _, p in pages.items():
            infos = p.get("imageinfo", [])
            if infos: return infos[0].get("thumburl") or infos[0].get("url")
    except Exception:
        pass
    return None

def best_photo_for_place(place_name: str, lang: str = "auto"):
    try:
        results, used_lang = wiki_search(place_name, lang=lang, limit=1)
        thumb_url = None
        if results:
            pid = results[0].get("pageid")
            if pid: thumb_url = wiki_page_thumb(pid, lang=used_lang, size=900)
        commons_hits = commons_image_search(place_name, limit=50)
        if not thumb_url and commons_hits:
            first_file = commons_hits[0].get("title")
            if first_file: thumb_url = commons_first_image_url(first_file, thumb_width=900)
        return thumb_url, len(commons_hits)
    except Exception:
        return None, 0

# ---------- ICS ----------
def itinerary_to_ics(events_df: pd.DataFrame, title_prefix="Trip"):
    """
    events_df: columns = ["start_dt", "end_dt", "title", "location", "notes"]
    """
    def sanitize(s):
        if s is None: return ""
        s = str(s).replace("\r\n","\n").replace("\r","\n").replace("\n"," ")
        s = s.replace(",", r"\,").replace(";", r"\;"); return s

    lines = ["BEGIN:VCALENDAR","VERSION:2.0","PRODID:-//LLM Travel Guide//KR//EN"]

    for _, r in events_df.iterrows():
        uid = f"{r['start_dt'].strftime('%Y%m%dT%H%M%S')}@llm-travel"
        dtstart = r["start_dt"].strftime("%Y%m%dT%H%M%S")
        dtend   = r["end_dt"].strftime("%Y%m%dT%H%M%S")
        summary_raw = f"{title_prefix} - {r.get('title','')}"
        summary  = sanitize(summary_raw)
        location = sanitize(r.get("location",""))
        descr    = sanitize(r.get("notes",""))
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{summary}",
            f"LOCATION:{location}",
            f"DESCRIPTION:{descr}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines).encode("utf-8")
