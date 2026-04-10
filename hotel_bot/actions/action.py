from typing import Any, Text, Dict, List, Optional, Tuple
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, FollowupAction
from datetime import datetime, date, time
import dateparser
import csv
import os
import json
import re
import urllib.request
import urllib.error
import urllib.parse
import unicodedata

class ActionValidateBookingDates(Action):
    def name(self) -> Text:
        return "action_validate_booking_dates"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        check_in = tracker.get_slot("check_in_date")
        check_out = tracker.get_slot("check_out_date")

        # If LLM hasn't collected both yet, let it keep doing its job
        if not check_in or not check_out:
            return []

        # Parse the natural language dates (e.g., "tomorrow", "Oct 12")
        in_date_parsed = dateparser.parse(check_in)
        out_date_parsed = dateparser.parse(check_out)

        if in_date_parsed and out_date_parsed:
            # Strip time to compare pure dates
            in_date = in_date_parsed.date()
            out_date = out_date_parsed.date()
            
            if out_date <= in_date:
                dispatcher.utter_message(text="I noticed your check-out date is before or on the same day as your check-in date. Let's get those dates sorted out.")
                # Wipe both slots so the LLM knows it needs to ask the user again
                return [SlotSet("check_in_date", None), SlotSet("check_out_date", None)]
            
            if in_date < datetime.now().date():
                dispatcher.utter_message(text="It looks like your check-in date is in the past. We can only book for today or future dates.")
                return [SlotSet("check_in_date", None)]

        return []

class ActionCheckAvailability(Action):
    def name(self) -> Text:
        return "action_check_availability"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        room_type = tracker.get_slot("room_type")
        
        # Mock Hotel Database
        inventory = {
            "Deluxe": 5,
            "Junior Suite": 2,
            "Club Suite": 0  # Fully booked to demonstrate unhappy path logic
        }

        if not room_type:
            return []

        # Normalize string matching (e.g., user says "a deluxe room", we match "Deluxe")
        matched_room = next((key for key in inventory.keys() if key.lower() in room_type.lower()), None)

        if matched_room:
            if inventory[matched_room] > 0:
                dispatcher.utter_message(text=f"Great news! We have {matched_room} rooms available.")
                # Standardize the slot value to match our database exactly
                return [SlotSet("room_type", matched_room)] 
            else:
                dispatcher.utter_message(text=f"I'm so sorry, but we are completely booked for the {matched_room} on those dates. Would you like to try a different room type?")
                # Wipe the slot to force the LLM to ask for a different room
                return [SlotSet("room_type", None)] 

        return []

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICES_CSV = os.path.join(BASE_DIR, "hotel_services.csv")
ASSIGNMENTS_CSV = os.path.join(BASE_DIR, "hotel_service_assignments.csv")
FEEDBACK_COMPLAINT_CSV = os.path.join(BASE_DIR, "hotel_feedback_complaint.csv")

ASSIGNMENT_LLM_ENDPOINT = os.getenv("ASSIGNMENT_LLM_ENDPOINT", "").strip()
ASSIGNMENT_LLM_API_KEY = os.getenv("ASSIGNMENT_LLM_API_KEY", "").strip()
ASSIGNMENT_LLM_MODEL = os.getenv("ASSIGNMENT_LLM_MODEL", "lm-studio").strip()
if not ASSIGNMENT_LLM_ENDPOINT:
    ASSIGNMENT_LLM_ENDPOINT = "http://127.0.0.1:1234/v1/chat/completions"

VALID_SERVICE_CODES = {
    "housekeeping", "room_service", "front_desk", "spa_massage",
    "restaurant", "laundry", "maintenance", "bell_boy"
}

DEFAULT_IN_ROOM_SERVICE_CODES = {"housekeeping", "room_service", "maintenance", "minibar"}
DEFAULT_NON_IN_ROOM_SERVICE_CODES = {"front_desk", "spa_massage", "restaurant", "laundry", "bell_boy", "gym"}

SERVICE_CODE_SYNONYMS = {
    "housekeeping": {
        "housekeeping", "don phong", "dọn phòng", "ve sinh phong", "vệ sinh phòng", 
        "dich vu don phong", "dịch vụ dọn phòng", "ve sinh", "vệ sinh"
    },
    "room_service": {
        "room_service", "room service", "phuc vu phong", "phục vụ phòng", 
        "do an tai phong", "đồ ăn tại phòng", "dich vu phong", "dịch vụ phòng"
    },
    "front_desk": {
        "front_desk", "front desk", "le tan", "lễ tân", "quay le tan", "quầy lễ tân",
        "truc quay", "trực quầy", "truc ban", "trực ban", "check in", "check-in", 
        "check out", "check-out", "checkin", "checkout", "nhan phong", "nhận phòng",
        "tra phong", "trả phòng"
    },
    "spa_massage": {
        "spa_massage", "spa massage", "spa", "massage", "spa va massage", "spa và massage"
    },
    "restaurant": {
        "restaurant", "nha hang", "nhà hàng", "buffet", "an sang", "ăn sáng",
        "an trua", "ăn trưa", "an toi", "ăn tối"
    },
    "laundry": {
        "laundry", "giat ui", "giặt ủi", "giat do", "giặt đồ", "ui do", "ủi đồ",
        "dich vu giat", "dịch vụ giặt"
    },
    "maintenance": {
        "maintenance", "bao tri", "bảo trì", "sua chua", "sửa chữa", 
        "ky thuat", "kỹ thuật", "hong", "hỏng", "dieu hoa", "điều hòa",
        "dien nuoc", "điện nước"
    },
    "bell_boy": {
        "bell_boy", "bell boy", "hanh ly", "hành lý", "be hanh ly", "bê hành lý", 
        "xach do", "xách đồ", "vali", "va li", "mang do", "mang đồ"
    },
}

SEVERITY_SYNONYMS = {
    "low": {"low", "nhe", "nhẹ", "thap", "thấp", "khong anh huong", "không ảnh hưởng"},
    "medium": {"medium", "trung binh", "trung bình", "vua", "vừa", "binh thuong", "bình thường"},
    "high": {"high", "cao", "nang", "nặng", "nghiem trong", "nghiêm trọng", "rat nghiem trong", "rất nghiêm trọng", "rat nang", "rất nặng"},
}


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _latest_user_text(tracker: Tracker) -> str:
    """Safely read latest user text from tracker without raising on missing payload."""
    latest_message = getattr(tracker, "latest_message", None)
    if isinstance(latest_message, dict):
        text = str(latest_message.get("text") or "").strip()
        if text:
            return text

    # CALM/e2e can call actions before latest_message is populated.
    # Fallback: scan tracker events and return the most recent user text.
    events = getattr(tracker, "events", None)
    if isinstance(events, list):
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            if event.get("event") != "user":
                continue
            text = str(event.get("text") or "").strip()
            if text:
                return text
    return ""


def _load_csv_rows(file_path: str) -> List[Dict[str, str]]:
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    normalized_rows: List[Dict[str, str]] = []
    for row in rows:
        normalized_row: Dict[str, str] = {}
        for key, value in row.items():
            clean_key = str(key or "").replace("\ufeff", "").strip()
            normalized_row[clean_key] = value if value is not None else ""
        normalized_rows.append(normalized_row)
    return normalized_rows


def _parse_date_to_date(value: str) -> Optional[datetime.date]:
    """Parse date string to date object. Supports M/D/YYYY and YYYY-MM-DD formats."""
    if not value:
        return None
    try:
        # Try M/D/YYYY format (e.g., "4/1/2026")
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError:
        pass
    try:
        # Try YYYY-MM-DD format
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _service_code_exists(service_code: str) -> bool:
    """Check if service_code exists in CSV."""
    return _canonicalize_service_code(service_code) is not None


def _canonicalize_service_code(service_code: str) -> Optional[str]:
    normalized_value = _normalize_text(service_code)
    if not normalized_value:
        return None

    if normalized_value in VALID_SERVICE_CODES:
        return normalized_value

    for canonical_code, synonyms in SERVICE_CODE_SYNONYMS.items():
        normalized_synonyms = {_normalize_text(item) for item in synonyms}
        if normalized_value in normalized_synonyms:
            return canonical_code

    return None


def _canonicalize_severity(severity: str) -> Optional[str]:
    normalized_value = _normalize_text(severity)
    if not normalized_value:
        return None

    for canonical, synonyms in SEVERITY_SYNONYMS.items():
        normalized_synonyms = {_normalize_text(item) for item in synonyms}
        if normalized_value in normalized_synonyms:
            return canonical

    return None


def _classify_request_type_from_text(text: str) -> Optional[str]:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return None

    complaint_keywords = {
        "complaint", "problem", "issue", "bad", "not good", "terrible",
        "phan nan", "khieu nai", "loi", "su co", "khong hai long", "bao loi", "van de",
        "toi muon phan nan", "toi muon khieu nai", "khong chap nhan"
    }
    feedback_keywords = {
        "feedback", "praise", "good", "great", "excellent", "thank",
        "phan hoi", "gop y", "khen", "hai long", "cam on", "danh gia", "tot"
    }

    if any(keyword in normalized_text for keyword in complaint_keywords):
        return "complaint"
    if any(keyword in normalized_text for keyword in feedback_keywords):
        return "feedback"

    return None


def _parse_rating_1_to_5(rating: str) -> Optional[int]:
    raw = str(rating or "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        return None
    value = int(raw)
    if 1 <= value <= 5:
        return value
    return None


def _resolve_service_date(value: Any) -> date:
    normalized_value = _normalize_text(value)
    if not normalized_value or normalized_value in {"today", "hom nay", "hôm nay", "nay"}:
        return datetime.now().date()

    direct_parsed = _parse_date_to_date(str(value))
    if direct_parsed:
        return direct_parsed

    parsed = dateparser.parse(str(value))
    if parsed:
        return parsed.date()

    return datetime.now().date()


def _parse_shift_time(value: str) -> Optional[time]:
    raw = str(value or "").strip()
    if not raw:
        return None

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _resolve_service_time(value: Any) -> Optional[time]:
    normalized_value = _normalize_text(value)
    if not normalized_value:
        return None

    if normalized_value in {"bay gio", "bây giờ", "now", "hien tai", "hiện tại"}:
        return datetime.now().time().replace(second=0, microsecond=0)

    direct = _parse_shift_time(str(value))
    if direct:
        return direct

    parsed = dateparser.parse(str(value))
    if parsed:
        return parsed.time().replace(second=0, microsecond=0)

    return None


def _extract_keywords(text: str) -> List[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    tokens = [token for token in normalized.replace("-", " ").split() if len(token) >= 3]
    seen = set()
    result: List[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _notes_match_score(row: Dict[str, str], context_text: str) -> int:
    notes = _normalize_text(row.get("notes", ""))
    if not notes:
        return 0
    keywords = _extract_keywords(context_text)
    return sum(1 for keyword in keywords if keyword in notes)


def _is_time_within_shift(row: Dict[str, str], target_time: Optional[time]) -> bool:
    if not target_time:
        return False

    start = _parse_shift_time(row.get("start_time", ""))
    end = _parse_shift_time(row.get("end_time", ""))
    if not start or not end:
        return False

    if start <= end:
        return start <= target_time <= end

    # Overnight shift, e.g. 22:00 -> 06:00
    return target_time >= start or target_time <= end


def _shift_distance_minutes(row: Dict[str, str], target_date: date, target_time: Optional[time]) -> float:
    start_time = _parse_shift_time(row.get("start_time", ""))
    if not start_time:
        return 10**9

    reference_time = target_time or datetime.now().time()
    shift_start_dt = datetime.combine(target_date, start_time)
    reference_dt = datetime.combine(target_date, reference_time)
    return abs((shift_start_dt - reference_dt).total_seconds()) / 60.0


def _pick_best_assignment(
    rows: List[Dict[str, str]],
    target_date: date,
    target_time: Optional[time],
    context_text: str,
) -> Optional[Dict[str, str]]:
    if not rows:
        return None

    priority = {"in_progress": 0, "assigned": 1, "done": 2}
    rows.sort(
        key=lambda row: (
            priority.get(_normalize_text(row.get("status", "")), 99),
            -_notes_match_score(row, context_text),
            0 if _is_time_within_shift(row, target_time) else 1,
            _shift_distance_minutes(row, target_date, target_time),
        )
    )
    return rows[0]


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try a loose fallback for simple key/value output.
    assignment_id_match = re.search(r'"assignment_id"\s*:\s*"([^"]+)"', candidate)
    if assignment_id_match:
        return {"assignment_id": assignment_id_match.group(1)}
    return None


def _llm_choose_assignment_id(
    rows: List[Dict[str, str]],
    service_code: str,
    service_date: date,
    room_number: str,
    service_time: Optional[time],
    context_text: str,
) -> Optional[str]:
    shortlist = [
        {
            "assignment_id": str(row.get("assignment_id", "")),
            "service_code": str(row.get("service_code", "")),
            "staff_id": str(row.get("staff_id", "")),
            "staff_name": str(row.get("staff_name", "")),
            "status": str(row.get("status", "")),
            "room_number": str(row.get("room_number", "")),
            "start_time": str(row.get("start_time", "")),
            "end_time": str(row.get("end_time", "")),
            "notes": str(row.get("notes", "")),
        }
        for row in rows
    ]
    valid_ids = {item["assignment_id"] for item in shortlist if item["assignment_id"]}
    if not valid_ids:
        return None

    prompt_context = {
        "service_code": service_code,
        "service_date": service_date.isoformat(),
        "room_number": room_number,
        "service_time": service_time.strftime("%H:%M") if service_time else None,
        "user_context": context_text,
    }

    # Use a local OpenAI-compatible endpoint (LM Studio by default).
    if not ASSIGNMENT_LLM_ENDPOINT:
        return None

    messages = [
        {
            "role": "system",
            "content": (
                "You are selecting the best assignment for a complaint from a shortlist. "
                "Pick exactly one assignment_id from the shortlist based on notes relevance, status, and time fit. "
                "Return strict JSON only: {\"assignment_id\": \"<id>\"} or {\"assignment_id\": null}."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"context": prompt_context, "shortlist": shortlist},
                ensure_ascii=False,
            ),
        },
    ]

    payload = {
        "model": ASSIGNMENT_LLM_MODEL,
        "messages": messages,
        "temperature": 0,
    }

    headers = {"Content-Type": "application/json"}
    if ASSIGNMENT_LLM_API_KEY:
        headers["Authorization"] = f"Bearer {ASSIGNMENT_LLM_API_KEY}"

    request = urllib.request.Request(
        ASSIGNMENT_LLM_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None

    llm_text = ""
    if isinstance(parsed, dict):
        # OpenAI-compatible response shape
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    llm_text = str(message.get("content") or "")
        if not llm_text and "assignment_id" in parsed:
            candidate_id = str(parsed.get("assignment_id") or "").strip()
            return candidate_id if candidate_id in valid_ids else None

    if not llm_text:
        llm_text = raw

    obj = _extract_json_object(llm_text)
    if not obj:
        return None

    candidate_id = str(obj.get("assignment_id") or "").strip()
    if candidate_id in valid_ids:
        return candidate_id
    return None


def _get_service_name(service_code: str) -> Optional[str]:
    """Get service name by code from CSV."""
    for row in _load_csv_rows(SERVICES_CSV):
        if _normalize_text(row.get("service_code", "")) == _normalize_text(service_code):
            return row.get("service_name", "")
    return None


def _is_in_room_service(service_code: str) -> bool:
    canonical_code = _canonicalize_service_code(service_code)
    if not canonical_code:
        return False

    if canonical_code in DEFAULT_IN_ROOM_SERVICE_CODES:
        return True
    if canonical_code in DEFAULT_NON_IN_ROOM_SERVICE_CODES:
        return False

    for row in _load_csv_rows(SERVICES_CSV):
        if _normalize_text(row.get("service_code", "")) != canonical_code:
            continue

        # Fallback heuristic using existing columns only (service_name/description).
        service_name = _normalize_text(row.get("service_name", ""))
        description = _normalize_text(row.get("description", ""))
        text = f"{service_name} {description}"

        if "tai phong" in text or "trong phong" in text:
            return True
        if "nha hang" in text or "le tan" in text or "spa" in text or "massage" in text:
            return False

    return False


def _select_staff_for_feedback(
    service_code: str,
    room_number: str,
    service_date: date,
    service_time: Optional[time],
    context_text: str,
) -> Tuple[Optional[str], Optional[str]]:
    assignments = _load_csv_rows(ASSIGNMENTS_CSV)

    filtered = [
        row for row in assignments
        if _normalize_text(row.get("service_code", "")) == _normalize_text(service_code)
        and _parse_date_to_date(row.get("date", "")) == service_date
    ]
    if not filtered:
        return None, None

    is_in_room_service = _is_in_room_service(service_code)
    if is_in_room_service:
        if not str(room_number or "").strip():
            return None, None
        filtered = [
            row for row in filtered
            if _normalize_text(row.get("room_number", "")) == _normalize_text(room_number)
        ]
        if not filtered:
            return None, None

    chosen = _pick_best_assignment(filtered, service_date, service_time, context_text)
    if not chosen:
        return None, None

    return chosen.get("staff_id") or None, chosen.get("staff_name") or None


def _select_staff_for_complaint(
    service_code: str,
    room_number: str,
    service_date: date,
    service_time: Optional[time],
    context_text: str,
) -> Tuple[Optional[str], Optional[str]]:
    assignments = _load_csv_rows(ASSIGNMENTS_CSV)

    by_service_date = [
        row for row in assignments
        if _normalize_text(row.get("service_code", "")) == _normalize_text(service_code)
        and _parse_date_to_date(row.get("date", "")) == service_date
    ]

    if not by_service_date:
        return None, None

    is_in_room_service = _is_in_room_service(service_code)

    if is_in_room_service:
        if not str(room_number or "").strip():
            return None, None
        candidate_rows = [
            row for row in by_service_date
            if _normalize_text(row.get("room_number", "")) == _normalize_text(room_number)
        ]
    else:
        candidate_rows = by_service_date

    if not candidate_rows:
        return None, None

    llm_selected_id = _llm_choose_assignment_id(
        candidate_rows,
        service_code,
        service_date,
        room_number,
        service_time,
        context_text,
    )
    if llm_selected_id:
        for row in candidate_rows:
            if str(row.get("assignment_id", "")).strip() == llm_selected_id:
                return row.get("staff_id") or None, row.get("staff_name") or None

    chosen = _pick_best_assignment(candidate_rows, service_date, service_time, context_text)
    if not chosen:
        return None, None

    return chosen.get("staff_id") or None, chosen.get("staff_name") or None


def _next_feedback_id() -> str:
    max_number = 0
    for row in _load_csv_rows(FEEDBACK_COMPLAINT_CSV):
        raw_id = (row.get("id") or "").strip().upper()
        if raw_id.startswith("F") and raw_id[1:].isdigit():
            max_number = max(max_number, int(raw_id[1:]))
    return f"F{max_number + 1:03d}"


def _write_feedback_or_complaint_row(row: Dict[str, str]) -> None:
    file_exists = os.path.exists(FEEDBACK_COMPLAINT_CSV)
    fieldnames = [
        "id", "timestamp", "session_id", "user_id", "request_type", "service_type", "rating",
        "complaint_detail", "severity", "status", "assigned_to", "resolution_note"
    ]

    mode = "a" if file_exists else "w"
    with open(FEEDBACK_COMPLAINT_CSV, mode, encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)




class ActionValidateRequestType(Action):
    def name(self) -> Text:
        return "action_validate_request_type"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        request_type = _normalize_text(tracker.get_slot("request_type"))
        latest_text = _latest_user_text(tracker)

        if request_type in {"feedback", "phan hoi", "gop y"}:
            return [SlotSet("request_type", "feedback")]
        if request_type in {"complaint", "phan nan", "khieu nai", "bao cao van de"}:
            return [SlotSet("request_type", "complaint")]

        inferred_type = _classify_request_type_from_text(latest_text)
        if inferred_type:
            return [SlotSet("request_type", inferred_type)]

        dispatcher.utter_message(text="Bạn muốn gửi phản hồi hay báo cáo vấn đề cần xử lý?")
        return [SlotSet("request_type", None), FollowupAction("action_listen")]


class ActionClassifyFeedbackComplaint(Action):
    def name(self) -> Text:
        return "action_classify_feedback_complaint"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        # Backward-compatible classifier for older trained models that still call this action.
        existing_request_type = _normalize_text(tracker.get_slot("request_type"))
        if existing_request_type in {"feedback", "complaint"}:
            return [SlotSet("request_type", existing_request_type)]

        latest_text = _latest_user_text(tracker)
        inferred_type = _classify_request_type_from_text(latest_text)
        if inferred_type:
            return [SlotSet("request_type", inferred_type)]

        dispatcher.utter_message(text="Bạn muốn gửi phản hồi hay báo cáo vấn đề cần xử lý?")
        return [SlotSet("request_type", None), FollowupAction("action_listen")]


class ActionValidateServiceCode(Action):
    """Validate and canonicalize service_code from user input."""
    
    def name(self) -> Text:
        return "action_validate_service_code"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        # Get the service_code slot value or latest user message
        service_code_slot = tracker.get_slot("service_code")
        latest_text = _normalize_text(_latest_user_text(tracker))
        
        # Try to canonicalize from slot first
        if service_code_slot:
            canonical = _canonicalize_service_code(str(service_code_slot))
            if canonical:
                return [SlotSet("service_code", canonical)]
        
        # Try to extract from latest user message
        if latest_text:
            canonical = _canonicalize_service_code(latest_text)
            if canonical:
                return [SlotSet("service_code", canonical)]
            
            # Try partial matching for common Vietnamese terms
            service_mapping = {
                "le tan": "front_desk",
                "truc quay": "front_desk",
                "truc ban": "front_desk",
                "check in": "front_desk",
                "check out": "front_desk",
                "don phong": "housekeeping",
                "ve sinh": "housekeeping",
                "phuc vu phong": "room_service",
                "room service": "room_service",
                "nha hang": "restaurant",
                "buffet": "restaurant",
                "giat ui": "laundry",
                "giat do": "laundry",
                "ky thuat": "maintenance",
                "bao tri": "maintenance",
                "sua chua": "maintenance",
                "spa": "spa_massage",
                "massage": "spa_massage",
                "hanh ly": "bell_boy",
                "vali": "bell_boy",
            }
            
            for keyword, code in service_mapping.items():
                if keyword in latest_text:
                    return [SlotSet("service_code", code)]
        
        # If still can't determine, ask user again
        dispatcher.utter_message(text="Bạn đang nói về dịch vụ nào? (lễ tân, dọn phòng, phục vụ phòng, nhà hàng, giặt ủi, kỹ thuật, spa/massage, hành lý)")
        return [SlotSet("service_code", None), FollowupAction("action_listen")]


class ActionValidateSeverity(Action):
    """Validate and canonicalize severity from user input."""
    
    def name(self) -> Text:
        return "action_validate_severity"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        # Get the severity slot value or latest user message
        severity_slot = tracker.get_slot("severity")
        latest_text = _normalize_text(_latest_user_text(tracker))
        
        # Try to canonicalize from slot first
        if severity_slot:
            canonical = _canonicalize_severity(str(severity_slot))
            if canonical:
                return [SlotSet("severity", canonical)]
        
        # Try to extract from latest user message
        if latest_text:
            canonical = _canonicalize_severity(latest_text)
            if canonical:
                return [SlotSet("severity", canonical)]
        
        # If still can't determine, ask user again
        dispatcher.utter_message(text="Mức độ ảnh hưởng với bạn như thế nào? Vui lòng chọn: thấp (low), vừa phải (medium), hoặc cao/nặng (high)")
        return [SlotSet("severity", None), FollowupAction("action_listen")]


class ActionValidateServiceDate(Action):
    """Validate and normalize service_date from user input."""

    def name(self) -> Text:
        return "action_validate_service_date"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        service_date_slot = tracker.get_slot("service_date")
        latest_text = _latest_user_text(tracker)

        # Prefer the collected slot, then fallback to latest user text.
        raw_value = service_date_slot if service_date_slot else latest_text
        if not str(raw_value or "").strip():
            dispatcher.utter_message(text="Bạn sử dụng dịch vụ này vào ngày nào?")
            return [SlotSet("service_date", None), FollowupAction("action_listen")]

        direct = _parse_date_to_date(str(raw_value))
        parsed = dateparser.parse(str(raw_value)) if not direct else None
        normalized = direct or (parsed.date() if parsed else None)

        if not normalized:
            normalized_text = _normalize_text(raw_value)
            if normalized_text in {"hom nay", "hôm nay", "today", "nay"}:
                normalized = datetime.now().date()

        if not normalized:
            dispatcher.utter_message(text="Mình chưa rõ ngày sử dụng dịch vụ. Bạn cho mình ngày cụ thể (ví dụ: 01/04/2026) nhé.")
            return [SlotSet("service_date", None), FollowupAction("action_listen")]

        return [SlotSet("service_date", normalized.isoformat())]


class ActionValidateServiceSubContext(Action):
    """Validate and accept service_sub_context from user input."""
    
    def name(self) -> Text:
        return "action_validate_service_sub_context"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        # Get the service_sub_context slot or latest user message
        sub_context_slot = tracker.get_slot("service_sub_context")
        latest_text = _normalize_text(_latest_user_text(tracker))
        
        # If slot was set, keep it
        if sub_context_slot:
            return []
        
        # If user provided text, use it directly
        if latest_text:
            return [SlotSet("service_sub_context", _latest_user_text(tracker).strip())]
        
        # If nothing, ask again
        dispatcher.utter_message(text="Bạn gặp vấn đề ở khâu nào của dịch vụ này? (ví dụ: trực quầy, check-in, check-out)")
        return [SlotSet("service_sub_context", None), FollowupAction("action_listen")]


class ActionLookupStaffFeedback(Action):
    def name(self) -> Text:
        return "action_lookup_staff_feedback"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        service_code = tracker.get_slot("service_code")
        room_number = tracker.get_slot("room_number")
        service_date_slot = tracker.get_slot("service_date")
        service_date = _resolve_service_date(service_date_slot)
        service_time_slot = tracker.get_slot("service_time")
        service_time = _resolve_service_time(service_time_slot)
        service_sub_context = str(tracker.get_slot("service_sub_context") or "").strip()
        feedback_note = str(tracker.get_slot("feedback_note") or "").strip()
        context_text = " ".join(part for part in [service_sub_context, feedback_note] if part)

        canonical_service_code = _canonicalize_service_code(str(service_code or ""))
        if not canonical_service_code:
            return [SlotSet("assigned_staff_id", None), SlotSet("assigned_staff_name", None)]

        staff_id, staff_name = _select_staff_for_feedback(
            canonical_service_code,
            str(room_number or ""),
            service_date,
            service_time,
            context_text,
        )
        return [
            SlotSet("service_code", canonical_service_code),
            SlotSet("service_date", service_date.isoformat()),
            SlotSet("service_time", service_time.strftime("%H:%M") if service_time else None),
            SlotSet("assigned_staff_id", staff_id),
            SlotSet("assigned_staff_name", staff_name),
        ]


class ActionLookupStaffComplaint(Action):
    def name(self) -> Text:
        return "action_lookup_staff_complaint"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        service_code = tracker.get_slot("service_code")
        room_number = tracker.get_slot("room_number")
        service_date_slot = tracker.get_slot("service_date")
        service_date = _resolve_service_date(service_date_slot)
        service_time_slot = tracker.get_slot("service_time")
        service_time = _resolve_service_time(service_time_slot)
        service_sub_context = str(tracker.get_slot("service_sub_context") or "").strip()
        complaint_detail = str(tracker.get_slot("complaint_detail") or "").strip()
        context_text = " ".join(part for part in [service_sub_context, complaint_detail] if part)
        canonical_service_code = _canonicalize_service_code(str(service_code or ""))
        if not canonical_service_code:
            return [SlotSet("assigned_staff_id", None), SlotSet("assigned_staff_name", None)]

        staff_id, staff_name = _select_staff_for_complaint(
            canonical_service_code,
            str(room_number or ""),
            service_date,
            service_time,
            context_text,
        )
        return [
            SlotSet("service_code", canonical_service_code),
            SlotSet("service_date", service_date.isoformat()),
            SlotSet("service_time", service_time.strftime("%H:%M") if service_time else None),
            SlotSet("assigned_staff_id", staff_id),
            SlotSet("assigned_staff_name", staff_name),
        ]


class ActionSaveFeedbackRecord(Action):
    def name(self) -> Text:
        return "action_save_feedback_record"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        service_code_input = str(tracker.get_slot("service_code") or "").strip()
        service_code = _canonicalize_service_code(service_code_input)
        feedback_rating_raw = str(tracker.get_slot("feedback_rating") or "").strip()
        feedback_rating = _parse_rating_1_to_5(feedback_rating_raw)

        if not service_code:
            dispatcher.utter_message(text="Mình không tìm thấy dịch vụ này. Bạn có thể nói rõ hơn không?")
            return [SlotSet("service_code", None), FollowupAction("action_listen")]

        if feedback_rating is None:
            dispatcher.utter_message(text="Bạn đánh giá dịch vụ này mấy sao? (1-5)")
            return [SlotSet("feedback_rating", None), FollowupAction("action_listen")]

        record = {
            "id": _next_feedback_id(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "session_id": f"S{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "user_id": str(tracker.sender_id or "guest"),
            "request_type": "feedback",
            "service_type": service_code,
            "rating": str(feedback_rating),
            "complaint_detail": "" if _normalize_text(tracker.get_slot("feedback_note")) in {"", "khong", "khong co", "khong can", "no"} else str(tracker.get_slot("feedback_note") or ""),
            "severity": "",
            "status": "new",
            "assigned_to": str(tracker.get_slot("assigned_staff_id") or ""),
            "resolution_note": "",
        }

        _write_feedback_or_complaint_row(record)
        return [SlotSet("service_code", service_code), SlotSet("feedback_rating", str(feedback_rating))]


class ActionSaveComplaintRecord(Action):
    def name(self) -> Text:
        return "action_save_complaint_record"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        service_code_input = str(tracker.get_slot("service_code") or "").strip()
        service_code = _canonicalize_service_code(service_code_input)
        service_date = _resolve_service_date(tracker.get_slot("service_date"))
        complaint_detail = str(tracker.get_slot("complaint_detail") or "").strip()
        severity_input = str(tracker.get_slot("severity") or "").strip()
        severity = _canonicalize_severity(severity_input)

        if not service_code:
            dispatcher.utter_message(text="Mình không tìm thấy dịch vụ này. Bạn có thể nói rõ hơn không?")
            return [SlotSet("service_code", None), FollowupAction("action_listen")]

        if not complaint_detail:
            dispatcher.utter_message(text="Bạn mô tả giúp mình vấn đề cụ thể là gì nhé?")
            return [SlotSet("complaint_detail", None), FollowupAction("action_listen")]

        if not severity:
            dispatcher.utter_message(text="Mức độ ảnh hưởng với bạn như thế nào? (low / medium / high)")
            return [SlotSet("severity", None), FollowupAction("action_listen")]

        record = {
            "id": _next_feedback_id(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "session_id": f"S{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "user_id": str(tracker.sender_id or "guest"),
            "request_type": "complaint",
            "service_type": service_code,
            "rating": "",
            "complaint_detail": complaint_detail,
            "severity": severity,
            "status": "in_progress",
            "assigned_to": str(tracker.get_slot("assigned_staff_id") or ""),
            "resolution_note": "",
        }

        _write_feedback_or_complaint_row(record)
        return [
            SlotSet("service_code", service_code),
            SlotSet("service_date", service_date.isoformat()),
            SlotSet("severity", severity),
        ]


class ActionConfirmComplaintAssignment(Action):
    def name(self) -> Text:
        return "action_confirm_complaint_assignment"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> List[Dict[Text, Any]]:
        if not str(tracker.get_slot("service_code") or "").strip():
            return []

        service_code = str(tracker.get_slot("service_code") or "")
        service_name = _get_service_name(service_code) or "dịch vụ"
        staff_name_raw = str(tracker.get_slot("assigned_staff_name") or "").strip()
        room_number = str(tracker.get_slot("room_number") or "").strip()
        service_date = _resolve_service_date(tracker.get_slot("service_date"))
        service_date_text = service_date.strftime("%d/%m/%Y")

        if not staff_name_raw:
            dispatcher.utter_message(
                response="utter_complaint_result_no_staff",
                service_name=service_name,
                service_date_text=service_date_text,
                room_number=room_number,
            )
            return []

        dispatcher.utter_message(
            response="utter_complaint_result_assigned_staff",
            service_name=service_name,
            service_date_text=service_date_text,
            staff_name=staff_name_raw,
        )
        return []