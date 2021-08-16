import subprocess


def uci_get(property_name) -> str:
    """
    Get the value of a specified UCI property.
    :param property_name: The UCI property to look up.
    :return: The property value if found, empty string if not found.
    """
    return subprocess.run(['uci', 'get', property_name], capture_output=True, check=True).stdout


def uci_set(property_name, value) -> bool:
    """
    Set the value of a specified UCI property to a value.
    :param property_name: The UCI property to set.
    :param value: The value to set the property to
    :return: True if successful, false if not.
    """
    uci_string = property_name + '=' + value
    return subprocess.run(['uci', 'set', uci_string], check=True).returncode == 0
