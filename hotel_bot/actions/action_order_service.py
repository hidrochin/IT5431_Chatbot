import os
import csv
from rasa_sdk import Action

class ActionCreateOrder(Action):
    file_booking = "db/booking_service.csv"
    file_service = "db/services_detail.csv"

    def name(self):
        return "action_create_order"

    def run(self, dispatcher, tracker, domain):
        os.makedirs(os.path.dirname(self.file_booking), exist_ok=True)

        # Get slots
        service_type_order = tracker.get_slot("service_type_order")  # UC3 input
        quantity = tracker.get_slot("quantity") or 1
        date = tracker.get_slot("date")
        time = tracker.get_slot("time")
        note = tracker.get_slot("note") or ""
        user_name = tracker.get_slot("user_name") or "Guest"
        phone_number = tracker.get_slot("phone_number") or "Not provided"

        if not service_type_order or not date or not time:
            dispatcher.utter_message(text="Sorry, missing information to create booking.")
            return []

        # Read CSV service_detail (service_type)
        service_db = {}
        if os.path.exists(self.file_service):
            with open(self.file_service, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # key is service_name lower (assumed to match user input)
                    service_db[row["service_type"].lower()] = {
                        "category": row["service_category"],
                        "price": int(row["price"]),
                        "type": row["service_type"]  # to write to booking CSV
                    }
        else:
            dispatcher.utter_message(text="Service file does not exist.")
            return []

        service_key = service_type_order.lower()
        if service_key not in service_db:
            dispatcher.utter_message(text=f"Sorry, we do not have the service '{service_type_order}'.")
            return []

        category = service_db[service_key]["category"]
        service_type = service_db[service_key]["type"]
        price = service_db[service_key]["price"]

        try:
            quantity = int(quantity)
        except:
            quantity = 1

        total_price = quantity * price
        service_time = f"{date} {time}"

        # CSV booking already has header, append directly
        max_id = 0
        if os.path.exists(self.file_booking):
            with open(self.file_booking, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                ids = [int(row["booking_service_id"]) for row in reader if row["booking_service_id"].isdigit()]
                if ids:
                    max_id = max(ids)
        new_id = max_id + 1

        # Ensure file ends with newline before appending
        if os.path.exists(self.file_booking):
            with open(self.file_booking, "rb") as f:
                content = f.read()
                if content and not content.endswith(b'\n'):
                    with open(self.file_booking, "ab") as f:
                        f.write(b'\n')

        # Write new booking
        with open(self.file_booking, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([new_id, user_name, phone_number, category, service_type,
                             service_time, quantity, total_price, note])

        # Bot response
        dispatcher.utter_message(text=f"🎉 Service booking successful! Booking ID: {new_id}\n"
                                      f"- Service: {service_type_order}\n"
                                      f"- Date/Time: {service_time}\n"
                                      f"- Quantity: {quantity}\n"
                                      f"- Total price: {total_price} VND\n"
                                      f"- Name: {user_name}\n"
                                      f"- Phone: {phone_number}\n"
                                      f"- Note: {note}")

        return []