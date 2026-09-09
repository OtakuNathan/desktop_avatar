"""Bounded, memory-only projection for the current turn's work area."""
from collections import OrderedDict


class ToolActivityProjection:
    def __init__(self):
        self.turn_id = ""
        self.calls = OrderedDict()
        self.omitted = 0

    def apply(self, payload):
        turn_id = str(payload.get("turn_id") or "")
        action = payload.get("action")
        if not turn_id:
            return None
        if action == "begin":
            if turn_id != self.turn_id:
                self.calls.clear()
                self.omitted = 0
            self.turn_id = turn_id
        elif turn_id != self.turn_id:
            return None
        elif action == "end":
            self.turn_id = ""
            self.calls.clear()
            return {"type": "tool_activity", "payload": {"action": "end", "turn_id": turn_id}}
        elif action == "call":
            call_id = str(payload.get("call_id") or "")
            if not call_id:
                return None
            self.calls[call_id] = dict(payload)
            while len(self.calls) > 100:
                self.calls.popitem(last=False)
                self.omitted += 1
        else:
            return None
        return {"type": "tool_activity", "payload": {**payload, "omitted": self.omitted}}

    def frames(self):
        if not self.turn_id:
            return []
        return [
            {"type": "tool_activity", "payload": {"action": "begin", "turn_id": self.turn_id, "omitted": self.omitted}},
            *({"type": "tool_activity", "payload": call} for call in self.calls.values()),
        ]
