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