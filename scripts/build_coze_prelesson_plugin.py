"""Build a credential-free OpenAPI 3.0.3 import candidate; never contact a server."""
import argparse
from copy import deepcopy
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PATH = '/api/v1/lesson-plans/draft'
PLACEHOLDER = 'https://configure-your-service.invalid'


def schema30(value, schemas=None):
    """Translate the used JSON Schema vocabulary without flattening API fields."""
    if isinstance(value, list):
        return [schema30(item, schemas) for item in value]
    if not isinstance(value, dict):
        return value
    value = deepcopy(value)
    variants = value.get('anyOf')
    if variants and {'type': 'null'} in variants:
        nonnull = [item for item in variants if item != {'type': 'null'}]
        if len(nonnull) != 1:
            raise ValueError('Unsupported nullable union; review conversion explicitly')
        del value['anyOf']
        branch = nonnull[0]
        if '$ref' in branch:
            branch = deepcopy(schemas[branch['$ref'].rsplit('/', 1)[-1]])
        value.update(branch)
        value['nullable'] = True
    result = {key: schema30(item, schemas) for key, item in value.items()}
    if 'const' in result:
        result['enum'] = [result.pop('const')]
    for exclusive, bound in [('exclusiveMinimum', 'minimum'), ('exclusiveMaximum', 'maximum')]:
        if exclusive in result and type(result[exclusive]) in (int, float):
            result[bound] = result[exclusive]
            result[exclusive] = True
    if result.get('nullable') and 'enum' in result:
        result['enum'].append(None)
    if result.get('type') == 'null':
        raise ValueError('Unsupported standalone null schema')
    return result


def checked_origin(value):
    """Require a bare HTTPS origin; not an assertion of deployment or DNS trust."""
    if any(ord(c) <= 32 or ord(c) >= 127 for c in value) or '\\' in value:
        raise ValueError('Supply a bare HTTPS service origin without credentials')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError('Invalid service origin') from None
    host = parsed.hostname
    if (parsed.scheme != 'https' or not host or parsed.username is not None
            or parsed.password is not None or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment or '?' in value or '#' in value
            or host.endswith(('.invalid', '.localhost', '.test', '.example'))
            or host in ('localhost', 'example.com', 'example.org', 'example.net')
            or host.endswith(('.example.com', '.example.org', '.example.net'))
            or port == 0):
        raise ValueError('Supply your verified HTTPS service origin, without path or credentials')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host or any(not part or not all(c.isalnum() or c == '-' for c in part)
                                  or part.startswith('-') or part.endswith('-') for part in host.split('.')):
            raise ValueError('Invalid public service hostname')
    else:
        if not address.is_global:
            raise ValueError('Service address must be public HTTPS')
    return value.rstrip('/')


def build(origin=PLACEHOLDER):
    source = json.loads((ROOT / 'docs/coze-integration-v01.openapi.json').read_text())
    operation = schema30(deepcopy(source['paths'][PATH]['post']))
    operation.update(operationId='generatePrelessonDraft', summary='生成待教师审核的45分钟七要素教案',
        description='仅零基础冰上双足滑行与身体姿态控制。预计负荷非实测；知识依据未核实；不能批准教案。',
        security=[{'HTTPBearer': []}])
    operation['requestBody']['content']['application/json']['example'] = json.loads(
        (ROOT / 'docs/prelesson-workflow-v01.example-request.json').read_text())
    operation['responses']['200']['content']['application/json']['example'] = json.loads(
        (ROOT / 'docs/prelesson-workflow-v01.example-response.json').read_text())
    return {'openapi': '3.0.3', 'info': {'title': 'CoachLoop-FS 智能备课助手', 'version': '0.1.0',
        'description': 'Coze导入候选，待平台实测。仅生成draft/unverified教案，不认证教师审核。'},
        'servers': [{'url': origin, 'description': '未部署占位地址，导入前必须配置' if origin == PLACEHOLDER
                     else '用户提供地址；本工具未验证部署状态'}],
        'paths': {PATH: {'post': operation}},
        'components': {'schemas': schema30(source['components']['schemas'], source['components']['schemas']),
                       'securitySchemes': {'HTTPBearer': {'type': 'http', 'scheme': 'bearer',
                           'description': '仅通过平台安全认证配置注入；禁止写入工具参数或示例'}}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        origin = checked_origin(args.origin)
    except ValueError as error:
        # argparse type= would echo the supplied URL, potentially including a secret.
        parser.error(str(error))
    args.output.write_text(json.dumps(build(origin), ensure_ascii=False, indent=2) + '\n')
    print('Import candidate written; Coze import and endpoint verification remain manual.')


if __name__ == '__main__':
    main()
