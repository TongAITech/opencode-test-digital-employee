"""Pure frozen HTTP response projection shared with independent review."""
from copy import deepcopy


def map_response(mapping,status,body):
    result={}
    for key,path in mapping.items():
        if path=='$http':
            value={'status':status}
        else:
            value=body
            if path!='$json':
                for token in path[len('$json.'):].split('.'):
                    if isinstance(value,dict) and token in value:
                        value=value[token]
                    elif isinstance(value,list) and token.isdigit() and int(token)<len(value):
                        value=value[int(token)]
                    else:
                        raise ValueError('N7_NATIVE_HTTP_RESPONSE_MAPPING_UNRESOLVED')
        result[key]=deepcopy(value)
    return result

