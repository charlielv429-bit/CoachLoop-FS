"""Exact JSON numbers, deterministic model encoding; no float round-trip."""
import json
from datetime import datetime,timezone
from decimal import Decimal
from uuid import UUID


def encode(value):
    if isinstance(value,Decimal):
        if not value.is_finite(): raise ValueError('Finite JSON number required')
        if value==0: return '0'
        parts=value.as_tuple()
        if max(0,-parts.exponent)>60 or len(parts.digits)+max(0,parts.exponent)>80:
            raise ValueError('Numeric precision exceeds interchange limits')
        token=format(value,'f')
        if '.' in token: token=token.rstrip('0').rstrip('.')
        return '0' if value==0 else token
    if isinstance(value,UUID): value=str(value)
    if isinstance(value,datetime): value=value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    if isinstance(value,dict): return '{'+','.join(json.dumps(str(k))+':'+encode(v) for k,v in sorted(value.items()))+'}'
    if isinstance(value,(list,tuple)): return '['+','.join(encode(v) for v in value)+']'
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def decode(raw):
    def invalid(_): raise ValueError('Non-finite JSON number')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('Duplicate JSON object key')
            result[key]=value
        return result
    return json.loads(raw,parse_float=Decimal,parse_constant=invalid,object_pairs_hook=unique)
