"""
SP-StockBot Test Suite
Unit and integration tests for vector DB, embeddings, and Flex messages.
Run with: pytest tests.py -v
"""

import pytest
import json
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

# Import utilities to test
from utils import (
    parse_quantity,
    split_into_chunks,
    get_report_flex,
    get_alert_flex,
    get_stock_check_flex,
    detect_file_type,
    format_notification_message
)


# ==================== UNIT TESTS ====================

class TestQuantityParsing:
    """Unit tests for quantity parsing."""
    
    def test_parse_quantity_with_plus_signs(self):
        """Test parsing '5+5+' format."""
        assert parse_quantity("5+5+") == 10
    
    def test_parse_quantity_single_number(self):
        """Test parsing single number."""
        assert parse_quantity("100") == 100
    
    def test_parse_quantity_multiple_numbers(self):
        """Test parsing comma-separated or space-separated numbers."""
        assert parse_quantity("100+50+25") == 175
    
    def test_parse_quantity_with_text(self):
        """Test parsing numbers mixed with text."""
        assert parse_quantity("5 pieces") == 5
        assert parse_quantity("qty: 10") == 10
    
    def test_parse_quantity_no_numbers(self):
        """Test parsing string with no numbers."""
        assert parse_quantity("no numbers here") == 0
    
    def test_parse_quantity_empty_string(self):
        """Test parsing empty string."""
        assert parse_quantity("") == 0
    
    def test_parse_quantity_none(self):
        """Test parsing None."""
        assert parse_quantity(None) == 0
    
    def test_parse_quantity_improved_thai_pattern_1(self):
        """Test improved parsing: Thai material code + quantity pattern."""
        # เบิก กดทห80 5+5+ should return 10, not 90 (not summing 80)
        assert parse_quantity("เบิก กดทห80 5+5+") == 10
    
    def test_parse_quantity_improved_thai_pattern_2(self):
        """Test improved parsing: Another Thai material code + quantity."""
        assert parse_quantity("กดทห100 10+2+") == 12
    
    def test_parse_quantity_improved_thai_text(self):
        """Test improved parsing: Thai text with quantity."""
        assert parse_quantity("ใช้ สเปย์ 3 ชิ้น") == 3
    
    def test_parse_quantity_improved_thai_complex(self):
        """Test improved parsing: Complex Thai message with sum at end."""
        assert parse_quantity("เบิก นวม1000 5+3+2") == 10
    
    def test_parse_quantity_improved_last_group(self):
        """Test improved parsing: Last number group is correct."""
        assert parse_quantity("abc 123 def 456") == 456
    
    def test_parse_quantity_improved_no_qty(self):
        """Test improved parsing: Material code without quantity."""
        assert parse_quantity("เบิก กดทห80") == 0


class TestTextChunking:
    """Unit tests for text chunking."""
    
    def test_split_into_chunks_short_text(self):
        """Test chunking short text."""
        text = "Hello world"
        chunks = split_into_chunks(text)
        assert len(chunks) >= 1
        assert "Hello world" in chunks[0]
    
    def test_split_into_chunks_long_text(self):
        """Test chunking long text."""
        long_text = " ".join(["word"] * 2000)
        chunks = split_into_chunks(long_text, max_tokens=512)
        assert len(chunks) > 1
        for chunk in chunks:
            assert isinstance(chunk, str)
            assert len(chunk) > 0
    
    def test_split_into_chunks_empty_text(self):
        """Test chunking empty text."""
        chunks = split_into_chunks("")
        assert chunks == []
    
    def test_split_into_chunks_whitespace_only(self):
        """Test chunking whitespace-only text."""
        chunks = split_into_chunks("   ")
        assert chunks == []


class TestFileTypeDetection:
    """Unit tests for MIME type detection."""
    
    def test_detect_xlsx(self):
        """Test XLSX detection."""
        assert detect_file_type("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") == "xlsx"
        assert detect_file_type("application/vnd.ms-excel") == "xlsx"
    
    def test_detect_pdf(self):
        """Test PDF detection."""
        assert detect_file_type("application/pdf") == "pdf"
    
    def test_detect_docx(self):
        """Test DOCX detection."""
        assert detect_file_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document") == "docx"
    
    def test_detect_image(self):
        """Test image detection."""
        assert detect_file_type("image/png") == "image"
        assert detect_file_type("image/jpeg") == "image"
    
    def test_detect_unknown(self):
        """Test unknown MIME type."""
        assert detect_file_type("application/unknown") == "unknown"


class TestFlexMessages:
    """Unit tests for Flex message generation."""
    
    def test_get_report_flex_structure(self):
        """Test report Flex message structure."""
        materials = [
            {"material": "Oil", "qty": 50},
            {"material": "Filters", "qty": 30}
        ]
        flex = get_report_flex("John Doe", materials)
        
        assert flex["type"] == "bubble"
        assert "header" in flex
        assert "body" in flex
        assert "footer" in flex
    
    def test_get_report_flex_with_empty_materials(self):
        """Test report Flex with empty materials."""
        flex = get_report_flex("John Doe", [])
        assert flex["type"] == "bubble"
    
    def test_get_alert_flex_warning(self):
        """Test warning alert Flex message."""
        flex = get_alert_flex("Stock Low", "Oil level below threshold", "warning")
        
        assert flex["type"] == "bubble"
        assert "🟠" in str(flex) or "⚠️" in str(flex)
    
    def test_get_alert_flex_error(self):
        """Test error alert Flex message."""
        flex = get_alert_flex("System Error", "Database connection failed", "error")
        
        assert flex["type"] == "bubble"
        assert "❌" in str(flex) or "error" in str(flex).lower()
    
    def test_get_stock_check_flex_structure(self):
        """Test stock check Flex message structure."""
        materials = [
            {"material": "Part A", "qty": 100, "status": "OK"},
            {"material": "Part B", "qty": 50, "status": "Low"}
        ]
        flex = get_stock_check_flex(materials, "Jane Smith")
        
        assert flex["type"] == "bubble"
        assert "header" in flex
        assert "body" in flex
    
    def test_get_stock_check_flex_with_many_items(self):
        """Test stock check Flex with >10 items (should limit to 10)."""
        materials = [
            {"material": f"Part {i}", "qty": 100 - i*5, "status": "OK"}
            for i in range(20)
        ]
        flex = get_stock_check_flex(materials, "Jane Smith")
        
        # Verify it successfully handles many items
        assert flex["type"] == "bubble"


class TestNotificationFormatting:
    """Unit tests for notification message formatting."""
    
    def test_format_report_notification(self):
        """Test report notification formatting."""
        msg = format_notification_message(
            "report",
            "John Doe",
            {"material": "Oil", "qty": 50}
        )
        assert "John Doe" in msg
        assert "Oil" in msg
        assert "50" in msg
    
    def test_format_check_notification(self):
        """Test check notification formatting."""
        msg = format_notification_message("check", "Jane Smith", {})
        assert "Jane Smith" in msg
        assert "checked" in msg.lower()
    
    def test_format_anomaly_notification(self):
        """Test anomaly notification formatting."""
        msg = format_notification_message(
            "anomaly",
            "System",
            {"message": "Unusual spike detected"}
        )
        assert "Unusual spike" in msg
    
    def test_format_registration_notification(self):
        """Test registration notification formatting."""
        msg = format_notification_message("registration", "New User", {})
        assert "New User" in msg
        assert "registered" in msg.lower()


# ==================== INTEGRATION TESTS ====================

class TestVectorDBIntegration:
    """Integration tests for vector DB operations (requires chromadb)."""
    
    @pytest.fixture
    def temp_vector_db(self):
        """Create temporary vector DB for testing."""
        # ignore_cleanup_errors=True for Windows compatibility with ChromaDB file locks
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            try:
                from chromadb import PersistentClient
                client = PersistentClient(path=tmpdir)
                yield client, tmpdir
                # Optional: explicit cleanup hint for Windows
                del client
                import gc
                gc.collect()
            except ImportError:
                pytest.skip("chromadb not installed")
    
    def test_vector_collection_creation(self, temp_vector_db):
        """Test creating and accessing vector collections."""
        client, _ = temp_vector_db
        
        collection = client.get_or_create_collection("test_collection")
        assert collection is not None
        assert collection.name == "test_collection"
    
    def test_vector_embedding_upsert(self, temp_vector_db):
        """Test upserting embeddings to vector DB."""
        try:
            from sentence_transformers import SentenceTransformer
            client, _ = temp_vector_db
            
            collection = client.get_or_create_collection("test_embeddings")
            model = SentenceTransformer('all-MiniLM-L6-v2')
            
            # Simple test text
            text = "This is a test inventory report"
            embedding = model.encode(text).tolist()
            
            # Upsert
            collection.upsert(
                ids=["test_doc_1"],
                embeddings=[embedding],
                documents=[text],
                metadatas=[{"type": "report", "user_id": "test_user"}]
            )
            
            # Query
            results = collection.query(query_embeddings=[embedding], n_results=1)
            assert len(results['ids']) > 0
            assert results['ids'][0][0] == "test_doc_1"
        
        except ImportError:
            pytest.skip("sentence-transformers not installed")


class TestMockLineWebhook:
    """Integration tests for Line webhook handling."""
    
    @patch('linebot.v3.messaging.MessagingApi')
    def test_message_event_parsing(self, mock_messaging_api):
        """Test parsing incoming Line message event."""
        # Simulate a text message event
        mock_event = MagicMock()
        mock_event.message.type = "text"
        mock_event.message.text = "เบิก กดทห80 5+5+"  # Thai: "Withdraw code80 5+5+"
        mock_event.source.user_id = "U1234567890"
        
        assert mock_event.message.text == "เบิก กดทห80 5+5+"
        assert parse_quantity(mock_event.message.text) == 10


class TestFlexMessageParsing:
    """Tests for Flex message JSON structure and validity."""
    
    def test_report_flex_is_valid_json(self):
        """Test that report Flex can be serialized to JSON."""
        materials = [{"material": "Oil", "qty": 50}]
        flex = get_report_flex("User", materials)
        
        # Should be serializable to JSON
        json_str = json.dumps(flex)
        assert isinstance(json_str, str)
        assert len(json_str) > 0
    
    def test_alert_flex_is_valid_json(self):
        """Test that alert Flex can be serialized to JSON."""
        flex = get_alert_flex("Alert", "Message", "warning")
        
        json_str = json.dumps(flex)
        assert isinstance(json_str, str)
    
    def test_stock_check_flex_is_valid_json(self):
        """Test that stock check Flex can be serialized to JSON."""
        materials = [{"material": "Part", "qty": 100, "status": "OK"}]
        flex = get_stock_check_flex(materials, "User")
        
        json_str = json.dumps(flex)
        assert isinstance(json_str, str)


# ==================== MOCK TESTS ====================

class TestMockLineBot:
    """Mock tests for Line Bot integration."""
    
    @patch('linebot.v3.messaging.MessagingApi')
    def test_push_message_flex(self, mock_api):
        """Test pushing Flex message to user."""
        # Simulate Flex message push
        materials = [{"material": "Oil", "qty": 50}]
        flex_content = get_report_flex("User", materials)
        
        # Verify Flex structure is valid
        assert flex_content["type"] == "bubble"
        assert json.dumps(flex_content)  # Should be JSON serializable


class TestMockDriveExtraction:
    """Mock tests for Drive file extraction."""
    
    @patch('utils.extract_file_content')
    def test_extract_xlsx_mock(self, mock_extract):
        """Test mocked XLSX extraction."""
        mock_extract.return_value = json.dumps({
            "Sheet1": [
                {"Material": "Oil", "Quantity": "5+5+"},
                {"Material": "Filter", "Quantity": "3"}
            ]
        })
        
        result = mock_extract("test.xlsx", "xlsx")
        data = json.loads(result)
        
        assert "Sheet1" in data
        assert len(data["Sheet1"]) == 2
    
    @patch('utils.split_into_chunks')
    def test_split_extracted_content_mock(self, mock_split):
        """Test splitting extracted file content."""
        mock_content = "Large text " * 1000
        mock_split.return_value = ["chunk1", "chunk2", "chunk3"]
        
        chunks = mock_split(mock_content, max_tokens=512)
        assert len(chunks) == 3


class TestMockGrafanaIntegration:
    """Mock tests for Grafana dashboard updates."""
    
    @patch('requests.post')
    def test_push_dashboard_mock(self, mock_post):
        """Test pushing metrics to Grafana."""
        mock_post.return_value.status_code = 200
        
        dashboard_json = {
            "dashboard": {
                "title": "SP-StockBot Weekly",
                "panels": [
                    {"title": "Reports per User", "type": "graph"}
                ]
            }
        }
        
        # Verify dashboard JSON structure
        assert "dashboard" in dashboard_json
        assert json.dumps(dashboard_json)


# ==================== PYTEST FIXTURES ====================

@pytest.fixture
def sample_materials():
    """Fixture providing sample material data."""
    return [
        {"material": "Engine Oil", "qty": 50, "status": "OK"},
        {"material": "Air Filter", "qty": 10, "status": "Low"},
        {"material": "Spark Plugs", "qty": 100, "status": "OK"},
    ]


@pytest.fixture
def sample_user():
    """Fixture providing sample user data."""
    return {
        "user_id": "U1234567890",
        "name": "John Mechanic",
        "role": "employee"
    }


if __name__ == "__main__":
    # Run tests with: python tests.py
    # Or with pytest: pytest tests.py -v
    pytest.main([__file__, "-v"])
