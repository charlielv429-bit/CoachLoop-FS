"""Synthetic-only diagnostics; no platform credential, network or model calls."""
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
with pytest.MonkeyPatch.context() as patch:
    patch.syspath_prepend(str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('gateway_diagnostics', ROOT / 'scripts/diagnose_coze_gateway.py')
    diagnostic = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diagnostic)

APP = 'synthetic-application-review-token'
PLATFORM = 'synthetic-platform-review-token'


def test_gateway_intercepts_health_and_application_token_does_not_bypass_it():
    def send(method, path, payload, headers):
        if headers.get('Authorization') != 'Bearer ' + PLATFORM:
            return 401, {'detail': 'Missing authorization header'}
        return (200, {'status': 'ok'}) if path == '/health' else (403, {'detail': 'Invalid workflow credential'})
    report = diagnostic.diagnose(send, APP, PLATFORM)
    rows = {row['name']: row for row in report['checks']}
    assert rows['health_no_credentials']['missing_authorization_header_signature']
    assert rows['health_platform_credential']['application_health_shape']
    assert rows['draft_platform_credential_only']['status'] == 403
    assert report['authorization_header_collision']
    assert not any(row['verified_draft'] for row in report['checks'])
    assert APP not in json.dumps(report) and PLATFORM not in json.dumps(report)


def test_separate_header_is_used_only_when_explicitly_supplied():
    calls = []
    # Deliberately synthetic header name; no claim that Coze supports it.
    def send(method, path, payload, headers):
        calls.append(headers)
        if headers.get('X-Test-Platform-Credential') != PLATFORM:
            return 401, {'detail': 'Missing authorization header'}
        if path == '/health':
            return 200, {'status': 'ok'}
        if headers.get('Authorization') != 'Bearer ' + APP:
            return 403, {'detail': 'Invalid workflow credential'}
        if payload['total_minutes'] != 45:
            return 422, {'detail': 'Invalid minutes'}
        # Contract binds expected anonymous classroom; generate only locally.
        from graphs.prelesson_graph import run_prelesson
        return 200, run_prelesson(payload).model_dump(mode='json')
    report = diagnostic.diagnose(send, APP, PLATFORM, 'X-Test-Platform-Credential', 'raw')
    rows = {row['name']: row for row in report['checks']}
    assert not report['authorization_header_collision']
    assert rows['draft_combined_credentials']['verified_draft']
    assert rows['alias_combined_credentials']['verified_draft']
    assert rows['invalid_minutes_combined_credentials']['status'] == 422
    assert rows['wrong_application_with_platform']['status'] == 403
    assert any(h.get('Authorization') == 'Bearer ' + APP and h.get('X-Test-Platform-Credential') == PLATFORM for h in calls)


@pytest.mark.parametrize('body', ['detail', {'detail': 'denied', 'lesson_plan': {}}, {'detail': None}])
def test_error_payloads_cannot_be_reported_as_valid_application_errors(body):
    report = diagnostic.diagnose(lambda *args: (401, body), APP)
    assert all(not row['application_error_shape'] and not row['verified_draft'] for row in report['checks'])


def test_reflected_secrets_and_transport_exceptions_never_appear_in_report():
    def send(*args):
        raise RuntimeError(APP + PLATFORM)
    report = diagnostic.diagnose(send, APP, PLATFORM)
    assert all(row['status'] is None for row in report['checks'])
    assert APP not in json.dumps(report) and PLATFORM not in json.dumps(report)
    reflected = diagnostic.diagnose(lambda *args: (401, {'detail': APP + PLATFORM}), APP)
    assert APP not in json.dumps(reflected) and PLATFORM not in json.dumps(reflected)


@pytest.mark.parametrize('origin', ['http://127.0.0.1', 'https://user:secret@service.org',
    'https://service.org/path', 'https://service.org?token=secret', 'https://service.org\n'])
def test_transport_rejects_unsafe_or_credential_bearing_origins(origin):
    with pytest.raises(ValueError):
        diagnostic.HTTPSProbe(origin)


def test_redirects_and_non_json_errors_are_reported_without_following_or_printing(monkeypatch):
    transport = diagnostic.HTTPSProbe(diagnostic.DEFAULT_ORIGIN)
    def redirect(*args, **kwargs):
        raise HTTPError(diagnostic.DEFAULT_ORIGIN, 302, 'synthetic', {'Location': 'https://other.invalid'}, io.BytesIO(b'<html>synthetic</html>'))
    monkeypatch.setattr(transport.opener, 'open', redirect)
    assert transport('GET', '/health', None, {}) == (302, None)
    report = diagnostic.diagnose(transport, APP)
    assert all(row['redirect_refused'] and not row['verified_draft'] for row in report['checks'])
    assert diagnostic.contract.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid') is None


@pytest.mark.parametrize('header', ['Cookie', 'Host', 'X-Test\nSecret: value'])
def test_unexpected_or_injected_platform_headers_are_rejected(header):
    with pytest.raises(ValueError):
        diagnostic.diagnose(lambda *args: None, APP, PLATFORM, header)


def test_cli_refuses_noninteractive_secret_input(monkeypatch, capsys):
    monkeypatch.setattr(diagnostic.sys.stdin, 'isatty', lambda: False)
    assert diagnostic.main([]) == 2
    assert 'hidden' not in capsys.readouterr().out


def test_cli_never_echoes_unknown_argument_values(capsys):
    with pytest.raises(SystemExit):
        diagnostic.main(['--token', APP])
    assert APP not in capsys.readouterr().err
