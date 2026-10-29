"""No database needed: finite exact numbers and exponent/resource boundaries."""
import json
from decimal import Decimal,localcontext

import pytest
from pydantic import TypeAdapter,ValidationError

from integrations.reviewed_training.json_codec import decode,encode
from integrations.reviewed_training.schemas import OutputNumber


@pytest.mark.parametrize('value',[
    Decimal('0.'+'1'*61),Decimal('1e-16383'),Decimal('1e131071'),
    Decimal('9'*5000),Decimal('9'*131072+'.'+'1'*16383),
])
def test_output_decimal_round_trip_without_context_rounding(value):
    with localcontext() as context:
        context.prec=6
        validated=TypeAdapter(OutputNumber).validate_python(value)
        token=encode(validated)
        assert not token.startswith('"')
        assert json.loads(token,parse_float=Decimal,parse_int=Decimal)==value
        assert decode(token)==value


@pytest.mark.parametrize('value',[
    Decimal('NaN'),Decimal('sNaN'),Decimal('Infinity'),Decimal('-Infinity'),
    Decimal('1e131072'),Decimal('1e-16384'),
    Decimal('1e1000000000'),Decimal('1e-1000000000'),
])
def test_encoder_rejects_nonfinite_or_non_postgres_range(value):
    with pytest.raises(ValueError):encode(value)


@pytest.mark.parametrize('value',[Decimal('-1'),Decimal('NaN'),Decimal('Infinity'),Decimal('-Infinity'),True,'1.23'])
def test_event_output_rejects_invalid_numbers(value):
    with pytest.raises(ValidationError):TypeAdapter(OutputNumber).validate_python(value)


def test_decoder_keeps_frames_integer_and_large_tokens_decimal():
    assert type(decode('2147483647')) is int
    assert decode('9'*5000)==Decimal('9'*5000)
