"""Unit tests for config.py — environment variable loading."""

import pytest
import os
from unittest.mock import patch
import sys


def _reimport_config():
    """Reimport config with load_dotenv mocked so .env file doesn't interfere."""
    if 'config' in sys.modules:
        del sys.modules['config']
    with patch("dotenv.load_dotenv"):
        import config
        return config


class TestConfigLoading:
    """Test configuration loading from environment variables."""

    def test_telegram_bot_token_loads(self):
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'test_token_123'}, clear=True):
            config = _reimport_config()
            assert config.BOT_TOKEN == 'test_token_123'

    def test_webhook_url_loads(self):
        with patch.dict(os.environ, {'WEBHOOK_URL': 'https://example.com/webhook'}, clear=True):
            config = _reimport_config()
            assert config.WEBHOOK_URL == 'https://example.com/webhook'

    def test_webhook_secret_path_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.WEBHOOK_SECRET_PATH == 'webhook'

    def test_webhook_secret_path_loads_from_env(self):
        with patch.dict(os.environ, {'WEBHOOK_SECRET_PATH': 'custom/path'}, clear=True):
            config = _reimport_config()
            assert config.WEBHOOK_SECRET_PATH == 'custom/path'

    def test_telegram_webhook_secret_token_loads(self):
        with patch.dict(os.environ, {'TELEGRAM_WEBHOOK_SECRET_TOKEN': 'secret123'}, clear=True):
            config = _reimport_config()
            assert config.WEBHOOK_SECRET_TOKEN == 'secret123'

    def test_use_polling_false_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.USE_POLLING is False

    def test_use_polling_true_when_set(self):
        with patch.dict(os.environ, {'USE_POLLING': 'true'}, clear=True):
            config = _reimport_config()
            assert config.USE_POLLING is True

    def test_use_polling_case_insensitive(self):
        with patch.dict(os.environ, {'USE_POLLING': 'TRUE'}, clear=True):
            config = _reimport_config()
            assert config.USE_POLLING is True

    def test_supabase_url_loads(self):
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://project.supabase.co'}, clear=True):
            config = _reimport_config()
            assert config.SUPABASE_URL == 'https://project.supabase.co'

    def test_supabase_key_loads(self):
        with patch.dict(os.environ, {'SUPABASE_KEY': 'anon_key_123'}, clear=True):
            config = _reimport_config()
            assert config.SUPABASE_KEY == 'anon_key_123'

    def test_gemini_api_key_loads(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'gemini_key_123'}, clear=True):
            config = _reimport_config()
            assert config.GEMINI_API_KEY == 'gemini_key_123'

    def test_google_cloud_project_loads(self):
        with patch.dict(os.environ, {'GOOGLE_CLOUD_PROJECT': 'my-project'}, clear=True):
            config = _reimport_config()
            assert config.GOOGLE_CLOUD_PROJECT == 'my-project'

    def test_google_cloud_location_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.GOOGLE_CLOUD_LOCATION == 'us-central1'

    def test_google_cloud_location_loads_from_env(self):
        with patch.dict(os.environ, {'GOOGLE_CLOUD_LOCATION': 'europe-west1'}, clear=True):
            config = _reimport_config()
            assert config.GOOGLE_CLOUD_LOCATION == 'europe-west1'

    def test_host_defaults_to_0_0_0_0(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.HOST == '0.0.0.0'

    def test_port_defaults_to_8080(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.PORT == 8080

    def test_port_converts_to_int(self):
        with patch.dict(os.environ, {'PORT': '9000'}, clear=True):
            config = _reimport_config()
            assert config.PORT == 9000
            assert isinstance(config.PORT, int)

    def test_cloud_run_detection_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.IS_CLOUD_RUN is False

    def test_cloud_run_detection_on_with_k_service(self):
        with patch.dict(os.environ, {'K_SERVICE': 'my-service'}, clear=True):
            config = _reimport_config()
            assert config.IS_CLOUD_RUN is True

    def test_k_service_loads(self):
        with patch.dict(os.environ, {'K_SERVICE': 'my-bot-service'}, clear=True):
            config = _reimport_config()
            assert config.K_SERVICE == 'my-bot-service'

    def test_k_revision_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.K_REVISION == 'latest'

    def test_k_revision_loads(self):
        with patch.dict(os.environ, {'K_REVISION': '00042'}, clear=True):
            config = _reimport_config()
            assert config.K_REVISION == '00042'

    def test_k_region_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.K_REGION == 'unknown'

    def test_k_region_loads(self):
        with patch.dict(os.environ, {'K_REGION': 'us-central1'}, clear=True):
            config = _reimport_config()
            assert config.K_REGION == 'us-central1'


class TestConfigTypeConversions:
    """Test type conversions in config."""

    def test_port_string_to_int(self):
        with patch.dict(os.environ, {'PORT': '5000'}, clear=True):
            config = _reimport_config()
            assert config.PORT == 5000
            assert isinstance(config.PORT, int)

    def test_invalid_port_raises_error(self):
        with patch.dict(os.environ, {'PORT': 'invalid'}, clear=True):
            if 'config' in sys.modules:
                del sys.modules['config']
            with pytest.raises(ValueError):
                with patch("dotenv.load_dotenv"):
                    import config


class TestConfigDefaults:
    """Test default values for optional config."""

    def test_empty_strings_for_unset_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            config = _reimport_config()
            assert config.BOT_TOKEN == ''
            assert config.WEBHOOK_URL == ''
            assert config.SUPABASE_URL == ''
            assert config.SUPABASE_KEY == ''
            assert config.GEMINI_API_KEY == ''
            assert config.GOOGLE_CLOUD_PROJECT == ''
