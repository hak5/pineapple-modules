from pineapple.logger.pretty_formatter import PrettyFormatter

from logging.handlers import RotatingFileHandler
from logging import Logger
import logging


def get_logger(name: str, level: int, log_to_file: bool = True, console_logger_level: int = logging.DEBUG) -> Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    if log_to_file:
        log_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)")
        file_handler = RotatingFileHandler(f'/tmp/modules/{name}.log', maxBytes=1024*1024)
        file_handler.setFormatter(log_format)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    if level <= console_logger_level:
        console_logger = logging.StreamHandler()
        console_logger.setFormatter(PrettyFormatter())
        logger.addHandler(console_logger)

    return logger
