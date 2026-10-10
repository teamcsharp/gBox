import copy

from gbox.hermes_capabilities import audit, task_profile


def test_opt_in_removes_both_filters_and_preserves_accounts_and_worker_assignment():
    original = {'approvals': {'mode': 'manual', 'cron_mode': 'deny'},
                'model': {'provider': 'zai', 'default': 'glm-5.3'},
                'mcp_servers': {'gbox': {'command': '/python', 'args': ['-P', '-m', 'gbox'],
                    'env': {'GBOX_OPERATOR_WORKER': 'i9-NUC', 'GBOX_TEST_WORKER': 'JAYBUILTFINALE'},
                    'tools': {'include': [], 'exclude': ['job_*'], 'resources': False}},
                    'other': {'tools': {'include': ['specific']}}},
                'security': {'redact_secrets': True},
                'platform_toolsets': {'cli': ['memory', 'messaging'], 'cron': ['terminal']}}
    baseline = copy.deepcopy(original)
    result = task_profile(original)
    assert original == baseline
    assert result['mcp_servers']['gbox']['tools'] == {'resources': False}
    assert result['mcp_servers']['gbox']['env'] == original['mcp_servers']['gbox']['env']
    assert result['mcp_servers']['other'] == original['mcp_servers']['other']
    assert result['model'] == original['model']
    assert result['approvals']['mode'] == 'manual'
    assert result['security']['redact_secrets'] is True
    assert 'memory' in result['platform_toolsets']['cron']
    assert 'messaging' not in result['platform_toolsets']['cron']
    assert audit(result)['ready']
    assert task_profile(result) == result


def test_audit_reports_empty_include_and_disabled_execution_without_exposing_credentials():
    config = task_profile({'mcp_servers': {'gbox': {'command': '/python', 'env': {'SECRET': 'private-key'}}},
                           'model': {'api_key': 'private-key'}})
    config['mcp_servers']['gbox']['tools']['include'] = []
    config['agent'] = {'disabled_toolsets': ['code_execution']}
    result = audit(config)
    assert not result['ready'] and not result['full_gbox_catalog']
    assert 'gbox MCP tool filter' in result['missing']
    assert 'disabled toolset: code_execution' in result['missing']
    assert 'private-key' not in str(result)
