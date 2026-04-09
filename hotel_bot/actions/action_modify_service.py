import os
import csv
from rasa_sdk import Action

class ActionModifyService(Action):
    file_booking = "db/booking_service.csv"

    def name(self):
        return "action_modify_service"

    def run(self, dispatcher, tracker, domain):
        # Lấy thông tin xác thực
        user_name = tracker.get_slot("user_name_modify")
        phone_number = tracker.get_slot("phone_number_modify")

        # Lấy thông tin dịch vụ muốn sửa
        service_type_modify = tracker.get_slot("service_type_modify")

        if not user_name or not phone_number or not service_type_modify:
            dispatcher.utter_message(text="Xin lỗi, thiếu thông tin để xác thực và sửa dịch vụ.")
            return []

        # Đọc file booking để tìm booking cần sửa
        bookings = []
        booking_found = None
        booking_index = -1

        if os.path.exists(self.file_booking):
            with open(self.file_booking, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    bookings.append(row)
                    # Tìm booking theo tên, số điện thoại và dịch vụ
                    if (row["user_name"].lower() == user_name.lower() and
                        row["phone_number"] == phone_number and
                        row["service_type"].lower() == service_type_modify.lower()):
                        booking_found = row
                        booking_index = i
                        break

        if not booking_found:
            dispatcher.utter_message(text=f"❌ Không tìm thấy booking cho {user_name} với số điện thoại {phone_number} và dịch vụ {service_type_modify}.")
            return []

        # Cập nhật thông tin mới (chỉ cập nhật những gì có giá trị)
        updated_booking = booking_found.copy()

        # Lấy thông tin mới
        quantity_modify = tracker.get_slot("quantity_modify")
        date_modify = tracker.get_slot("date_modify")
        time_modify = tracker.get_slot("time_modify")
        note_modify = tracker.get_slot("note_modify")

        if quantity_modify is not None:
            updated_booking["quantity"] = str(quantity_modify)

        if date_modify and time_modify:
            updated_booking["service_time"] = f"{date_modify} {time_modify}"
        elif date_modify:
            # Chỉ cập nhật ngày, giữ nguyên giờ
            current_time = booking_found["service_time"].split(" ")[1] if " " in booking_found["service_time"] else ""
            updated_booking["service_time"] = f"{date_modify} {current_time}"
        elif time_modify:
            # Chỉ cập nhật giờ, giữ nguyên ngày
            current_date = booking_found["service_time"].split(" ")[0] if " " in booking_found["service_time"] else ""
            updated_booking["service_time"] = f"{current_date} {time_modify}"

        if note_modify is not None:
            updated_booking["note"] = note_modify

        # Tính lại tổng giá nếu quantity thay đổi
        if quantity_modify is not None:
            try:
                # Đọc service_detail để lấy giá
                service_db = {}
                if os.path.exists("db/services_detail.csv"):
                    with open("db/services_detail.csv", "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            service_db[row["service_type"].lower()] = int(row["price"])

                service_key = service_type_modify.lower()
                if service_key in service_db:
                    price = service_db[service_key]
                    total_price = int(quantity_modify) * price
                    updated_booking["total_price"] = str(total_price)
            except:
                pass  # Giữ nguyên giá cũ nếu có lỗi

        # Cập nhật booking trong danh sách
        bookings[booking_index] = updated_booking

        # Ghi lại file CSV
        with open(self.file_booking, "w", newline="", encoding="utf-8") as f:
            if bookings:
                writer = csv.DictWriter(f, fieldnames=bookings[0].keys())
                writer.writeheader()
                writer.writerows(bookings)

        # Thông báo thành công
        changes = []
        if quantity_modify is not None:
            changes.append(f"Số lượng: {quantity_modify}")
        if date_modify or time_modify:
            changes.append(f"Thời gian: {updated_booking['service_time']}")
        if note_modify is not None:
            changes.append(f"Ghi chú: {note_modify}")

        change_text = ", ".join(changes) if changes else "không có thay đổi"

        dispatcher.utter_message(text=f"✅ Đã cập nhật dịch vụ {service_type_modify} thành công!\n"
                                      f"Thay đổi: {change_text}\n"
                                      f"Booking ID: {updated_booking['booking_service_id']}")

        return []