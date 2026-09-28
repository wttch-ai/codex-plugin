#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rag.py —— 项目本地 RAG 记忆工具包 CLI 引擎（sqlite-vec + Ollama）。

每个项目一个本地记忆库；使用与保留约束由项目自身定义。
依赖：sqlite-vec（纯 python wheel，自带 vec0.dll）；Ollama 提供嵌入向量。

命令：
  check    环境自检（venv / sqlite-vec DLL / Ollama / 模型维度）
  ingest   读取 markdown/txt 入库（增量，跳过未变更）
  query    向量检索
  memorize 沉淀短期记忆 / 阶段结论
  summarize 汇总近期记忆（启发式，可 --chat-model）
  stats    库统计
  drop     清理记忆
  list     列出所有 agent 库
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.request
import urllib.error
import yaml
from datetime import datetime, timedelta

# ---------------------------------------------------------------- 常量

EMBEDDING_DIM = 768                      # nomic-embed-text-v2-moe
EMBED_MODEL = "nomic-embed-text-v2-moe:latest"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_URL = OLLAMA_URL + "/api/embed"
TAGS_URL = OLLAMA_URL + "/api/tags"
CHAT_URL = OLLAMA_URL + "/api/generate"

AGENTS = []
SCOPES = ["project"]
NEGOTIATION_AGENTS = []
ALL_AGENTS = ["*"]
DB_NAME = "rag"                                 # 融合单库文件名（data/rag.db）

CHUNK_TARGET = 300                       # 目标 chunk token 数
CHUNK_OVERLAP = 60                       # 重叠 token 数
EMBED_BATCH = 8                          # 每请求最多嵌入条数（512 context 预算）

CJK_RE = re.compile(r"[一-鿿]")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")

# MarkdownHeaderTextSplitter 的标题级别映射（必须配全 6 级，否则未配置级别不切分）
MD_HEADERS = [("#", "H1"), ("##", "H2"), ("###", "H3")]

# ---------------------------------------------------------------- 路径

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
# RAG code belongs to the plugin, but memories never do.  Resolve the data
# directory from the project that invokes the plugin so every project owns its
# own database and retention policy.  RAG_PROJECT_ROOT is useful for daemon
# deployments whose working directory is not the project root.
PROJECT_ROOT = os.path.abspath(os.environ.get("RAG_PROJECT_ROOT") or os.getcwd())
DATA_DIR = os.path.join(PROJECT_ROOT, ".agents", "wttch", "rag-data")
SCOPE_FILE = os.path.join(PROJECT_ROOT, ".agents", "wttch", "rag-scope.yml")


def load_scopes():
    """Load the invoking project's declarative RAG scope list."""
    if not os.path.exists(SCOPE_FILE):
        return [{"key": "project", "description": "当前项目的通用知识与约束"}]
    with open(SCOPE_FILE, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or []
    if not isinstance(data, list):
        raise SystemExit(f"错误：{SCOPE_FILE} 必须是 scope 列表")
    scopes = []
    for item in data:
        if not isinstance(item, dict):
            raise SystemExit(f"错误：{SCOPE_FILE} 的每项必须包含 key 和 description")
        key = str(item.get("key") or "").strip()
        description = str(item.get("description") or "").strip()
        if not key or not description:
            raise SystemExit(f"错误：{SCOPE_FILE} 的每项必须包含非空 key 和 description")
        scopes.append({"key": key, "description": description})
    if len({item["key"] for item in scopes}) != len(scopes):
        raise SystemExit(f"错误：{SCOPE_FILE} 不允许重复的 scope key")
    return scopes


def available_scope_keys():
    return [item["key"] for item in load_scopes()]


def default_scope():
    return available_scope_keys()[0]


SCOPES = available_scope_keys()


def _bootstrap():
    """Load optional dependencies from the plugin bootstrap environment.

    The plugin owns its shared virtual environment; a project must not create
    or reuse a RAG-specific venv next to its database.
    """
    try:
        import sqlite_vec  # noqa: F401
        globals()["sqlite_vec"] = sqlite_vec  # 绑定到模块级，供各命令使用
    except ImportError:
        sys.exit("错误：未找到 sqlite-vec，请先执行 uv venv .venv && uv pip install -r requirements.txt")


_bootstrap()


def _force_utf8():
    """Windows 下 stdout/stderr 默认 GBK，强制 UTF-8，避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


_force_utf8()


def _now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- sqlite-vec 连接

def _migrate_legacy_libs(conn=None):
    """首次使用时把历史分库（data/<agent>.db）合并进融合单库 data/rag.db。

    迁移为 scope=project、agent=原库名，向量一并复制（vec0 按 chunks_meta.rowid 关联）。
    完成标记：rag.db 中已存在该 (scope, agent) 的 project 数据则跳过；旧库文件保留不删。
    conn: 复用调用方连接；None 时自连（需 rag.db 已建表）。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    db_path = os.path.join(DATA_DIR, f"{DB_NAME}.db")
    if not os.path.exists(db_path):
        return
    try:
        import sqlite_vec
    except ImportError:
        return
    own = conn is None
    try:
        if own:
            conn = sqlite3.connect(db_path)
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
        for agent in AGENTS:
            legacy = os.path.join(DATA_DIR, f"{agent}.db")
            if not os.path.exists(legacy):
                continue
            cnt = conn.execute(
                "SELECT COUNT(*) FROM chunks_meta WHERE scope='project' AND agent=?",
                (agent,)).fetchone()[0]
            if cnt:
                continue
            try:
                lconn = sqlite3.connect(legacy)
                lconn.enable_load_extension(True)
                sqlite_vec.load(lconn)
            except Exception:
                continue
            try:
                rows = lconn.execute(
                    "SELECT rowid, content, source, section, agent, tag, origin, weight, "
                    "ingested_at, content_hash FROM chunks_meta").fetchall()
            except sqlite3.OperationalError:
                # 老库无 chunks_meta（空库或异常）则跳过
                lconn.close()
                continue
            moved = 0
            for rid, content, source, section, lagent, tag, origin, weight, ts, c_hash in rows:
                try:
                    cur = conn.execute(
                        "INSERT INTO chunks_meta(scope,content,source,section,agent,tag,origin,weight,ingested_at,content_hash)"
                        " VALUES('project',?,?,?,?,?,?,?,?,?)",
                        (content, source, section, lagent or agent, tag, origin, weight, ts, c_hash))
                    nrid = cur.lastrowid
                    rowv = lconn.execute(
                        "SELECT embedding FROM chunks WHERE rowid=?", (rid,)).fetchone()
                    if rowv is not None:
                        conn.execute("INSERT INTO chunks(rowid, embedding) VALUES(?,?)",
                                     (nrid, rowv[0]))
                    moved += 1
                except sqlite3.IntegrityError:
                    continue
            try:
                frows = lconn.execute(
                    "SELECT source, file_hash, ingested_at FROM files").fetchall()
                for fsrc, fhash, fts in frows:
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO files(scope,agent,source,file_hash,ingested_at)"
                            " VALUES('project',?,?,?,?)", (agent, fsrc, fhash, fts))
                    except sqlite3.IntegrityError:
                        pass
            except sqlite3.OperationalError:
                pass
            lconn.close()
            conn.commit()
            if moved:
                print(f"[migrate] {agent}.db → rag.db（project，{moved} 条）")
        if own:
            conn.close()
    except Exception as e:
        print(f"[migrate] 旧库迁移失败（可稍后执行 rag migrate）：{e}")


def connect(scope="project", agent=None):
    """打开融合单库 data/rag.db，加载 sqlite-vec 扩展并建表。

    所有数据均保存于调用项目的本地数据库。
    首次连接会自动把历史分库迁移合并进 rag.db。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    db_path = os.path.join(DATA_DIR, f"{DB_NAME}.db")
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    import sqlite_vec
    sqlite_vec.load(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS chunks_meta(
        rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
        scope         TEXT NOT NULL DEFAULT 'project',   -- project/negotiation/public
        content       TEXT NOT NULL,
        source        TEXT NOT NULL,
        section       TEXT,
        agent         TEXT NOT NULL,
        tag           TEXT,
        origin        TEXT NOT NULL DEFAULT 'user',   -- user=用户经 agent 建立(永久/高权重)；auto=agent 自动总结
        weight        REAL NOT NULL DEFAULT 1.0,      -- 查询加权因子（默认 user=1.0 / auto=0.5）
        ingested_at   TEXT NOT NULL,
        content_hash  TEXT NOT NULL,
        UNIQUE(scope, agent, content_hash)
    )""")
    # 兼容：老 rag.db 补充 scope 列并填默认值（历史数据视为 project）
    for col, ddl in (("scope", "TEXT"),):
        try:
            conn.execute(f"ALTER TABLE chunks_meta ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass  # 列已存在
    conn.execute("UPDATE chunks_meta SET scope='project' WHERE scope IS NULL")
    # 兼容：补充 origin/weight 列并填默认值（历史数据按 tag 推断：summary→auto，其余→user）
    for col, ddl in (("origin", "TEXT"), ("weight", "REAL")):
        try:
            conn.execute(f"ALTER TABLE chunks_meta ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError:
            pass  # 列已存在
    conn.execute("UPDATE chunks_meta SET origin='auto' WHERE origin IS NULL AND tag='summary'")
    conn.execute("UPDATE chunks_meta SET origin='user' WHERE origin IS NULL")
    conn.execute("UPDATE chunks_meta SET weight=0.5 WHERE weight IS NULL AND origin='auto'")
    conn.execute("UPDATE chunks_meta SET weight=1.0 WHERE weight IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_scope       ON chunks_meta(scope)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_scope_agent ON chunks_meta(scope, agent)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_source   ON chunks_meta(source)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_agent    ON chunks_meta(agent)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_tag      ON chunks_meta(tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_ingested ON chunks_meta(ingested_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS files(
        scope       TEXT NOT NULL DEFAULT 'project',
        agent       TEXT NOT NULL,
        source      TEXT NOT NULL,
        file_hash   TEXT NOT NULL,
        ingested_at TEXT NOT NULL,
        PRIMARY KEY(scope, agent, source)
    )""")
    # chunk_size=64：vec0 默认预分配 4096 个向量块（约 3MB），对 git 提交的记忆库过大；
    # 64 即够批量入库使用，显著减小 DB 体积。
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING vec0(embedding float[768], chunk_size=64)")
    conn.commit()
    _migrate_legacy_libs(conn)
    return conn, db_path


def _scope_clause(scope, agent, table=""):
    """返回 (where_sql, params)，用于按 scope/agent 过滤 chunks_meta。

    scope/agent 仅为兼容旧数据库保留，不再隔离项目本地数据。
    """
    if scope == "*":
        return "1=1", []
    if scope not in available_scope_keys():
        raise SystemExit(f"错误：未知 scope {scope!r}；运行 rag scopes 查看项目配置")
    return f"{table}scope=?", [scope]


def _insert_chunk(conn, scope, agent, content, source, section, tag, origin="user", weight=1.0):
    """插入一个 chunk（元数据 + 向量）。返回 rowid，哈希冲突则返回 None。

    origin: user=用户建立 / auto=agent 自动。
    weight: 查询加权因子（默认 user=1.0 / auto=0.5，可被命令覆盖）。
    """
    c_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    try:
        cur = conn.execute(
            "INSERT INTO chunks_meta(scope,content,source,section,agent,tag,origin,weight,ingested_at,content_hash)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (scope, content, source, section, agent, tag, origin, weight, _now_iso(), c_hash))
    except sqlite3.IntegrityError:
        return None  # 内容已存在（幂等）
    rid = cur.lastrowid
    emb = embed([content])[0]
    conn.execute("INSERT INTO chunks(rowid, embedding) VALUES(?,?)",
                 (rid, sqlite_vec.serialize_float32(emb)))
    return rid


# ---------------------------------------------------------------- Ollama 客户端

def embed(texts):
    """批量调用 Ollama 嵌入，返回 [[dim]...]。"""
    payload = json.dumps({"model": EMBED_MODEL, "input": texts}).encode("utf-8")
    req = urllib.request.Request(EMBED_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
    except Exception as e:
        sys.exit(f"错误：无法连接 Ollama ({EMBED_URL}) — {e}")
    embs = data.get("embeddings")
    if not embs or len(embs) != len(texts):
        sys.exit("错误：Ollama 返回 embeddings 数量不匹配")
    for e in embs:
        if len(e) != EMBEDDING_DIM:
            sys.exit(f"错误：embedding 维度 {len(e)} != 期望 {EMBEDDING_DIM}（模型 {EMBED_MODEL}）")
    return embs


def ollama_models():
    """GET /api/tags，返回 [(name, capability)]。"""
    try:
        with urllib.request.urlopen(TAGS_URL, timeout=10) as resp:
            data = json.load(resp)
    except Exception as e:
        sys.exit(f"错误：无法连接 Ollama ({TAGS_URL}) — {e}")
    out = []
    for m in data.get("models", []):
        caps = m.get("capabilities", []) or []
        out.append((m.get("name", ""), caps))
    return out


def pick_chat_model(explicit=None):
    """选择可用的对话模型；无则返回 None（回退启发式汇总）。"""
    if explicit:
        return explicit
    try:
        for name, caps in ollama_models():
            if "embedding" not in caps and "completion" in caps:
                return name
    except SystemExit:
        return None
    return None


def ollama_chat_summary(model, chunks):
    """调用对话模型汇总 chunk 文本，失败抛异常由调用方回退。"""
    budget = 0
    parts = []
    for c in chunks:
        budget += estimate_tokens(c["content"])
        if budget > 3800:      # 保守上限，防止超出上下文
            break
        parts.append(c["content"])
    joined = "\n---\n".join(parts)
    prompt = (
        "请将以下技术记忆条目汇总为简洁的中文摘要，按主题归类，"
        "保留关键结论、接口名、类名与决策理由：\n\n" + joined)
    payload = json.dumps({"model": model, "prompt": prompt,
                          "stream": False, "options": {"num_predict": 600}}).encode("utf-8")
    req = urllib.request.Request(CHAT_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    return (data.get("response") or "").strip()


# ---------------------------------------------------------------- 分块

def estimate_tokens(text):
    """启发式 token 估算：CJK 字符≈1，英文单词≈1.3，每行≈1。"""
    cjk = len(CJK_RE.findall(text))
    words = len(ASCII_WORD_RE.findall(text))
    lines = text.count("\n")
    return int(cjk + words * 1.3) + lines


def _langchain_splitters():
    """惰性导入 langchain 分块器并缓存。ingest/summarize 需要，check/stats 不需要。"""
    if "_splitter_cache" not in globals():
        try:
            from langchain_text_splitters import (
                MarkdownHeaderTextSplitter,
                RecursiveCharacterTextSplitter,
            )
            globals()["_splitter_cache"] = (MarkdownHeaderTextSplitter,
                                            RecursiveCharacterTextSplitter)
        except ImportError:
            sys.exit("错误：未找到 langchain-text-splitters，请先执行 "
                     "uv venv .venv && uv pip install -r requirements.txt")
    return globals()["_splitter_cache"]


def _size_cap(text, section):
    """块内超限时用 RecursiveCharacterTextSplitter 二次切（300 token / 60 重叠）。"""
    _mdh, rcts = _langchain_splitters()
    splitter = rcts(chunk_size=CHUNK_TARGET, chunk_overlap=CHUNK_OVERLAP,
                    length_function=estimate_tokens)
    return [(c.strip(), section) for c in splitter.split_text(text) if c.strip()]


def _split_markdown(text):
    """按标题结构分块：MarkdownHeaderTextSplitter 提取标题层级，
    最深标题作 section；块内超限用递归切片二次封顶。"""
    _mdh, _rcts = _langchain_splitters()
    docs = _mdh(headers_to_split_on=MD_HEADERS, strip_headers=True).split_text(text)
    out = []
    for d in docs:
        meta = d.metadata
        section = next((meta[k] for k in ("H6", "H5", "H4", "H3", "H2", "H1")
                        if meta.get(k)), None)
        out.extend(_size_cap(d.page_content, section))
    return out


def split_by_extension(path, text):
    """按扩展名分块，返回 [(chunk_text, section)]。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".markdown"):
        return _split_markdown(text)
    return _size_cap(text, None)   # txt：纯递归切片，无标题结构


# ---------------------------------------------------------------- ingest

def _iter_files(path, exts):
    if os.path.isfile(path):
        if os.path.splitext(path)[1].lower() in exts or not exts:
            yield os.path.abspath(path)
        return
    for root, _dirs, files in os.walk(path):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in exts:
                yield os.path.abspath(os.path.join(root, fn))


def _read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    return raw.decode("utf-8", errors="replace")


def _content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prune_tree(conn, scope, agent, dir_abspath, exts):
    """删除目录下已从磁盘消失的源文件 chunk（用于 ingest 目录时清理删除的文件）。

    仅清理扩展名属于本次 ingest 范围（exts）的源：避免 --ext txt 时误删 .md 文件。
    按 (scope, agent) 限定当前库，避免跨库误删。
    """
    on_disk = set(_iter_files(dir_abspath, exts))
    for (src,) in conn.execute(
            "SELECT source FROM files WHERE scope=? AND agent=?", (scope, agent)).fetchall():
        if not (src.startswith(dir_abspath + os.sep) and src not in on_disk):
            continue
        if os.path.splitext(src)[1].lower() not in exts:
            continue
        for (rid,) in conn.execute(
                "SELECT rowid FROM chunks_meta WHERE scope=? AND agent=? AND source=?",
                (scope, agent, src)).fetchall():
            conn.execute("DELETE FROM chunks WHERE rowid=?", (rid,))
            conn.execute("DELETE FROM chunks_meta WHERE rowid=?", (rid,))
        conn.execute("DELETE FROM files WHERE scope=? AND agent=? AND source=?",
                     (scope, agent, src))
        conn.commit()
        print(f"[prune] 源文件已删除，清理其 chunk: {src}")


def cmd_ingest(args):
    scope = getattr(args, "scope", "project")
    agent = args.agent or "*"
    conn, _ = connect(scope, agent)
    exts = [e if e.startswith(".") else "." + e for e in (args.ext or [".md", ".txt", ".markdown"])]
    files = sorted(_iter_files(args.path, exts))
    if not files and not (args.prune and os.path.isdir(args.path)):
        sys.exit(f"错误：路径下没有 {exts} 文件 — {args.path}")
    added = skipped = 0
    now = _now_iso()
    for fp in files:
        raw = _read_text(fp)
        f_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        row = conn.execute("SELECT file_hash FROM files WHERE scope=? AND agent=? AND source=?",
                           (scope, agent, fp)).fetchone()
        if row and row[0] == f_hash and not args.force:
            print(f"[skip] 未变更: {fp}")
            skipped += 1
            continue
        # chunk 级 diff：仅重嵌新增/变更的 chunk，未变 chunk 复用原 embedding 与 rowid
        chunks = split_by_extension(fp, raw)                    # [(text, section)]
        new_by_hash = {}
        for t, s in chunks:
            new_by_hash.setdefault(_content_hash(t), s)          # 同文件内 hash 冲突保留首个
        old = conn.execute(
            "SELECT rowid, content_hash, section FROM chunks_meta WHERE scope=? AND agent=? AND source=?",
            (scope, agent, fp)).fetchall()
        old_by_hash = {h: (rid, sec) for rid, h, sec in old}
        # 删除：旧 hash 不在新集合（内容被删/改）
        removed = 0
        for h, (rid, _) in old_by_hash.items():
            if h not in new_by_hash:
                conn.execute("DELETE FROM chunks WHERE rowid=?", (rid,))
                conn.execute("DELETE FROM chunks_meta WHERE rowid=?", (rid,))
                removed += 1
        # 新增：新 hash 不在旧集合 → 仅这些需要嵌入
        for t, s in chunks:
            h = _content_hash(t)
            if h not in old_by_hash:
                if _insert_chunk(conn, scope, agent, t, fp, s, "doc",
                              origin="user") is not None:
                    added += 1
        # 复用：hash 两端都在 → 章节变化仅 UPDATE section，不重嵌
        reused = 0
        for h, (rid, old_sec) in old_by_hash.items():
            if h in new_by_hash:
                reused += 1
                if new_by_hash[h] != old_sec:
                    conn.execute("UPDATE chunks_meta SET section=? WHERE rowid=?",
                                 (new_by_hash[h], rid))
        conn.execute(
            "INSERT INTO files(scope,agent,source,file_hash,ingested_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(scope,agent,source) DO UPDATE SET file_hash=excluded.file_hash, ingested_at=excluded.ingested_at",
            (scope, agent, fp, f_hash, now))
        conn.commit()
        print(f"[ok] {fp} → {len(chunks)} chunks（新增 {added} / 复用 {reused} / 删除 {removed}）")
    if args.prune and os.path.isdir(args.path):
        _prune_tree(conn, scope, agent, os.path.abspath(args.path), exts)
    conn.close()
    print(f"完成：新增 {added} 条，跳过 {skipped} 个未变更文件。")


# ---------------------------------------------------------------- query

def cmd_query(args):
    scope = getattr(args, "scope", "project")
    agent = args.agent
    conn, _ = connect(scope, agent)
    try:
        import sqlite_vec
    except ImportError:
        sys.exit("错误：未找到 sqlite-vec")
    qv = embed([args.question])[0]
    qv_blob = sqlite_vec.serialize_float32(qv)
    # scope/agent 过滤 + origin 过滤（默认全部）
    where, params = _scope_clause(scope, agent, "m.")
    origin_clause = ""
    if getattr(args, "origin", None):
        origin_clause = " AND m.origin = ?"
    select = ("SELECT m.rowid, v.distance, m.content, m.source, m.section, m.tag, "
              "m.origin, m.weight, m.ingested_at "
              "FROM chunks v JOIN chunks_meta m ON m.rowid = v.rowid "
              "WHERE v.embedding MATCH ? AND " + where + origin_clause + " AND v.k = ? ORDER BY v.distance")
    args_list = [qv_blob] + params
    if getattr(args, "origin", None):
        args_list.append(args.origin)
    args_list.append(args.top_k)
    try:
        rows = conn.execute(select, args_list).fetchall()
    except sqlite3.OperationalError:
        select = select.replace("MATCH ?", "MATCH vec_f32(?)")
        rows = conn.execute(select, args_list).fetchall()
    conn.close()
    if not rows:
        print("无匹配结果。")
        return
    for rid, dist, content, source, section, tag, origin, weight, ts in rows:
        score = (1.0 / (1.0 + dist)) * weight          # 加权：权重越高质量排序越靠前
        src = os.path.basename(source) if source != "memory" else "memory"
        print(f"[{score:.3f}] (id={rid}, {tag}/{origin}, w={weight:.1f}, {ts})")
        print(f"   来源: {src}" + (f"  |  {section}" if section else ""))
        txt = content.replace("\\n", "\\n    ")
        print(f"   {txt[:400]}{'…' if len(txt) > 400 else ''}")
        print()


# ---------------------------------------------------------------- memorize

def cmd_memorize(args):
    scope = getattr(args, "scope", "project")
    agent = args.agent or "*"
    conn, _ = connect(scope, agent)
    texts = []
    if args.text:
        texts.append(args.text)
    for fp in args.file or []:
        texts.append(_read_text(os.path.abspath(fp)))
    if not texts:
        sys.exit("错误：请提供 --text 或 --file")
    count = 0
    origin = getattr(args, "origin", "user") or "user"
    weight = 0.5 if origin == "auto" else 1.0
    for t in texts:
        # 记忆按行切成短条目，便于检索
        for line in t.split("\n"):
            line = line.strip()
            if not line:
                continue
            if _insert_chunk(conn, scope, agent, line, "memory", None,
                             args.tag or "memory", origin=origin, weight=weight) is not None:
                count += 1
    conn.commit()
    conn.close()
    print(f"已沉淀 {count} 条记忆（--scope {scope}, --agent {agent}, tag={args.tag or 'memory'}, origin={origin}, weight={weight}）。")


# ---------------------------------------------------------------- stats / drop / list

def cmd_stats(args):
    scope = getattr(args, "scope", "project")
    agent = args.agent
    conn, _ = connect(scope, agent)
    where, params = _scope_clause(scope, agent)
    total = conn.execute("SELECT COUNT(*) FROM chunks_meta WHERE " + where, params).fetchone()[0]
    total_bytes = conn.execute(
        "SELECT COALESCE(SUM(LENGTH(CAST(content AS BLOB))), 0) FROM chunks_meta WHERE " + where,
        params).fetchone()[0]
    by_tag = conn.execute(
        "SELECT tag, COUNT(*) FROM chunks_meta WHERE " + where + " GROUP BY tag ORDER BY 2 DESC", params).fetchall()
    by_source = conn.execute(
        "SELECT source, COUNT(*) FROM chunks_meta WHERE " + where + " GROUP BY source ORDER BY 2 DESC LIMIT 10", params).fetchall()
    by_origin = conn.execute(
        "SELECT origin, COUNT(*), ROUND(AVG(weight),2) FROM chunks_meta WHERE " + where + " GROUP BY origin", params).fetchall()
    last = conn.execute("SELECT MAX(ingested_at) FROM chunks_meta WHERE " + where, params).fetchone()[0]
    conn.close()
    label = f"{scope}/{agent}" if agent and agent != "*" else scope
    print(f"== {label} 记忆库 ==")
    print(f"总 chunk 数: {total}")
    size = (f"{total_bytes/1024/1024:.2f} MB" if total_bytes >= 1048576
            else f"{total_bytes/1024:.1f} KB" if total_bytes >= 1024 else f"{total_bytes} B")
    print(f"内容字节:   {total_bytes:,} B（{size}，UTF-8）")
    print(f"最近写入:   {last}")
    print("按 tag:")
    for tag, c in by_tag:
        print(f"  {tag or '(null)'}: {c}")
    print("按来源类别:")
    for origin, c, wavg in by_origin:
        print(f"  {origin or '(null)'}: {c} 条（平均权重 {wavg}）")
    print("按来源（前 10）:")
    for src, c in by_source:
        short = "memory" if src == "memory" else os.path.basename(src)
        print(f"  {short}: {c}")


def cmd_drop(args):
    scope = getattr(args, "scope", "project")
    agent = args.agent or "*"
    conn, _ = connect(scope, agent)
    clauses, params = _scope_clause(scope, agent)
    clauses = [clauses]
    if args.source:
        clauses.append("source=?")
        params.append(os.path.abspath(args.source))
    if args.tag:
        clauses.append("tag=?")
        params.append(args.tag)
    # origin 过滤：默认只清理 agent 自动总结(auto)；明确指定才清理用户(user)记忆
    if getattr(args, "origin", None) is None:
        clauses.append("origin != 'user'")
    else:
        clauses.append("origin=?")
        params.append(args.origin)
    if args.older_than:
        m = re.match(r"^(\d+)(d|h)?$", args.older_than)
        if not m:
            sys.exit("错误：--older-than 格式应为 Nd 或 Nh，如 7d / 12h")
        unit = m.group(2) or "d"
        delta = timedelta(days=int(m.group(1))) if unit == "d" else timedelta(hours=int(m.group(1)))
        cutoff = (datetime.now() - delta).strftime("%Y-%m-%d %H:%M:%S")
        clauses.append("ingested_at < ?")
        params.append(cutoff)
    rows = conn.execute("SELECT rowid FROM chunks_meta WHERE " + " AND ".join(clauses), params).fetchall()
    if not rows:
        print("没有符合条件的记忆。")
        return
    if args.dry_run:
        print(f"[dry-run] 将删除 {len(rows)} 条（--scope {scope}, --agent {agent}）")
        return
    for (rid,) in rows:
        conn.execute("DELETE FROM chunks WHERE rowid=?", (rid,))
        conn.execute("DELETE FROM chunks_meta WHERE rowid=?", (rid,))
    conn.commit()
    conn.close()
    print(f"已删除 {len(rows)} 条记忆。")


def cmd_list(args):
    os.makedirs(DATA_DIR, exist_ok=True)
    scope = getattr(args, "scope", None)
    agent = getattr(args, "agent", None)
    db_path = os.path.join(DATA_DIR, f"{DB_NAME}.db")
    if not os.path.exists(db_path):
        print("暂无记忆库。首次使用某 agent 时自动创建 data/rag.db。")
        return
    try:
        import sqlite_vec
    except ImportError:
        sys.exit("错误：未找到 sqlite-vec")
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    size = os.path.getsize(db_path)
    if scope is not None or agent:
        where, params = _scope_clause(scope, agent)
        rows = conn.execute(
            "SELECT scope, agent, COUNT(*) FROM chunks_meta WHERE " + where +
            " GROUP BY scope, agent ORDER BY scope, agent", params).fetchall()
    else:
        rows = conn.execute(
            "SELECT scope, agent, COUNT(*) FROM chunks_meta "
            "GROUP BY scope, agent ORDER BY scope, agent").fetchall()
    conn.close()
    print(f"融合记忆库: {DB_NAME}.db  ({size/1024:.1f} KB)")
    if not rows:
        print("  （空库，尚无记忆）")
        return
    cur = None
    for scope, agent, cnt in rows:
        if scope != cur:
            cur = scope
            print(f"[{scope}]")
        print(f"  {agent}: {cnt} 条")
    used_agents = {a for _s, a, _c in rows}
    unused = [a for a in AGENTS if a not in used_agents]
    if unused:
        print("\n未使用（首次使用时自动生成）:", ", ".join(unused))


# ---------------------------------------------------------------- summarize

def cmd_summarize(args):
    scope = getattr(args, "scope", "project")
    agent = args.agent or "*"
    conn, _ = connect(scope, agent)
    base_where, params = _scope_clause(scope, agent)
    where = [base_where, "tag != 'summary'"]
    if args.since != "all":
        m = re.match(r"^(\d+)d$", args.since)
        if not m:
            sys.exit("错误：--since 格式应为 all 或 Nd（如 7d）")
        cutoff = (datetime.now() - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d %H:%M:%S")
        where.append("ingested_at >= ?")
        params.append(cutoff)
    rows = conn.execute(
        "SELECT rowid, content, tag, source, ingested_at FROM chunks_meta "
        "WHERE " + " AND ".join(where) + " ORDER BY ingested_at", params).fetchall()
    if not rows:
        print("该时间段内没有可汇总的记忆。")
        return
    # 简单去重：按内容前 80 字符
    seen = set()
    entries = []
    for rid, content, tag, source, ts in rows:
        key = content[:80]
        if key in seen:
            continue
        seen.add(key)
        entries.append({"rowid": rid, "content": content, "tag": tag,
                        "source": source, "ts": ts})
    entries = entries[-args.limit:]
    # 按 tag 分组
    groups = {}
    for e in entries:
        groups.setdefault(e["tag"] or "misc", []).append(e)

    chat_model = pick_chat_model(args.chat_model)
    if chat_model:
        try:
            summary = ollama_chat_summary(chat_model, entries)
        except Exception as e:
            print(f"（对话模型 {chat_model} 失败：{e}，回退启发式汇总）")
            summary = heuristic_summary(groups)
    else:
        summary = heuristic_summary(groups)

    label = f"{scope}/{agent}" if agent and agent != "*" else scope
    header = f"===== {label} 记忆汇总（{args.since}）====="
    print(header)
    print(summary)
    if not args.no_store:
        block = header + "\n\n" + summary
        for text, section in split_by_extension("memory.md", block):
            if _insert_chunk(conn, scope, agent, text, "memory", section, "summary",
                              origin="auto", weight=0.5) is not None:
                pass
        conn.commit()
        print("\n（摘要已回存为 tag=summary，可被后续 query 检索）")
    conn.close()


def heuristic_summary(groups):
    lines = []
    for tag in sorted(groups):
        items = groups[tag]
        lines.append(f"## {tag}（{len(items)} 条）")
        for e in items:
            first = e["content"].replace("\n", " ").strip()
            lines.append(f"- [{e['ts']}] {first[:200]}")
    return "\n".join(lines)


# ---------------------------------------------------------------- check

def cmd_check(args):
    print("== rag-toolkit 环境自检 ==")
    print(f"Python     : {sys.executable}")
    try:
        import sqlite_vec
        print(f"sqlite-vec : {sqlite_vec.__version__ if hasattr(sqlite_vec, '__version__') else '已加载'}")
        print(f"vec0.dll   : {sqlite_vec.loadable_path()}.dll")
    except ImportError:
        print("sqlite-vec : 未安装（请 uv venv .venv && uv pip install -r requirements.txt）")
        return
    # 验证扩展可加载
    try:
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.execute("CREATE VIRTUAL TABLE t USING vec0(embedding float[768])")
        print("vec0 加载 : OK（虚拟表可创建）")
        conn.close()
    except Exception as e:
        print(f"vec0 加载 : 失败 — {e}")
    # langchain 分块器
    try:
        from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter  # noqa: F401
        import importlib.metadata as _md
        print(f"langchain : 已安装（text-splitters {_md.version('langchain-text-splitters')}）")
    except ImportError:
        print("langchain : 未安装（ingest 需先执行 uv pip install -r requirements.txt）")
    # Ollama
    try:
        models = ollama_models()
        print(f"Ollama    : 可达（{OLLAMA_URL}），模型 {len(models)} 个")
        emb_names = [n for n, caps in models if "embedding" in caps]
        chat_names = [n for n, caps in models if "embedding" not in caps and "completion" in caps]
        print(f"嵌入模型  : {emb_names or '无'}")
        print(f"对话模型  : {chat_names or '无（summarize 将用启发式）'}")
        print(f"EMBED_MODEL = {EMBED_MODEL}（维度 {EMBEDDING_DIM}）")
    except SystemExit:
        print("Ollama    : 不可达（请确认 ollama serve 在 11434 端口运行）")
    # 数据目录可写性 + agent 库
    os.makedirs(DATA_DIR, exist_ok=True)
    probe = os.path.join(DATA_DIR, ".write_probe")
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        print(f"data 目录: 可写（{DATA_DIR}）")
    except Exception as e:
        print(f"data 目录: 不可写 — {e}")
    if args.agent:
        scope = getattr(args, "scope", "project")
        conn, db_path = connect(scope, args.agent)
        conn.close()
        print(f"记忆库   : {args.agent}（scope={scope}）→ {db_path}（可打开）")
    print("自检完成。")


# ---------------------------------------------------------------- migrate

def cmd_migrate(_args):
    """显式执行历史分库 data/<agent>.db → 融合库 data/rag.db 迁移。"""
    conn, db_path = connect()      # 建表并触发自动迁移
    conn.close()
    print(f"迁移完成。融合库: {db_path}")


# ---------------------------------------------------------------- main

def cmd_help(args, parser, cmds):
    """打印指定命令或全部命令的详细帮助。"""
    if getattr(args, "command", None) and args.command in cmds:
        print(cmds[args.command].format_help())
    else:
        print(parser.format_help())


def cmd_scopes(_args):
    """Print the current project's recognized RAG scopes as YAML."""
    print(yaml.safe_dump(load_scopes(), allow_unicode=True, sort_keys=False).strip())


def build_parser():
    """构建 argparse 解析器。独立成函数，供 main 与 help 子命令共用，
    保证帮助文本始终与实际参数定义一致（权威来源）。"""
    fmt = argparse.RawDescriptionHelpFormatter
    p = argparse.ArgumentParser(
        prog="rag",
        description=(
            "项目本地 RAG 记忆工具包 CLI（sqlite-vec + Ollama 嵌入）。\n"
            "数据库保存于调用项目 .agents/wttch/rag-data/rag.db。\n\n"
            "统一调用（仓库根执行，rtk 前缀为项目规定）：\n"
            "  python ${PLUGIN_ROOT}/runtime/rag_toolkit/rag.py <命令> ...\n\n"
            "分块规则：.md/.markdown 用 MarkdownHeaderTextSplitter 按标题拆章节（section=最深标题）；\n"
            "          .txt 用 RecursiveCharacterTextSplitter 拆段落；均为 300 token / 60 重叠。\n"
            "更新机制：整文件 hash 判变更 + chunk 内容 hash 粒度 diff —— 仅新/改 chunk 重新嵌入。\n\n"
            "输入 'rag.py help [命令]' 查看任意命令的详细帮助。"),
        formatter_class=fmt)
    sub = p.add_subparsers(dest="cmd", required=True)
    cmds = {}

    sp = sub.add_parser("ingest", help="读取 markdown/txt 入库（增量，按扩展名分块）", formatter_class=fmt)
    sp.add_argument("--scope", choices=SCOPES, default="project",
                    help="目标库层级：project=项目库(默认) / negotiation=协商库 / public=公共库")
    sp.add_argument("--agent", choices=ALL_AGENTS,
                    help=f"目标 agent（scope=project 必填，如 backend；其他 scope 可省略或 '*')。取值：{'/'.join(ALL_AGENTS)}")
    sp.add_argument("--path", required=True,
                    help="要入库的文件或目录路径；目录递归收集匹配 --ext 的文件")
    sp.add_argument("--ext", nargs="*", default=[".md", ".txt", ".markdown"],
                    help="收集文件的扩展名（默认：.md .txt .markdown）")
    sp.add_argument("--prune", action="store_true",
                    help="目录入库后清理该目录下已从磁盘删除文件的旧 chunk（仅 --path 为目录时生效）")
    sp.add_argument("--force", action="store_true",
                    help="忽略整文件 hash 命中强制重建（分块器/嵌入模型变更后重建用）")
    sp.set_defaults(func=cmd_ingest)
    cmds["ingest"] = sp

    sp = sub.add_parser("scopes", help="输出当前项目可用的 RAG scope", formatter_class=fmt)
    sp.set_defaults(func=cmd_scopes)
    cmds["scopes"] = sp

    sp = sub.add_parser("query", help="向量检索记忆库", formatter_class=fmt)
    sp.add_argument("--scope", choices=SCOPES, default="project",
                    help="目标库层级：project=项目库(默认) / negotiation=协商库 / public=公共库")
    sp.add_argument("--agent", choices=ALL_AGENTS,
                    help=f"目标 agent（scope=project 必填；其他 scope 可省略）。取值：{'/'.join(ALL_AGENTS)}")
    sp.add_argument("--top-k", type=int, default=5,
                    help="返回最相似片段数（默认：5）")
    sp.add_argument("--origin", choices=["user", "auto"],
                    help="仅检索该来源类别（user=用户建立 / auto=agent 自动）；缺省检索全部")
    sp.add_argument("question",
                    help="检索问题（位置参数，如 '解析链路'）")
    sp.set_defaults(func=cmd_query)
    cmds["query"] = sp

    sp = sub.add_parser("memorize", help="沉淀短期记忆/阶段结论", formatter_class=fmt)
    sp.add_argument("--scope", choices=SCOPES, default="project",
                    help="目标库层级：project=项目库(默认) / negotiation=协商库 / public=公共库")
    sp.add_argument("--agent", choices=ALL_AGENTS,
                    help=f"目标 agent（scope=project 必填）。取值：{'/'.join(ALL_AGENTS)}")
    sp.add_argument("--text",
                    help="要沉淀的记忆文本（多行用引号包裹）；--text 与 --file 至少给一个")
    sp.add_argument("--file", action="append",
                    help="从文件读取内容沉淀（可多次指定）")
    sp.add_argument("--tag", default="memory",
                    help="记忆标签（默认：memory）")
    sp.add_argument("--origin", choices=["user", "auto"], default="user",
                    help="来源类别：user=用户建立(永久/高权重，默认)；auto=agent 自动（weight 0.5）")
    sp.set_defaults(func=cmd_memorize)
    cmds["memorize"] = sp

    sp = sub.add_parser("summarize", help="汇总近期记忆（启发式，可 --chat-model）", formatter_class=fmt)
    sp.add_argument("--scope", choices=SCOPES, default="project",
                    help="目标库层级：project=项目库(默认) / negotiation=协商库 / public=公共库")
    sp.add_argument("--agent", choices=ALL_AGENTS,
                    help=f"目标 agent（scope=project 必填）。取值：{'/'.join(ALL_AGENTS)}")
    sp.add_argument("--since", default="all",
                    help="汇总时间范围：all（全部）或 Nd（如 7d=最近 7 天）；默认 all")
    sp.add_argument("--chat-model",
                    help="指定 Ollama 对话模型生成摘要；缺省自动探测（无对话模型时回退启发式汇总）")
    sp.add_argument("--limit", type=int, default=20,
                    help="参与汇总的最大条目数（默认：20）")
    sp.add_argument("--no-store", action="store_true",
                    help="不把汇总结果回存为 tag=summary")
    sp.set_defaults(func=cmd_summarize)
    cmds["summarize"] = sp

    sp = sub.add_parser("stats", help="库统计（按 tag/来源）", formatter_class=fmt)
    sp.add_argument("--scope", choices=SCOPES, default="project",
                    help="目标库层级：project=项目库(默认) / negotiation=协商库 / public=公共库")
    sp.add_argument("--agent", choices=ALL_AGENTS,
                    help=f"目标 agent（scope=project 必填；其他 scope 可省略）。取值：{'/'.join(ALL_AGENTS)}")
    sp.set_defaults(func=cmd_stats)
    cmds["stats"] = sp

    sp = sub.add_parser("drop", help="清理记忆", formatter_class=fmt)
    sp.add_argument("--scope", choices=SCOPES, default="project",
                    help="目标库层级：project=项目库(默认) / negotiation=协商库 / public=公共库")
    sp.add_argument("--agent", choices=ALL_AGENTS,
                    help=f"目标 agent（scope=project 必填；其他 scope 可省略）。取值：{'/'.join(ALL_AGENTS)}")
    sp.add_argument("--source",
                    help="仅清理该来源的 chunk（文件绝对路径或 memory）")
    sp.add_argument("--tag",
                    help="仅清理该标签（doc/memory/summary/自定义）")
    sp.add_argument("--older-than",
                    help="仅清理早于该时间的条目，格式 Nd/Nh（如 7d / 12h）")
    sp.add_argument("--origin", choices=["user", "auto"],
                    help="来源类别过滤；缺省只清理 auto（agent 自动总结），不删 user（用户永久记忆）")
    sp.add_argument("--dry-run", action="store_true",
                    help="只统计将删除条数，不实际删除")
    sp.set_defaults(func=cmd_drop)
    cmds["drop"] = sp

    sp = sub.add_parser("list", help="列出记忆库（可按 scope/agent 过滤）", formatter_class=fmt)
    sp.add_argument("--scope", choices=SCOPES, default=None,
                    help="过滤库：project/negotiation/public（不指定 = 全部）")
    sp.add_argument("--agent", choices=ALL_AGENTS, default=None,
                    help="过滤 agent（scope=project 时必填）")
    sp.set_defaults(func=cmd_list)
    cmds["list"] = sp

    sp = sub.add_parser("check", help="环境自检（venv/sqlite-vec/Ollama/模型维度）", formatter_class=fmt)
    sp.add_argument("--scope", choices=SCOPES, default="project",
                    help="目标库层级（配合 --agent 校验库可打开）")
    sp.add_argument("--agent",
                    help="可选；指定后额外检查该库可打开")
    sp.set_defaults(func=cmd_check)
    cmds["check"] = sp

    sp = sub.add_parser("migrate", help="把历史分库 data/<agent>.db 合并迁移进融合库 rag.db", formatter_class=fmt)
    sp.set_defaults(func=cmd_migrate)
    cmds["migrate"] = sp

    sp = sub.add_parser("help", help="查看命令详细帮助", formatter_class=fmt)
    sp.add_argument("command", nargs="?",
                    help="要查看的命令名（如 query）；省略则显示全部命令总览")
    sp.set_defaults(func=lambda a: cmd_help(a, p, cmds))
    cmds["help"] = sp

    return p


def main():
    p = build_parser()
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
