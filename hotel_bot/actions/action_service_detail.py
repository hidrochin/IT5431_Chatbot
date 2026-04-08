from rasa_sdk import Action
from rasa_sdk.executor import CollectingDispatcher
import csv

class ActionServiceDetail(Action):
    def name(self):
        return "action_service_detail"

    def run(self, dispatcher, tracker, domain):
        user_input = tracker.get_slot("service_type")

        if not user_input:
            dispatcher.utter_message(text="Không nhận được dịch vụ")
            return []

        user_input = user_input.lower()

        try:
            with open("db/services_detail.csv", newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                for row in reader:
                    service_name = row["service_type"].lower()

                    # 🔥 match linh hoạt
                    if service_name in user_input:
                        message = (
                            f"📌 Dịch vụ: {row['service_type']}\n"
                            f"📂 Nhóm: {row['service_category']}\n"
                            f"💰 Giá: {row['price']} VND\n"
                            f"⏱ Thời gian: {row['duration']}\n"
                            f"📝 Mô tả: {row['description']}"
                        )
                        dispatcher.utter_message(text=message)
                        return []

        except Exception as e:
            dispatcher.utter_message(text=f"Lỗi: {str(e)}")
            return []

        dispatcher.utter_message(
            text="❌ Không tìm thấy dịch vụ. Bạn thử: Massage, Buffet..."
        )
        return []