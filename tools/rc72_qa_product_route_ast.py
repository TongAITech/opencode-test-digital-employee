"""Fail-closed source-level guards for RC7.2 product dispatch (Python 3.8+).

Static guards are necessary contract checks only. They cannot establish that
an R1 operation actually ran, a real business failure was repaired, or C03
and C09 have passed in-bank Field qualification.
"""
import ast


def _n8_condition(node):
    """Only equality/conjunction genuinely constrain the active node to N8."""
    if isinstance(node, ast.BoolOp):
        # OR admits non-N8 nodes and is not a sufficient fenced dispatch route.
        return isinstance(node.op, ast.And) and any(_n8_condition(value) for value in node.values)
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False
    if len(node.comparators) != 1:
        return False
    left, right = node.left, node.comparators[0]
    if isinstance(left, ast.Constant) and left.value == "N8_DIAGNOSIS_RECOVERY":
        left, right = right, left
    if not isinstance(right, ast.Constant) or right.value != "N8_DIAGNOSIS_RECOVERY":
        return False
    return (isinstance(left, ast.Name) and left.id in {"node_type", "current_node_type"}
            or isinstance(left, ast.Subscript) and isinstance(left.slice, ast.Constant)
            and left.slice.value == "node_type")


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
