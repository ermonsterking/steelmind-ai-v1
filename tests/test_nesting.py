from app.services.nesting import pack_one_sheet


def test_packing_placements_stay_inside_stock_and_do_not_overlap():
    parts = [
        {"part_id": "A", "component_name": "a", "width_mm": 400, "height_mm": 300, "allow_rotation": True},
        {"part_id": "B", "component_name": "b", "width_mm": 500, "height_mm": 200, "allow_rotation": True},
        {"part_id": "C", "component_name": "c", "width_mm": 250, "height_mm": 250, "allow_rotation": False},
    ]
    result = pack_one_sheet(parts, 1000, 1000, kerf_mm=3, edge_trim_mm=10, strategy="best_fit_decreasing")
    assert result["placed_count"] == 3
    for p in result["placements"]:
        assert p["x_mm"] >= 10
        assert p["y_mm"] >= 10
        assert p["x_mm"] + p["width_mm"] <= 990
        assert p["y_mm"] + p["height_mm"] <= 990
    for i, a in enumerate(result["placements"]):
        for b in result["placements"][i + 1:]:
            overlap_x = a["x_mm"] < b["x_mm"] + b["width_mm"] and a["x_mm"] + a["width_mm"] > b["x_mm"]
            overlap_y = a["y_mm"] < b["y_mm"] + b["height_mm"] and a["y_mm"] + a["height_mm"] > b["y_mm"]
            assert not (overlap_x and overlap_y)


def test_oversized_part_is_reported_unplaced():
    parts = [{"part_id": "TOO-BIG", "width_mm": 5000, "height_mm": 5000, "allow_rotation": True}]
    result = pack_one_sheet(parts, 1000, 1000, edge_trim_mm=10)
    assert result["placed_count"] == 0
    assert result["unplaced_part_ids"] == ["TOO-BIG"]
