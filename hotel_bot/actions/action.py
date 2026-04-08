from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from datetime import datetime
import dateparser

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
            return [SlotSet("is_cancellable", true)]

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