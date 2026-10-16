from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

ProductType = Literal["workbench_panel_kit", "flat_panel_kit", "custom_plate_kit"]


class PartDefinition(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)
    width_mm: float = Field(gt=0, le=10000)
    height_mm: float = Field(gt=0, le=10000)
    quantity_per_unit: int = Field(default=1, ge=1, le=10000)
    allow_rotation: bool = True
    material_grade: str | None = Field(default=None, max_length=80)
    thickness_mm: float | None = Field(default=None, gt=0, le=500)


class InterpretRequest(BaseModel):
    prompt: str = Field(min_length=8, max_length=8000)


class InterpretationResponse(BaseModel):
    product_type: ProductType | None
    product_name: str | None
    quantity: int | None
    length_mm: float | None
    width_mm: float | None
    height_mm: float | None
    material_grade: str | None
    thickness_mm: float | None
    confidence: Literal["low", "medium", "high"]
    interpreter_mode: str = "deterministic_rules"
    missing_questions: list[str]
    assumptions: list[str]
    note: str


class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    prompt: str = Field(min_length=8, max_length=8000)
    product_type: ProductType
    product_name: str = Field(min_length=2, max_length=120)
    quantity: int = Field(ge=1, le=10000)
    project_code: str = Field(min_length=2, max_length=80)
    length_mm: float = Field(gt=0, le=10000)
    width_mm: float = Field(gt=0, le=10000)
    height_mm: float = Field(gt=0, le=10000)
    material_grade: str = Field(min_length=2, max_length=80)
    thickness_mm: float = Field(gt=0, le=500)
    stock_length_mm: float = Field(default=3000, gt=0, le=20000)
    stock_width_mm: float = Field(default=1500, gt=0, le=10000)
    raw_stock_unit_cost: float = Field(default=22000, ge=0)
    kerf_mm: float = Field(default=3.0, ge=0, le=30)
    edge_trim_mm: float = Field(default=10.0, ge=0, le=100)
    parts: list[PartDefinition] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_part_config(self):
        if self.product_type == "custom_plate_kit" and not self.parts:
            raise ValueError("custom_plate_kit requires at least one rectangular plate component.")
        if self.edge_trim_mm * 2 >= min(self.stock_length_mm, self.stock_width_mm):
            raise ValueError("Edge trim leaves no usable stock area.")
        return self


class InventoryCreateRequest(BaseModel):
    id: str | None = Field(default=None, max_length=80)
    material_grade: str = Field(min_length=2, max_length=80)
    form: Literal["plate"] = "plate"
    thickness_mm: float = Field(gt=0, le=500)
    width_mm: float = Field(gt=0, le=10000)
    length_mm: float = Field(gt=0, le=20000)
    source_kind: Literal["new_stock", "remnant"]
    project_code: str | None = Field(default=None, max_length=80)
    quantity: int = Field(default=1, ge=1, le=100000)
    unit_value: float = Field(default=0, ge=0)
    traceability_verified: bool = False
    material_condition: str = Field(default="unknown", max_length=80)

    @model_validator(mode="after")
    def validate_remnant_quantity(self):
        if self.source_kind == "remnant" and self.quantity != 1:
            raise ValueError("A remnant record represents one physical remnant; quantity must be 1.")
        if self.source_kind == "remnant" and not self.project_code:
            raise ValueError("Remnants require a project/allocation code in V1.")
        return self


class ActualRemnant(BaseModel):
    material_grade: str = Field(min_length=2, max_length=80)
    thickness_mm: float = Field(gt=0, le=500)
    width_mm: float = Field(gt=0, le=10000)
    length_mm: float = Field(gt=0, le=20000)
    traceability_verified: bool = False
    material_condition: str = "inspection_required"
    project_code: str | None = None


class ReceiveProcurementRequest(BaseModel):
    inventory_lot_ids: list[str] = Field(min_length=1, max_length=100)
    actor: str = Field(default="procurement", min_length=2, max_length=80)
    note: str = Field(default="Received stock matched to planned sheet dimensions and allocation", max_length=1000)


class CompleteOrderRequest(BaseModel):
    plan_id: str = Field(min_length=8, max_length=80)
    engineering_signoff: bool = False
    procurement_confirmed: bool = False
    actual_remnants: list[ActualRemnant] = Field(default_factory=list, max_length=500)
    actor: str = Field(default="engineer", min_length=2, max_length=80)


class ApprovePlanRequest(BaseModel):
    actor: str = Field(default="engineer", min_length=2, max_length=80)
    note: str = Field(default="Approved for controlled engineering/procurement review", max_length=1000)
