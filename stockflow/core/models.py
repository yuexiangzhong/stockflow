from dataclasses import dataclass

@dataclass
class Product:
    id: int | None
    sku: str
    name: str
    spec: str | None = None
    unit: str = "pcs"
    cost_price: float = 0.0
    sale_price: float = 0.0
    enabled: bool = True
