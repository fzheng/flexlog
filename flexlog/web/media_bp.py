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
        target = paths.resolve_file_key(file_key)
    except FileKeyError:
        abort(404)
    if not target.is_file():
        abort(404)

    master_key = current_app.config.get("MASTER_KEY")
    if master_key is None:
        abort(403)  # shouldn't happen — auth gate runs first

    file_sha = _file_sha_from_key(file_key)
    mime = _guess_mime(file_key)

    # Read header to learn plaintext_size + chunk_size
    with target.open("rb") as f:
        header = parse_header(f.read(FILE_HEADER_SIZE))

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
        return _range_response(target, header, master_key, file_sha, start, end, mime)

    # No Range: stream the whole thing as 200
    return _full_response(target, header, master_key, file_sha, mime)


def _full_response(target, header, master_key, file_sha, mime):
    def gen():
        fek = derive_fek(master_key, file_sha)
        aead = AESGCM(fek)
        with target.open("rb") as f:
            f.seek(FILE_HEADER_SIZE)
            for i in range(header.total_chunks):
                if i == header.total_chunks - 1:
                    remainder = header.plaintext_size - i * header.chunk_size
                    enc_len = remainder + GCM_TAG_LEN
                else:
                    enc_len = header.chunk_size + GCM_TAG_LEN
                ct = f.read(enc_len)
                nonce = derive_chunk_nonce(master_key, file_sha, i)
                yield aead.decrypt(nonce, ct, i.to_bytes(4, "big"))

    resp = Response(stream_with_context(gen()), mimetype=mime)
    resp.headers["Content-Length"] = str(header.plaintext_size)
    resp.headers["Accept-Ranges"] = "bytes"
    return resp


def _range_response(target, header, master_key, file_sha, start, end, mime):
    cs = header.chunk_size
    first_chunk = start // cs
    last_chunk = end // cs
    enc_chunk_full = cs + GCM_TAG_LEN

    def gen():
        fek = derive_fek(master_key, file_sha)
        aead = AESGCM(fek)
        with target.open("rb") as f:
            f.seek(FILE_HEADER_SIZE + first_chunk * enc_chunk_full)
            for i in range(first_chunk, last_chunk + 1):
                if i == header.total_chunks - 1:
                    remainder = header.plaintext_size - i * cs
                    enc_len = remainder + GCM_TAG_LEN
                else:
                    enc_len = enc_chunk_full
                ct = f.read(enc_len)
                nonce = derive_chunk_nonce(master_key, file_sha, i)
                pt = aead.decrypt(nonce, ct, i.to_bytes(4, "big"))
                lo = (start % cs) if i == first_chunk else 0
                hi = ((end % cs) + 1) if i == last_chunk else len(pt)
                yield pt[lo:hi]

    resp = Response(stream_with_context(gen()), status=206, mimetype=mime)
    resp.headers["Content-Range"] = f"bytes {start}-{end}/{header.plaintext_size}"
    resp.headers["Content-Length"] = str(end - start + 1)
    resp.headers["Accept-Ranges"] = "bytes"
    return resp
