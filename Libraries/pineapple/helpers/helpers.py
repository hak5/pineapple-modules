import json


def json_to_bytes(message) -> bytes:
    """
    json deserialize a message and then decode it.
    Use this to convert your json message to bytes before publishing it over the socket.
    :param message: A json serializable list or a dict.
    :return: bytes
    """
    if not (type(message) is list or type(message) is dict):
        raise TypeError(f'Expected a list or dict but got {type(message)} instead.')

    d = json.dumps(message)

    return d.encode('utf-8')
