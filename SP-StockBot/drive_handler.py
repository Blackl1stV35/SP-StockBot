"""
Google Drive integration for SP-StockBot.
Handles authentication, file uploads/downloads, and folder structure.
"""

import os
import json
import io
from typing import Optional, List, Dict, Any
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from config import Config
from logger import activity_logger


class DriveHandler:
    """Google Drive API client for SP-StockBot."""

    SCOPES = ["https://www.googleapis.com/auth/drive"]

    def __init__(self):
        """Initialize Drive API client."""
        self.service = None
        self._authenticate()

    def _authenticate(self) -> None:
        """Authenticate with Google Drive API using service account."""
        try:
            service_account_info = Config.get_google_service_account()

            credentials = Credentials.from_service_account_info(
                service_account_info, scopes=self.SCOPES
            )

            self.service = build("drive", "v3", credentials=credentials)
            activity_logger.logger.info("✓ Google Drive authenticated")

        except Exception as e:
            activity_logger.log_error(
                f"Failed to authenticate Google Drive: {e}",
                error_type="drive_auth_error",
            )
            raise

    def create_folder_structure(self, parent_folder_id: str) -> Dict[str, str]:
        """
        Create folder structure:
        OurFirmInventory/
          ├── Stock_2569/
          ├── Stock_2570/
          └── Archives/
        Returns mapping of folder names to IDs.
        """
        try:
            folders = {}

            # Create main folder
            main_folder = self._create_folder(
                "OurFirmInventory", parent_folder_id
            )
            folders["OurFirmInventory"] = main_folder

            # Create year folders (Thai year)
            year_folders = ["Stock_2569", "Stock_2570", "Stock_2571"]
            for year_folder in year_folders:
                year_id = self._create_folder(year_folder, main_folder)
                folders[year_folder] = year_id

            # Create archives folder
            archives_id = self._create_folder("Archives", main_folder)
            folders["Archives"] = archives_id

            activity_logger.logger.info(
                f"✓ Created Drive folder structure: {folders}"
            )
            return folders

        except Exception as e:
            activity_logger.log_error(
                f"Failed to create folder structure: {e}",
                error_type="drive_folder_error",
            )
            raise

    def _create_folder(self, folder_name: str, parent_id: str) -> str:
        """Create a single folder and return its ID."""
        try:
            file_metadata = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = self.service.files().create(
                body=file_metadata, fields="id"
            ).execute()

            return folder.get("id")

        except Exception as e:
            activity_logger.log_error(
                f"Failed to create folder '{folder_name}': {e}",
                error_type="drive_create_folder_error",
            )
            raise

    def upload_file(
        self,
        file_path: str,
        parent_folder_id: str,
        file_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Upload file to Google Drive.
        Returns file ID if successful, None otherwise.
        """
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")

            if file_name is None:
                file_name = os.path.basename(file_path)

            file_metadata = {
                "name": file_name,
                "parents": [parent_folder_id],
            }

            media = MediaFileUpload(file_path, resumable=True)

            file = self.service.files().create(
                body=file_metadata, media_body=media, fields="id"
            ).execute()

            file_id = file.get("id")
            activity_logger.logger.info(
                f"✓ Uploaded file: {file_name} (ID: {file_id})"
            )
            return file_id

        except Exception as e:
            activity_logger.log_error(
                f"Failed to upload file '{file_path}': {e}",
                error_type="drive_upload_error",
            )
            return None

    def download_file(
        self,
        file_id: str,
        output_path: str,
    ) -> bool:
        """
        Download file from Google Drive.
        Returns True if successful, False otherwise.
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            request = self.service.files().get_media(fileId=file_id)

            with open(output_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False

                while not done:
                    status, done = downloader.next_chunk()

            activity_logger.logger.info(
                f"✓ Downloaded file: {output_path} (ID: {file_id})"
            )
            return True

        except Exception as e:
            activity_logger.log_error(
                f"Failed to download file '{file_id}': {e}",
                error_type="drive_download_error",
            )
            return False

    def list_files(
        self,
        folder_id: str,
        file_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List files in a folder.
        file_type: 'xlsx', 'pdf', full mimeType, or None for all.
        """
        try:
            mime_types = {
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pdf": "application/pdf",
                "folder": "application/vnd.google-apps.folder",
            }

            query = f"'{folder_id}' in parents and trashed=false"

            if file_type and file_type in mime_types:
                query += f" and mimeType='{mime_types[file_type]}'"
            elif file_type and file_type.startswith("application/"):
                query += f" and mimeType='{file_type}'"

            results = (
                self.service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(id, name, mimeType, createdTime, size)",
                    pageSize=limit,
                    orderBy="createdTime desc",
                )
                .execute()
            )

            return results.get("files", [])

        except Exception as e:
            activity_logger.log_error(
                f"Failed to list files in {folder_id}: {e}",
                error_type="drive_list_error",
            )
            return []

    def find_latest_xlsx(self, folder_id: str) -> Optional[Dict[str, Any]]:
        """Find the most recently uploaded .xlsx file."""
        try:
            files = self.list_files(folder_id, file_type="xlsx", limit=1)
            if files:
                return files[0]
            return None

        except Exception as e:
            activity_logger.log_error(
                f"Failed to find latest xlsx: {e}",
                error_type="drive_find_xlsx_error",
            )
            return None

    def get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed file information."""
        try:
            file = self.service.files().get(
                fileId=file_id,
                fields="id, name, mimeType, createdTime, size, parents",
            ).execute()

            return file

        except Exception as e:
            activity_logger.log_error(
                f"Failed to get file info for {file_id}: {e}",
                error_type="drive_file_info_error",
            )
            return None

    def share_folder_with_bot(
        self,
        folder_id: str,
        bot_service_account_email: str,
    ) -> bool:
        """
        Share folder with bot's service account (required for uploads).
        """
        try:
            permission = {
                "type": "user",
                "role": "writer",
                "emailAddress": bot_service_account_email,
            }

            self.service.permissions().create(
                fileId=folder_id, body=permission
            ).execute()

            activity_logger.logger.info(
                f"✓ Shared folder {folder_id} with {bot_service_account_email}"
            )
            return True

        except Exception as e:
            activity_logger.log_error(
                f"Failed to share folder: {e}",
                error_type="drive_share_error",
            )
            return False

    def move_file(self, file_id: str, new_parent_id: str) -> bool:
        """Move file to different folder."""
        try:
            # Get current parents
            file = self.service.files().get(
                fileId=file_id, fields="parents"
            ).execute()

            previous_parents = ",".join(file.get("parents", []))

            # Move file
            self.service.files().update(
                fileId=file_id,
                addParents=new_parent_id,
                removeParents=previous_parents,
                fields="id, parents",
            ).execute()

            activity_logger.logger.info(
                f"✓ Moved file {file_id} to {new_parent_id}"
            )
            return True

        except Exception as e:
            activity_logger.log_error(
                f"Failed to move file {file_id}: {e}",
                error_type="drive_move_error",
            )
            return False

    def delete_file(self, file_id: str) -> bool:
        """Delete file from Drive."""
        try:
            self.service.files().delete(fileId=file_id).execute()
            activity_logger.logger.info(f"✓ Deleted file {file_id}")
            return True

        except Exception as e:
            activity_logger.log_error(
                f"Failed to delete file {file_id}: {e}",
                error_type="drive_delete_error",
            )
            return False


# Global instance
_drive_handler: Optional[DriveHandler] = None


def get_drive_handler() -> DriveHandler:
    """Get or create Drive handler instance."""
    global _drive_handler
    if _drive_handler is None:
        _drive_handler = DriveHandler()
    return _drive_handler


if __name__ == "__main__":
    # Test Drive integration
    try:
        handler = DriveHandler()
        print("✓ Google Drive authentication successful")

        # Test listing files in root
        if Config.GOOGLE_DRIVE_FOLDER_ID:
            files = handler.list_files(
                Config.GOOGLE_DRIVE_FOLDER_ID, limit=5
            )
            print(f"Files in {Config.GOOGLE_DRIVE_FOLDER_ID}:")
            for f in files:
                print(f"  - {f['name']} (ID: {f.get('id')})")
        else:
            print("GOOGLE_DRIVE_FOLDER_ID not configured")

    except Exception as e:
        print(f"✗ Error: {e}")
