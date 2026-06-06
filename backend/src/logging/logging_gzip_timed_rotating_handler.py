from __future__ import annotations

import gzip
import logging
import os
import shutil
from logging.handlers import TimedRotatingFileHandler

rotation_logger = logging.getLogger("poseidon.logging.gzip_timed_rotating_handler")
compressed_archive_extension = ".gz"


class PoseidonGzipTimedRotatingFileHandler(TimedRotatingFileHandler):
    def rotation_filename(self, default_rotated_log_file_path: str) -> str:
        return default_rotated_log_file_path + compressed_archive_extension

    def rotate(self, source_log_file_path: str, destination_archive_path: str) -> None:
        try:
            with open(source_log_file_path, "rb") as source_log_file:
                with gzip.open(destination_archive_path, "wb") as compressed_archive_file:
                    shutil.copyfileobj(source_log_file, compressed_archive_file)
            os.remove(source_log_file_path)
        except OSError:
            rotation_logger.exception(
                "[LOGGING][ROTATION] Failed to gzip rotated log file from %s to %s",
                source_log_file_path,
                destination_archive_path,
            )
            raise

    def getFilesToDelete(self) -> list[str]:
        log_directory_path, base_log_file_name = os.path.split(self.baseFilename)
        directory_entries = os.listdir(log_directory_path)
        rotated_log_file_paths: list[str] = []
        rotated_log_file_prefix = base_log_file_name + "."
        rotated_log_file_prefix_length = len(rotated_log_file_prefix)

        for directory_entry in directory_entries:
            if directory_entry[:rotated_log_file_prefix_length] != rotated_log_file_prefix:
                continue

            rotated_log_suffix = directory_entry[rotated_log_file_prefix_length:]
            if rotated_log_suffix.endswith(compressed_archive_extension):
                rotated_log_suffix = rotated_log_suffix[: -len(compressed_archive_extension)]

            if self.extMatch.match(rotated_log_suffix):
                rotated_log_file_paths.append(os.path.join(log_directory_path, directory_entry))

        if len(rotated_log_file_paths) < self.backupCount:
            return []

        rotated_log_file_paths.sort()
        rotated_log_files_to_delete_count = len(rotated_log_file_paths) - self.backupCount
        return rotated_log_file_paths[:rotated_log_files_to_delete_count]
