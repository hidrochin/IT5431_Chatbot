from rasa_sdk import Action
from rasa_sdk.executor import CollectingDispatcher
import csv
from collections import defaultdict

class ActionListServices(Action):
    def name(self):
        return "action_list_services"

    def run(self, dispatcher, tracker, domain):
        services = defaultdict(list)

        try:
            with open("db/services.csv", newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    services[row["service_category"]].append(row["service_type"])
        except:
            dispatcher.utter_message(text="Unable to read service data")
            return []

        if not services:
            dispatcher.utter_message(text="No services available at the moment")
            return []

        message = "🏨 List of services:\n"

        for category, items in services.items():
            message += f"\n{category}:\n"
            for item in items:
                message += f" - {item}\n"

        dispatcher.utter_message(text=message.strip())

        return []