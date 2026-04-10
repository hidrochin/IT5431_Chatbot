import os
import csv
from rasa_sdk import Action
from rasa_sdk.events import SlotSet

class ActionCheckBookingExist(Action):
    file_booking = "db/booking_service.csv"

    def name(self):
        return "action_check_booking_exist"

    def run(self, dispatcher, tracker, domain):
        user_name = tracker.get_slot("user_name_modify")
        phone_number = tracker.get_slot("phone_number_modify")
        service_type = tracker.get_slot("service_type_modify")

        if not user_name or not phone_number or not service_type:
            dispatcher.utter_message(text="❌ Missing information to check booking.")
            return [SlotSet("booking_found", False)]

        if not os.path.exists(self.file_booking):
            return [SlotSet("booking_found", False)]

        with open(self.file_booking, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (
                    row["user_name"].lower() == user_name.lower()
                    and row["phone_number"] == phone_number
                    and row["service_type"].lower() == service_type.lower()
                ):
                    return [SlotSet("booking_found", True)]

        # dispatcher.utter_message(
        #     text=f"❌ No booking found for {user_name} with service {service_type}."
        # )
        return [SlotSet("booking_found", False)]


class ActionModifyService(Action):
    file_booking = "db/booking_service.csv"

    def name(self):
        return "action_modify_service"

    def run(self, dispatcher, tracker, domain):
        # ===== GET INFORMATION =====
        user_name = tracker.get_slot("user_name_modify")
        phone_number = tracker.get_slot("phone_number_modify")
        service_type_modify = tracker.get_slot("service_type_modify")

        quantity_modify = tracker.get_slot("quantity_modify")
        date_modify = tracker.get_slot("date_modify")
        time_modify = tracker.get_slot("time_modify")
        note_modify = tracker.get_slot("note_modify")

        if not os.path.exists(self.file_booking):
            dispatcher.utter_message(text="❌ No booking data available.")
            return []

        # ===== READ FILE =====
        bookings = []
        booking_found = None
        booking_index = -1

        with open(self.file_booking, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                bookings.append(row)
                if (
                    row["user_name"].lower() == user_name.lower()
                    and row["phone_number"] == phone_number
                    and row["service_type"].lower() == service_type_modify.lower()
                ):
                    booking_found = row
                    booking_index = i

        if booking_found is None:
            dispatcher.utter_message(text="❌ Booking does not exist.")
            return []

        updated_booking = booking_found.copy()

        # ===== UPDATE =====
        changes = []

        # Quantity
        if quantity_modify not in [None, "", "không", "no"]:
            updated_booking["quantity"] = str(quantity_modify)
            changes.append(f"Quantity: {quantity_modify}")

        # Time
        old_time = booking_found.get("service_time", "")
        old_date = old_time.split(" ")[0] if " " in old_time else ""
        old_hour = old_time.split(" ")[1] if " " in old_time else ""

        new_date = date_modify if date_modify not in [None, "", "không", "no"] else old_date
        new_time = time_modify if time_modify not in [None, "", "không", "no"] else old_hour

        if new_date or new_time:
            updated_booking["service_time"] = f"{new_date} {new_time}".strip()
            if date_modify or time_modify:
                changes.append(f"Time: {updated_booking['service_time']}")

        # Note
        if note_modify not in [None, ""]:
            updated_booking["note"] = note_modify
            changes.append(f"Note: {note_modify}")

        # ===== UPDATE PRICE =====
        if quantity_modify not in [None, "", "không", "no"]:
            try:
                service_db = {}
                if os.path.exists("db/services_detail.csv"):
                    with open("db/services_detail.csv", "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            service_db[row["service_type"].lower()] = int(row["price"])

                key = service_type_modify.lower()
                if key in service_db:
                    total_price = int(quantity_modify) * service_db[key]
                    updated_booking["total_price"] = str(total_price)
            except:
                pass

        # ===== SAVE =====
        bookings[booking_index] = updated_booking

        with open(self.file_booking, "w", newline="", encoding="utf-8") as f:
            if bookings:
                writer = csv.DictWriter(f, fieldnames=bookings[0].keys())
                writer.writeheader()
                writer.writerows(bookings)

        # ===== RESPONSE =====
        change_text = ", ".join(changes) if changes else "no changes"

        dispatcher.utter_message(
            text=(
                f"✅ Successfully updated service {service_type_modify}!\n"
                f"Changes: {change_text}\n"
                f"Booking ID: {updated_booking['booking_service_id']}"
            )
        )

        return []