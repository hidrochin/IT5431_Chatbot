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

        # Lấy slot
        service_type_order = tracker.get_slot("service_type_order")  # UC3 input
        quantity = tracker.get_slot("quantity") or 1
        date = tracker.get_slot("date")
        time = tracker.get_slot("time")
        note = tracker.get_slot("note") or ""
        user_name = tracker.get_slot("user_name") or "Khách"
        phone_number = tracker.get_slot("phone_number") or "Chưa có"

        if not service_type_order or not date or not time:
            dispatcher.utter_message(text="Xin lỗi, thiếu thông tin để tạo booking.")
            return []

        # Đọc CSV service_detail (service_type)
        service_db = {}
        if os.path.exists(self.file_service):
            with open(self.file_service, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # key là service_name lower (giả sử giống tên user nhập)
                    service_db[row["service_type"].lower()] = {
                        "category": row["service_category"],
                        "price": int(row["price"]),
                        "type": row["service_type"]  # để ghi CSV booking
                    }
        else:
            dispatcher.utter_message(text="File dịch vụ không tồn tại.")
            return []

        service_key = service_type_order.lower()
        if service_key not in service_db:
            dispatcher.utter_message(text=f"Xin lỗi, chúng tôi không có dịch vụ '{service_type_order}'.")
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

        # CSV booking đã có header, append trực tiếp
        max_id = 0
        if os.path.exists(self.file_booking):
            with open(self.file_booking, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                ids = [int(row["booking_service_id"]) for row in reader if row["booking_service_id"].isdigit()]
                if ids:
                    max_id = max(ids)
        new_id = max_id + 1

        # Đảm bảo file kết thúc với newline trước khi append
        if os.path.exists(self.file_booking):
            with open(self.file_booking, "rb") as f:
                content = f.read()
                if content and not content.endswith(b'\n'):
                    with open(self.file_booking, "ab") as f:
                        f.write(b'\n')

        # Ghi thêm booking mới
        with open(self.file_booking, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([new_id, user_name, phone_number, category, service_type,
                             service_time, quantity, total_price, note])

        # Phản hồi bot
        dispatcher.utter_message(text=f"🎉 Đặt dịch vụ thành công! Booking ID: {new_id}\n"
                                      f"- Dịch vụ: {service_type_order}\n"
                                      f"- Ngày/giờ: {service_time}\n"
                                      f"- Số lượng: {quantity}\n"
                                      f"- Tổng giá: {total_price} VNĐ\n"
                                      f"- Tên: {user_name}\n"
                                      f"- SĐT: {phone_number}\n"
                                      f"- Ghi chú: {note}")

        return []