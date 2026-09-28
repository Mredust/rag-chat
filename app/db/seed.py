"""内置数据装载：全新（空）数据库首次启动时导入根目录的 ragchat.sql。

判定「是否首次」依据数据库本身是否为空（探测核心业务表），不引入额外标记：
- 首次启动（空库）→ 导入一次，后续启动因库中已有数据自动跳过；
- 删除数据库后重启 → 会重新导入，与数据库状态天然保持一致；
- 导入在单个事务中执行，中途失败整体回滚，下次启动自动重试。

只执行 dump 中的 INSERT 语句，两个关键处理：

1. **列顺序重排**：dump 按导出时的物理列序写 VALUES（按位置对应），
   而合并后的迁移按模型定义建表，列序可能不同（如 ml_eval_dimension）。
   这里用 dump 自带的 DDL 解析源列序、运行时 SHOW COLUMNS 取目标列序，
   重建为带显式列名的 INSERT，按列名对齐，两种列序都能正确导入。
2. **跳过 alembic_version**：dump 记录的是导出时的版本号，与当前迁移链无关，
   导入会污染 Alembic 状态。DDL（DROP/CREATE）同样不参与，表结构由迁移创建。

使用 pymysql 独立连接执行（而非异步引擎）：dump 文本中含大量字面 ``%``
（法律条文中的百分比），裸 SQL 经 asyncmy 会被当作参数化模板做 ``%`` 替换而报错；
pymysql 在 args=None 时原样执行，无此问题。
"""
from __future__ import annotations

import asyncio
import logging
import re

from app.core.config import BASE_DIR, settings

logger = logging.getLogger(__name__)

SEED_FILE = BASE_DIR / "ragchat.sql"

# 探测表：任一非空即视为「已有数据」，跳过导入
_PROBE_TABLES = ("user", "knowledge_space", "document", "chunk", "ml_dataset")

# 跳过导入的表（alembic 版本由迁移管理）
_SKIP_TABLES = frozenset({"alembic_version"})

_INSERT_RE = re.compile(r"INSERT INTO `([^`]+)` VALUES (.+);$")
_DDL_TABLE_RE = re.compile(r"CREATE TABLE `([^`]+)`\s*\((.*?)\)\s*ENGINE", re.S)
_DDL_COL_RE = re.compile(r"\s*`([^`]+)`\s+")


def _parse_dump_columns(sql_text: str) -> dict[str, list[str]]:
    """从 dump 的 DDL 中解析各表列顺序（与该 dump 的 VALUES 位置一一对应）。"""
    columns: dict[str, list[str]] = {}
    for match in _DDL_TABLE_RE.finditer(sql_text):
        name, body = match.group(1), match.group(2)
        ordered: list[str] = []
        for line in body.splitlines():
            col = _DDL_COL_RE.match(line)
            if col:  # 索引/约束行不以反引号开头，天然被过滤
                ordered.append(col.group(1))
        columns[name] = ordered
    return columns


def _split_value_tuples(values_src: str) -> list[list[str]] | None:
    """把 ``(v1, v2), (v3, v4)`` 解析成字段列表的列表，字段保留 SQL 原文。

    引号内处理：``\\\\`` 转义下一字符、``''`` 为转义的单引号；返回 None 表示解析失败。
    """
    tuples: list[list[str]] = []
    i, n = 0, len(values_src)
    while i < n:
        if values_src[i] != "(":
            i += 1
            continue
        i += 1  # 跳过 '('
        fields: list[str] = []
        buf: list[str] = []
        in_string = False
        closed = False
        while i < n:
            ch = values_src[i]
            if in_string:
                if ch == "\\":  # 反斜杠转义：连同下一字符原样保留
                    buf.append(ch)
                    i += 1
                    if i < n:
                        buf.append(values_src[i])
                        i += 1
                    continue
                if ch == "'":
                    buf.append(ch)
                    i += 1
                    if i < n and values_src[i] == "'":  # '' 转义的单引号
                        buf.append("'")
                        i += 1
                        continue
                    in_string = False
                    continue
                buf.append(ch)
                i += 1
                continue
            if ch == "'":
                in_string = True
                buf.append(ch)
                i += 1
                continue
            if ch == ",":
                fields.append("".join(buf).strip())
                buf = []
                i += 1
                continue
            if ch == ")":
                fields.append("".join(buf).strip())
                buf = []
                i += 1
                closed = True
                break
            buf.append(ch)
            i += 1
        if not closed:
            return None
        tuples.append(fields)
        while i < n and values_src[i] in ", \t\r\n":
            i += 1
    return tuples or None


def _reorder_insert(
    table: str, statement: str, source_cols: list[str], target_cols: list[str]
) -> str | None:
    """按列名把按位置书写的 INSERT 重排为目标列序（带显式列名）。失败返回 None。"""
    matched = _INSERT_RE.match(statement)
    if matched is None:
        return None
    tuples = _split_value_tuples(matched.group(2))
    if not tuples:
        return None

    index = {name: pos for pos, name in enumerate(source_cols)}
    if any(len(row) != len(source_cols) for row in tuples):
        logger.warning("表 %s 存在字段数与 DDL 不符的行，跳过该语句", table)
        return None
    ordered_cols = [c for c in target_cols if c in index]
    if len(ordered_cols) != len(target_cols):
        logger.warning(
            "表 %s 列集合不一致（dump 独有 %s / 迁移独有 %s），仅导入交集列",
            table,
            [c for c in source_cols if c not in target_cols],
            [c for c in target_cols if c not in index],
        )
    rebuilt_rows = [
        "(" + ", ".join(row[index[c]] for c in ordered_cols) + ")" for row in tuples
    ]
    col_list = ", ".join(f"`{c}`" for c in ordered_cols)
    return f"INSERT INTO `{table}` ({col_list}) VALUES {', '.join(rebuilt_rows)};"


def _parse_statements(sql_text: str) -> list[tuple[str, str]]:
    """提取 dump 中的 INSERT 语句，返回 (表名, 语句) 列表。

    Navicat 导出的每条 INSERT 独占一行、以分号结尾（字符串内换行已转义）。
    """
    statements: list[tuple[str, str]] = []
    for line in sql_text.splitlines():
        if not line.startswith("INSERT INTO"):
            continue
        table = line.split("`")[1] if "`" in line else ""
        if not table:
            logger.warning("无法解析的 INSERT 行已跳过: %s", line[:80])
            continue
        if table in _SKIP_TABLES:
            continue
        statements.append((table, line))
    return statements


def _prepare_statements(
    sql_text: str, target_columns: dict[str, list[str]]
) -> list[tuple[str, str]]:
    """解析 INSERT 并在列序不一致时按列名重排。"""
    source_columns = _parse_dump_columns(sql_text)
    prepared: list[tuple[str, str]] = []
    for table, stmt in _parse_statements(sql_text):
        source = source_columns.get(table)
        target = target_columns.get(table)
        if source and target and source != target:
            rebuilt = _reorder_insert(table, stmt, source, target)
            if rebuilt is None:
                logger.warning("表 %s 的语句重排失败，已跳过: %s", table, stmt[:80])
                continue
            prepared.append((table, rebuilt))
        else:
            prepared.append((table, stmt))
    return prepared


def _existing_table(cursor) -> str | None:
    """返回已存在且非空的探测表名；全部为空（或不存在）时返回 None。"""
    cursor.execute("SHOW TABLES")
    present = {row[0] for row in cursor.fetchall()}
    for table in _PROBE_TABLES:
        if table not in present:
            continue
        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
        if cursor.fetchone()[0]:
            return table
    return None


def _seed_sync() -> int:
    """同步执行探测与导入（供 asyncio.to_thread 调用）。返回导入语句数（0 = 未导入）。"""
    import pymysql

    if not SEED_FILE.is_file():
        logger.info("未发现内置数据文件 %s，跳过内置数据导入", SEED_FILE)
        return 0

    sql_text = SEED_FILE.read_text(encoding="utf-8")
    statements = _parse_statements(sql_text)
    if not statements:
        logger.warning("内置数据文件 %s 未解析到 INSERT 语句", SEED_FILE)
        return 0

    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DB,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        with conn.cursor() as cursor:
            existing = _existing_table(cursor)
            if existing:
                logger.info(
                    "数据库已有数据（%s 表非空），跳过内置数据导入", existing
                )
                return 0

            # 取目标列序（供按列名重排），只查有语句的表
            target_columns: dict[str, list[str]] = {}
            cursor.execute("SHOW TABLES")
            present = {row[0] for row in cursor.fetchall()}
            for table in {t for t, _ in statements} & present:
                cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                target_columns[table] = [row[0] for row in cursor.fetchall()]
            statements = _prepare_statements(sql_text, target_columns)
            if not statements:
                logger.warning("内置数据文件 %s 没有可导入的语句", SEED_FILE)
                return 0

            # dump 未按外键依赖排序（如 chunk 先于 document），导入期间关闭外键检查
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            try:
                for _table, stmt in statements:
                    cursor.execute(stmt)
            finally:
                try:
                    cursor.execute("SET FOREIGN_KEY_CHECKS=1")
                except Exception:  # noqa: BLE001 - 连接异常时会话随连接销毁，无需恢复
                    pass
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    tables = len({table for table, _ in statements})
    logger.info(
        "首次启动：已导入内置数据 %s（%d 条 INSERT / %d 张表）",
        SEED_FILE.name,
        len(statements),
        tables,
    )
    return len(statements)


async def load_builtin_data() -> int:
    """空库时导入内置数据；已有数据或文件缺失时跳过（阻塞操作放线程池执行）。"""
    return await asyncio.to_thread(_seed_sync)
