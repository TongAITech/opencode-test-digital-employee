"""Author synthetic API expectations before execution; no product compiler used."""
from copy import deepcopy


def api_case_spec(profile):
    journey = profile['api_journey']
    steps = []; expected = []
    for index, action in enumerate(journey['steps']):
        steps.append({'step': index+1, 'step_id': action['step_id'],
                      'action': 'Exercise the approved synthetic HTTP business operation'})
        expected.append({'step': index+1, 'step_id': action['step_id'],
                         'expected': 'Every mandatory frozen business observation succeeds',
                         'api': {'status_code': action['status_code'],
                                 'assertions': deepcopy(action['assertions']),
                                 'cross_channel': deepcopy(action.get('cross_channel', [])),
                                 'extract': deepcopy(action.get('extract', {})),
                                 'idempotency': deepcopy(action.get('idempotency'))}})
    return {'ordered_steps': steps, 'expected_results': expected,
            'oracle': {'api_oracle_version': 1, 'api_variables': deepcopy(journey.get('variables', {}))}}
