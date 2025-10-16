"""Data models for hvcwatch."""

from pydantic import BaseModel, ConfigDict, Field


class TickerData(BaseModel):
    """
    📊 Represents enriched data for a stock ticker.

    This model combines ticker details from Polygon.io with current market stats,
    providing all the information needed to send notifications across platforms.
    """

    model_config = ConfigDict(
        populate_by_name=True  # Allow using both 'price' and 'close' as field names
    )

    ticker: str = Field(..., description="Stock ticker symbol (e.g., 'AAPL')")
    name: str = Field(..., description="Company name (e.g., 'Apple Inc')")
    description: str | None = Field(
        None, description="Company description (None if not available from API)"
    )
    type: str = Field(..., description="Security type (e.g., 'CS' for Common Stock)")
    logo_url: str = Field(..., description="URL to company logo image")

    price: float = Field(..., description="Current/close price", alias="close")
    volume: int = Field(..., description="Current trading volume")
    volume_sma: float | None = Field(
        None,
        description="20-day simple moving average of volume (None if insufficient data)",
    )
    volume_ratio: float | None = Field(
        None,
        description="Ratio of current volume to 20-day SMA (None if insufficient data)",
    )
