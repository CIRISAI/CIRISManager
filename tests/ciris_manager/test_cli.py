"""
Unit tests for CIRISManager CLI.
"""

import pytest
from unittest.mock import patch, Mock
from pathlib import Path
import argparse
from ciris_manager.cli import generate_default_config, main


class TestCLI:
    """Test cases for CLI functionality."""
    
    def test_generate_default_config(self, tmp_path):
        """Test config generation."""
        config_path = tmp_path / "test-config.yml"
        
        # Generate config
        generate_default_config(str(config_path))
        
        # Check file was created
        assert config_path.exists()
        
        # Check content is valid YAML
        import yaml
        content = config_path.read_text()
        config = yaml.safe_load(content)
        assert "docker" in config
        assert "watchdog" in config
        # Check for key components
        assert "docker" in config
        assert "watchdog" in config
    
    @patch('ciris_manager.cli.asyncio.run')
    @patch('ciris_manager.cli.CIRISManagerConfig.from_file')
    @patch('ciris_manager.cli.CIRISManager')
    def test_main_run(self, mock_manager_class, mock_config_from_file, mock_asyncio_run):
        """Test main run mode."""
        # Mock config
        mock_config = Mock()
        mock_config_from_file.return_value = mock_config
        
        # Mock manager
        mock_manager = Mock()
        mock_manager.run = Mock()
        mock_manager_class.return_value = mock_manager
        
        # Mock argument parsing
        with patch('sys.argv', ['ciris-manager']):
            with patch('ciris_manager.cli.Path') as mock_path:
                mock_path_obj = Mock()
                mock_path_obj.exists.return_value = True
                mock_path.return_value = mock_path_obj
                mock_path_obj.expanduser.return_value = mock_path_obj
                
                main()
        
        # Should run manager
        mock_asyncio_run.assert_called_once()
    
    @patch('ciris_manager.cli.print')
    def test_main_generate_config_and_exit(self, mock_print, tmp_path):
        """Test main with --generate-config flag."""
        config_path = tmp_path / "config.yml"
        
        with patch('sys.argv', ['ciris-manager', '--generate-config', '--config', str(config_path)]):
            with pytest.raises(SystemExit) as exc:
                main()
            
            assert exc.value.code == 0
        
        # Config should be created
        assert config_path.exists()