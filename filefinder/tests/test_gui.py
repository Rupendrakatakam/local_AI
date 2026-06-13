import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGUI:
    """Test GUI module."""
    
    def test_app_creation(self):
        """Test Flask app creates successfully."""
        with patch('gui.cfg') as mock_cfg:
            mock_cfg.return_value = 5000
            
            from gui import app
            assert app is not None
            assert app.template_folder == "templates"
            # static_folder is set to "static" (string) but may be absolute path
            assert "static" in app.static_folder
    
    def test_api_search_endpoint(self):
        """Test /api/search endpoint."""
        with patch('gui.cfg') as mock_cfg:
            mock_cfg.return_value = 5000
            
            from gui import app
            client = app.test_client()
            
            with patch('gui.search') as mock_search:
                mock_search.return_value = ([], False)
                
                response = client.get('/api/search?q=test')
                assert response.status_code == 200
                data = response.get_json()
                assert 'results' in data
                assert 'is_fuzzy' in data
    
    def test_api_search_empty_query(self):
        """Test /api/search with empty query."""
        with patch('gui.cfg') as mock_cfg:
            mock_cfg.return_value = 5000
            
            from gui import app
            client = app.test_client()
            
            response = client.get('/api/search?q=')
            assert response.status_code == 200
            data = response.get_json()
            assert data['results'] == []
            assert data['is_fuzzy'] is False
    
    def test_api_preview_security(self):
        """Test /api/preview validates path against watch_path."""
        with patch('gui.cfg') as mock_cfg:
            mock_cfg.side_effect = lambda k, d=None: {
                'watch_path': '~'
            }.get(k, d)
            
            from gui import app
            client = app.test_client()
            
            # Try to access file outside watch_path
            response = client.get('/api/preview?path=/etc/passwd')
            assert response.status_code == 403
            data = response.get_json()
            assert data['type'] == 'error'
            assert 'Access denied' in data['content']
    
    def test_api_open_security(self):
        """Test /api/open validates path against watch_path."""
        with patch('gui.cfg') as mock_cfg:
            mock_cfg.side_effect = lambda k, d=None: {
                'watch_path': '~'
            }.get(k, d)
            
            from gui import app
            client = app.test_client()
            
            with patch('gui.subprocess.Popen') as mock_popen:
                response = client.post('/api/open', 
                    json={'path': '/etc/passwd', 'query': 'test'})
                assert response.status_code == 403
                data = response.get_json()
                assert data['ok'] is False
                assert 'Access denied' in data['error']


class TestGUIAPIs:
    """Test other GUI API endpoints."""
    
    def test_api_stats(self):
        """Test /api/stats endpoint."""
        with patch('gui.cfg') as mock_cfg:
            mock_cfg.return_value = 5000
            
            from gui import app
            client = app.test_client()
            
            with patch('gui.db_stats') as mock_db_stats:
                mock_db_stats.return_value = {"total": 100, "ready": True}
                
                response = client.get('/api/stats')
                assert response.status_code == 200
                data = response.get_json()
                assert 'total' in data
                assert 'ready' in data
    
    def test_api_aliases(self):
        """Test /api/aliases endpoint."""
        with patch('gui.cfg') as mock_cfg:
            mock_cfg.return_value = 5000
            
            from gui import app
            client = app.test_client()
            
            with patch('aliases.list_aliases', return_value={}):
                with patch('aliases.set_alias'):
                    with patch('aliases.remove_alias'):
                        response = client.get('/api/aliases')
                        assert response.status_code == 200
                        data = response.get_json()
                        assert 'aliases' in data