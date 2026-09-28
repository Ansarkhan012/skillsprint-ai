"""Offline router contract: all HTTP uses MockTransport, never a live model alias."""
import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app import generation_api
from app.generation_prompt import build_prompt, FORMAT_RETRY_RULE, PROMPT_VERSION, template_hash
from app.generation_provider import GeminiProvider, GroqProvider, JSON_SCHEMA_RESPONSE_FORMAT, ProviderFailure
from app.generation_service import generate_unverified
from app.nararouter_provider import (NaraRouterConfig, NaraRouterEnvironment, NaraRouterProvider,
                                    nararouter_request_payload, OUTPUT_INSTRUCTIONS)
from test_generation_context import ready, EMP
from test_generation_service import REQUEST, complete_output

SECRET = 'offline-test-credential'
MODEL = 'test-only/alias'
BASE = 'https://router.bynara.id/v1'


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER', 'nararouter')
    for name, value in {'API_KEY': SECRET, 'MODEL': MODEL, 'BASE_URL': BASE,
                        'TIMEOUT_SECONDS': '30', 'MAX_OUTPUT_TOKENS': '8192', 'TEMPERATURE': '0.1'}.items():
        monkeypatch.setenv('NARAROUTER_' + name, value)


def config(**updates):
    return NaraRouterConfig(**{'provider': 'nararouter', 'model': MODEL, 'api_key': SECRET,
                              'base_url': BASE, **updates})


def response_body(content=None, **updates):
    return {'choices': [{'finish_reason': 'stop', 'message': {
        'content': json.dumps(complete_output()) if content is None else content}}],
        'model': 'test-only/resolved', **updates}


def execute(handler, prompt=None, retry=False):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await NaraRouterProvider(client, config()).generate(
                prompt or build_prompt(ready().snapshot, REQUEST), format_retry=retry)
    return asyncio.run(run())


def test_factory_selects_only_nararouter():
    client = object()
    provider, selected = generation_api.get_provider_bundle(SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(supabase_http=client))))
    assert isinstance(provider, NaraRouterProvider) and provider.client is client
    assert selected.provider == 'nararouter' and selected.model == MODEL
    assert SECRET not in repr(selected) and SECRET not in selected.model_dump_json()


@pytest.mark.parametrize('name', ['API_KEY', 'MODEL', 'BASE_URL'])
def test_missing_configuration_fails_without_fallback(monkeypatch, name):
    monkeypatch.setenv('NARAROUTER_' + name, '')
    with pytest.raises(ProviderFailure, match='PROVIDER_CONFIGURATION_FAILED'):
        NaraRouterEnvironment(_env_file=None).adapter_config()
    with pytest.raises(HTTPException) as error:
        generation_api.get_provider_bundle(SimpleNamespace())
    assert error.value.status_code == 503
    assert error.value.detail == 'GENERATION_PROVIDER_NOT_CONFIGURED'
    assert SECRET not in str(error.value)


@pytest.mark.parametrize('name,value', [
    ('API_KEY', ' '), ('API_KEY', 'key\r\nInjected: value'),
    ('MODEL', 'bad alias'), ('MODEL', 'x'*101), ('MODEL', 'alias\n'),
    ('TIMEOUT_SECONDS', 'not-a-number'), ('TIMEOUT_SECONDS', '61'),
    ('MAX_OUTPUT_TOKENS', '0'), ('TEMPERATURE', '2'),
    ('BASE_URL', 'http://router.bynara.id/v1'), ('BASE_URL', 'https://user:password@router.bynara.id/v1'),
    ('BASE_URL', 'https://router.bynara.id/v1?key=hidden'), ('BASE_URL', 'https://router.bynara.id/v1#fragment'),
    ('BASE_URL', 'not-a-url'),
])
def test_invalid_configuration_is_safely_classified(monkeypatch, name, value):
    monkeypatch.setenv('NARAROUTER_' + name, value)
    with pytest.raises(HTTPException) as error:
        generation_api.get_provider_bundle(SimpleNamespace())
    assert (error.value.status_code, error.value.detail) == (503, 'GENERATION_PROVIDER_NOT_CONFIGURED')


@pytest.mark.parametrize('retry', [False, True])
def test_request_preserves_v2_and_response_metadata(caplog, retry):
    caplog.set_level(logging.DEBUG)
    prompt = build_prompt(ready().snapshot, REQUEST)
    def handler(request):
        assert str(request.url) == BASE + '/chat/completions'
        assert request.headers['Authorization'] == 'Bearer ' + SECRET
        body = json.loads(request.content)
        assert body == {**nararouter_request_payload(prompt, config(), format_retry=retry),
                        'response_format': JSON_SCHEMA_RESPONSE_FORMAT}
        assert body['messages'] == [
            {'role': 'system', 'content': prompt.system + '\n' + prompt.rules + '\n' + OUTPUT_INSTRUCTIONS + ('\n'+FORMAT_RETRY_RULE if retry else '')},
            {'role': 'user', 'content': prompt.untrusted_data}]
        assert body['model'] == MODEL and body['max_tokens'] == 8192
        assert body['stream'] is False
        assert SECRET.encode() not in request.content
        assert prompt.prompt_version == 'phase4d-compact-context/2.0.0'
        return httpx.Response(200, json=response_body(usage={
            'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140,
            'unsafe_extra': SECRET}))
    result = execute(handler, prompt, retry)
    assert result.model == 'test-only/resolved' and result.finish_reason == 'STOP'
    assert result.usage.model_dump() == {'prompt_tokens': 100, 'completion_tokens': 40, 'total_tokens': 140}
    assert result.latency_ms >= 0
    assert SECRET not in result.model_dump_json() and SECRET not in caplog.text


def test_trailing_slash_and_invalid_provider():
    assert config(base_url=BASE+'/').base_url == BASE
    with pytest.raises(ProviderFailure, match='PROVIDER_CONFIGURATION_FAILED'):
        NaraRouterProvider(object(), config(provider='groq'))


@pytest.mark.parametrize('metadata', [None, 'unsafe', {}, {'prompt_tokens': True},
    {'prompt_tokens': -1, 'total_tokens': 1_000_000_001}, {'completion_tokens': '42'},
    {'prompt_tokens': 1.5}, {'secret': SECRET}])
def test_malformed_usage_is_ignored(metadata):
    result = execute(lambda _: httpx.Response(200, json=response_body(usage=metadata)))
    assert result.usage is None


def test_usage_partial_values_are_not_inferred():
    result = execute(lambda _: httpx.Response(200, json=response_body(usage={
        'prompt_tokens': 0, 'completion_tokens': 'secret', 'total_tokens': 9})))
    assert result.usage.model_dump(exclude_none=True) == {'prompt_tokens': 0, 'total_tokens': 9}


@pytest.mark.parametrize('model', [None, {}, '', 'x'*101, 'model\ncommand', SECRET])
def test_returned_model_is_bounded_optional_metadata(model):
    result = execute(lambda _: httpx.Response(200, json=response_body(model=model)))
    assert result.model is None


@pytest.mark.parametrize('retry', [False, True])
@pytest.mark.parametrize('kind', ['serialized', 'projection'])
def test_size_guard_never_calls_http(retry, kind):
    prompt = build_prompt(ready().snapshot, REQUEST).model_copy(update=(
        {'untrusted_data': '"漢'*9000} if kind == 'serialized' else {'within_budget': False}))
    def forbidden(_):
        pytest.fail('Oversized context reached HTTP transport')
    with pytest.raises(ProviderFailure, match='GENERATION_PROJECTION_TOO_LARGE'):
        execute(forbidden, prompt, retry)


@pytest.mark.parametrize('status,code,retryable', [
    (401, 'PROVIDER_AUTH_FAILED', False), (402, 'PROVIDER_PAYMENT_REQUIRED', False),
    (403, 'PROVIDER_ACCESS_DENIED', False),
    (400, 'PROVIDER_REQUEST_FAILED', False), (404, 'PROVIDER_REQUEST_FAILED', False),
    (405, 'PROVIDER_REQUEST_FAILED', False),
    (408, 'PROVIDER_TIMEOUT', True),
    (413, 'GENERATION_PROJECTION_TOO_LARGE', False), (429, 'PROVIDER_RATE_LIMIT', True),
    (422, 'PROVIDER_REQUEST_FAILED', False),
    (500, 'PROVIDER_UNAVAILABLE', True), (503, 'PROVIDER_UNAVAILABLE', True),
])
def test_safe_http_error_mapping(status, code, retryable, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ProviderFailure) as error:
        execute(lambda _: httpx.Response(status, json={'error': {
            'message': 'telegram_required: bind account ' + SECRET}}))
    assert error.value.code == code and error.value.retryable is retryable
    assert SECRET not in str(error.value) and SECRET not in caplog.text
    assert 'telegram_required' not in str(error.value)


@pytest.mark.parametrize('status,code,hint', [
    (400, 'invalid_request_error', 'response_format'),
    (422, 'unsupported_parameter', 'max_tokens'),
    (403, 'forbidden', 'none'),
])
def test_upstream_diagnostics_log_only_allowlisted_metadata(status, code, hint, caplog):
    caplog.set_level(logging.WARNING)
    with pytest.raises(ProviderFailure):
        execute(lambda _: httpx.Response(status, json={'error': {
            'type': code, 'message': ('unsupported response_format' if hint == 'response_format'
                                      else 'invalid max_tokens' if hint == 'max_tokens'
                                      else 'access denied') + ' ' + SECRET}}))
    assert f'upstream_status={status}' in caplog.text
    assert f'upstream_code={code}' in caplog.text
    assert f'upstream_hint={hint}' in caplog.text
    assert SECRET not in caplog.text
    assert 'access denied' not in caplog.text


def test_unrecognized_upstream_error_never_logs_raw_code_or_message(caplog):
    caplog.set_level(logging.WARNING)
    with pytest.raises(ProviderFailure, match='PROVIDER_REQUEST_FAILED'):
        execute(lambda _: httpx.Response(400, json={'error': {
            'code': 'secret_' + SECRET, 'message': 'private prompt ' + SECRET}}))
    assert 'upstream_status=400 upstream_code=unknown upstream_hint=none' in caplog.text
    assert SECRET not in caplog.text and 'private prompt' not in caplog.text


@pytest.mark.parametrize('header,expected', [('1', 1.0), ('2', 2.0), ('0', 0.0), ('90', None), ('bad', None)])
def test_rate_limit_is_retryable_with_bounded_hint(header, expected):
    with pytest.raises(ProviderFailure) as error:
        execute(lambda _: httpx.Response(429, headers={'Retry-After': header}))
    assert error.value.retry_after_seconds == expected
    assert error.value.retryable is True


@pytest.mark.parametrize('kind,code', [('timeout', 'PROVIDER_TIMEOUT'), ('network', 'PROVIDER_UNAVAILABLE')])
def test_transport_errors_do_not_expose_exception_details(kind, code):
    def handler(request):
        cls = httpx.ReadTimeout if kind == 'timeout' else httpx.ConnectError
        raise cls(SECRET, request=request)
    with pytest.raises(ProviderFailure) as error:
        execute(handler)
    assert error.value.code == code and error.value.retryable
    assert SECRET not in str(error.value)


@pytest.mark.parametrize('body', [None, [], {}, {'choices': []}, {'choices': [None]},
    {'choices': [{}, {}]}, {'choices': [{'finish_reason': 'stop', 'message': {}}]},
    response_body(content=''), response_body(content='  '), response_body(content=[]),
])
def test_malformed_or_empty_response_is_rejected(body):
    with pytest.raises(ProviderFailure, match='PROVIDER_INVALID_RESPONSE'):
        execute(lambda _: httpx.Response(200, content=json.dumps(body)))


def test_non_json_response_is_rejected():
    with pytest.raises(ProviderFailure, match='PROVIDER_INVALID_RESPONSE'):
        execute(lambda _: httpx.Response(200, text='invalid '+SECRET))


@pytest.mark.parametrize('finish,code', [('length', 'PROVIDER_TRUNCATED'), ('content_filter', 'PROVIDER_RESPONSE_REJECTED')])
def test_non_stop_response_is_never_accepted(finish, code):
    body = response_body()
    body['choices'][0]['finish_reason'] = finish
    with pytest.raises(ProviderFailure, match=code):
        execute(lambda _: httpx.Response(200, json=body))


def test_response_size_is_bounded():
    with pytest.raises(ProviderFailure, match='PROVIDER_RESPONSE_TOO_LARGE'):
        execute(lambda _: httpx.Response(200, content=b'x'*2_000_001))


def test_redirect_does_not_forward_credentials():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(307, headers={'Location': 'https://different.invalid/chat/completions'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            with pytest.raises(ProviderFailure, match='PROVIDER_REQUEST_FAILED'):
                await NaraRouterProvider(client, config()).generate(build_prompt(ready().snapshot))
    asyncio.run(run())
    assert calls == [BASE+'/chat/completions']


@pytest.mark.parametrize('kind,count,status', [
    ('valid', 1, 'UNVERIFIED'), ('401', 1, 'FAILED'), ('403', 1, 'FAILED'),
    ('404', 1, 'FAILED'), ('413', 1, 'FAILED'), ('408', 3, 'FAILED'),
    ('503', 3, 'FAILED'), ('empty', 2, 'FAILED'), ('invalid-plan', 2, 'FAILED'),
    ('429', 3, 'FAILED'),
])
def test_service_retry_budget_and_no_fallback(monkeypatch, kind, count, status):
    async def forbidden(*args, **kwargs):
        pytest.fail('Unexpected fallback to another provider')
    monkeypatch.setattr(GeminiProvider, 'generate', forbidden)
    monkeypatch.setattr(GroqProvider, 'generate', forbidden)
    calls = []
    def handler(request):
        calls.append(request)
        if kind.isdigit():
            return httpx.Response(int(kind), headers={'Retry-After': '1'}, text=SECRET)
        return httpx.Response(200, json=response_body(content=(
            '' if kind == 'empty' else '{}' if kind == 'invalid-plan' else None)))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await generate_unverified(ready(), REQUEST, NaraRouterProvider(client, config()),
                                               sleep=lambda _: asyncio.sleep(0))
            assert result.status == status and result.provider_calls == count
            if kind == '403':
                assert result.error_code == 'PROVIDER_ACCESS_DENIED'
    asyncio.run(run())
    assert len(calls) == count


def test_api_reserves_requested_provider_model_and_unchanged_snapshot():
    from test_generation_api import Store, actor
    from app.generation_context import input_hash
    from app.generation_models import GenerationInputSnapshot
    store = Store()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json=response_body()))) as client:
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(supabase_http=client)))
            result = await generation_api.create_generation(generation_api.GenerationCreate(employee_id=EMP),
                request, idempotency_key='offline-nara-01', principal=actor(), store=store)
            assert result['status'] == 'UNVERIFIED'
    asyncio.run(run())
    reserved = next(payload for name, payload in store.calls if name == 'reserve')
    assert (reserved['p_provider'], reserved['p_model']) == ('nararouter', MODEL)
    assert reserved['p_prompt_version'] == PROMPT_VERSION and reserved['p_template_hash'] == template_hash()
    snapshot = GenerationInputSnapshot.model_validate(reserved['p_input'])
    assert input_hash(snapshot) == reserved['p_input_hash']
    assert snapshot.requirements[0].evidence and 'timing' in reserved['p_input']['requirements'][0]
    assert reserved['p_provider_config']['projection_hash'] == build_prompt(snapshot).projection_hash
    assert SECRET not in json.dumps(reserved)
    assert len(store.attempts) == 1 and store.attempts[0].latency_ms >= 0


def test_migration_changes_only_provider_acceptance():
    root = Path(__file__).resolve().parents[3]/'supabase'/'migrations'
    old = (root/'202609270001_compact_context_v2.sql').read_text()
    new = (root/'202609270002_nararouter_generation_provider.sql').read_text()
    marker = 'create or replace function'
    old_function = old[old.index(marker):]
    normalized = new[new.index(marker):].replace("p_provider not in ('gemini','groq','nararouter')",
        "p_provider not in ('gemini','groq')").replace(
        "     or (p_provider = 'nararouter' and p_model is distinct from 'gemini-3.8-flash-high')\n", '')
    assert normalized == old_function
    assert "check (provider in ('gemini','groq','nararouter'))" in new
    assert "p_provider = 'nararouter' and p_model is distinct from 'gemini-3.8-flash-high'" in new
    assert "p_provider = 'nararouter' and p_model !~" not in new
    assert '\nbegin;' in new and new.rstrip().endswith('commit;')
    assert PROMPT_VERSION in new and template_hash() in new
    assert 'onboarding-plan/1.0.0' in new
    assert 'update public.generation_runs' not in new.lower()
    assert 'generation_runs_compact_v2_projection_check' not in new  # existing constraint survives


@pytest.mark.parametrize('wrapper', ['```json\n%s\n```', 'Here is the plan: %s', '%s\nExplanation', '<think>reasoning</think>%s'])
def test_output_instructions_do_not_relax_strict_json_acceptance(wrapper):
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=response_body(content=wrapper % json.dumps(complete_output())))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await generate_unverified(ready(), REQUEST, NaraRouterProvider(client, config()))
        assert result.status == 'FAILED' and result.error_code == 'MALFORMED_JSON'
        assert result.provider_calls == len(calls) == 2
    asyncio.run(run())


def test_discovered_flash_alias_fits_existing_config_and_sql_contract():
    selected = config(model='gemini-3.8-flash-high')
    assert selected.model == 'gemini-3.8-flash-high'
    prompt = build_prompt(ready().snapshot, REQUEST)
    payload = nararouter_request_payload(prompt, selected)
    assert payload['model'] == selected.model
    assert 'exactly one JSON object' in payload['messages'][0]['content']
    assert prompt.template_hash == '11b1127daf611a0d6739c185f9815570cff9abd29e73bcee7117121daf85abbc'


def test_table_model_check_accepts_only_discovered_nararouter_alias():
    root = Path(__file__).resolve().parents[3]/'supabase'/'migrations'
    original = (root/'202609270002_nararouter_generation_provider.sql').read_text()
    correction = (root/'202609280001_nararouter_model_constraint.sql').read_text()
    assert 'generation_runs_model_check' not in original
    assert "provider = 'gemini' and model ~ '^[A-Za-z0-9_.-]{1,100}$'" in correction
    assert "provider = 'groq' and model = 'openai/gpt-oss-20b'" in correction
    assert "provider = 'nararouter' and model = 'gemini-3.8-flash-high'" in correction
    assert "position('nararouter' in v_model_check) > 0" in correction
    assert correction.count('alter table public.generation_runs') == 2
    assert not any(line.lstrip().lower().startswith(('update ', 'delete ', 'insert ', 'truncate '))
                   for line in correction.splitlines())


def test_free_model_migration_changes_only_the_nararouter_model_allowlist():
    root = Path(__file__).resolve().parents[3]/'supabase'/'migrations'
    previous = (root/'202609270002_nararouter_generation_provider.sql').read_text()
    new = (root/'202609280003_nararouter_free_models.sql').read_text()
    marker = 'create or replace function'
    allow = ("('gemini-3.8-flash-high','agnes-3-flash','agnes-2.5-flash','nemotron-3-ultra-free')")
    old_function = previous[previous.index(marker):previous.index('end $$;', previous.index(marker))]
    new_function = new[new.index(marker):new.index('end $$;', new.index(marker))]
    assert new_function.replace(
        "     or (p_provider = 'nararouter' and p_model not in\n         " + allow + ")",
        "     or (p_provider = 'nararouter' and p_model is distinct from 'gemini-3.8-flash-high')") == old_function
    assert new.count(allow) == 2  # reservation function and table check agree
    assert "provider = 'groq' and model = 'openai/gpt-oss-20b'" in new
    assert PROMPT_VERSION in new and template_hash() in new
    assert new.lstrip().startswith('--') and '\nbegin;' in new and new.rstrip().endswith('commit;')
    top_level = new[:new.index(marker)] + new[new.index('end $$;', new.index(marker)):]
    assert not any(line.lstrip().lower().startswith(('update ', 'delete ', 'insert ', 'truncate '))
                   for line in top_level.splitlines())  # the function body itself inserts runs
