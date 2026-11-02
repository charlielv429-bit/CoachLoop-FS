"""Local SQLite knowledge history only; no production SQLAlchemy/DB configuration.

One owner-only directory, append-only transactions, strict replay on every read.
The shared knowledge registry is not a store for private plans or student data.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat

from integrations.reviewed_training.json_codec import decode
from .registry import Registry, RegistryError, Knowledge, Archive, presented

DEFAULT_DIRECTORY = Path(__file__).resolve().parents[3] / '.local' / 'coachloop-kb'


class PersistenceError(RuntimeError):
    pass


def private_directory(directory):
    path = Path(directory).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise PersistenceError('Knowledge directory must not contain symlinks')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PersistenceError('Knowledge directory must be owned by this OS user with mode 0700')
    return path


class SQLiteRegistry(Registry):
    storage_description = '本地共享知识库 SQLite；所有已授权本机会话可访问。知识与历史重启保留，不保存私有教案或学生资料。'

    def __init__(self, directory=DEFAULT_DIRECTORY):
        super().__init__()
        self.directory = private_directory(directory)
        self.path = self.directory / 'knowledge.sqlite3'
        self._connection = None
        try:
            # Precreate securely; SQLite journals inherit the DB's private mode.
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
            info = self.path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise PersistenceError('Knowledge database must be a private regular file (0600)')
            for suffix in ('-journal', '-wal', '-shm'):
                sidecar = Path(str(self.path) + suffix)
                if sidecar.exists() or sidecar.is_symlink():
                    extra = sidecar.lstat()
                    if not stat.S_ISREG(extra.st_mode) or extra.st_uid != os.getuid() or extra.st_nlink != 1 or stat.S_IMODE(extra.st_mode) != 0o600:
                        raise PersistenceError('Unsafe SQLite sidecar file')
            self._connection = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=5)
            self._connection.execute('PRAGMA trusted_schema=OFF')
            self._connection.execute('PRAGMA temp_store=MEMORY')
            self._connection.execute('PRAGMA synchronous=FULL')
            self._connection.execute('PRAGMA journal_mode=DELETE')
            with self._transaction(write=True):
                version = self._connection.execute('PRAGMA user_version').fetchone()[0]
                if version == 0:
                    if self._connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                        raise PersistenceError('Unknown SQLite schema; no automatic overwrite')
                    self._connection.execute('CREATE TABLE revisions (knowledge_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0), payload TEXT NOT NULL, PRIMARY KEY(knowledge_id, version))')
                    self._connection.execute("CREATE TRIGGER no_revision_update BEFORE UPDATE ON revisions BEGIN SELECT RAISE(ABORT,'append only'); END")
                    self._connection.execute("CREATE TRIGGER no_revision_delete BEFORE DELETE ON revisions BEGIN SELECT RAISE(ABORT,'append only'); END")
                    self._connection.execute('PRAGMA user_version=1')
                elif version != 1:
                    raise PersistenceError('Unsupported SQLite schema version')
                self._load()
        except Exception as error:
            if self._connection is not None:
                self._connection.close()
            self._connection = None
            if isinstance(error, PersistenceError):
                raise
            raise PersistenceError('Knowledge database cannot be opened or validated; original data retained') from None

    @contextmanager
    def _transaction(self, write=False):
        with self._lock:
            if self._connection is None:
                raise PersistenceError('Knowledge database is closed')
            try:
                self._connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield
                self._connection.execute('COMMIT')
            except Exception as error:
                if self._connection.in_transaction:
                    self._connection.execute('ROLLBACK')
                self._history = {}
                if isinstance(error, (RegistryError, PersistenceError)):
                    raise
                raise PersistenceError('Knowledge transaction failed; no partial write') from None

    def _load(self):
        sizes = self._connection.execute('SELECT length(CAST(payload AS BLOB)) FROM revisions LIMIT 501').fetchall()
        if len(sizes) > 500 or any(size is None or size > 128*1024 for (size,) in sizes):
            raise PersistenceError('Knowledge database exceeds supported capacity')
        rows = self._connection.execute('SELECT knowledge_id, version, payload FROM revisions ORDER BY knowledge_id, version LIMIT 501').fetchall()
        entries = []
        for knowledge_id, version, payload in rows:
            entry = Knowledge.model_validate(decode(payload))
            if entry.knowledge_id != knowledge_id or entry.version != version:
                raise PersistenceError('Knowledge row identity mismatch')
            entries.append(entry)
        self._history = {}
        self._history = self._merged(entries)

    def import_archive(self, archive):
        archive = Archive.model_validate(archive.model_dump())
        with self._transaction(write=True):
            self._load()
            proposed = self._merged(archive.entries)
            self._connection.executemany('INSERT INTO revisions(knowledge_id,version,payload) VALUES(?,?,?)',
                [(entry.knowledge_id,entry.version,entry.model_dump_json()) for entry in archive.entries])
            self._history = proposed
        return {'imported_versions': len(archive.entries)}

    def save(self, entry):
        entry = Knowledge.model_validate(entry.model_dump())
        self.import_archive(Archive(entries=[entry]))
        return presented(entry)

    def export(self):
        with self._transaction():
            self._load()
            return super().export()

    def history(self, knowledge_id):
        with self._transaction():
            self._load()
            return super().history(knowledge_id)

    def search(self, category=None, lesson_id=None, keyword=''):
        with self._transaction():
            self._load()
            return super().search(category,lesson_id,keyword)

    def clear(self):
        # Lifecycle cleanup must never DELETE persistent history.
        self.close()

    def close(self):
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._history.clear()


def review_materials(registry):
    """Inspectable source/content snapshots; no certification or importable approval."""
    return {'schema_version':'coachloop-offline-review-v1', 'status':'pending_review',
            'warning':'离线待审核材料，不是已核实依据或专项认证；普通导入不接受审核通过状态。',
            'archive':registry.export(),
            'review_checklist':['核对来源原文及定位','核对内容与引用支持关系','核查专项准确性、安全及适用范围','在可信渠道记录审核人及意见；本应用不认证身份']}
