"""Interactive HTTPS-only diagnostics; no secrets in argv, logs or reports."""
import argparse
import getpass
import json
import re
import sys
import urllib.request
from urllib.error import HTTPError

import check_coze_deployment as contract

DEFAULT_ORIGIN = 'https://33vnf9hq7m.coze.site'
CANONICAL = '/api/v1/lesson-plans/draft'
ALIAS = '/prelesson/draft'


class RedactedParser(argparse.ArgumentParser):
    def error(self, _message):
        self.exit(2, 'Invalid arguments; values omitted. Use --help.\n')


class HTTPSProbe:
    def __init__(self, origin):
        self.origin = contract.validate_origin(origin)
        if not self.origin.startswith('https://'):
            raise ValueError('HTTPS required')
        self.opener = urllib.request.build_opener(contract.NoRedirect())

    def __call__(self, method, path, payload, headers):
        req = urllib.request.Request(self.origin + path, method=method,
            headers={'Content-Type': 'application/json', **headers},
            data=json.dumps(payload).encode() if payload is not None else None)
        try:
            response = self.opener.open(req, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                return response.status, None
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError, RecursionError):
                data = None
            return response.status, data


def checked_secret(value):
    if not value or not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError('Expected a nonempty visible ASCII token')
    return value


def checked_platform_header(value):
    # Only use a distinct header if the platform's actual official call example
    # specifies it; this tool does not invent or attest a Coze header name.
    if value.lower() != 'authorization' and not re.fullmatch(r'X-[A-Za-z0-9-]{1,64}', value, re.I):
        raise ValueError('Expected Authorization or an explicitly documented X- header')
    return value


def diagnose(send, app_token, platform_token=None, platform_header='Authorization', platform_prefix='Bearer'):
    checked_secret(app_token)
    checked_platform_header(platform_header)
    if platform_token is not None:
        checked_secret(platform_token)
    if platform_prefix not in ('Bearer', 'raw'):
        raise ValueError('Invalid platform authentication prefix')
    rows = []
    def probe(name, path, headers, payload=None):
        try:
            status, data = send('POST' if payload is not None else 'GET', path, payload, headers)
            row = {'name': name, 'status': status,
                'application_health_shape': status == 200 and isinstance(data, dict) and data.get('status') == 'ok',
                'verified_draft': status == 200 and contract.valid_draft(data, contract.SAMPLE),
                'application_error_shape': status in (400, 401, 403, 404, 405, 413, 422, 503) and contract.valid_error_response(data),
                'error_contains_success_payload': status >= 400 and contract.contains_success_payload(data),
                # Exact fingerprints are observations, not cryptographic proof
                # of which proxy/application generated the response.
                'missing_authorization_header_signature': isinstance(data, dict) and
                    any(data.get(k) == 'Missing authorization header' for k in ('detail', 'error', 'message')),
                'application_bearer_required_signature': isinstance(data, dict) and data.get('detail') == 'Bearer credential required',
                'redirect_refused': 300 <= status < 400}
        except Exception:
            row = {'name': name, 'status': None, 'transport_or_response_error': True}
        rows.append(row)
    app = {'Authorization': 'Bearer ' + app_token}
    probe('health_no_credentials', '/health', {})
    probe('health_application_bearer', '/health', app)
    probe('draft_no_credentials', CANONICAL, {}, contract.SAMPLE)
    probe('draft_wrong_application_bearer', CANONICAL, {'Authorization': 'Bearer synthetic-deliberately-invalid'}, contract.SAMPLE)
    probe('draft_application_bearer', CANONICAL, app, contract.SAMPLE)
    probe('alias_application_bearer', ALIAS, app, contract.SAMPLE)
    probe('invalid_minutes_application_bearer', CANONICAL, app, {**contract.SAMPLE, 'total_minutes': 44})
    collision = False
    if platform_token is not None:
        platform = {platform_header: ('' if platform_prefix == 'raw' else 'Bearer ') + platform_token}
        probe('health_platform_credential', '/health', platform)
        probe('draft_platform_credential_only', CANONICAL, platform, contract.SAMPLE)
        collision = platform_header.lower() == 'authorization' and platform_token != app_token
        if platform_header.lower() != 'authorization':
            combined = {**platform, **app}
            probe('health_combined_credentials', '/health', combined)
            probe('draft_combined_credentials', CANONICAL, combined, contract.SAMPLE)
            probe('alias_combined_credentials', ALIAS, combined, contract.SAMPLE)
            probe('invalid_minutes_combined_credentials', CANONICAL, combined, {**contract.SAMPLE, 'total_minutes': 44})
            probe('wrong_application_with_platform', CANONICAL,
                {**platform, 'Authorization': 'Bearer synthetic-deliberately-invalid'}, contract.SAMPLE)
    return {'mode': 'coze_gateway_diagnostic', 'checks': rows,
        'authorization_header_collision': collision,
        'coze_platform_auth_specification': 'not_verified',
        'interpretation': 'HTTP observations only; compare sanitized results with deployment access logs.'}


def main(argv=None):
    parser = RedactedParser(description=__doc__)
    parser.add_argument('--base-url', default=DEFAULT_ORIGIN)
    parser.add_argument('--with-platform-token', action='store_true')
    parser.add_argument('--platform-header', default='Authorization')
    parser.add_argument('--platform-prefix', choices=('Bearer', 'raw'), default='Bearer')
    args = parser.parse_args(argv)
    try:
        send = HTTPSProbe(args.base_url)
        checked_platform_header(args.platform_header)
        if not sys.stdin.isatty():
            raise ValueError('Use an interactive terminal for hidden token input')
        print('Target: ' + send.origin, file=sys.stderr)
        app_token = checked_secret(getpass.getpass('Application COACHLOOP_PRELESSON_TOKEN (hidden): '))
        platform_token = None
        if args.with_platform_token:
            platform_token = checked_secret(getpass.getpass('Platform credential from official call example (hidden): '))
        report = diagnose(send, app_token, platform_token, args.platform_header, args.platform_prefix)
    except (Exception, KeyboardInterrupt):
        print('Diagnostic could not start; raw arguments, exceptions and secrets omitted.', file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Diagnostic observations never mean deployment/plugin acceptance passed.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
