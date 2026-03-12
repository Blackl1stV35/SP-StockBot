"""
Google Drive integration for SP-StockBot.
Handles authentication, file listing, and folder operations.
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
from googleapiclient.errors import HttpError

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

            self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            activity_logger.logger.info("✓ Google Drive authenticated successfully")

            # Test minimal access
            self.service.files().get(fileId="root", fields="id").execute()
            activity_logger.logger.debug("Drive API test call succeeded")

        except ValueError as e:
            activity_logger.logger.warning(
                f"Google Drive credentials not configured: {e}. Drive features unavailable."
            )
            self.service = None

        except HttpError as e:
            activity_logger.log_error(
                f"Drive API authentication failed: {e}",
                error_type="drive_auth_http_error"
            )
            self.service = None

        except Exception as e:
            activity_logger.log_error(
                f"Unexpected error authenticating Drive: {e}",
                error_type="drive_auth_error"
            )
            self.service = None

    def get_folder_files(self, folder_id: str, mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", limit: int = 10) -> List[Dict[str, Any]]:
        """List XLSX files in a specific folder."""
        if not self.service:
            activity_logger.logger.warning("Drive service not available - authentication failed")
            return []

        if not folder_id:
            activity_logger.logger.warning("No folder ID provided for file listing")
            return []

        try:
            # Log the query details for debugging
            mime_type_short = mime_type.split("/")[-1] if "+" not in mime_type else "xlsx"
            activity_logger.logger.debug(
                f"[Drive] Querying folder: {folder_id} | MIME: {mime_type_short} | Limit: {limit}"
            )

            query = f"'{folder_id}' in parents and trashed=false and mimeType='{mime_type}'"
            
            activity_logger.logger.debug(f"[Drive] Query: {query}")
            
            results = self.service.files().list(
                q=query,
                spaces="drive",
                fields="files(id, name, mimeType, createdTime, size)",
                pageSize=limit,
                orderBy="createdTime desc"
            ).execute()

            files = results.get("files", [])
            
            activity_logger.logger.info(
                f"[Drive] Found {len(files)} files in folder {folder_id} | "
                f"Folder: {folder_id}"
            )
            
            for file in files:
                activity_logger.logger.debug(
                    f"[Drive] File: {file.get('name')} | ID: {file.get('id')} | "
                    f"Size: {file.get('size', 0)} bytes"
                )
            
            return files

        except HttpError as e:
            error_code = e.resp.status if hasattr(e, 'resp') else 'unknown'
            activity_logger.log_error(
                f"Failed to list files in {folder_id}: HTTP {error_code} - {e}",
                error_type=f"drive_list_error_{error_code}"
            )
            return []

        except Exception as e:
            activity_logger.log_error(
                f"Unexpected error listing files in {folder_id}: {e}",
                error_type="drive_list_unexpected"
            )
            return []

    def scan_recursive(self, folder_id: str, file_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Recursively scan folder and all subfolders for files.
        Also returns root-level files (loose XLSX at target folder level).
        
        Args:
            folder_id: Root folder to scan
            file_types: List of file types to find ['xlsx', 'pdf', 'docx'] or None for all
        
        Returns:
            List of file dicts with 'id', 'name', 'path', 'mimeType', 'size'
        """
        if not self.service:
            activity_logger.logger.warning("[Drive] Service not available")
            return []
        
        if not file_types:
            file_types = ['xlsx', 'pdf', 'docx']
        
        mime_types = {
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }
        
        found_files = []
        visited_folders = set()
        
        def scan_folder(folder_id_curr: str, path_prefix: str = ""):
            """Helper: recursively scan a folder."""
            if folder_id_curr in visited_folders:
                return
            visited_folders.add(folder_id_curr)
            
            try:
                # Query all items in this folder
                query = f"'{folder_id_curr}' in parents and trashed=false"
                
                results = self.service.files().list(
                    q=query,
                    spaces="drive",
                    fields="files(id, name, mimeType, createdTime, size)",
                    pageSize=100
                ).execute()
                
                items = results.get("files", [])
                activity_logger.logger.debug(
                    f"[Drive] Scan: {folder_id_curr[:8]}... found {len(items)} items at path '{path_prefix}'"
                )
                
                for item in items:
                    item_name = item.get('name', 'Unknown')
                    item_mime = item.get('mimeType', '')
                    item_id = item.get('id', '')
                    item_path = f"{path_prefix}/{item_name}" if path_prefix else item_name
                    
                    # Process file if matches desired types
                    if item_mime != 'application/vnd.google-apps.folder':
                        # Check if this is a wanted file type
                        for ft in file_types:
                            if mime_types[ft] == item_mime:
                                found_files.append({
                                    'id': item_id,
                                    'name': item_name,
                                    'path': item_path,
                                    'mimeType': item_mime,
                                    'size': item.get('size', 0),
                                    'createdTime': item.get('createdTime', '')
                                })
                                activity_logger.logger.debug(
                                    f"[Drive] Found: {item_path} ({item_mime})"
                                )
                                break
                    else:
                        # Recursively scan subfolder
                        scan_folder(item_id, item_path)
                
            except Exception as e:
                activity_logger.logger.warning(
                    f"[Drive] Error scanning {folder_id_curr}: {e}"
                )
        
        # Start recursive scan
        activity_logger.logger.info(
            f"[Drive] Starting recursive scan of {folder_id} for types: {file_types}"
        )
        scan_folder(folder_id)
        
        activity_logger.logger.info(
            f"[Drive] Recursive scan complete: found {len(found_files)} files"
        )
        for f in found_files:
            activity_logger.logger.info(
                f"[Drive] - {f['path']} ({f.get('size', 0)} bytes)"
            )
        
        return found_files

    def create_folder_structure(self, parent_folder_id: str = None) -> Dict[str, str]:
        """
        Create standard folder structure if needed.
        Returns mapping of folder names to IDs.
        """
        if not self.service:
            return {}

        folders = {
            "OurFirmInventory": parent_folder_id,
            "Stock_2569": None,
            "Archives": None,
        }

        for name, parent in folders.items():
            if parent is None:
                parent = "root" if name == "OurFirmInventory" else folders["OurFirmInventory"]

            query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and '{parent}' in parents and trashed=false"
            response = self.service.files().list(q=query, fields="files(id, name)").execute()
            existing = response.get("files", [])

            if existing:
                folders[name] = existing[0]["id"]
                activity_logger.logger.info(f"Found existing folder {name} (ID: {folders[name]})")
            else:
                file_metadata = {
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent] if parent != "root" else []
                }
                folder = self.service.files().create(body=file_metadata, fields="id").execute()
                folders[name] = folder.get("id")
                activity_logger.logger.info(f"Created folder {name} (ID: {folders[name]})")

        return folders

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
        if not self.service:
            activity_logger.logger.warning(
                "Google Drive not authenticated. File upload skipped."
            )
            return None
        
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
        if not self.service:
            activity_logger.logger.warning(
                "Google Drive not authenticated. File download skipped."
            )
            return False
        
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
        if not self.service:
            activity_logger.logger.warning(
                "Google Drive not authenticated. Cannot find xlsx files."
            )
            return None
        
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
    # Quick test
    try:
        handler = get_drive_handler()
        print("Drive handler initialized")

        if Config.GOOGLE_DRIVE_FOLDER_ID:
            files = handler.get_folder_files(Config.GOOGLE_DRIVE_FOLDER_ID)
            print(f"Files in folder {Config.GOOGLE_DRIVE_FOLDER_ID}:")
            for f in files:
                print(f"  - {f['name']} (ID: {f['id']})")
        else:
            print("No folder ID set in config")

    except Exception as e:
        print(f"Test failed: {e}")
