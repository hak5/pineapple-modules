import subprocess
from typing import List


def grep_output(command: str, grep_text: str, grep_options: List[str] = None) -> bytes:
    """
    Run a command and pipe it to grep for some output.
    The output is returned.

    For example this command:
        ps -aux | grep pineap
    Looks like this:
        grep_output('ps -aux', 'pineap')

    :param command: The initial command to run.
    :param grep_text: The text to grep for
    :param grep_options: Any options to be passed to grep.
    :return: The output as bytes.
    """
    cmd = command.split(' ')

    grep_options = grep_options if grep_options else []
    grep = ['grep'] + grep_options
    grep.append(grep_text)

    ps = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    return subprocess.run(grep, stdin=ps.stdout, capture_output=True).stdout


def check_for_process(process_name) -> bool:
    """
    Check if a process is running by its name.
    :param process_name: The name of the process to look for
    :return: True if the process is running, False if it is not.
    """
    return subprocess.run(['pgrep', '-l', process_name], capture_output=True).stdout != b''
