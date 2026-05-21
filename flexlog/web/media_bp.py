"""Sandboxed media file serving — decrypts chunked AES-GCM on the fly with
HTTP byte-range support."""
from __future__ import annotations

import re

from flask import (
    Blueprint, Response, abort, current_app, request, stream_with_context,
)

from flexlog import paths
from flexlog.crypto import (
    FILE_HEADER_SIZE, GCM_TAG_LEN, decrypt_file_full, parse_header,
    derive_chunk_nonce, derive_fek,
)
from flexlog.paths import FileKeyError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

media_bp = Blueprint("media", __name__)

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _file_sha_from_key(file_key: str) -> str:
    """uploads/aa/bb/<sha>.<ext> → <sha>."""
    name = file_key.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0]


def _guess_mime(file_key: str) -> str:
    ext = file_key.rsplit(".", 1)[-1].lower()
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "webp": "image/webp",
        "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/x-m4a",
        "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
    }.get(ext, "application/octet-stream")


@media_bp.get("/media/<path:file_key>")
def serve(file_key: str):
    try:
        # Validate the file_key shape (raises FileKeyError on traversal).
        # Don't open the file directly — let the storage backend handle bytes.
        paths.resolve_file_key(file_key)
    except FileKeyError:
        abort(404)

    from flexlog.storage import get_storage
    storage = get_storage()
    if not storage.exists(file_key):
        abort(404)

    master_key = current_app.config.get("MASTER_KEY")
    if master_key is None:
        abort(403)  # shouldn't happen — auth gate runs first

    file_sha = _file_sha_from_key(file_key)
    mime = _guess_mime(file_key)

    # Read the 16-byte header to learn plaintext_size + chunk_size.
    header_bytes = storage.get_range(file_key, 0, FILE_HEADER_SIZE - 1)
    header = parse_header(header_bytes)

    range_header = request.headers.get("Range", "")
    if range_header:
        m = _RANGE_RE.match(range_header.strip())
        if not m:
            abort(416)
        s, e = m.group(1), m.group(2)
        if s == "" and e == "":
            abort(416)
        if s == "":
            # suffix: bytes=-N → last N bytes
            n = int(e)
            start = max(0, header.plaintext_size - n)
            end = header.plaintext_size - 1
        else:
            start = int(s)
            end = int(e) if e else header.plaintext_size - 1
        if start >= header.plaintext_size or end < start:
            return Response(status=416, headers={
                "Content-Range": f"bytes */{header.plaintext_size}"
            })
        if end >= header.plaintext_size:
            end = header.plaintext_size - 1
        return _range_response(storage, file_key, header, master_key, file_sha, start, end, mime)

    # No Range: stream the whole thing as 200
    return _full_response(storage, file_key, header, master_key, file_sha, mime)


# Max encrypted bytes fetched per storage.get_range call. Tuning trade-off:
# bigger = fewer S3 round trips per Range request (smoother video), but
# more memory held by the worker. 8 MiB covers most browser Range requests
# (typically 1-4 MiB) in a single GET, while capping memory growth for
# unusual large-Range requests (e.g., player asking for bytes=0- on a
# 2 GB video — we'd batch through it 8 MiB at a time instead of holding
# all 2 GB resident).
_BATCH_BYTES = 8 * 1024 * 1024
_CACHE_CONTROL = "private, max-age=31536000, immutable"


def _stream_range(storage, file_key, header, master_key, file_sha,
                  start: int, end: int):
    """Generator: yield plaintext bytes covering [start, end] inclusive.

    Coalesces what would otherwise be one storage.get_range call per
    encrypted chunk into batched fetches of up to _BATCH_BYTES. For a
    typical 1-4 MiB browser Range request, this is a SINGLE S3 GET
    instead of 16-64 sequential ones — the difference between smooth
    video playback and stuttering.
    """
    cs = header.chunk_size
    enc_chunk_full = cs + GCM_TAG_LEN
    first_chunk = start // cs
    last_chunk = end // cs
    last_is_tail = (last_chunk == header.total_chunks - 1)
    if last_is_tail:
        last_enc_len = (header.plaintext_size - last_chunk * cs) + GCM_TAG_LEN
    else:
        last_enc_len = enc_chunk_full
    first_offset = FILE_HEADER_SIZE + first_chunk * enc_chunk_full
    last_byte = (
        FILE_HEADER_SIZE + last_chunk * enc_chunk_full + last_enc_len - 1
    )

    fek = derive_fek(master_key, file_sha)
    aead = AESGCM(fek)

    buf = bytearray()
    chunk_idx = first_chunk
    pos = first_offset
    while chunk_idx <= last_chunk:
        # Refill the buffer if we don't have enough bytes for the next
        # full chunk.
        if chunk_idx == header.total_chunks - 1:
            need = (header.plaintext_size - chunk_idx * cs) + GCM_TAG_LEN
        else:
            need = enc_chunk_full
        if len(buf) < need and pos <= last_byte:
            batch_end = min(pos + _BATCH_BYTES - 1, last_byte)
            buf += storage.get_range(file_key, pos, batch_end)
            pos = batch_end + 1
            continue  # re-check after fill
        ct = bytes(buf[:need])
        del buf[:need]
        nonce = derive_chunk_nonce(master_key, file_sha, chunk_idx)
        pt = aead.decrypt(nonce, ct, chunk_idx.to_bytes(4, "big"))
        lo = (start % cs) if chunk_idx == first_chunk else 0
        hi = ((end % cs) + 1) if chunk_idx == last_chunk else len(pt)
        yield pt[lo:hi]
        chunk_idx += 1


def _full_response(storage, file_key, header, master_key, file_sha, mime):
    gen = _stream_range(
        storage, file_key, header, master_key, file_sha,
        start=0, end=header.plaintext_size - 1,
    )
    resp = Response(stream_with_context(gen), mimetype=mime)
    resp.headers["Content-Length"] = str(header.plaintext_size)
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Cache-Control"] = _CACHE_CONTROL
    return resp


def _range_response(storage, file_key, header, master_key, file_sha,
                    start, end, mime):
    gen = _stream_range(
        storage, file_key, header, master_key, file_sha, start, end,
    )
    resp = Response(stream_with_context(gen), status=206, mimetype=mime)
    resp.headers["Content-Range"] = f"bytes {start}-{end}/{header.plaintext_size}"
    resp.headers["Content-Length"] = str(end - start + 1)
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Cache-Control"] = _CACHE_CONTROL
    return resp
