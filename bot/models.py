from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Jersey:
    name: str
    team: str
    jersey_type: str          # "Authentic", "Premier", "Practice", "Breakaway"
    sale_price: float
    original_price: Optional[float]
    url: str
    sizes_available: list = field(default_factory=list)
    image_url: Optional[str] = None

    def discount_pct(self) -> Optional[int]:
        if self.original_price and self.original_price > 0:
            return round((1 - self.sale_price / self.original_price) * 100)
        return None

    def format_price(self) -> str:
        orig = f"${self.original_price:.2f}" if self.original_price else "N/A"
        pct = f"  ({self.discount_pct()}% off)" if self.discount_pct() else ""
        return f"{orig} → ${self.sale_price:.2f}{pct}"

    def format_sizes(self) -> str:
        return ", ".join(self.sizes_available) if self.sizes_available else "check site"
