from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
from datetime import datetime
from zoneinfo import ZoneInfo
import dateparser
import difflib

class ActionValidateBookingDates(Action):
    def name(self) -> Text:
        return "action_validate_booking_dates"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        check_in = tracker.get_slot("check_in_date")
        check_out = tracker.get_slot("check_out_date")

        if not check_in or not check_out:
            return []

        # Parse the natural language dates
        in_date_parsed = dateparser.parse(check_in)
        out_date_parsed = dateparser.parse(check_out)

        if in_date_parsed and out_date_parsed:
            in_date = in_date_parsed.date()
            out_date = out_date_parsed.date()
            
            # Anchor to Hanoi time to prevent timezone hallucinations
            hanoi_tz = ZoneInfo("Asia/Ho_Chi_Minh")
            today = datetime.now(hanoi_tz).date()

            # 1. Past-date checking
            if in_date < today:
                dispatcher.utter_message(text="SYSTEM_INSTRUCTION: The check-in date is in the past. Politely inform the user that we can only book for today or future dates.")
                return [SlotSet("check_in_date", None)]

            # 2. Check-out validation
            if out_date <= in_date:
                dispatcher.utter_message(text="SYSTEM_INSTRUCTION: The check-out date is before or on the check-in date. Ask the user to provide a check-out date that is at least one day after check-in.")
                return [SlotSet("check_out_date", None)]

            # 3. 14-Day Maximum Stay Limit
            stay_duration = (out_date - in_date).days
            if stay_duration > 14:
                dispatcher.utter_message(
                    text="SYSTEM_INSTRUCTION: The requested stay is {stay_duration} days, which exceeds our 14-day maximum. Politely inform the user that they need to speak with our long-stay sales agent, and safely cancel this booking process."
                )
                return [SlotSet("check_in_date", None), SlotSet("check_out_date", None)]

        return []

class ActionCheckAvailability(Action):
    def name(self) -> Text:
        return "action_check_availability"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

        room_type = tracker.get_slot("room_type")
        
        inventory = {
            "Deluxe": 5,
            "Junior Suite": 2,
            "Club Suite": 0  # Fully booked for testing
        }

        if not room_type:
            return []

        # 1. Semantic Synonym Mapping
        synonyms = {
            "cheapest": "Deluxe",
            "standard": "Deluxe",
            "basic": "Deluxe",
            "normal": "Deluxe",
            "family": "Junior Suite",
            "best": "Club Suite",
            "luxury": "Club Suite",
            "expensive": "Club Suite",
            "vip": "Club Suite"
        }
        
        user_input_lower = room_type.lower().strip()
        matched_room = None

        # Check for semantic match first
        for key, value in synonyms.items():
            if key in user_input_lower:
                matched_room = value
                break

        # 2. Fuzzy String Matching for Typos (if no semantic match)
        if not matched_room:
            valid_rooms = list(inventory.keys())
            # cutoff=0.6 allows for slight misspellings like "Delux" or "Suit"
            closest_matches = difflib.get_close_matches(room_type, valid_rooms, n=1, cutoff=0.6)
            if closest_matches:
                matched_room = closest_matches[0]

        # 3. Inventory & Alternative Routing Logic
        if matched_room:
            if inventory[matched_room] > 0:
                # We silently normalize the slot without an explicit utterance. 
                # The LLM will naturally continue to the next flow step.
                return [SlotSet("room_type", matched_room)] 
            else:
                # Alternative Room Logic
                alternative = next((room for room, count in inventory.items() if count > 0), None)
                
                if alternative:
                    dispatcher.utter_message(
                        text=f"SYSTEM_INSTRUCTION: Inform the user that the {matched_room} is fully booked for those dates. However, we have the {alternative} available. Ask if they would like to book the {alternative} instead."
                    )
                else:
                    dispatcher.utter_message(
                        text="SYSTEM_INSTRUCTION: Apologize deeply. The hotel is completely fully booked for these dates. Ask if they would like to search for different dates."
                    )
                
                # Wipe the slot so the CALM flow pauses and waits for the user's decision
                return [SlotSet("room_type", None)] 
        else:
            # Catch-all if the LLM extracted something completely unrecognized
            dispatcher.utter_message(text="SYSTEM_INSTRUCTION: We could not identify the requested room type. Remind the user that we offer Deluxe Rooms, Junior Suites, and Club Suites, and ask which they prefer.")
            return [SlotSet("room_type", None)]

    

class ActionWipeTargetSlot(Action):
    def name(self) -> Text:
        return "action_wipe_target_slot"

    def run(self, dispatcher: CollectingDispatcher,
            tracker: Tracker,
            domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        
        # Identify what the user wants to change
        slot_to_modify = tracker.get_slot("slot_to_modify")
        
        if slot_to_modify:
            # Wipe the target slot, AND wipe the 'slot_to_modify' memory 
            # so the flow can be used again later if needed.
            return [SlotSet(slot_to_modify, None), SlotSet("slot_to_modify", None)]
            
        return []