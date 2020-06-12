from pineapple.logger.pretty_formatter import PrettyFormatter

import logging


def get_logger(name: str, level: int) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(PrettyFormatter())
    logger.addHandler(ch)

    return logger
