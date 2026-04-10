import csv
import os
import random
import string
import unicodedata
from datetime import datetime, timedelta

# Configuration
NUM_RECORDS = 100
BOOKINGS_FILE = os.path.join("bookings.csv")

# Mock Data Pools (Tailored for a Hanoi Hotel context)
FIRST_NAMES = ["Anh", "Bình", "Châu", "Duy", "Hải", "Hương", "Khánh", "Linh", "Minh", "Ngọc", "Phong", "Quang", "Trang", "Tuấn", "Yến", "Thịnh"]
LAST_NAMES = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương"]
ROOM_TYPES = ["Deluxe", "Junior Suite", "Club Suite"]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "hust.edu.vn", "company.vn", "outlook.com"]

def generate_booking_id() -> str:
    """Generates a matching 6-character alphanumeric ID (e.g., HN829X)."""
    chars = string.ascii_uppercase + string.digits
    return "HN" + ''.join(random.choice(chars) for _ in range(4))

def generate_phone() -> str:
    """Generates a realistic 10-digit Vietnamese phone number."""
    prefixes = ["090", "091", "098", "097", "086", "088"]
    return random.choice(prefixes) + "".join(str(random.randint(0, 9)) for _ in range(7))

def strip_accents(text: str) -> str:
    """Removes Vietnamese accents for clean email generation."""
    return ''.join(c for c in unicodedata.normalize('NFD', text)
                  if unicodedata.category(c) != 'Mn').replace('đ', 'd').replace('Đ', 'D')

def generate_fake_data():
    os.makedirs(DB_DIR, exist_ok=True)
    
    # We use 'w' to overwrite the file so you can run this multiple times cleanly
    with open(BOOKINGS_FILE, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        # Write exact Header from your action_finalize_booking script
        writer.writerow(["Booking ID", "Name", "Phone", "Email", "Check In", "Check Out", "Room Type", "Adults", "Children"])
        
        base_date = datetime.now()
        
        for _ in range(NUM_RECORDS):
            booking_id = generate_booking_id()
            name = f"{random.choice(LAST_NAMES)} {random.choice(FIRST_NAMES)}"
            
            # Generate a realistic email format
            clean_name = strip_accents(name.lower()).replace(" ", ".")
            email = f"{clean_name}{random.randint(1,99)}@{random.choice(EMAIL_DOMAINS)}"
            
            phone = generate_phone()
            
            # Weighted random choice so the hotel isn't exclusively VIPs
            room_type = random.choices(ROOM_TYPES, weights=[60, 30, 10], k=1)[0]
            
            adults = random.randint(1, 4)
            # Make children less likely than adults
            children = random.choices([0, 1, 2, 3], weights=[50, 30, 15, 5], k=1)[0] 
            
            # Dates: Random check-in between yesterday and 90 days in the future
            days_ahead = random.randint(-1, 90)
            check_in_date = base_date + timedelta(days=days_ahead)
            
            # Check-out is strictly 1 to 7 days after check-in
            stay_duration = random.randint(1, 7)
            check_out_date = check_in_date + timedelta(days=stay_duration)
            
            writer.writerow([
                booking_id, 
                name, 
                phone, 
                email, 
                check_in_date.strftime("%Y-%m-%d"), 
                check_out_date.strftime("%Y-%m-%d"), 
                room_type, 
                adults, 
                children
            ])

if __name__ == "__main__":
    generate_fake_data()
    print(f"Successfully generated {NUM_RECORDS} fake bookings in {BOOKINGS_FILE}")