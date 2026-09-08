"""
结构化日志模块

提供带 trace_id 的统一日志接口，替代 print()
"""

import logging
import sys

# 配置日志格式（不依赖 trace_id 字段，避免第三方库日志报错）
LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(message)s"
DATE_FORMAT = "%H:%M:%S"


class TraceLogger:
    """带 trace_id 的日志适配器"""

    def __init__(self, name: str, trace_id: str = ""):
        self.logger = logging.getLogger(name)
        self.trace_id = trace_id

    def _log(self, level: int, msg: str, *args, **kwargs):
        extra = kwargs.pop("extra", {})
        extra["trace_id"] = self.trace_id
        self.logger.log(level, msg, *args, extra=extra, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        kwargs.setdefault("exc_info", True)
        self._log(logging.ERROR, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)


class TraceFilter(logging.Filter):
    """注入 trace_id 到日志记录"""

    def filter(self, record):
        if not hasattr(record, "trace_id"):
            record.trace_id = ""
        return True


def setup_logging(level: int = logging.INFO):
    """初始化日志系统"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    root.addFilter(TraceFilter())


def get_logger(name: str, trace_id: str = "") -> TraceLogger:
    """获取带 trace_id 的日志器"""
    return TraceLogger(name, trace_id)


def log_ocr_call(attachment_id: str, elapsed: float, success: bool):
    """记录OCR调用"""
    logger = get_logger("ocr", attachment_id)
    if success:
        logger.info(f"OCR success, elapsed={elapsed:.2f}s")
    else:
        logger.error(f"OCR failed, elapsed={elapsed:.2f}s")


def log_api_error(method: str, path: str, status: int, error: str):
    """记录API错误"""
    logger = get_logger("api")
    logger.error(f"{method} {path} → {status}: {error}")
