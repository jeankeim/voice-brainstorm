"""
结构化日志模块
提供统一的日志格式和级别管理
"""
import logging
import json
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

# 设置东八区时区（北京时间）
try:
    from zoneinfo import ZoneInfo
    TZ_BEIJING = ZoneInfo("Asia/Shanghai")
except ImportError:
    try:
        import pytz
        TZ_BEIJING = pytz.timezone("Asia/Shanghai")
    except ImportError:
        TZ_BEIJING = None

def get_beijing_time():
    """获取北京时间"""
    if TZ_BEIJING:
        return datetime.now(TZ_BEIJING)
    else:
        return datetime.utcnow() + timedelta(hours=8)

# 日志级别
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL


class StructuredFormatter(logging.Formatter):
    """结构化日志格式器，输出 JSON 格式"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": get_beijing_time().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # 添加额外字段
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        
        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)


class SimpleFormatter(logging.Formatter):
    """简单日志格式器，适合开发环境"""
    
    def format(self, record: logging.LogRecord) -> str:
        timestamp = get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")
        return f"[{timestamp}] [{record.levelname}] {record.getMessage()}"


def setup_logger(
    name: str = "voice-brainstorm",
    level: int = INFO,
    structured: bool = False
) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志器名称
        level: 日志级别
        structured: 是否使用 JSON 结构化格式
    
    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 清除已有处理器
    logger.handlers.clear()
    
    # 创建控制台处理器
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    
    # 设置格式
    if structured:
        formatter = StructuredFormatter()
    else:
        formatter = SimpleFormatter()
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    return logger


# 默认日志器
_default_logger: Optional[logging.Logger] = None


def get_logger() -> logging.Logger:
    """获取默认日志器"""
    global _default_logger
    if _default_logger is None:
        _default_logger = setup_logger()
    return _default_logger


def log_info(message: str, **kwargs):
    """记录 INFO 级别日志"""
    logger = get_logger()
    if kwargs:
        record = logger.makeRecord(
            logger.name, INFO, "", 0, message, (), None
        )
        record.extra = kwargs
        logger.handle(record)
    else:
        logger.info(message)


def log_debug(message: str, **kwargs):
    """记录 DEBUG 级别日志"""
    logger = get_logger()
    if kwargs:
        record = logger.makeRecord(
            logger.name, DEBUG, "", 0, message, (), None
        )
        record.extra = kwargs
        logger.handle(record)
    else:
        logger.debug(message)


def log_warning(message: str, **kwargs):
    """记录 WARNING 级别日志"""
    logger = get_logger()
    if kwargs:
        record = logger.makeRecord(
            logger.name, WARNING, "", 0, message, (), None
        )
        record.extra = kwargs
        logger.handle(record)
    else:
        logger.warning(message)


def log_error(message: str, exc_info: bool = False, **kwargs):
    """记录 ERROR 级别日志"""
    logger = get_logger()
    if kwargs or exc_info:
        record = logger.makeRecord(
            logger.name, ERROR, "", 0, message, (), None
        )
        if kwargs:
            record.extra = kwargs
        record.exc_info = sys.exc_info() if exc_info else None
        logger.handle(record)
    else:
        logger.error(message)


# 便捷函数：API 请求日志
def log_api_request(endpoint: str, method: str = "POST", **kwargs):
    """记录 API 请求日志"""
    log_info(f"API Request: {method} {endpoint}", type="api_request", endpoint=endpoint, method=method, **kwargs)


def log_api_response(endpoint: str, status: str, duration_ms: Optional[float] = None, **kwargs):
    """记录 API 响应日志"""
    log_info(
        f"API Response: {endpoint} - {status}",
        type="api_response",
        endpoint=endpoint,
        status=status,
        duration_ms=duration_ms,
        **kwargs
    )


# 便捷函数：数据库操作日志
def log_db_operation(operation: str, table: str, **kwargs):
    """记录数据库操作日志"""
    log_debug(f"DB Operation: {operation} on {table}", type="db_operation", operation=operation, table=table, **kwargs)


# 便捷函数：RAG 检索日志
def log_rag_search(query: str, kb_ids: list, results_count: int, **kwargs):
    """记录 RAG 检索日志"""
    log_info(
        f"RAG Search: '{query[:50]}...' - {results_count} results",
        type="rag_search",
        query=query[:100],
        kb_ids=kb_ids,
        results_count=results_count,
        **kwargs
    )
