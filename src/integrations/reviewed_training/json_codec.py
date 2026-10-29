"""Exact JSON numbers, deterministic model encoding; no float round-trip."""
import json
from datetime import datetime,timezone
from decimal import Decimal
from uuid import UUID


def postgres_numeric(value):
    """Validate a finite unconstrained PostgreSQL NUMERIC without rounding.

    Bound the exponent before rendering, independently of Decimal's ambient
    arithmetic context. Import admission has its own, narrower limits.
    """
    if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)):
        raise ValueError('JSON number required')
    value=value if isinstance(value,Decimal) else Decimal(str(value))
    if not value.is_finite(): raise ValueError('Finite JSON number required')
    if value==0: return Decimal(0)
    if value.adjusted()+1>131072 or -value.as_tuple().exponent>16383:
        raise ValueError('Number exceeds PostgreSQL NUMERIC limits')
    return value


def encode(value):
    if isinstance(value,Decimal):
        # str(Decimal) is exact and may use a compact JSON exponent. Never use
        # float(), normalize() or arithmetic: all can discard evidence digits.
        return str(postgres_numeric(value))
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
    # Preserve ordinary ints for strict frame/sequence fields, but avoid Python's
    # integer-string digit cap when reading a legal large NUMERIC JSON token.
    def integer(token): return int(token) if len(token.lstrip('-'))<=640 else Decimal(token)
    return json.loads(raw,parse_float=Decimal,parse_int=integer,
                      parse_constant=invalid,object_pairs_hook=unique)
