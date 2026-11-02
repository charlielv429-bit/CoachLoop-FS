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
from .review import EvidenceReport, AuthenticatedDecision, knowledge_digest, authenticated, read_key

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

    def __init__(self, directory=DEFAULT_DIRECTORY, *, review_key_file=None):
        super().__init__()
        self._review_key = read_key(review_key_file) if review_key_file is not None else None
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
                elif version not in (1,2):
                    raise PersistenceError('Unsupported SQLite schema version')
                if version in (0,1):
                    for table in ('evidence_reports','review_decisions'):
                        self._connection.execute(f'CREATE TABLE {table} (record_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                        self._connection.execute(f"CREATE TRIGGER no_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'append only'); END")
                        self._connection.execute(f"CREATE TRIGGER no_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'append only'); END")
                    self._connection.execute('PRAGMA user_version=2')
                self._load()
                self._reports()
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

    def _reports(self):
        sizes=self._connection.execute('SELECT length(CAST(payload AS BLOB)) FROM evidence_reports LIMIT 501').fetchall()
        if len(sizes)>500 or any(size is None or size>128*1024 for (size,) in sizes):raise PersistenceError('Evidence capacity exceeded')
        rows=self._connection.execute('SELECT record_id,payload FROM evidence_reports LIMIT 501').fetchall()
        if len(rows)>500:raise PersistenceError('Too many evidence reports')
        result=[]
        for record_id,payload in rows:
            report=EvidenceReport.model_validate(decode(payload))
            if report.evidence_id!=record_id:raise PersistenceError('Evidence identity mismatch')
            result.append(report)
        return result

    def _entry(self, knowledge_id, version):
        versions=self._history.get(knowledge_id,[])
        if not 1<=version<=len(versions):raise RegistryError('Knowledge version does not exist')
        return versions[version-1]

    def save_report(self, report):
        report=EvidenceReport.model_validate(report.model_dump())
        self.save_reports([report])
        return {'evidence_id':report.evidence_id,'system_trusted':False,'status':'reported_not_verified'}

    def save_reports(self, reports):
        reports=[EvidenceReport.model_validate(report.model_dump()) for report in reports]
        with self._transaction(write=True):
            self._load()
            existing=self._reports();ids={r.evidence_id for r in existing}
            for report in reports:
                entry=self._entry(report.knowledge_id,report.knowledge_version)
                if knowledge_digest(entry.model_dump())!=report.knowledge_digest or report.source_id!=entry.source_id:
                    raise RegistryError('Evidence must bind the exact existing knowledge and source')
                if report.evidence_id in ids:raise RegistryError('Evidence ID already exists')
                ids.add(report.evidence_id)
            if len(existing)+len(reports)>500 or sum(len(r.model_dump_json().encode()) for r in [*existing,*reports])>900*1024:
                raise RegistryError('Evidence capacity reached')
            self._connection.executemany('INSERT INTO evidence_reports VALUES(?,?)',[(r.evidence_id,r.model_dump_json()) for r in reports])
        return {'registered_reports':len(reports),'system_trusted':False}

    def evidence_reports(self, knowledge_id=None):
        with self._transaction():
            return [r.model_dump() for r in self._reports() if knowledge_id is None or r.knowledge_id==knowledge_id]

    def _decision_supported(self, record):
        entry=self._entry(record.knowledge_id,record.knowledge_version)
        if (knowledge_digest(entry.model_dump())!=record.knowledge_digest or record.approved_statement!=entry.content
                or not set(record.lesson_ids)<=set(entry.lesson_ids) or len(set(record.lesson_ids))!=len(record.lesson_ids)
                or not all((entry.source_id,entry.source_title,entry.source_locator))
                or entry.content_kind in ('catalogue_lead','unspecified')):
            raise RegistryError('Decision does not bind an eligible exact statement/version')
        reports={r.evidence_id:r for r in self._reports()}
        source=reports.get(record.source_evidence_id);specialist=reports.get(record.specialist_evidence_id)
        if source is None or specialist is None:raise RegistryError('Independent source and specialist evidence required')
        for report in (source,specialist):
            if (report.knowledge_digest!=record.knowledge_digest or report.knowledge_id!=record.knowledge_id
                    or report.knowledge_version!=record.knowledge_version or report.source_id!=entry.source_id):
                raise RegistryError('Review evidence binding mismatch')
        if (source.kind!='source_report' or source.basis_kind!='original_source_excerpt'
                or source.locator!=entry.source_locator or not source.reviewer
                or specialist.kind!='specialist_report' or specialist.basis_kind!='specialist_review'
                or not specialist.reviewer or specialist.reviewer!=record.reviewer):
            raise RegistryError('Original-page verification and explicit specialist review are required')
        return entry

    def apply_decision(self, envelope, *, source_artifact=None, specialist_artifact=None):
        # Offline operator entry only. No web route dispatches to this method.
        envelope=AuthenticatedDecision.model_validate(envelope.model_dump())
        if not authenticated(envelope,self._review_key):raise RegistryError('Review authentication unavailable or invalid')
        with self._transaction(write=True):
            self._load()
            record=envelope.record
            self._decision_supported(record)
            if record.decision=='approved_for_lesson_draft':
                import hashlib
                reports={r.evidence_id:r for r in self._reports()}
                for path,report_id in ((source_artifact,record.source_evidence_id),(specialist_artifact,record.specialist_evidence_id)):
                    if path is None:raise RegistryError('Original evidence artifacts required for offline approval')
                    hasher=hashlib.sha256();size=0
                    with Path(path).open('rb') as file:
                        while True:
                            block=file.read(1024*1024)
                            if not block:break
                            size+=len(block)
                            if size>100*1024*1024:raise RegistryError('Evidence artifact too large')
                            hasher.update(block)
                    if not size or hasher.hexdigest()!=reports[report_id].artifact_sha256:
                        raise RegistryError('Evidence artifact hash mismatch')
            if self._connection.execute('SELECT 1 FROM review_decisions WHERE record_id=?',(record.review_id,)).fetchone():
                raise RegistryError('Review ID already exists')
            if self._connection.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0]>=500:
                raise RegistryError('Review capacity reached')
            self._connection.execute('INSERT INTO review_decisions VALUES(?,?)',(record.review_id,envelope.model_dump_json()))
        return {'review_id':record.review_id,'decision':record.decision,'identity_assurance':'local_operator_attestation_only'}

    def teaching_evidence(self, lesson_id):
        if self._review_key is None:return []
        with self._transaction():
            self._load()
            sizes=self._connection.execute('SELECT length(CAST(payload AS BLOB)) FROM review_decisions LIMIT 501').fetchall()
            if len(sizes)>500 or any(size is None or size>128*1024 for (size,) in sizes):raise PersistenceError('Review capacity exceeded')
            rows=self._connection.execute('SELECT payload FROM review_decisions ORDER BY rowid LIMIT 501').fetchall()
            latest={}
            for (payload,) in rows:
                envelope=AuthenticatedDecision.model_validate(decode(payload))
                if not authenticated(envelope,self._review_key):continue
                record=envelope.record
                latest[(record.knowledge_id,record.knowledge_version)]=record
            result=[]
            for record in latest.values():
                if record.decision!='approved_for_lesson_draft' or lesson_id not in record.lesson_ids:continue
                versions=self._history.get(record.knowledge_id,[])
                if not versions or versions[-1].version!=record.knowledge_version:continue
                try:entry=self._decision_supported(record)
                except RegistryError:continue
                result.append(dict(knowledge_id=entry.knowledge_id,category=entry.category,version=entry.version,source_id=entry.source_id,
                    source_title=entry.source_title,source_locator=entry.source_locator,chapter=entry.chapter,
                    statement=record.approved_statement,content_kind=entry.content_kind,review_id=record.review_id,
                    source_evidence_id=record.source_evidence_id,specialist_evidence_id=record.specialist_evidence_id,
                    source_content_verified=True,specialist_confirmed=True,system_review_status='operator_authenticated',
                    identity_assurance='local_operator_attestation_only',applicability_limitations=entry.applicability_limitations))
            return result

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
            'archive':registry.export(), 'evidence_reports':registry.evidence_reports(),
            'review_checklist':['核对来源原文及定位','核对内容与引用支持关系','核查专项准确性、安全及适用范围','在可信渠道记录审核人及意见；本应用不认证身份']}
