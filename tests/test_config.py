"""Unit tests for config.py — environment variable loading."""

import pytest
import os
from unittest.mock import patch, MagicMock
import sys


class TestConfigLoading:
    """Test configuration loading from environment variables."""

    def test_telegram_bot_token_loads(self):
        """TELEGRAM_BOT_TOKEN should load from env."""
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'test_token_123'}):
            # Re-import config to pick up new env vars
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.BOT_TOKEN == 'test_token_123'

    def test_webhook_url_loads(self):
        """WEBHOOK_URL should load from env."""
        with patch.dict(os.environ, {'WEBHOOK_URL': 'https://example.com/webhook'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.WEBHOOK_URL == 'https://example.com/webhook'

    def test_webhook_secret_path_defaults(self):
        """WEBHOOK_SECRET_PATH should default to 'webhook'."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.WEBHOOK_SECRET_PATH == 'webhook'

    def test_webhook_secret_path_loads_from_env(self):
        """WEBHOOK_SECRET_PATH should load from env if set."""
        with patch.dict(os.environ, {'WEBHOOK_SECRET_PATH': 'custom/path'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.WEBHOOK_SECRET_PATH == 'custom/path'

    def test_telegram_webhook_secret_token_loads(self):
        """TELEGRAM_WEBHOOK_SECRET_TOKEN should load from env."""
        with patch.dict(os.environ, {'TELEGRAM_WEBHOOK_SECRET_TOKEN': 'secret123'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.WEBHOOK_SECRET_TOKEN == 'secret123'

    def test_use_polling_false_by_default(self):
        """USE_POLLING should default to False."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.USE_POLLING is False

    def test_use_polling_true_when_set(self):
        """USE_POLLING should be True when set to 'true'."""
        with patch.dict(os.environ, {'USE_POLLING': 'true'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.USE_POLLING is True

    def test_use_polling_case_insensitive(self):
        """USE_POLLING should be case-insensitive."""
        with patch.dict(os.environ, {'USE_POLLING': 'TRUE'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.USE_POLLING is True

    def test_supabase_url_loads(self):
        """SUPABASE_URL should load from env."""
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://project.supabase.co'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.SUPABASE_URL == 'https://project.supabase.co'

    def test_supabase_key_loads(self):
        """SUPABASE_KEY should load from env."""
        with patch.dict(os.environ, {'SUPABASE_KEY': 'anon_key_123'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.SUPABASE_KEY == 'anon_key_123'

    def test_gemini_api_key_loads(self):
        """GEMINI_API_KEY should load from env."""
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'gemini_key_123'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.GEMINI_API_KEY == 'gemini_key_123'

    def test_google_cloud_project_loads(self):
        """GOOGLE_CLOUD_PROJECT should load from env."""
        with patch.dict(os.environ, {'GOOGLE_CLOUD_PROJECT': 'my-project'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.GOOGLE_CLOUD_PROJECT == 'my-project'

    def test_google_cloud_location_defaults(self):
        """GOOGLE_CLOUD_LOCATION should default to 'us-central1'."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.GOOGLE_CLOUD_LOCATION == 'us-central1'

    def test_google_cloud_location_loads_from_env(self):
        """GOOGLE_CLOUD_LOCATION should load from env if set."""
        with patch.dict(os.environ, {'GOOGLE_CLOUD_LOCATION': 'europe-west1'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.GOOGLE_CLOUD_LOCATION == 'europe-west1'

    def test_host_defaults_to_0_0_0_0(self):
        """HOST should default to '0.0.0.0'."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.HOST == '0.0.0.0'

    def test_port_defaults_to_8080(self):
        """PORT should default to 8080."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.PORT == 8080

    def test_port_converts_to_int(self):
        """PORT should be converted to integer."""
        with patch.dict(os.environ, {'PORT': '9000'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.PORT == 9000
            assert isinstance(config.PORT, int)

    def test_cloud_run_detection_off_by_default(self):
        """IS_CLOUD_RUN should be False by default."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.IS_CLOUD_RUN is False

    def test_cloud_run_detection_on_with_k_service(self):
        """IS_CLOUD_RUN should be True when K_SERVICE is set."""
        with patch.dict(os.environ, {'K_SERVICE': 'my-service'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.IS_CLOUD_RUN is True

    def test_k_service_loads(self):
        """K_SERVICE should load from env."""
        with patch.dict(os.environ, {'K_SERVICE': 'my-bot-service'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.K_SERVICE == 'my-bot-service'

    def test_k_revision_defaults(self):
        """K_REVISION should default to 'latest'."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.K_REVISION == 'latest'

    def test_k_revision_loads(self):
        """K_REVISION should load from env."""
        with patch.dict(os.environ, {'K_REVISION': '00042'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.K_REVISION == '00042'

    def test_k_region_defaults(self):
        """K_REGION should default to 'unknown'."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.K_REGION == 'unknown'

    def test_k_region_loads(self):
        """K_REGION should load from env."""
        with patch.dict(os.environ, {'K_REGION': 'us-central1'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.K_REGION == 'us-central1'


class TestConfigTypeConversions:
    """Test type conversions in config."""

    def test_port_string_to_int(self):
        """PORT conversion from string to int."""
        with patch.dict(os.environ, {'PORT': '5000'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.PORT == 5000
            assert isinstance(config.PORT, int)

    def test_invalid_port_raises_error(self):
        """Invalid PORT should raise ValueError."""
        with patch.dict(os.environ, {'PORT': 'invalid'}):
            if 'config' in sys.modules:
                del sys.modules['config']
            with pytest.raises(ValueError):
                import config


class TestConfigDefaults:
    """Test default values for optional config."""

    def test_empty_strings_for_unset_credentials(self):
        """Unset credentials should be empty strings, not None."""
        with patch.dict(os.environ, {}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            import config
            assert config.BOT_TOKEN == ''
            assert config.WEBHOOK_URL == ''
            assert config.SUPABASE_URL == ''
            assert config.SUPABASE_KEY == ''
            assert config.GEMINI_API_KEY == ''
            assert config.GOOGLE_CLOUD_PROJECT == ''
