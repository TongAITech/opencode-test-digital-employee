"""Exact model-facing Code tools, distinct from evidence categories."""
LEGACY_CODE_TOOLS = ('git', 'codegraph')
NATIVE_CODE_TOOLS = ('mcp__pfc_aitest_rc7__git_show_revision',
                     'mcp__pfc_aitest_rc7__git_diff',
                     'mcp__pfc_aitest_rc7__codegraph_mcp_tools',
                     'mcp__pfc_aitest_rc7__codegraph_mcp_call')


def has_codegraph_execution(names):
    # A catalogue/probe proves discovery only, never an executed graph query.
    return ('codegraph' in names or NATIVE_CODE_TOOLS[-1] in names)


def canonical_code_tools(tools, *, allow_legacy=True):
    if not isinstance(tools, (list, tuple)) or any(not isinstance(t,str) for t in tools):
        raise ValueError('CODE_TOOL_BINDING_EXACT_REGISTERED_NAMES_REQUIRED')
    if len(tools)==len(NATIVE_CODE_TOOLS) and set(tools)==set(NATIVE_CODE_TOOLS):
        return NATIVE_CODE_TOOLS
    if allow_legacy and len(tools)==len(LEGACY_CODE_TOOLS) and set(tools)==set(LEGACY_CODE_TOOLS):
        return LEGACY_CODE_TOOLS
    raise ValueError('CODE_TOOL_BINDING_EXACT_REGISTERED_NAMES_REQUIRED')
