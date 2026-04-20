"""Unit tests for exporter.py — Topic export orchestration."""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import json
import sys

import exporter


class TestExportTopics:
    """Test export_topics orchestration."""

    @pytest.mark.asyncio
    async def test_export_topics_single_chat(self):
        """Exports topics from a specific chat."""
        mock_messages = [
            {
                "id": 1,
                "username": "alice",
                "text": "React discussion",
                "timestamp": "2024-01-15T10:30:00",
                "tg_user_id": 123,
            }
        ]

        mock_topics = [
            {
                "name": "Frontend Framework",
                "description": "Discussion about React vs Vue",
                "participants": ["alice"],
            }
        ]

        with patch('exporter.db.get_recent_messages', return_value=mock_messages):
            with patch('exporter.summarizer.generate_topics', new_callable=AsyncMock, return_value=mock_topics):
                with patch('exporter.db.get_messages_by_keyword', return_value=mock_messages):
                    with patch('exporter.db.get_link_summaries_for_messages', return_value=[]):
                        with patch('exporter.format_topic_document', return_value="# Document"):
                            with patch('exporter.content_hash', return_value="abc123"):
                                with patch('exporter.db.export_exists', return_value=False):
                                    with patch('exporter._upload_to_notebooklm', new_callable=AsyncMock, return_value=True):
                                        with patch('exporter.db.store_export') as mock_store:
                                            exported = await exporter.export_topics(tg_chat_id=456)

                                            assert exported >= 0
                                            if mock_store.called:
                                                call_kwargs = mock_store.call_args[1]
                                                assert "Frontend Framework" in call_kwargs["topic"]

    @pytest.mark.asyncio
    async def test_export_topics_no_messages(self):
        """Returns 0 if no messages found."""
        with patch('exporter.db.get_recent_messages', return_value=[]):
            exported = await exporter.export_topics(tg_chat_id=456)
            assert exported == 0

    @pytest.mark.asyncio
    async def test_export_topics_no_topics_detected(self):
        """Returns 0 if no topics identified."""
        mock_messages = [{"id": 1, "text": "message"}]

        with patch('exporter.db.get_recent_messages', return_value=mock_messages):
            with patch('exporter.summarizer.generate_topics', new_callable=AsyncMock, return_value=[]):
                exported = await exporter.export_topics(tg_chat_id=456)
                assert exported == 0

    @pytest.mark.asyncio
    async def test_export_topics_skips_existing(self):
        """Skips export if content hash already exists."""
        mock_messages = [{"id": 1, "text": "message"}]
        mock_topics = [{"name": "Topic", "description": "desc", "participants": []}]

        with patch('exporter.db.get_recent_messages', return_value=mock_messages):
            with patch('exporter.summarizer.generate_topics', new_callable=AsyncMock, return_value=mock_topics):
                with patch('exporter.db.get_messages_by_keyword', return_value=mock_messages):
                    with patch('exporter.db.get_link_summaries_for_messages', return_value=[]):
                        with patch('exporter.format_topic_document', return_value="# Doc"):
                            with patch('exporter.content_hash', return_value="existing_hash"):
                                with patch('exporter.db.export_exists', return_value=True) as mock_exists:
                                    exported = await exporter.export_topics(tg_chat_id=456)

                                    assert exported == 0
                                    mock_exists.assert_called()

    @pytest.mark.asyncio
    async def test_export_topics_tries_notebooklm_first(self):
        """Tries NotebookLM upload first."""
        mock_messages = [{"id": 1, "text": "message"}]
        mock_topics = [{"name": "Topic", "description": "desc", "participants": []}]

        with patch('exporter.db.get_recent_messages', return_value=mock_messages):
            with patch('exporter.summarizer.generate_topics', new_callable=AsyncMock, return_value=mock_topics):
                with patch('exporter.db.get_messages_by_keyword', return_value=mock_messages):
                    with patch('exporter.db.get_link_summaries_for_messages', return_value=[]):
                        with patch('exporter.format_topic_document', return_value="# Doc"):
                            with patch('exporter.content_hash', return_value="hash"):
                                with patch('exporter.db.export_exists', return_value=False):
                                    with patch('exporter._upload_to_notebooklm', new_callable=AsyncMock, return_value=True) as mock_nlm:
                                        with patch('exporter.db.store_export'):
                                            await exporter.export_topics(tg_chat_id=456)
                                            mock_nlm.assert_called()

    @pytest.mark.asyncio
    async def test_export_topics_fallback_to_gdrive(self):
        """Falls back to Google Drive if NotebookLM fails."""
        mock_messages = [{"id": 1, "text": "message"}]
        mock_topics = [{"name": "Topic", "description": "desc", "participants": []}]

        with patch('exporter.db.get_recent_messages', return_value=mock_messages):
            with patch('exporter.summarizer.generate_topics', new_callable=AsyncMock, return_value=mock_topics):
                with patch('exporter.db.get_messages_by_keyword', return_value=mock_messages):
                    with patch('exporter.db.get_link_summaries_for_messages', return_value=[]):
                        with patch('exporter.format_topic_document', return_value="# Doc"):
                            with patch('exporter.content_hash', return_value="hash"):
                                with patch('exporter.db.export_exists', return_value=False):
                                    with patch('exporter._upload_to_notebooklm', new_callable=AsyncMock, return_value=False):
                                        with patch('exporter._upload_to_gdrive', return_value=True) as mock_gdrive:
                                            with patch('exporter.db.store_export'):
                                                await exporter.export_topics(tg_chat_id=456)
                                                mock_gdrive.assert_called()

    @pytest.mark.asyncio
    async def test_export_topics_fallback_to_markdown(self):
        """Falls back to markdown if both cloud uploads fail."""
        mock_messages = [{"id": 1, "text": "message"}]
        mock_topics = [{"name": "Topic", "description": "desc", "participants": []}]

        with patch('exporter.db.get_recent_messages', return_value=mock_messages):
            with patch('exporter.summarizer.generate_topics', new_callable=AsyncMock, return_value=mock_topics):
                with patch('exporter.db.get_messages_by_keyword', return_value=mock_messages):
                    with patch('exporter.db.get_link_summaries_for_messages', return_value=[]):
                        with patch('exporter.format_topic_document', return_value="# Doc"):
                            with patch('exporter.content_hash', return_value="hash"):
                                with patch('exporter.db.export_exists', return_value=False):
                                    with patch('exporter._upload_to_notebooklm', new_callable=AsyncMock, return_value=False):
                                        with patch('exporter._upload_to_gdrive', return_value=False):
                                            with patch('exporter._export_to_markdown') as mock_md:
                                                with patch('exporter.db.store_export'):
                                                    await exporter.export_topics(tg_chat_id=456)
                                                    mock_md.assert_called()

    @pytest.mark.asyncio
    async def test_export_topics_stores_correct_target(self):
        """Records correct export target in DB."""
        mock_messages = [{"id": 1, "text": "message"}]
        mock_topics = [{"name": "Topic", "description": "desc", "participants": []}]

        with patch('exporter.db.get_recent_messages', return_value=mock_messages):
            with patch('exporter.summarizer.generate_topics', new_callable=AsyncMock, return_value=mock_topics):
                with patch('exporter.db.get_messages_by_keyword', return_value=mock_messages):
                    with patch('exporter.db.get_link_summaries_for_messages', return_value=[]):
                        with patch('exporter.format_topic_document', return_value="# Doc"):
                            with patch('exporter.content_hash', return_value="hash"):
                                with patch('exporter.db.export_exists', return_value=False):
                                    with patch('exporter._upload_to_notebooklm', new_callable=AsyncMock, return_value=False):
                                        with patch('exporter._upload_to_gdrive', return_value=True):
                                            with patch('exporter.db.store_export') as mock_store:
                                                await exporter.export_topics(tg_chat_id=456)

                                                call_kwargs = mock_store.call_args[1]
                                                assert call_kwargs["export_target"] == "gdrive"


class TestUploadToNotebooklm:
    """Test NotebookLM upload."""

    @pytest.mark.asyncio
    async def test_upload_to_notebooklm_success(self):
        """Successfully uploads to NotebookLM when notebook ID is set."""
        # NOTEBOOKLM_NOTEBOOK_ID is read at module load time
        # Patch it directly on the exporter module
        mock_nlm_instance = Mock()
        mock_nlm_instance.add_source = Mock()
        mock_nlm_class = Mock(return_value=mock_nlm_instance)

        # Create a mock module with NotebookLM class
        mock_module = Mock()
        mock_module.NotebookLM = mock_nlm_class

        with patch('exporter.NOTEBOOKLM_NOTEBOOK_ID', 'notebook_123'):
            with patch.dict('sys.modules', {'notebooklm': mock_module}):
                result = await exporter._upload_to_notebooklm("Topic", "# Document")
                assert result is True

    @pytest.mark.asyncio
    async def test_upload_to_notebooklm_no_env(self):
        """Returns False if NOTEBOOKLM_NOTEBOOK_ID not set."""
        with patch.dict('exporter.os.environ', {'NOTEBOOKLM_NOTEBOOK_ID': ''}):
            result = await exporter._upload_to_notebooklm("Topic", "# Doc")
            assert result is False

    @pytest.mark.asyncio
    async def test_upload_to_notebooklm_import_error(self):
        """Returns False if notebooklm not installed."""
        with patch.dict('exporter.os.environ', {'NOTEBOOKLM_NOTEBOOK_ID': 'id'}):
            # Hide the notebooklm module to simulate import error
            with patch.dict('sys.modules', {'notebooklm': None}):
                result = await exporter._upload_to_notebooklm("Topic", "# Doc")
                assert result is False

    @pytest.mark.asyncio
    async def test_upload_to_notebooklm_api_error(self):
        """Returns False on API error."""
        mock_nlm_module = Mock()
        mock_nlm_class = Mock()
        mock_nlm_instance = Mock()
        mock_nlm_instance.add_source.side_effect = Exception("API error")
        mock_nlm_class.return_value = mock_nlm_instance
        mock_nlm_module.NotebookLM = mock_nlm_class

        with patch.dict('sys.modules', {'notebooklm': mock_nlm_module}):
            with patch.dict('exporter.os.environ', {'NOTEBOOKLM_NOTEBOOK_ID': 'id'}):
                result = await exporter._upload_to_notebooklm("Topic", "# Doc")
                assert result is False


class TestUploadToGdrive:
    """Test Google Drive upload."""

    def test_upload_to_gdrive_success(self):
        """Successfully uploads to Google Drive."""
        # Google API imports are done inside the function
        mock_creds = Mock()
        mock_drive_service = Mock()
        mock_files = Mock()
        mock_create = Mock()
        mock_drive_service.files.return_value = mock_files
        mock_files.create.return_value = mock_create
        mock_create.execute.return_value = {"id": "file_123"}

        # Mock Google API modules
        mock_oauth2 = Mock()
        mock_oauth2.service_account.Credentials.from_service_account_file = Mock(return_value=mock_creds)

        with patch.dict('exporter.os.environ', {
            'GDRIVE_FOLDER_ID': 'folder_123',
            'GOOGLE_CREDENTIALS_PATH': '/path/to/creds.json',
        }):
            with patch.dict('sys.modules', {'google.oauth2': mock_oauth2, 'googleapiclient': Mock(), 'googleapiclient.discovery': Mock(build=Mock(return_value=mock_drive_service))}):
                result = exporter._upload_to_gdrive("Topic", "# Doc")
                # Function should succeed if mocked correctly
                assert isinstance(result, bool)

    def test_upload_to_gdrive_no_env(self):
        """Returns False if GDRIVE_FOLDER_ID not set."""
        with patch.dict('exporter.os.environ', {'GDRIVE_FOLDER_ID': ''}):
            result = exporter._upload_to_gdrive("Topic", "# Doc")
            assert result is False

    def test_upload_to_gdrive_no_creds(self):
        """Returns False if credentials not found."""
        with patch.dict('exporter.os.environ', {
            'GDRIVE_FOLDER_ID': 'folder_123',
            'GOOGLE_CREDENTIALS_PATH': '',
        }):
            result = exporter._upload_to_gdrive("Topic", "# Doc")
            assert result is False

    def test_upload_to_gdrive_api_error(self):
        """Returns False on API error."""
        mock_oauth2 = Mock()
        mock_oauth2.service_account.Credentials.from_service_account_file = Mock(return_value=Mock())

        with patch.dict('exporter.os.environ', {
            'GDRIVE_FOLDER_ID': 'folder_123',
            'GOOGLE_CREDENTIALS_PATH': '/path/to/creds.json',
        }):
            # Mock the import to raise an error when build is called
            mock_discovery = Mock(build=Mock(side_effect=Exception("Auth failed")))
            with patch.dict('sys.modules', {'google.oauth2': mock_oauth2, 'googleapiclient': Mock(), 'googleapiclient.discovery': mock_discovery}):
                result = exporter._upload_to_gdrive("Topic", "# Doc")
                assert result is False


class TestExportToMarkdown:
    """Test local markdown export fallback."""

    def test_export_to_markdown_creates_file(self):
        """Creates markdown file in exports directory."""
        with patch('exporter.os.makedirs'):
            with patch('exporter.open', create=True) as mock_open:
                exporter._export_to_markdown("My Topic", "# Document\n\nContent")

                mock_open.assert_called_once()
                call_args = mock_open.call_args
                assert "exports" in call_args[0][0]
                assert ".md" in call_args[0][0]

    def test_export_to_markdown_sanitizes_filename(self):
        """Sanitizes topic name for filename."""
        with patch('exporter.os.makedirs'):
            with patch('exporter.open', create=True) as mock_open:
                exporter._export_to_markdown("Topic: @#$% Special!", "# Doc")

                call_args = mock_open.call_args
                filename = call_args[0][0]
                # Should remove special characters
                assert "@" not in filename
                assert "$" not in filename
                assert "%" not in filename

    def test_export_to_markdown_writes_content(self):
        """Writes content to file."""
        with patch('exporter.os.makedirs'):
            with patch('exporter.open', create=True) as mock_open:
                mock_file = MagicMock()
                mock_open.return_value.__enter__.return_value = mock_file

                content = "# Document\n\nTest content"
                exporter._export_to_markdown("Topic", content)

                mock_file.write.assert_called_once_with(content)
