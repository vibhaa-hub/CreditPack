"""Uploaded-file storage reachable from every LDU (design D7; deployable-units: files reachable
from every LDU).

A document's location is a local path (LocalFileStore, single-process mode) or an `s3://bucket/key`
URI (S3FileStore: MinIO locally, or any S3-compatible store). It is kept in the document record's
`uri` and in the `documents.path` column, so document IDs, hashes and provenance do not change.

  CPA_FILE_STORE   local (default) | s3
  CPA_UPLOAD_DIR   root folder for local storage
  CPA_S3_BUCKET, CPA_S3_ENDPOINT_URL, CPA_S3_PREFIX, plus the usual AWS_ACCESS_KEY_ID /
  AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION for s3."""
import os
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent / ".adk" / "uploads"


def safe_name(filename: str) -> str:
    return "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._- ")[:120] or "upload"


class FileStore:
    def put(self, sid: str, name: str, data: bytes) -> str: ...
    def get(self, uri: str) -> bytes: ...
    def exists(self, uri: str) -> bool: ...


class LocalFileStore(FileStore):
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getenv("CPA_UPLOAD_DIR") or DEFAULT_ROOT)

    def put(self, sid, name, data):
        folder = self.root / sid
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / name
        p.write_bytes(data)
        return str(p)

    def get(self, uri):
        return Path(uri.removeprefix("file://")).read_bytes()

    def exists(self, uri):
        return Path(uri.removeprefix("file://")).is_file()


class S3FileStore(FileStore):
    def __init__(self, bucket: str | None = None, endpoint_url: str | None = None, prefix: str | None = None,
                 client=None):
        self.bucket = bucket or os.environ["CPA_S3_BUCKET"]
        self.prefix = (prefix if prefix is not None else os.getenv("CPA_S3_PREFIX", "uploads")).strip("/")
        if client is None:
            import boto3
            client = boto3.client("s3", endpoint_url=endpoint_url or os.getenv("CPA_S3_ENDPOINT_URL") or None)
        self.s3 = client

    def _key(self, uri: str) -> tuple[str, str]:
        if not uri.startswith("s3://"):
            raise ValueError(f"not an s3 URI: {uri}")
        bucket, _, key = uri[5:].partition("/")
        return bucket, key

    def put(self, sid, name, data):
        key = "/".join(p for p in (self.prefix, sid, name) if p)
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}"

    def get(self, uri):
        bucket, key = self._key(uri)
        return self.s3.get_object(Bucket=bucket, Key=key)["Body"].read()

    def exists(self, uri):
        bucket, key = self._key(uri)
        try:
            self.s3.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:                                     # noqa: BLE001  (404 / access denied)
            return False


_store: FileStore | None = None


def get_file_store() -> FileStore:
    global _store
    if _store is None:
        kind = os.getenv("CPA_FILE_STORE", "local")
        _store = S3FileStore() if kind == "s3" else LocalFileStore()
    return _store


def set_file_store(store: FileStore | None) -> None:
    """Tests and the migration script point the process at another store."""
    global _store
    _store = store


def read(location: str) -> bytes:
    """Bytes of a stored document, wherever it is: an s3:// URI or a local path."""
    if location.startswith("s3://"):
        s = get_file_store()
        return (s if isinstance(s, S3FileStore) else S3FileStore()).get(location)
    return LocalFileStore().get(location)


def write_sidecar(location: str, suffix: str, data: bytes) -> None:
    """Store derived data next to a document (e.g. its extraction), in the same store."""
    if location.startswith("s3://"):
        s = get_file_store()
        s3 = s if isinstance(s, S3FileStore) else S3FileStore()
        bucket, key = s3._key(location)
        s3.s3.put_object(Bucket=bucket, Key=key + suffix, Body=data)
    else:
        # only inside the upload store: a document read from elsewhere (e.g. samples/) is cached in
        # memory only, so derived files never land in source folders
        p, s = Path(location.removeprefix("file://")).resolve(), get_file_store()
        if isinstance(s, LocalFileStore) and p.is_relative_to(s.root.resolve()):
            Path(str(p) + suffix).write_bytes(data)


def read_sidecar(location: str, suffix: str) -> bytes | None:
    try:
        return read(location + suffix)
    except Exception:                                         # noqa: BLE001  (missing: not derived yet)
        return None


def location(doc: dict) -> str:
    """Where a document record's bytes are (records made before `uri` existed only have `path`)."""
    return doc.get("uri") or doc["path"]
