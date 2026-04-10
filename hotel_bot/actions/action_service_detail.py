from rasa_sdk import Action
from rasa_sdk.executor import CollectingDispatcher
import csv

class ActionServiceDetail(Action):
    def name(self):
        return "action_service_detail"

    def run(self, dispatcher, tracker, domain):
        user_input = tracker.get_slot("service_type")

        if not user_input:
            dispatcher.utter_message(text="Service not received")
            return []

        user_input = user_input.lower()

        try:
            with open("db/services_detail.csv", newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                for row in reader:
                    service_name = row["service_type"].lower()

                    # 🔥 flexible matching
                    if service_name in user_input:
                        message = (
                            f"📌 Service: {row['service_type']}\n"
                            f"📂 Category: {row['service_category']}\n"
                            f"💰 Price: {row['price']} VND\n"
                            f"⏱ Duration: {row['duration']}\n"
                            f"📝 Description: {row['description']}"
                        )
                        dispatcher.utter_message(text=message)
                        return []

        except Exception as e:
            dispatcher.utter_message(text=f"Error: {str(e)}")
            return []

        dispatcher.utter_message(
            text="❌ Service not found. Try: Massage, Buffet..."
        )
        return []