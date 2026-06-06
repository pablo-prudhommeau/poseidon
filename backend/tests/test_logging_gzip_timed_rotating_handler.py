from __future__ import annotations

import gzip
import logging
import time
from pathlib import Path

from src.logging.logging_gzip_timed_rotating_handler import PoseidonGzipTimedRotatingFileHandler


def create_timed_rotating_handler(
        log_file_path: Path,
        backup_count: int,
) -> PoseidonGzipTimedRotatingFileHandler:
    return PoseidonGzipTimedRotatingFileHandler(
        filename=str(log_file_path),
        when="D",
        interval=1,
        backupCount=backup_count,
        encoding="utf-8",
    )


def test_rotation_filename_appends_gzip_extension() -> None:
    handler = PoseidonGzipTimedRotatingFileHandler(
        filename="/tmp/poseidon.log",
        when="D",
        interval=1,
        backupCount=1,
        encoding="utf-8",
    )

    rotated_log_file_path = handler.rotation_filename("/tmp/poseidon.log.2026-06-05")

    assert rotated_log_file_path == "/tmp/poseidon.log.2026-06-05.gz"


def test_rotate_creates_gzip_archive_and_removes_source_file(tmp_path: Path) -> None:
    handler = create_timed_rotating_handler(log_file_path=tmp_path / "poseidon.log", backup_count=1)
    source_log_file_path = tmp_path / "poseidon.log.2026-06-05"
    destination_archive_path = tmp_path / "poseidon.log.2026-06-05.gz"
    source_log_file_path.write_text("rotated log content\n", encoding="utf-8")

    handler.rotate(
        source_log_file_path=str(source_log_file_path),
        destination_archive_path=str(destination_archive_path),
    )

    assert source_log_file_path.exists() is False
    assert destination_archive_path.exists() is True
    with gzip.open(destination_archive_path, "rt", encoding="utf-8") as compressed_archive_file:
        archive_content = compressed_archive_file.read()
    assert archive_content == "rotated log content\n"


def test_get_files_to_delete_removes_oldest_gzip_archives_beyond_backup_count(tmp_path: Path) -> None:
    log_file_path = tmp_path / "poseidon.log"
    handler = create_timed_rotating_handler(log_file_path=log_file_path, backup_count=2)

    archive_paths = [
        tmp_path / "poseidon.log.2026-06-01.gz",
        tmp_path / "poseidon.log.2026-06-02.gz",
        tmp_path / "poseidon.log.2026-06-03.gz",
    ]
    for archive_path in archive_paths:
        archive_path.write_bytes(b"archive")

    files_to_delete = handler.getFilesToDelete()

    assert files_to_delete == [str(tmp_path / "poseidon.log.2026-06-01.gz")]


def test_get_files_to_delete_includes_legacy_plain_rotated_files(tmp_path: Path) -> None:
    log_file_path = tmp_path / "poseidon.log"
    handler = create_timed_rotating_handler(log_file_path=log_file_path, backup_count=1)

    legacy_plain_log_file_path = tmp_path / "poseidon.log.2026-06-01"
    gzip_archive_path = tmp_path / "poseidon.log.2026-06-02.gz"
    legacy_plain_log_file_path.write_text("legacy plain log\n", encoding="utf-8")
    gzip_archive_path.write_bytes(b"archive")

    files_to_delete = handler.getFilesToDelete()

    assert files_to_delete == [str(legacy_plain_log_file_path)]


def test_rotated_log_file_is_gzipped_on_rollover(tmp_path: Path) -> None:
    log_file_path = tmp_path / "poseidon.log"
    log_file_path.write_text("active log line\n", encoding="utf-8")
    handler = create_timed_rotating_handler(log_file_path=log_file_path, backup_count=5)

    log_record = logging.LogRecord(
        name="poseidon.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="rotation trigger message",
        args=(),
        exc_info=None,
    )
    handler.emit(log_record)
    handler.rolloverAt = int(time.time()) - 1
    handler.doRollover()
    handler.close()

    gzip_archive_paths = list(tmp_path.glob("poseidon.log.*.gz"))
    plain_rotated_log_paths = [
        rotated_log_path
        for rotated_log_path in tmp_path.glob("poseidon.log.*")
        if rotated_log_path.suffix != ".gz"
    ]

    assert len(gzip_archive_paths) == 1
    assert plain_rotated_log_paths == []
    with gzip.open(gzip_archive_paths[0], "rt", encoding="utf-8") as compressed_archive_file:
        archive_content = compressed_archive_file.read()
    assert "rotation trigger message" in archive_content
