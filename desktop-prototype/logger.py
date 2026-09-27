import logging
from pathlib import Path


def setup_logger() -> logging.Logger:
    """Configure one application-wide rotating-style file logger."""
    log_dir = Path(__file__).resolve().parent / "app_logging"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("LicensureExamApp")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.propagate = False
    return logger


logger = setup_logger()
