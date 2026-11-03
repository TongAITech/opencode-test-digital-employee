"""Fail-closed source-level guards for RC7.2 product dispatch (Python 3.8+).

Static guards are necessary contract checks only. They cannot establish that
an R1 operation actually ran, a real business failure was repaired, or C03
and C09 have passed in-bank Field qualification.
"""
import ast


def _n8_condition(node):
    """A branch must explicitly compare the active node type to native N8."""
    for item in ast.walk(node):
        if not isinstance(item, ast.Compare):
            continue
        if not any(isinstance(value, ast.Constant) and value.value == "N8_DIAGNOSIS_RECOVERY"
                   for value in list(item.comparators) + [item.left]):
            continue
        other = (item.left if not (isinstance(item.left, ast.Constant)
                 and item.left.value == "N8_DIAGNOSIS_RECOVERY")
                 else item.comparators[0])
        if (isinstance(other, ast.Name) and other.id in {"node_type", "current_node_type"}
                or isinstance(other, ast.Subscript)
                and isinstance(other.slice, ast.Constant)
                and other.slice.value == "node_type"):
            return True
    return False


def _owned_n8_call(statement):
    for child in ast.walk(statement):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if (isinstance(target, ast.Attribute) and target.attr in {"complete", "run", "resume", "reconcile"}
                and isinstance(target.value, ast.Attribute)
                and target.value.attr == "n8_pipeline"
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "self"):
            return True
    return False


def has_real_n8_branch(function_source):
    """Reject unrelated method calls, bypass-only and foreign mock routes."""
    if not isinstance(function_source, str):
        return False
    try:
        tree = ast.parse(function_source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _n8_condition(node.test):
            continue
        if any(_owned_n8_call(stmt) for stmt in node.body):
            return True
    return False
