from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from datetime import datetime
from zoneinfo import ZoneInfo
import dateparser
import difflib
import csv
import os
import random
import string
from langchain_community.vectorstores import FAISS
# from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate

class ActionValidateBookingDates(Action):
    def name(self) -> Text:
        return "action_validate_booking_dates"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        check_in = tracker.get_slot("check_in_date")
        check_out = tracker.get_slot("check_out_date")

        if not check_in or not check_out:
            return []

        # Parse the natural language dates
        in_date_parsed = dateparser.parse(check_in)
        out_date_parsed = dateparser.parse(check_out)

        if in_date_parsed and out_date_parsed:
            in_date = in_date_parsed.date()
            out_date = out_date_parsed.date()
            
            # Anchor to Hanoi time to prevent timezone hallucinations
            hanoi_tz = ZoneInfo("Asia/Ho_Chi_Minh")
            today = datetime.now(hanoi_tz).date()

            # 1. Past-date checking
            if in_date < today:
                dispatcher.utter_message(text="SYSTEM_INSTRUCTION: The check-in date is in the past. Politely inform the user that we can only book for today or future dates.")
                return [SlotSet("check_in_date", None)]

            # 2. Check-out validation
            if out_date <= in_date:
                dispatcher.utter_message(text="SYSTEM_INSTRUCTION: The check-out date is before or on the check-in date. Ask the user to provide a check-out date that is at least one day after check-in.")
                return [SlotSet("check_out_date", None)]

            # 3. 14-Day Maximum Stay Limit
            stay_duration = (out_date - in_date).days
            if stay_duration > 14:
                dispatcher.utter_message(
                    text="SYSTEM_INSTRUCTION: The requested stay is {stay_duration} days, which exceeds our 14-day maximum. Politely inform the user that they need to speak with our long-stay sales agent, and safely cancel this booking process."
                )
                return [SlotSet("check_in_date", None), SlotSet("check_out_date", None)]

        return []

class ActionCheckAvailability(Action):
    def name(self) -> Text:
        return "action_check_availability"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        room_type = tracker.get_slot("room_type")
        
        inventory = {
            "Deluxe": 5,
            "Junior Suite": 2,
            "Club Suite": 0  # Fully booked for testing
        }

        if not room_type:
            return []

        # 1. Semantic Synonym Mapping
        synonyms = {
            "cheapest": "Deluxe",
            "standard": "Deluxe",
            "basic": "Deluxe",
            "normal": "Deluxe",
            "family": "Junior Suite",
            "best": "Club Suite",
            "luxury": "Club Suite",
            "expensive": "Club Suite",
            "vip": "Club Suite"
        }
        
        user_input_lower = room_type.lower().strip()
        matched_room = None

        # Check for semantic match first
        for key, value in synonyms.items():
            if key in user_input_lower:
                matched_room = value
                break

        # 2. Fuzzy String Matching for Typos (if no semantic match)
        if not matched_room:
            valid_rooms = list(inventory.keys())
            # cutoff=0.6 allows for slight misspellings like "Delux" or "Suit"
            closest_matches = difflib.get_close_matches(room_type, valid_rooms, n=1, cutoff=0.6)
            if closest_matches:
                matched_room = closest_matches[0]

        # 3. Inventory & Alternative Routing Logic
        if matched_room:
            if inventory[matched_room] > 0:
                # We silently normalize the slot without an explicit utterance. 
                # The LLM will naturally continue to the next flow step.
                return [SlotSet("room_type", matched_room)] 
            else:
                # Alternative Room Logic
                alternative = next((room for room, count in inventory.items() if count > 0), None)
                
                if alternative:
                    dispatcher.utter_message(
                        text=f"SYSTEM_INSTRUCTION: Inform the user that the {matched_room} is fully booked for those dates. However, we have the {alternative} available. Ask if they would like to book the {alternative} instead."
                    )
                else:
                    dispatcher.utter_message(
                        text="SYSTEM_INSTRUCTION: Apologize deeply. The hotel is completely fully booked for these dates. Ask if they would like to search for different dates."
                    )
                
                # Wipe the slot so the CALM flow pauses and waits for the user's decision
                return [SlotSet("room_type", None)] 
        else:
            # Catch-all if the LLM extracted something completely unrecognized
            dispatcher.utter_message(text="SYSTEM_INSTRUCTION: We could not identify the requested room type. Remind the user that we offer Deluxe Rooms, Junior Suites, and Club Suites, and ask which they prefer.")
            return [SlotSet("room_type", None)]

    

class ActionWipeTargetSlot(Action):
    def name(self) -> Text:
        return "action_wipe_target_slot"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Identify what the user wants to change
        slot_to_modify = tracker.get_slot("slot_to_modify")
        
        if slot_to_modify:
            # Wipe the target slot, AND wipe the 'slot_to_modify' memory 
            # so the flow can be used again later if needed.
            return [SlotSet(slot_to_modify, None), SlotSet("slot_to_modify", None)]
            
        return []

class ActionFinalizeBooking(Action):
    def name(self) -> Text:
        return "action_finalize_booking"

    def generate_booking_id(self) -> str:
        """Generates a random 6-character alphanumeric ID (e.g., HN829X)."""
        chars = string.ascii_uppercase + string.digits
        return "HN" + ''.join(random.choice(chars) for _ in range(4))

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # 1. Extract all finalized slots
        booking_id = self.generate_booking_id()
        guest_name = tracker.get_slot("guest_name")
        phone = tracker.get_slot("guest_phone")
        email = tracker.get_slot("guest_email")
        check_in = tracker.get_slot("check_in_date")
        check_out = tracker.get_slot("check_out_date")
        room_type = tracker.get_slot("room_type")
        adults = tracker.get_slot("adults_count")
        children = tracker.get_slot("children_count")
        
        # Ensure directories exist
        os.makedirs("db", exist_ok=True)
        bookings_path = os.path.join("db", "bookings.csv")
        inventory_path = os.path.join("db", "inventory.csv")

        # 2. Append to bookings.csv
        file_exists = os.path.isfile(bookings_path)
        with open(bookings_path, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if not file_exists:
                # Write header if file is brand new
                writer.writerow(["Booking ID", "Name", "Phone", "Email", "Check In", "Check Out", "Room Type", "Adults", "Children"])
            
            writer.writerow([booking_id, guest_name, phone, email, check_in, check_out, room_type, adults, children])

        # 3. Update inventory.csv (Subtract 1 from Available)
        updated_inventory = []
        try:
            with open(inventory_path, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                fieldnames = reader.fieldnames
                for row in reader:
                    if row["Room Type"] == room_type and int(row["Available"]) > 0:
                        row["Available"] = str(int(row["Available"]) - 1)
                    updated_inventory.append(row)
            
            # Write the updated inventory back to the file
            with open(inventory_path, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(updated_inventory)
                
        except FileNotFoundError:
            print("ERROR: db/inventory.csv not found. Could not update inventory.")

        # 4. Save the Booking ID to memory so the bot can tell the user
        return [SlotSet("booking_reference", booking_id)]
    

# ======================================================================
# GLOBAL INITIALIZATION (Runs once when the action server starts)
# ======================================================================
print("Loading BGE-M3 Embeddings and FAISS index into memory...")
embeddings = HuggingFaceEmbeddings(
    model_name="BAAI/bge-m3",
    model_kwargs={'device': 'cpu'}, 
    encode_kwargs={'normalize_embeddings': True}
)

# allow_dangerous_deserialization=True is required by FAISS to load local .pkl files safely
vector_store = FAISS.load_local(
    "db/faiss_index", 
    embeddings, 
    allow_dangerous_deserialization=True
)

# Initialize the Gemini model for synthesizing the final answer
# Ensure your GOOGLE_API_KEY environment variable is still active in this terminal
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1)

# ======================================================================
# THE RASA ACTION
# ======================================================================
class ActionTriggerSearch(Action):
    def name(self) -> Text:
        # Rasa CALM automatically looks for this exact action name
        return "action_trigger_search"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # 1. Grab the user's question
        user_query = tracker.latest_message.get("text")
        print(f"RAG Search Triggered for Query: {user_query}")
        
        # 2. Vector Search: Retrieve the top 3 most relevant policy chunks
        docs = vector_store.similarity_search(user_query, k=3)
        context = "\n\n".join([doc.page_content for doc in docs])
        
        # 3. Construct the RAG Prompt
        # This forces the LLM to ground its answer ONLY in the PDF data
        # 3. Construct the RAG Prompt
        prompt_template = """
        You are a warm, highly professional, and empathetic human concierge at Hotel Angela in Hanoi. 
        A guest is asking you a question mid-conversation.
        
        Your job is to answer their question using ONLY the provided hotel policy context below.
        
        CRITICAL RULES FOR YOUR TONE:
        1. TRANSLATE LEGALESE: Do not repeat formal legal jargon, law numbers, or robotic phrasing from the PDF. Translate the rules into natural, polite, and friendly hospitality language.
        2. BE EMPATHETIC: If the answer is "no" (like no pets allowed), deliver the news gently and politely.
        3. BE CONCISE: Keep the answer to 1 or 2 short sentences. Do not over-explain.
        4. STAY GROUNDED: If the answer is not in the context, apologize and say you need to check with the front desk. Do not make up rules.
        
        Context from Hotel Policies:
        {context}
        
        Guest Question: {question}
        
        Friendly Concierge Answer:
        """
        
        prompt = PromptTemplate(template=prompt_template, input_variables=["context", "question"])
        chain = prompt | llm
        
        # 4. Generate the answer and send it to the user
        try:
            response = chain.invoke({"context": context, "question": user_query})
            dispatcher.utter_message(text=response.content)
        except Exception as e:
            dispatcher.utter_message(text="I apologize, but I am having trouble accessing the hotel registry right now. Please try asking again in a moment.")
            print(f"RAG Pipeline Error: {e}")
            
        return []
    
#-----------------------------------SERVICES-----------------------------------

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from datetime import datetime, timedelta, timezone
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from typing import Any, Text, Dict, List


# ✅ UC5: View Booking
class ActionViewServiceBooking(Action):
    def name(self) -> Text:
        return "action_view_service_booking"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        # 1. Lấy ID từ slot và làm sạch dữ liệu đầu vào
        booking_id = tracker.get_slot("booking_service_id")
        booking_id_str = str(booking_id).strip() if booking_id else None

        if not booking_id_str:
            dispatcher.utter_message(text="Please provide a valid Booking Reference ID.")
            return []

        try:
            # 2. Thiết lập đường dẫn file CSV
            BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(BASE_DIR, "db", "booking-service.csv")

            if not os.path.exists(file_path):
                dispatcher.utter_message(text="Database error: Booking file not found.")
                return []

            # 3. Đọc CSV - Ép kiểu ID và Phone về string để tránh mất số 0 hoặc sai lệch định dạng
            df = pd.read_csv(file_path, dtype={'booking_service_id': str, 'phone_number': str})
            
            # Làm sạch tên cột và dữ liệu (xử lý lỗi dấu cách thừa trong file CSV)
            df.columns = df.columns.str.strip()
            df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

            # 4. Tìm kiếm Booking
            booking = df[df['booking_service_id'] == booking_id_str]

            # 5. Trường hợp KHÔNG tìm thấy ID
            if booking.empty:
                dispatcher.utter_message(
                    response="utter_service_not_found",
                    booking_service_id=booking_id_str
                )
                return []

            # 6. Trường hợp TÌM THẤY - Trích xuất dữ liệu
            row = booking.iloc[0]
            
            # Xử lý an toàn cho kiểu số trước khi format
            try:
                total_price = float(row['total_price'])
                quantity = int(row['quantity'])
            except (ValueError, TypeError):
                total_price = 0
                quantity = 0

            # 7. Xây dựng thông điệp hiển thị (Markdown)
            message = (
                f"**Booking Details for ID: {row['booking_service_id']}**\n"
                f"**Customer:** {row['user_name']}\n"
                f"**Phone:** {row['phone_number']}\n"
                f"**Category:** {row['service_category']}\n"
                f"**Service:** {row['service_type']}\n"
                f"**Time:** {row['service_time']}\n"
                f"**Quantity:** {quantity}\n"
                f"**Total Price:** {total_price:,.0f} VND"
            )

            dispatcher.utter_message(text=message)

        except Exception as e:
            # In lỗi chi tiết ra console của Action Server để dễ debug
            print(f"Error in ActionViewServiceBooking: {str(e)}")
            dispatcher.utter_message(text="Sorry, an error occurred while retrieving your booking information.")

        return []


class ActionHandleCancellation(Action):
    def name(self) -> Text:
        return "action_handle_cancellation"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        booking_id = tracker.get_slot("booking_service_id")
        
        try:
            # 1. Thiết lập thời gian hiện tại chuẩn Việt Nam (UTC+7)
            vn_tz = timezone(timedelta(hours=7))
            now_vn = datetime.now(vn_tz).replace(tzinfo=None) 

            # 2. Đọc file CSV
            BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(BASE_DIR, "db", "booking-service.csv")
            
            if not os.path.exists(file_path):
                return [SlotSet("is_cancellable", False)]

            df = pd.read_csv(file_path, dtype={'booking_service_id': str})
            df.columns = df.columns.str.strip()

            # Tìm booking dựa trên ID đã được làm sạch
            booking = df[df['booking_service_id'] == str(booking_id).strip()]

            if booking.empty:
                # Nếu không tìm thấy ID, mặc định không cho hủy và báo lỗi
                dispatcher.utter_message(response="utter_service_not_found", booking_service_id=booking_id)
                return [SlotSet("is_cancellable", False)]

            # 3. Parse thời gian từ CSV
            service_time_str = str(booking.iloc[0]['service_time']).strip()
            service_time = datetime.strptime(service_time_str, "%Y-%m-%d %H:%M")

            # 4. LOGIC KIỂM TRA CHẶN HỦY
            
            # Tính mốc deadline 2 tiếng trước giờ dịch vụ
            deadline = now_vn + timedelta(hours=2)

            # --- TRƯỜNG HỢP 1: Dịch vụ đã diễn ra (Quá khứ) ---
            if service_time < now_vn:
                print(f"DEBUG: [BLOCKED] ID {booking_id} - Dịch vụ đã kết thúc hoặc đang diễn ra ({service_time})")
                # Bạn có thể dùng chung Slot này để Flow rẽ nhánh sang thông báo không thể hủy
                return [SlotSet("is_cancellable", False)]

            # --- TRƯỜNG HỢP 2: Vi phạm chính sách 2 giờ ---
            if service_time < deadline:
                print(f"DEBUG: [BLOCKED] ID {booking_id} - Sắp diễn ra trong < 2h ({service_time})")
                return [SlotSet("is_cancellable", False)]

            # --- TRƯỜNG HỢP 3: Hợp lệ (Tương lai xa > 2 tiếng) ---
            print(f"DEBUG: [ALLOWED] ID {booking_id} - Đủ điều kiện hủy (Service: {service_time})")
            return [SlotSet("is_cancellable", True)]

        except Exception as e:
            print(f"Error in ActionHandleCancellation: {str(e)}")
            return [SlotSet("is_cancellable", False)]


class ActionConfirmCancellation(Action):
    def name(self) -> Text:
        return "action_confirm_cancellation"

    def run(self, dispatcher, tracker, domain):
        import os
        import pandas as pd

        booking_id = tracker.get_slot("booking_service_id")
        confirm = tracker.get_slot("confirm_cancellation")

        try:
            BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(BASE_DIR, "db", "booking-service.csv")

            if confirm is None:
                dispatcher.utter_message(text="Please reply with yes or no.")
                return []

            # Ép kiểu về string và viết thường để so sánh
            confirm_val = str(confirm).lower().strip()

            #  NO: nhận diện cả 'no', 'n' và 'false'
            if confirm_val in ["no", "n", "false"]:
                dispatcher.utter_message(response="utter_cancel_aborted")
                return []

            #  YES: nhận diện cả 'yes', 'y' và 'true'
            if confirm_val in ["yes", "y", "true"]:
                df = pd.read_csv(file_path, dtype={'booking_service_id': str})
                df.columns = df.columns.str.strip()

                df = df[df['booking_service_id'] != str(booking_id)]
                df.to_csv(file_path, index=False)

                dispatcher.utter_message(
                    response="utter_service_cancel_success",
                    booking_service_id=booking_id
                )
                return []

            #  Trường hợp không khớp cái nào
            dispatcher.utter_message(text="Please reply with yes or no.")

        except Exception as e:
            dispatcher.utter_message(text=f"An error occurred: {str(e)}")

        return []

#  UC7: Show promotions
class ActionShowPromotions(Action):
    def name(self) -> Text:
        return "action_show_promotions"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict) -> List:
        category = tracker.get_slot("service_category")
        category_str = str(category).lower().strip() if category else "all"
        vn_tz = timezone(timedelta(hours=7))
        now_vn = datetime.now(vn_tz).date()

        try:
            BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            df_promo = pd.read_csv(os.path.join(BASE_DIR, "db", "promotions.csv"))
            df_promo.columns = df_promo.columns.str.strip()
            df_promo = df_promo.apply(lambda x: x.str.strip() if x.dtype == "object" else x)

            df_promo['start_date'] = pd.to_datetime(df_promo['start_date']).dt.date
            df_promo['end_date'] = pd.to_datetime(df_promo['end_date']).dt.date

            active_promos = df_promo[(df_promo['start_date'] <= now_vn) & (df_promo['end_date'] >= now_vn)]
            is_view_all = category_str in ["all", "tất cả", "none"]

            if is_view_all:
                display_promos = active_promos
                msg_header = "Here are all available promotions today:\n"
            else:
                display_promos = active_promos[active_promos['service_category'].str.lower() == category_str]
                msg_header = f"Current promotions for {category}:\n"

            if display_promos.empty:
                dispatcher.utter_message(text=f"Currently, there are no active promotions.")
                return []

            df_detail = pd.read_csv(os.path.join(BASE_DIR, "db", "detail_service.csv"))
            df_detail.columns = df_detail.columns.str.strip()

            msg = msg_header
            for _, row in display_promos.iterrows():
                detail = df_detail[df_detail['service_type'].str.strip() == str(row['service_type']).strip()]
                price_info = ""
                if not detail.empty:
                    final_price = detail.iloc[0]['price'] * (1 - row['discount_percent'] / 100)
                    price_info = f" → {final_price:,.0f} VND"
                msg += f"- [{row['service_category']}] {row['promotion_name']}: {row['discount_percent']}% off {row['service_type']}{price_info}\n"

            dispatcher.utter_message(text=msg.strip())
        except Exception as e:
            dispatcher.utter_message(text=f"Error processing promotions: {str(e)}")
        return []

