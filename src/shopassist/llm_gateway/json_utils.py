"""Strict JSON shared by native envelopes and Gateway structured output."""
import json


def strict_json_loads(text):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    def reject(_):raise ValueError('Non-finite JSON number')
    return json.loads(text,object_pairs_hook=unique,parse_constant=reject)
