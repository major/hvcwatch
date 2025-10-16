"""Tests for data models."""

import pytest
from pydantic import ValidationError

from hvcwatch.models import TickerData


class TestTickerData:
    """Tests for the TickerData model."""

    def test_ticker_data_creation_with_all_fields(self) -> None:
        """✅ Test creating TickerData with all fields populated."""
        ticker_data = TickerData(
            ticker="AAPL",
            name="Apple Inc",
            description="Technology company",
            type="CS",
            logo_url="https://example.com/logo.png",
            close=150.25,
            volume=1_000_000,
            volume_sma=900_000.0,
            volume_ratio=1.11,
        )

        assert ticker_data.ticker == "AAPL"
        assert ticker_data.name == "Apple Inc"
        assert ticker_data.description == "Technology company"
        assert ticker_data.type == "CS"
        assert ticker_data.logo_url == "https://example.com/logo.png"
        assert ticker_data.price == 150.25
        assert ticker_data.volume == 1_000_000
        assert ticker_data.volume_sma == 900_000.0
        assert ticker_data.volume_ratio == 1.11

    def test_ticker_data_with_none_volume_fields(self) -> None:
        """✅ Test TickerData with None values for volume_sma and volume_ratio (insufficient data case)."""
        ticker_data = TickerData(
            ticker="TSLA",
            name="Tesla Inc",
            description="Electric vehicles",
            type="CS",
            logo_url="https://example.com/tesla.png",
            close=250.50,
            volume=500_000,
            volume_sma=None,
            volume_ratio=None,
        )

        assert ticker_data.ticker == "TSLA"
        assert ticker_data.price == 250.50
        assert ticker_data.volume == 500_000
        assert ticker_data.volume_sma is None
        assert ticker_data.volume_ratio is None

    def test_ticker_data_price_alias(self) -> None:
        """✅ Test that 'close' field can be accessed via 'price' alias."""
        ticker_data = TickerData(
            ticker="MSFT",
            name="Microsoft Corporation",
            description="Software company",
            type="CS",
            logo_url="https://example.com/msft.png",
            close=380.75,
            volume=750_000,
            volume_sma=700_000.0,
            volume_ratio=1.07,
        )

        # Both 'close' and 'price' should work
        assert ticker_data.price == 380.75

    @pytest.mark.parametrize(
        "missing_field",
        ["ticker", "name", "type", "logo_url", "close", "volume"],
    )
    def test_ticker_data_missing_required_fields(self, missing_field: str) -> None:
        """❌ Test that ValidationError is raised when required fields are missing."""
        data = {
            "ticker": "GOOGL",
            "name": "Alphabet Inc",
            "description": "Search and advertising",
            "type": "CS",
            "logo_url": "https://example.com/googl.png",
            "close": 140.25,
            "volume": 2_000_000,
        }

        # Remove the field we're testing
        del data[missing_field]

        with pytest.raises(ValidationError):
            TickerData(**data)

    def test_ticker_data_with_zero_volume(self) -> None:
        """✅ Test TickerData with zero volume (edge case)."""
        ticker_data = TickerData(
            ticker="EDGE",
            name="Edge Case Corp",
            description="Testing edge cases",
            type="CS",
            logo_url="https://example.com/edge.png",
            close=10.0,
            volume=0,
            volume_sma=100_000.0,
            volume_ratio=0.0,
        )

        assert ticker_data.volume == 0
        assert ticker_data.volume_ratio == 0.0

    def test_ticker_data_serialization(self) -> None:
        """✅ Test that TickerData can be serialized to dict."""
        ticker_data = TickerData(
            ticker="AMZN",
            name="Amazon.com Inc",
            description="E-commerce and cloud computing",
            type="CS",
            logo_url="https://example.com/amzn.png",
            close=180.50,
            volume=3_000_000,
            volume_sma=2_500_000.0,
            volume_ratio=1.20,
        )

        data_dict = ticker_data.model_dump()

        assert data_dict["ticker"] == "AMZN"
        assert data_dict["name"] == "Amazon.com Inc"
        assert data_dict["price"] == 180.50
        assert data_dict["volume"] == 3_000_000

    def test_ticker_data_from_dict(self) -> None:
        """✅ Test creating TickerData from dictionary (common use case in orchestrator)."""
        ticker_details = {
            "ticker": "NVDA",
            "name": "NVIDIA Corporation",
            "description": "Graphics processors",
            "type": "CS",
            "logo_url": "https://example.com/nvda.png",
        }

        ticker_stats = {
            "close": 495.50,
            "volume": 5_000_000,
            "volume_sma": 4_000_000.0,
            "volume_ratio": 1.25,
        }

        # Combine both dicts (simulating what orchestrator does)
        ticker_data = TickerData(**ticker_details, **ticker_stats)

        assert ticker_data.ticker == "NVDA"
        assert ticker_data.name == "NVIDIA Corporation"
        assert ticker_data.price == 495.50
        assert ticker_data.volume == 5_000_000

    def test_ticker_data_with_none_description(self) -> None:
        """✅ Test TickerData with None description (Polygon.io doesn't always provide this)."""
        ticker_data = TickerData(
            ticker="IPAC",
            name="Income Opportunity REIT Corp",
            description=None,  # Some tickers don't have a description in Polygon.io
            type="CS",
            logo_url="https://example.com/ipac.png",
            close=10.50,
            volume=100_000,
            volume_sma=80_000.0,
            volume_ratio=1.25,
        )

        assert ticker_data.ticker == "IPAC"
        assert ticker_data.name == "Income Opportunity REIT Corp"
        assert ticker_data.description is None
        assert ticker_data.price == 10.50
