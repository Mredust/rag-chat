"""文档解析与文本切片。

- 解析：按扩展名选择解析器（PDF / Docx / TXT / Markdown / JSON / JSONL / HTML / XLSX / CSV），
  失败时降级为纯文本读取；针对 Docx 识别标题样式、Markdown 保留标题层级，尽量保留文档结构。
- 切片：基于分隔符的递归字符切分 + 重叠，参数可配置
  （chunk_size / chunk_overlap / separators / min_chunk_size / overlap_mode）。
- 策略匹配：`resolve_strategy` 为「文件类型 + 文本长度区间」绑定最优切分配置。
"""
from __future__ import annotations

import csv
import logging
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# 递归切分使用的默认分隔符，优先级从高到低
DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " ", ""]


def parse_text(file_type: str, file_path: str) -> str:
    """按文件类型解析出纯文本内容。

    支持的 file_type：pdf / docx / txt / md / json / jsonl / html / xlsx / csv。
    """
    ft = (file_type or "").lower().lstrip(".")
    path = Path(file_path)

    if ft == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("缺少 pypdf 依赖，无法解析 PDF") from exc
        reader = PdfReader(str(path))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        logger.info("PDF 解析成功: %d 页, 提取 %d 字符", len(reader.pages), len(text))
        return text

    if ft == "docx":
        try:
            import docx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("缺少 python-docx 依赖，无法解析 Docx") from exc
        document = docx.Document(str(path))
        return _docx_to_text(document)

    if ft in {"json", "jsonl"}:
        # JSON / JSONL 按 UTF-8 文本读取，JSONL 逐行保留结构
        text = path.read_text(encoding="utf-8", errors="ignore")
        logger.debug("JSON/JSONL 解析完成: type=%s, %d 字符", ft, len(text))
        return text

    if ft == "html":
        raw = path.read_text(encoding="utf-8", errors="ignore")
        text = _html_to_text(raw)
        logger.debug("HTML 解析完成: %d 字符", len(text))
        return text

    if ft == "xlsx":
        text = _xlsx_to_text(path)
        logger.debug("XLSX 解析完成: %d 字符", len(text))
        return text

    if ft == "csv":
        text = _csv_to_text(path)
        logger.debug("CSV 解析完成: %d 字符", len(text))
        return text

    # txt / md / 其它：按文本读取（Markdown 保留原文标题标记）
    text = path.read_text(encoding="utf-8", errors="ignore")
    logger.debug("文本解析完成: type=%s, %d 字符", ft, len(text))
    return text


def _docx_to_text(document) -> str:
    """按段落读取 Docx，将 Heading 样式转为 Markdown 标题标记以保留层级结构。"""
    lines: list[str] = []
    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            lines.append("")
            continue
        style = ""
        try:
            style = (para.style.name or "") if para.style is not None else ""
        except Exception:  # noqa: BLE001 - 样式读取失败则按正文处理
            style = ""
        if style.startswith("Heading 1"):
            lines.append("\n# " + text)
        elif style.startswith("Heading 2"):
            lines.append("\n## " + text)
        elif style.startswith("Heading"):
            lines.append("\n### " + text)
        else:
            lines.append(text)
    return "\n".join(lines)


_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}


class _HtmlTextExtractor(HTMLParser):
    """抽取 HTML 纯文本：去除脚本/样式，块级标签转换为换行。"""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: ARG002 - 统一接口
        if tag in {"script", "style"}:
            self._skip_depth += 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def _html_to_text(raw: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(raw)
    lines = [line.strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def _csv_to_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        rows = ["\t".join(row) for row in reader]
    return "\n".join(rows)


_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx_to_text(path: Path) -> str:
    """纯标准库解析 XLSX：读取共享字符串与首个工作表，单元格以制表符、行以换行拼接。"""

    def _tag(name: str) -> str:
        return f"{{{_SPREADSHEET_NS}}}{name}"

    with zipfile.ZipFile(str(path)) as z:
        names = z.namelist()

        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.iter(_tag("si")):
                shared.append("".join(t.text or "" for t in si.iter(_tag("t"))))

        sheet_name = ""
        for name in names:
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                sheet_name = name
                break
        if not sheet_name:
            return ""

        root = ET.fromstring(z.read(sheet_name))
        rows: list[str] = []
        for row in root.iter(_tag("row")):
            cells: list[str] = []
            for c in row.iter(_tag("c")):
                cell_type = c.get("t")
                value_el = c.find(_tag("v"))
                if value_el is not None and value_el.text is not None:
                    value = value_el.text
                    if cell_type == "s" and value.isdigit() and int(value) < len(shared):
                        value = shared[int(value)]
                else:
                    inline = c.find(_tag("is"))
                    if inline is None:
                        continue
                    value = "".join(t.text or "" for t in inline.iter(_tag("t")))
                cells.append(value)
            if cells:
                rows.append("\t".join(cells))
        return "\n".join(rows)


def split_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    separators: list[str] | None = None,
    min_chunk_size: int = 1,
    overlap_mode: str = "fixed",
) -> list[str]:
    """递归字符切分 + 重叠切片，返回按顺序排列的文本片段列表。

    - separators：自定义分隔符（优先级从高到低），None 使用默认分隔符；
    - min_chunk_size：过小的片段会与其后续片段合并（避免碎片化）；
    - overlap_mode：`fixed` 表示 chunk_overlap 为固定字符数，
      `ratio` 表示 chunk_overlap 为 chunk_size 的百分比（如 15 表示 15%）。
    """
    text = (text or "").strip()
    if not text:
        return []
    if chunk_size <= 0:
        chunk_size = 512
    if chunk_overlap < 0:
        chunk_overlap = 0

    seps = list(separators) if separators else list(DEFAULT_SEPARATORS)

    # 重叠方式：ratio 下将 chunk_overlap 解释为百分比
    overlap = chunk_overlap
    if overlap_mode == "ratio":
        overlap = int(chunk_size * chunk_overlap / 100.0)

    final: list[str] = []

    def _recursive(piece: str, remaining: list[str]) -> None:
        if len(piece) <= chunk_size:
            if piece:
                final.append(piece)
            return
        sep = remaining[0] if remaining else ""
        rest = list(remaining[1:]) if remaining else []
        if not sep:
            # 分隔符耗尽（空串为字符级兜底）：按 chunk_size 强行切片，避免无限递归
            for i in range(0, len(piece), chunk_size):
                final.append(piece[i:i + chunk_size])
            return
        parts = piece.split(sep)
        buf = ""
        for p in parts:
            candidate = (buf + sep + p).strip() if buf else p
            if len(candidate) <= chunk_size:
                buf = candidate
            else:
                if buf:
                    final.append(buf)
                    buf = ""
                if len(p) > chunk_size:
                    _recursive(p, list(rest))
                else:
                    buf = p
        if buf:
            final.append(buf)

    _recursive(text, seps)

    # 合并过小片段
    if min_chunk_size > 1:
        final = _merge_small(final, min_chunk_size, chunk_size)

    if overlap <= 0:
        logger.debug(
            "切片完成: chunk_size=%d, pieces=%d", chunk_size, len(final)
        )
        return final

    overlapped: list[str] = []
    step = max(chunk_size - overlap, 1)
    for chunk in final:
        if len(chunk) <= chunk_size:
            overlapped.append(chunk)
            continue
        start = 0
        while start < len(chunk):
            overlapped.append(chunk[start:start + chunk_size])
            if start + chunk_size >= len(chunk):
                break
            start += step
    logger.debug(
        "切片完成（含重叠）: chunk_size=%d, overlap=%d, pieces=%d",
        chunk_size,
        overlap,
        len(overlapped),
    )
    return overlapped


def _merge_small(chunks: list[str], min_size: int, chunk_size: int) -> list[str]:
    """将长度小于 min_size 的片段向后合并，避免产生过短碎片。"""
    result: list[str] = []
    for piece in chunks:
        if result and len(piece) < min_size:
            if len(result[-1]) + len(piece) <= chunk_size:
                result[-1] = (result[-1] + " " + piece).strip()
                continue
        result.append(piece)
    return result


def resolve_strategy(file_type: str, text_length: int, strategies: list[dict] | None) -> dict:
    """从策略列表中选择「文件类型 + 长度区间」最匹配的一项，返回策略参数字典。

    匹配规则：file_types 为空表示通用；min_len/max_len 限定长度区间；
    越具体的策略（类型明确 + 区间明确）优先级越高。
    """
    file_type = (file_type or "").lower().lstrip(".")
    best: dict | None = None
    best_score = -1
    for s in strategies or []:
        types = s.get("file_types") or []
        if types and file_type not in types:
            continue
        min_len = s.get("min_len")
        max_len = s.get("max_len")
        if min_len is not None and text_length < int(min_len):
            continue
        if max_len is not None and text_length > int(max_len):
            continue
        score = 0
        if types:
            score += 2
        if min_len is not None:
            score += 1
        if max_len is not None:
            score += 1
        if score > best_score:
            best_score = score
            best = s
    return best or {}


_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def clean_text(
    text: str,
    collapse_whitespace: bool = False,
    remove_urls_email: bool = False,
) -> str:
    """文本预处理：可选删除 URL/邮箱，或合并连续空白字符。"""
    text = text or ""
    if remove_urls_email:
        text = _URL_RE.sub("", text)
        text = _EMAIL_RE.sub("", text)
    if collapse_whitespace:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def split_hierarchical(text: str, max_level: int = 3) -> list[dict]:
    """按 Markdown 标题层级将文档切分为若干片段。

    仅识别 level <= max_level 的标题作为分段边界；返回 [{level, title, content}]。
    标题行之前的正文归入一个无标题（title=""、level=1）的片段。
    """
    text = (text or "").strip()
    nodes: list[dict] = []
    preamble: list[str] = []
    current: dict | None = None

    def _flush() -> None:
        nonlocal current
        if current is not None:
            current["content"] = (current.get("content") or "").strip()
            nodes.append(current)
            current = None

    for raw in text.splitlines():
        m = _HEADING_RE.match(raw)
        if m:
            level = len(m.group(1))
            if level <= max_level:
                _flush()
                current = {"level": level, "title": m.group(2).strip(), "content": ""}
                continue
        if current is not None:
            current["content"] += raw + "\n"
        else:
            preamble.append(raw)

    _flush()
    if preamble:
        nodes.insert(0, {"level": 1, "title": "", "content": "\n".join(preamble).strip()})

    return [n for n in nodes if n.get("title") or n.get("content")]