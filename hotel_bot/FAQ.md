# FAQ Feature Design Spec
**Date:** 2026-04-10  
**Project:** Hotel Concierge Chatbot (Rasa Pro CALM)  
**Scope:** Add FAQ / hotel information Q&A capability

---

## 1. Overview

Add a dedicated FAQ flow that allows guests to ask any informational question about the hotel (rooms, policies, amenities, location, general info). The bot reads structured CSV data and uses the LLM to generate natural, concierge-style answers. When a question is out of scope, the bot refers the guest to front desk staff.

---

## 2. Architecture

```
User asks informational question
    ↓
CompactLLMCommandGenerator detects → triggers `faq` flow
    ↓
collect: faq_query  (LLM extracts question from user message)
    ↓
action_faq_lookup
    ├── detect_category(faq_query) → keyword matching
    ├── load db/<category>.csv → format as text
    └── dispatcher.utter_message("SYSTEM_INSTRUCTION: ...")
    ↓
IntentlessPolicy / LLM generates concierge-style answer
    ↓
action_reset_faq_slots → clears faq_query slot
    ↓
Flow ends, bot ready for next turn
```

---

## 3. Data Layer — `hotel_bot/db/`

Five CSV files, each covering one category:

| File | Category | Content |
|------|----------|---------|
| `rooms.csv` | Rooms | room_type, price_usd_per_night, size_sqm, max_adults, max_children, view, highlights |
| `policies.csv` | Policies | policy, detail |
| `amenities.csv` | Amenities | service, description, hours, notes |
| `location.csv` | Location | item, detail |
| `general.csv` | General | topic, detail |

### Example: `rooms.csv`
```
room_type,price_usd_per_night,size_sqm,max_adults,max_children,view,highlights
Deluxe,150,35,2,1,City view,"King bed, AC, minibar, safe, flat TV, bathtub"
Junior Suite,250,55,2,2,Pool view,"King bed, AC, minibar, safe, flat TV, bathtub, living area, balcony"
Club Suite,400,85,2,2,Panoramic Hanoi view,"King bed, AC, Jacuzzi, living area, balcony, club lounge access"
```

### Example: `policies.csv`
```
policy,detail
Check-in time,From 14:00 (2:00 PM)
Check-out time,Until 12:00 (12:00 PM)
Early check-in,Available upon request subject to availability. Fee may apply.
Late check-out,Available upon request until 18:00. Fee may apply.
Cancellation,Free cancellation up to 48 hours before check-in. After that 1 night charge applies.
Deposit,Credit card guarantee required at booking.
Pets,Not allowed.
Smoking,Non-smoking hotel. Outdoor designated areas only.
```

### Example: `amenities.csv`
```
service,description,hours,notes
Swimming Pool,Outdoor rooftop pool,06:00-22:00,Towels provided
Spa,Full-service spa with massage and beauty treatments,09:00-21:00,Reservation recommended
Gym,Fully equipped fitness center,24 hours,Complimentary for guests
Restaurant,Vietnamese and international cuisine,06:30-22:30,Breakfast included in some packages
WiFi,High-speed WiFi throughout the hotel,24 hours,Complimentary
Airport Transfer,Private car transfer to/from Noi Bai Airport,On request,Fee applies - contact front desk
```

### Example: `location.csv`
```
item,detail
Address,1 Hang Dao Street, Hoan Kiem District, Hanoi, Vietnam
From Noi Bai Airport,Approximately 45 minutes by car (35 km)
Nearby attraction,Hoan Kiem Lake - 5 minutes walk
Nearby attraction,Old Quarter - 3 minutes walk
Nearby attraction,Temple of Literature - 15 minutes by taxi
Nearby attraction,Ho Chi Minh Mausoleum - 20 minutes by taxi
Public transport,Multiple bus routes nearby. Grab/taxi readily available.
```

### Example: `general.csv`
```
topic,detail
Hotel name,The Hanoi Grand - A Luxury Collection Hotel
Star rating,5 stars
Total rooms,120 rooms and suites
Front desk,24 hours
Phone,+84 24 1234 5678
Email,concierge@hanoigrand.com
Languages spoken,Vietnamese, English, French, Japanese
```

---

## 4. Flow — `data/flows/faq.yml`

```yaml
flows:
  faq:
    description: >
      Answer guest questions about the hotel including room types and pricing,
      hotel policies, amenities and services, location and nearby attractions,
      and general hotel information. Trigger this flow when the user asks
      any informational question about the hotel.
    steps:
      - collect: faq_query
        description: The guest's question or topic they want to know about
      - action: action_faq_lookup
      - action: action_reset_faq_slots
```

---

## 5. Actions — `actions/action.py`

Two new classes added to the existing file:

### `ActionFaqLookup`

```
name: action_faq_lookup

Logic:
1. Read faq_query slot
2. Call detect_category(query) using keyword matching
3. Load db/<category>.csv, format rows as readable text
4. If CSV found → send SYSTEM_INSTRUCTION with hotel data context
5. If CSV not found → send SYSTEM_INSTRUCTION to refer guest to front desk
6. Return [] (no slot changes — reset handled by next action)
```

**Category keyword mapping:**

| Category | Trigger keywords |
|----------|----------------|
| `rooms` | room, suite, deluxe, junior, club, price, rate, cost, size, bed, view, floor, accommodation |
| `policies` | check-in, check-out, cancel, deposit, pet, smoke, refund, policy, early, late |
| `amenities` | spa, gym, pool, restaurant, wifi, breakfast, airport, transfer, service, amenity, facility, fitness |
| `location` | address, location, near, attraction, transport, bus, taxi, distance, map, airport, how to get |
| `general` | contact, phone, email, hour, open, overview, hotel, about, star, rating |

**Default:** If no keyword matches → load `general.csv`.

**Cross-category questions** (e.g., "What amenities come with the Club Suite?"): First matching category wins. `rooms.csv` has a `highlights` column covering in-room amenities, sufficient for most cross-category cases.

**Not found / staff referral:**
When the CSV file for a category is missing, the action loads `general.csv`
to extract contact details (phone, email) dynamically, then sends:
```
SYSTEM_INSTRUCTION: You do not have specific data for this guest's question.
Politely inform them you don't have that information readily available and
suggest they contact our front desk team using the contact details below.
Maintain a warm, professional concierge tone.
[contact info from general.csv inserted here]
```
This avoids hardcoding contact details in action code.

### `ActionResetFaqSlots`

```
name: action_reset_faq_slots

Logic:
1. Return [SlotSet("faq_query", None)]
```

---

## 6. Domain Changes — `domain/book_room.yml`

**Add slot:**
```yaml
slots:
  faq_query:
    type: text
    mappings:
      - type: from_llm
```

**Add actions:**
```yaml
actions:
  - action_faq_lookup
  - action_reset_faq_slots
```

No new `utter_*` responses needed — all answers generated dynamically via LLM.

---

## 7. Prompt Update — `prompts/intentless.jinja2`

Add Rule 5 to CRITICAL RULES:

```
5. FAQ: For hotel information questions, rely ONLY on data provided via
   SYSTEM_INSTRUCTION. Never guess prices, policies, or amenities not
   explicitly stated in the provided data.
```

---

## 8. Error Handling

| Scenario | Handling |
|----------|---------|
| `faq_query` slot is null | Action falls back to loading `general.csv` |
| CSV file missing for category | SYSTEM_INSTRUCTION to refer to front desk staff |
| Cross-category question | First matching category keyword wins |
| Question completely out of scope | Refer to front desk (same as CSV missing) |

---

## 9. Files Summary

| File | Action |
|------|--------|
| `hotel_bot/db/rooms.csv` | Create |
| `hotel_bot/db/policies.csv` | Create |
| `hotel_bot/db/amenities.csv` | Create |
| `hotel_bot/db/location.csv` | Create |
| `hotel_bot/db/general.csv` | Create |
| `hotel_bot/data/flows/faq.yml` | Create |
| `hotel_bot/actions/action.py` | Add 2 action classes at end of file |
| `hotel_bot/domain/book_room.yml` | Add slot `faq_query` + 2 action entries |
| `hotel_bot/prompts/intentless.jinja2` | Add Rule 5 |

---

## 10. Post-Implementation Steps

1. **`rasa train`** — required after adding new flow
2. **`rasa inspect`** — test with sample FAQ questions
3. No changes needed to `config.yml` or `endpoints.yml`

---

## 11. Sample Test Questions After Implementation

```
# Rooms
What are your room types?
How much does a Junior Suite cost per night?
What's the difference between Deluxe and Club Suite?

# Policies
What time is check-in?
Can I bring my dog?
What is your cancellation policy?

# Amenities
Do you have a swimming pool?
Is breakfast included?
Can you arrange airport transfer?

# Location
Where is the hotel located?
What attractions are nearby?
How far is it from the airport?

# General
What is your phone number?
How many stars is the hotel?
Do you speak Japanese?
```
