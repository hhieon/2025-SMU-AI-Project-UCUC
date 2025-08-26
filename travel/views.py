# travel/views.py
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_POST
from datetime import datetime, timedelta
import pandas as pd
import json
import base64

from .llm_providers import ask_llm, DEFAULT_MODEL
from .utils import (
    run_llm_vision,          # 사진(멀티모달)만 기존 유틸 사용
    safe_json_loads,
    best_photo_for_place,
    itinerary_to_ics,
    get_current_weather,     # ✅ 날씨 조회
)

# 폼 기본 제공사
DEFAULT_PROVIDER = "openai"


# --- 도시 가이드 ---
def guide_view(request):
    # 기본 선택값(초기 GET에서도 템플릿에 내려줌)
    ctx = {
        "result": None,
        "error": None,
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL.get(DEFAULT_PROVIDER),
        "weather": None,           # ✅ 날씨
        "weather_error": None,     # ✅ 날씨 에러
    }

    if request.method == "POST":
        city = request.POST.get("city", "Seoul").strip()
        days = int(request.POST.get("days", "3"))
        lang = request.POST.get("lang", "ko")
        prefs = request.POST.get("prefs", "").strip()

        # ✅ 날씨 조회 (실패해도 페이지는 계속)
        try:
            weather, werr = get_current_weather(city)
        except Exception:
            weather, werr = None, "날씨 조회 실패"
        ctx["weather"], ctx["weather_error"] = weather, werr

        # 모델 선택값 수집 (없으면 기본)
        provider = (request.POST.get("provider") or DEFAULT_PROVIDER).lower()
        model = request.POST.get("model") or DEFAULT_MODEL.get(provider)
        ctx["provider"], ctx["model"] = provider, model

        sys_prompt = (
            "너는 여행 큐레이터다. 반드시 코드블록(백틱) 없이 '순수 JSON'만 출력한다.\n"
            "각 Day마다 3~6개의 POI를 순서대로 추천하고,\n"
            "각 POI는 'name','why','time_slot','area','tips' 필드를 가진다.\n"
            "출력 형식 예:\n"
            "{\"city\":\"...\",\"days\":["
            "{\"day\":1,\"theme\":\"...\",\"items\":[{\"name\":\"...\",\"why\":\"...\","
            "\"time_slot\":\"09:00-10:30\",\"area\":\"...\",\"tips\":\"...\"}]}]}"
        )
        lang_note = "(한국어로)" if lang == "ko" else "(English)"
        prompt = (
            f"도시: {city}\n여행일수: {days}일\n선호/제약: {prefs or '특이사항 없음'}\n{lang_note}\n"
            "JSON만 출력."
        )

        try:
            raw = ask_llm(provider, model, sys_prompt, prompt, temperature=0.6)
            plan = safe_json_loads(raw)
        except Exception as e:
            return render(
                request,
                "travel/guide.html",
                {
                    "error": f"응답 파싱 실패: {e}",
                    "result": None,
                    "raw": raw if "raw" in locals() else "(no raw)",
                    "provider": provider,
                    "model": model,
                    "weather": weather,
                    "weather_error": werr,
                },
            )

        city_name = plan.get("city", city)
        days_list = plan.get("days", [])

        # 썸네일 조회(최대 12개)
        thumbs_map = {}
        picked = 0
        for d in days_list:
            for item in d.get("items", []):
                if picked >= 12:
                    break
                name = (item.get("name") or "").strip()
                if name and name not in thumbs_map:
                    url, _ = best_photo_for_place(name, lang="auto")
                    if url:
                        thumbs_map[name] = url
                        picked += 1
            if picked >= 12:
                break

        # 각 아이템에 thumb 필드 주입
        for d in days_list:
            for item in d.get("items", []):
                name = (item.get("name") or "").strip()
                item["thumb"] = thumbs_map.get(name)

        # ICS용 이벤트 세션 저장
        all_events = []
        base_today = datetime.today().replace(hour=9, minute=0, second=0, microsecond=0)
        for day in days_list:
            for item in day.get("items", []):
                slot = item.get("time_slot", "09:00-10:00")
                try:
                    s, e = slot.split("-")
                    sh, sm = int(s[:2]), int(s[3:5])
                    eh, em = int(e[:2]), int(e[3:5])
                except Exception:
                    sh, sm, eh, em = 9, 0, 10, 0
                d0 = base_today + timedelta(days=int(day.get("day", 1)) - 1)
                sdt, edt = d0.replace(hour=sh, minute=sm), d0.replace(hour=eh, minute=em)
                all_events.append(
                    {
                        "start_dt": sdt.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_dt": edt.strftime("%Y-%m-%d %H:%M:%S"),
                        "title": item.get("name", ""),
                        "location": item.get("area", ""),
                        "notes": item.get("why", ""),
                    }
                )
        request.session["guide_events"] = all_events

        pretty_json = json.dumps(plan, ensure_ascii=False, indent=2)
        ctx["result"] = {"city": city_name, "days": days_list, "pretty_json": pretty_json}

    return render(request, "travel/guide.html", ctx)


def guide_ics_download(request):
    events = request.session.get("guide_events")
    city = request.POST.get("city", "") or "Trip"
    if not events:
        return HttpResponseBadRequest("다운로드할 일정이 없습니다.")
    rows = [
        {
            "start_dt": datetime.strptime(e["start_dt"], "%Y-%m-%d %H:%M:%S"),
            "end_dt": datetime.strptime(e["end_dt"], "%Y-%m-%d %H:%M:%S"),
            "title": e["title"],
            "location": e["location"],
            "notes": e["notes"],
        }
        for e in events
    ]
    df = pd.DataFrame(rows)
    ics = itinerary_to_ics(df, title_prefix=f"{city} Trip")
    resp = HttpResponse(ics, content_type="text/calendar")
    resp["Content-Disposition"] = f'attachment; filename="{city}_trip.ics"'
    return resp


# --- 사진 장소 (힌트 기본값 제거 버전) ---
def photo_view(request):
    ctx = {"result": None, "error": None}
    if request.method == "POST" and request.FILES.get("photo"):
        photo = request.FILES["photo"].read()
        city_hint = request.POST.get("city_hint", "").strip()        # 기본값 없음
        country_hint = request.POST.get("country_hint", "").strip()  # 기본값 없음
        topk = int(request.POST.get("topk", "3"))

        sys_prompt = (
            "너는 사진 속 랜드마크/장소를 식별하는 전문가다. "
            "출력은 코드블록(백틱) 없이 JSON만 반환한다. 한국어로 작성.\n"
            "스키마:{\"candidates\":[{\"name\":\"장소명\",\"city\":\"도시\",\"country\":\"국가\","
            "\"type\":\"랜드마크/박물관/전망대/자연/상업지구\",\"confidence\":0~100,\"reasons\":\"근거\"}],"
            "\"best\":0기반 인덱스,\"notable_features\":[\"시각 단서\"],\"need_more_photos\":true/false}"
        )
        user_prompt = (
            f"도시 힌트:{city_hint or '없음'} / 국가 힌트:{country_hint or '없음'} / 최대 후보:{topk}. "
            "스키마로만 JSON 출력."
        )

        try:
            raw = run_llm_vision(photo, prompt=user_prompt, sys_prompt=sys_prompt, temperature=0.2)
            obj = safe_json_loads(raw)
        except Exception as e:
            ctx["error"] = f"식별 실패: {e}"
            ctx["raw"] = raw if "raw" in locals() else "(no raw)"
            return render(request, "travel/photo.html", ctx)

        cands = obj.get("candidates", [])[:topk]
        if not cands:
            ctx["error"] = "후보를 찾지 못했습니다. 다른 각도/넓은 구도의 사진을 올려보세요."
            return render(request, "travel/photo.html", ctx)

        best_idx = obj.get("best", 0)
        if best_idx < 0 or best_idx >= len(cands):
            best_idx = 0
        best = cands[best_idx]
        place = best.get("name", "")
        ref_url, hits = best_photo_for_place(place, lang="auto")

        # 세션 저장 (Q&A용)
        request.session["photo_ctx"] = {
            "obj": obj,
            "image_b64": base64.b64encode(photo).decode("ascii"),
        }
        ctx["result"] = {
            "cands": cands,
            "best_idx": best_idx,
            "ref_url": ref_url,
            "hits": hits,
            "place": place,
        }
    return render(request, "travel/photo.html", ctx)


def photo_qa_view(request):
    q = request.POST.get("question", "").strip()
    if not q:
        return redirect("photo")
    st = request.session.get("photo_ctx")
    if not st:
        return redirect("photo")

    obj = st["obj"]
    photo = base64.b64decode(st["image_b64"].encode("ascii"))
    ctx_text = json.dumps(obj, ensure_ascii=False)
    prompt = f"아래 컨텍스트(후보 JSON)를 우선 근거로 간결히 답하라.\n\n{ctx_text}\n\n[질문]\n{q}"
    ans = run_llm_vision(photo, prompt=prompt, sys_prompt="", temperature=0.3)
    return render(request, "travel/photo.html", {"qa_answer": ans, "result": None})


# --- 번역 ---
def translate_view(request):
    # 기본 선택값(폼에 선택 박스가 없더라도 기본 동작)
    ctx = {
        "result": None,
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL.get(DEFAULT_PROVIDER),
    }

    if request.method == "POST":
        src = request.POST.get("src", "자동감지")
        tgt = request.POST.get("tgt", "en")
        tone = request.POST.get("tone", "중립")
        text = request.POST.get("text", "")

        provider = (request.POST.get("provider") or DEFAULT_PROVIDER).lower()
        model = request.POST.get("model") or DEFAULT_MODEL.get(provider)
        ctx["provider"], ctx["model"] = provider, model

        sys = (
            "너는 여행 번역 도우미다. 표지판/식당/교통의 짧은 문장을 자연스럽게 번역하라.\n"
            "- 고유명사는 번역하지 말고 원문 유지.\n- 돈/시간/거리 단위는 현지 표기 유지.\n"
            f"- 말투는 '{tone}'.\n결과는 순수 번역문만 출력."
        )
        prompt = (
            f"[목표 언어={tgt}]\n{text}\n(원문 언어는 스스로 추정)"
            if src == "자동감지"
            else f"[원문 언어={src} → 목표 언어={tgt}]\n{text}"
        )
        try:
            ctx["result"] = ask_llm(provider, model, sys, prompt, temperature=0.2)
        except Exception as e:
            ctx["error"] = f"번역 실패: {e}"

    return render(request, "travel/translate.html", ctx)


# --- 날짜별 계획 ---
def planner_view(request):
    ctx = {
        "result": None,
        "table_rows": None,
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL.get(DEFAULT_PROVIDER),
        "weather": None,
        "weather_error": None,
        "cal_start": None,   # ✅ 캘린더 시작일
    }

    if request.method == "POST":
        city = request.POST.get("city", "Seoul").strip()
        start_date = request.POST.get("start_date") or datetime.today().strftime("%Y-%m-%d")
        n_days = int(request.POST.get("n_days", "4"))
        intensity = request.POST.get("intensity", "보통")
        notes = request.POST.get("notes", "")

        provider = (request.POST.get("provider") or DEFAULT_PROVIDER).lower()
        model = request.POST.get("model") or DEFAULT_MODEL.get(provider)
        ctx["provider"], ctx["model"] = provider, model

        # ✅ 날씨 / 캘린더 시작일
        w, werr = get_current_weather(city, lang="kr", units="metric")
        ctx["weather"], ctx["weather_error"] = w, werr
        ctx["cal_start"] = start_date

        # 긴 일정은 아이템 수 축소해서 답변 컴팩트하게
        max_items = 3 if n_days >= 7 else 5

        sys_prompt = (
            "너는 여행 일정 플래너다. 반드시 코드블록(백틱) 없이 JSON만 출력한다.\n"
            f"각 날짜(day)마다 items는 최대 {max_items}개, notes는 40자 이내로 간결하게.\n"
            "스키마는 다음과 같다.\n"
            "{\"days\":[{\"day\":1,\"items\":[{\"title\":\"...\",\"start\":\"09:00\",\"end\":\"10:30\","
            "\"location\":\"...\",\"notes\":\"...\"}]}]}\n"
            "반드시 위 스키마의 순수 JSON만 출력."
        )
        prompt = (
            f"도시:{city}\n여행 시작일:{start_date}\n일수:{n_days}\n강도:{intensity}\n"
            f"요청:{notes or '특이사항 없음'}\n(한국어)"
        )

        raw = ask_llm(provider, model, sys_prompt, prompt, temperature=0.5)

        # 파싱 + 자동 보정 1회
        try:
            obj = safe_json_loads(raw)
        except Exception:
            try:
                fixer_prompt = (
                    "아래 텍스트에서 JSON 본문만 추출해 올바른 JSON으로 출력하라. 설명/코드블록 금지.\n\n"
                    + str(raw)[:7000]
                )
                fixed = ask_llm(provider, model, "", fixer_prompt, temperature=0)
                obj = safe_json_loads(fixed)
            except Exception as e2:
                return render(
                    request,
                    "travel/planner.html",
                    {"error": f"응답 파싱 실패: {e2}", "raw": raw, "provider": provider, "model": model},
                )

        # rows 생성
        rows = []
        base = datetime.strptime(start_date, "%Y-%m-%d")
        for day in obj.get("days", []):
            d0 = base + timedelta(days=int(day.get("day", 1)) - 1)
            for it in day.get("items", []):
                s = it.get("start", "09:00"); e = it.get("end", "10:00")
                try:
                    sh, sm = int(s[:2]), int(s[3:5]); eh, em = int(e[:2]), int(e[3:5])
                except Exception:
                    sh, sm, eh, em = 9, 0, 10, 0
                sdt = d0.replace(hour=sh, minute=sm); edt = d0.replace(hour=eh, minute=em)
                rows.append({
                    "date": d0.date(), "start_dt": sdt, "end_dt": edt,
                    "title": it.get("title", ""), "location": it.get("location", ""),
                    "notes": it.get("notes", "")
                })

        df = pd.DataFrame(rows).sort_values(["start_dt"])

        # 세션 저장(ICS용)
        request.session["planner_city"] = city
        request.session["planner_events"] = [
            {"start_dt": r["start_dt"].strftime("%Y-%m-%d %H:%M:%S"),
             "end_dt": r["end_dt"].strftime("%Y-%m-%d %H:%M:%S"),
             "title": r["title"], "location": r["location"], "notes": r["notes"]}
            for _, r in df.iterrows()
        ]

        # 템플릿용 행 튜플
        ctx["table_rows"] = list(df.itertuples(index=False, name="Row"))
        ctx["result"] = f"{city} {n_days}일 일정이 생성되었습니다."

    return render(request, "travel/planner.html", ctx)


@require_POST
def planner_save_api(request):
    """
    FullCalendar에서 수정/추가한 이벤트를 세션에 반영.
    요청 바디 예:
    {
      "events":[
        {"title":"...", "start":"2025-08-26T09:00:00", "end":"2025-08-26T10:30:00",
         "location":"...", "notes":"..."},
        ...
      ]
    }
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        events = payload.get("events", [])
    except Exception as e:
        return HttpResponseBadRequest(f"Invalid JSON: {e}")

    saved = []
    for ev in events:
        title = (ev.get("title") or "").strip()
        start = (ev.get("start") or "").split(".")[0].replace("Z", "")
        end   = (ev.get("end") or "").split(".")[0].replace("Z", "")
        location = ev.get("location") or ""
        notes    = ev.get("notes") or ""
        if not title or not start or not end:
            continue
        # 'YYYY-MM-DDTHH:MM:SS' 파싱
        try:
            sdt = datetime.fromisoformat(start)
            edt = datetime.fromisoformat(end)
        except Exception:
            try:
                sdt = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")
                edt = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue

        saved.append({
            "start_dt": sdt.strftime("%Y-%m-%d %H:%M:%S"),
            "end_dt":   edt.strftime("%Y-%m-%d %H:%M:%S"),
            "title":    title,
            "location": location,
            "notes":    notes,
        })

    request.session["planner_events"] = saved
    return JsonResponse({"ok": True, "count": len(saved)})


def planner_ics_download(request):
    city = request.session.get("planner_city", "Trip")
    events = request.session.get("planner_events")
    if not events:
        return HttpResponseBadRequest("다운로드할 일정이 없습니다.")
    rows = [
        {
            "start_dt": datetime.strptime(e["start_dt"], "%Y-%m-%d %H:%M:%S"),
            "end_dt": datetime.strptime(e["end_dt"], "%Y-%m-%d %H:%M:%S"),
            "title": e["title"],
            "location": e["location"],
            "notes": e["notes"],
        }
        for e in events
    ]
    df = pd.DataFrame(rows)
    ics = itinerary_to_ics(df, title_prefix=f"{city} Trip")
    resp = HttpResponse(ics, content_type="text/calendar")
    resp["Content-Disposition"] = f'attachment; filename="{city}_itinerary.ics"'
    return resp
