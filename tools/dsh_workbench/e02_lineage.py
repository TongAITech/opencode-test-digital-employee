"""Fail-closed joins across canonical objects of one authorized Mission."""
from .business_store import BusinessError

def validate_lineage(records,mission,batch):
    def require(ok):
        if not ok:raise BusinessError(503,'R1_LINEAGE_UNRESOLVED')
    def index(kind,key):
        rows=records[kind];result={row[key]:row for row in rows}
        require(len(result)==len(rows))
        for row in rows:require(row.get('mission_id')==mission['mission_id'] and row.get('release_id')==mission['release_id'])
        return result
    nodes=index('rc72_mission_node','mission_node_id');deliveries=index('rc72_node_delivery','delivery_id');gates=index('rc72_node_gate','gate_id')
    tasks=index('rc7_task','task_id');etus=index('rc72_etu','etu_id');bindings=index('rc72_workitem_attempt_binding','binding_id')
    attempts=index('execution_attempt','attempt_id');obligations=index('rc72_test_obligation','obligation_id')
    edges=index('rc72_back_edge','back_edge_id');transitions=index('rc72_node_transition','transition_id')
    for obligation in obligations.values():
        require(obligation.get('release_batch_id') == batch)
    def node_for(row):
        node=nodes.get(row.get('mission_node_id'));require(node is not None and node['node_type']==row.get('node_type'));return node
    for delivery in deliveries.values():
        node_for(delivery)
        for task in delivery.get('created_by_workitems',[]):require(task in tasks)
    for gate in gates.values():
        node_for(gate);delivery=deliveries.get(gate['delivery_id'])
        require(delivery is not None and delivery['mission_node_id']==gate['mission_node_id'] and delivery['node_type']==gate['node_type'])
    for node in nodes.values():
        for key,lookup in (('delivery_refs',deliveries),('gate_refs',gates)):
            for ref in node.get(key,[]):require(ref in lookup and lookup[ref]['mission_node_id']==node['mission_node_id'])
        if node.get('active_delivery_version') is not None:require(any(d['mission_node_id']==node['mission_node_id'] and d['version']==node['active_delivery_version'] for d in deliveries.values()))
    for edge in edges.values():
        delivery=deliveries.get(edge['from_delivery_id']);require(delivery is not None and delivery['node_type']==edge['from_node'])
        if edge.get('resolved_by_delivery_id'):require(edge['resolved_by_delivery_id'] in deliveries and deliveries[edge['resolved_by_delivery_id']]['node_type']==edge['return_node'])
    for transition in transitions.values():
        for prefix in ('from','to'):require(transition[prefix+'_mission_node_id'] in nodes and nodes[transition[prefix+'_mission_node_id']]['node_type']==transition[prefix+'_node_type'])
        if transition.get('source_gate_id'):require(transition['source_gate_id'] in gates and gates[transition['source_gate_id']]['mission_node_id']==transition['from_mission_node_id'])
        if transition.get('back_edge_id'):require(transition['back_edge_id'] in edges)
    for etu in etus.values():
        require(etu.get('release_batch_id')==batch and etu['obligation_id'] in obligations)
        for ref in etu.get('child_etu_ids',[]):require(ref in etus)
        if etu.get('parent_etu_id'):require(etu['parent_etu_id'] in etus)
    for binding in bindings.values():
        etu=etus.get(binding['etu_id']);require(etu is not None and binding['workitem_id'] in tasks and binding['case_id'] in etu['case_ids'])
        attempt=attempts.get(binding['attempt_id'])
        if attempt is not None:require(attempt.get('tc_id',attempt.get('case_id'))==binding['case_id'])
        else:require(binding['state']=='RESERVED')
        if binding.get('mission_node_id'):require(binding['mission_node_id'] in nodes and nodes[binding['mission_node_id']]['node_type']==binding.get('mission_node_type'))
        if binding.get('parent_attempt_id'):require(binding['parent_attempt_id'] in attempts)
